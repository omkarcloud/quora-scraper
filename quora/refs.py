"""Reference resolvers + the persisted GraphQL operation table for /quora/*.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair). Each resolver takes a bare id, a bare slug/name OR any
quora.com link and returns ONE canonical string the fetch layer understands
(a `Ref`, below); it raises ValueError with a user-facing message (RefField
turns it into a 400).

Identifier shapes (quora.com, researched 2026-11-03):
  question   numeric qid (116252) or the URL slug
             (As-an-intermediate-Python-programmer-how-can-I-take-my-skills-to-the-next-level);
             links: /<slug>, /unanswered/<slug>, /<slug>/answer/<Name>,
             /<slug>/answers/<aid>, /<slug>/log, /<slug>/comments
  answer     numeric aid (176847) or the permalink
             /<slug>/answer/<Name> ("<slug>/answer/<Name>" is the ref; the
             answer page carries the aid), /<slug>/answer/<handle>/<Name>
             (Quora's own permaUrl for some answers, e.g. .../answer/ix_/Ashish-Kedia,
             seen 2026-11-03; both forms serve the same answer page) or
             /<slug>/answers/<aid>
  user       numeric uid (335) or the profile name (Adam-DAngelo);
             links: /profile/<Name>[/answers|/posts|/<post-slug>...]
  topic      numeric tid (948) or the topic slug (Machine-Learning);
             links: /topic/<Name>[/...]
  space      numeric tribeId (1575194) or the subdomain (humanity);
             links: https://<subdomain>.quora.com[/...]
  post       numeric pid (246876762) or a post link:
             https://<space>.quora.com/<slug>  (a Space post) or
             https://www.quora.com/profile/<Name>/<slug>  (a profile post)

Bare numbers are ids; a bare slug is anything else without a slash or
whitespace. Language networks (es.quora.com, hi.quora.com, ...) are
separate content networks and are not served: a link on one is refused
with a message rather than silently read as www.
"""
import re
from urllib.parse import unquote, urlparse

SITE = "https://www.quora.com"
SITE_HOST = "www.quora.com"

# Subdomains of quora.com that are not Spaces (a Space is any other label).
_NON_SPACE_HOSTS = {"www", "quora", "help", "careers", "about", "m", "api", "qsbr", "qph", "qsf",
                    "producthelp", "business", "ads", "blog", "poe", "www2"}
# Two-letter language networks: separate content, refused.
_LANG_HOST_RE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$")

_ID_RE = re.compile(r"^[0-9]{1,20}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._%-]*$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._%-]*$")
# question slugs never begin with the reserved first segments
_RESERVED_FIRST = {"profile", "topic", "search", "unanswered", "answer", "answers", "about",
                   "settings", "notifications", "spaces", "sitemap", "contact", "careers", "q",
                   "login", "signup", "api", "graphql", "ads", "business", "press", "content"}

ANSWER_PATH_RE = re.compile(r"^([^/]+)/answer/([^/?#]+)(?:/([^/?#]+))?$")
# Sub-pages of an answer permalink (…/answer/<Name>/log): never part of the ref.
_ANSWER_SUBPAGES = {"log", "comments", "upvoters", "shares", "quotes", "edit"}


class Ref(str):
    """A resolved reference: the canonical string plus how to read it."""
    kind = None   # "id" | "slug" | "name" | "subdomain" | "path" | "link"

    def __new__(cls, value, kind):
        obj = str.__new__(cls, value)
        obj.kind = kind
        return obj


def _parse_link(value):
    """(host, path segments, path) of a quora.com link; ValueError otherwise."""
    url = value if not value.startswith("//") else "https:" + value
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not (host == "quora.com" or host.endswith(".quora.com")):
        raise ValueError("Must be a quora.com link.")
    label = host[:-len(".quora.com")] if host.endswith(".quora.com") else ""
    if label and label not in _NON_SPACE_HOSTS and _LANG_HOST_RE.match(label):
        raise ValueError(f"{host} is a separate Quora language network; only www.quora.com "
                         "links and ids are served.")
    path = unquote(parsed.path or "/")
    segments = [s for s in path.split("/") if s]
    return host, label, segments, path


def _is_link(value):
    return value.startswith(("http://", "https://", "//"))


def _space_label(host_label):
    """The Space subdomain of a quora.com host, or None for www / service hosts."""
    if not host_label or host_label in _NON_SPACE_HOSTS:
        return None
    return host_label


# ---- questions ---------------------------------------------------------------

def resolve_question(value):
    """qid / slug / any www.quora.com question link -> Ref (id or slug)."""
    value = (value or "").strip()
    if _ID_RE.match(value):
        return Ref(value, "id")
    if _is_link(value):
        _, label, segments, _ = _parse_link(value)
        if _space_label(label):
            raise ValueError("That is a Space link; a question lives at https://www.quora.com/<slug>.")
        if segments and segments[0] == "unanswered":
            segments = segments[1:]
        if segments and segments[0] not in _RESERVED_FIRST and _SLUG_RE.match(segments[0]):
            return Ref(segments[0], "slug")
        raise ValueError("Must be a www.quora.com question link (https://www.quora.com/<question-slug>).")
    if _SLUG_RE.match(value) and value not in _RESERVED_FIRST:
        return Ref(value, "slug")
    raise ValueError("Must be a Quora question id (116252), the question's URL slug "
                     "(What-is-machine-learning) or a www.quora.com question link.")


# ---- answers -----------------------------------------------------------------

def resolve_answer(value):
    """aid / an answer permalink -> Ref (id, or path '<slug>/answer/<Name>')."""
    value = (value or "").strip()
    if _ID_RE.match(value):
        return Ref(value, "id")
    if _is_link(value):
        _, label, segments, _ = _parse_link(value)
        if _space_label(label):
            raise ValueError("That is a Space link; an answer permalink looks like "
                             "https://www.quora.com/<question-slug>/answer/<Author-Name>.")
        if segments and segments[0] == "unanswered":
            segments = segments[1:]
        if len(segments) >= 3 and segments[1] == "answers" and _ID_RE.match(segments[2]):
            return Ref(segments[2], "id")
        if len(segments) >= 3 and segments[1] == "answer" and _NAME_RE.match(segments[2]) \
                and _SLUG_RE.match(segments[0]):
            tail = [segments[2]]
            if len(segments) >= 4 and _NAME_RE.match(segments[3]) and segments[3] not in _ANSWER_SUBPAGES:
                tail.append(segments[3])
            return Ref(f"{segments[0]}/answer/{'/'.join(tail)}", "path")
        raise ValueError("Must be an answer permalink "
                         "(https://www.quora.com/<question-slug>/answer/<Author-Name>) or an answer id.")
    match = ANSWER_PATH_RE.match(value)
    if match and _SLUG_RE.match(match.group(1)) and _NAME_RE.match(match.group(2)) \
            and (match.group(3) is None or (_NAME_RE.match(match.group(3))
                                            and match.group(3) not in _ANSWER_SUBPAGES)):
        return Ref(value, "path")
    raise ValueError("Must be a Quora answer id (176847) or an answer permalink "
                     "(https://www.quora.com/<question-slug>/answer/<Author-Name>).")


# ---- users -------------------------------------------------------------------

def resolve_user(value):
    """uid / profile name / any /profile/<Name> link -> Ref (id or name)."""
    value = (value or "").strip()
    if _ID_RE.match(value):
        return Ref(value, "id")
    if _is_link(value):
        _, _, segments, _ = _parse_link(value)
        if len(segments) >= 2 and segments[0] == "profile" and _NAME_RE.match(segments[1]):
            return Ref(segments[1], "name")
        raise ValueError("Must be a Quora profile link (https://www.quora.com/profile/<Name>).")
    if _NAME_RE.match(value):
        return Ref(value, "name")
    raise ValueError("Must be a Quora user id (335), a profile name (Adam-DAngelo) "
                     "or a profile link (https://www.quora.com/profile/Adam-DAngelo).")


# ---- topics ------------------------------------------------------------------

def resolve_topic(value):
    """tid / topic slug / any /topic/<Name> link -> Ref (id or slug)."""
    value = (value or "").strip()
    if _ID_RE.match(value):
        return Ref(value, "id")
    if _is_link(value):
        _, _, segments, _ = _parse_link(value)
        if len(segments) >= 2 and segments[0] == "topic" and _SLUG_RE.match(segments[1]):
            return Ref(segments[1], "slug")
        raise ValueError("Must be a Quora topic link (https://www.quora.com/topic/<Name>).")
    if _SLUG_RE.match(value):
        return Ref(value, "slug")
    raise ValueError("Must be a Quora topic id (948), a topic slug (Machine-Learning) "
                     "or a topic link (https://www.quora.com/topic/Machine-Learning).")


# ---- spaces ------------------------------------------------------------------

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def resolve_space(value):
    """tribeId / subdomain / any <subdomain>.quora.com link -> Ref (id or subdomain)."""
    value = (value or "").strip()
    if _ID_RE.match(value):
        return Ref(value, "id")
    if _is_link(value):
        _, label, _, _ = _parse_link(value)
        sub = _space_label(label)
        if sub:
            return Ref(sub, "subdomain")
        raise ValueError("Must be a Quora Space link (https://<space>.quora.com/).")
    low = value.lower()
    if low.endswith(".quora.com"):
        sub = _space_label(low[:-len(".quora.com")])
        if sub:
            return Ref(sub, "subdomain")
    if _SUBDOMAIN_RE.match(low) and low not in _NON_SPACE_HOSTS:
        return Ref(low, "subdomain")
    raise ValueError("Must be a Quora Space id (1575194), its subdomain (humanity) "
                     "or its link (https://humanity.quora.com/).")


# ---- posts -------------------------------------------------------------------

def resolve_post(value):
    """pid / a Space post link / a profile post link -> Ref (id or link)."""
    value = (value or "").strip()
    if _ID_RE.match(value):
        return Ref(value, "id")
    if _is_link(value):
        host, label, segments, _ = _parse_link(value)
        sub = _space_label(label)
        if sub and len(segments) >= 1 and _SLUG_RE.match(segments[0]) \
                and segments[0] not in ("people", "about", "submissions", "quality", "log"):
            return Ref(f"https://{sub}.quora.com/{segments[0]}", "link")
        if not sub and len(segments) >= 3 and segments[0] == "profile" and _SLUG_RE.match(segments[2]) \
                and segments[2] not in ("answers", "posts", "questions", "followers", "following",
                                        "edits", "activity", "log", "published"):
            return Ref(f"{SITE}/profile/{segments[1]}/{segments[2]}", "link")
        raise ValueError("Must be a Quora post link (https://<space>.quora.com/<post-slug> or "
                         "https://www.quora.com/profile/<Name>/<post-slug>) or a post id.")
    raise ValueError("Must be a Quora post id (246876762) or a post link "
                     "(https://<space>.quora.com/<post-slug>).")


# ---- links -------------------------------------------------------------------

def abs_link(path):
    """'/profile/X' -> 'https://www.quora.com/profile/X'; absolute links pass through."""
    if not path:
        return None
    if path.startswith(("http://", "https://")):
        return path
    if path.startswith("//"):
        return "https:" + path
    return SITE + (path if path.startswith("/") else "/" + path)


def question_link(slug):
    return f"{SITE}/{slug}" if slug else None


def profile_link(name):
    return f"{SITE}/profile/{name}" if name else None


def topic_link(slug):
    return f"{SITE}/topic/{slug}" if slug else None


def space_link(subdomain):
    return f"https://{subdomain}.quora.com" if subdomain else None


# ---- the persisted GraphQL operations ------------------------------------------
# Quora's Relay client sends persisted queries: {queryName, variables,
# extensions: {hash}} to /graphql/gql_para_POST?q=<name>. The hashes are the
# `params.id` of the Relay artifacts in the rspack chunks
# (qsbr.cf2.quoracdn.net/-4-ans_frontend-relay-rspack-*.webpack), read on
# 2026-11-03 by evaluating every chunk the logged-out pages load (1180
# operations). A deploy of Quora's frontend can rotate them; when an
# operation starts failing, re-read `params:{id:"<64 hex>",...,name:"<op>"}`
# from the chunk named after it.
OPS = {
    "QuestionPageHeaderSectionQuery": "9b25a5c7206756c06542e09ce2bc9d583a245710d87ce2393cbac2813e44309e",
    "QuestionDesktopSidebarSectionQuery": "e291a5a0c82a7ba6c40b91f6578e4db910d57bdf07d87e56673fdaa8c9e385ac",
    "QuestionAnswerPagedListQuery": "834fe4416e9dad6f9fd1acad8ca40281d291422375e86d9124cd351bb0715791",
    "ContentLogMainQuery": "b3ee6979e52ad62adabb4881ac534744cc45f5477eda9242233de272592a2f61",
    "AllCommentsListQuery": "12057f1b3ab2b7c2207ce81ba0f3129964dc0d703dac01620b746341a9feded8",
    "CommentRepliesListQuery": "65da84c2274317a9daa74f479c22bdcb5bfbd6d9a91bfa0c3edc1dd6eae9ab79",
    "QuestionFollowerPagedListQuery": "1226ee37f55bf73bb0c46ca2aaca032489444b13916ad40dc308f97c70d3c063",
    "AnswerPageLoadableQuery": "d6e0251cb538f41ea0484de2050367b5c79daca0423e3a19c9df5e29a4be4c3e",
    "UpvoterPagedListQuery": "12fb520fade94d3cf2ce5eb50a017f751e6d04523c9d698495dc50d048490f07",
    "UserProfilePageLoadableQuery": "07cfbc324dddaa3a457814711a87cb86713b90e3233b2bbbe6ebc1fcb598f640",
    "UserProfileAnswersMostRecent_RecentAnswers_Query": "3f2f0c513359ea2060477d467d63957a3fdd3dc1215ffd873080f12a0aff24c4",
    "UserProfileAnswersMostViewed_RecentAnswers_Query": "0edb9bd06199dc66c486ff037923f968dcf9ce45949ee5d0e36700b359cb1fcf",
    "UserProfilePostsList_Posts_Query": "4034d097222809b5a7afcc593983ce4a1dcb239a3fdf5a7210a85f01e08dca9d",
    "UserProfileQuestionsList_Questions_Query": "0c910f4ee7a9f7c11e7f6c65fc6f3ad19c1632116a9aa412ca85c33b1f4dd810",
    "UserProfileFollowers_ProfileTopics_Query": "48b9f7dbeea78efaffe11c436288c9532f564494f32f4291b2938eed9289cd3f",
    "UserProfileFollowingPeople_ProfileTopics_Query": "6b80f923dcdf7727dd5755dd7425ad988bc2f3e27f7a3391fd39507f906e8d9b",
    "UserProfileFollowingTopics_ProfileTopics_Query": "43fdb0bdefdec53222a8aa08840e30f613d410079c5478fc0120486945d6aa73",
    "UserProfileFollowingSpaces_ProfileTopics_Query": "c9517e6e22c1707118b7c5bfc01c3ff8ad79b1641ac750fe958e9b1c08f03241",
    "TopicPageLoadableQuery": "c310f540a753ac414663868383b8b0a170529cd1b2c2e33a7d59646906f14f77",
    "TopicReadMultifeedLoggedOut_Query": "6f20e03d74b699a2fdb10adda68eb33bc6aaad031d5def80084cfc7720b98482",
    "TribeMainPageLoadableQuery": "cdc7c26a35d638cb3adf75f7fe5596a4ea5c7d5f7e766300160b312095508cf6",
    "MultifeedQuery": "a195ba3dfad3e5d869783db71ab3727c91d09b24a94f05749d676135e8ca7605",
    "NullspacePostPageLoadableQuery": "79834b843c42e657cf0a4f0586b4a7f3510568c6f55e85bad9a46a0c61c4385e",
}
