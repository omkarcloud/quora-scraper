"""The /quora/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs).

Every entity has ONE cached record that resolves its reference to the
site's numeric id and carries the details response (cache.cached_call under
quora.question / quora.answer / quora.user / quora.topic / quora.space /
quora.post, keyed on the reference string): a slug or link costs one page
or header fetch the first time, and every list endpoint on the same entity
(answers, comments, followers, posts, ...) reads the id from that record
instead of resolving again. The lists cache their own pages.

Pagination: Quora's answer / comment / follower / profile lists are
cursor-paged where the cursor is a plain offset, so `page` maps to one
upstream call (after = page * size - size - 1). The topic answer feed and
the Space post feed hand out opaque cursors that are only valid inside the
session that issued them, so page N walks N hops on one session
(fetch.graphql_walk). The site publishes no totals: responses carry
has_next and null totals (route_glue.paginate follows has_next).
"""
import base64
from urllib.parse import quote

from cache import cached_call
from quora import cache_config as ttl
from quora import parsers
from quora.fetch import QuoraNotFound, fetch_page, graphql, graphql_walk
from quora.refs import SITE, Ref, space_link

LIST_PAGE_SIZE = 20   # items per upstream call on the offset-cursor lists
# Quora serves at most 10 per call on its people and comment lists, whatever
# `first` asks for (measured 2026-11-03: first=20 -> 10 items, endCursor "9"
# on comments, question followers, upvoters, user followers and all three
# following lists). Paging those by 20 would skip items 10-19 of every page.
PEOPLE_PAGE_SIZE = 10
FEED_PAGE_SIZE = 10   # bundles per hop on the multifeed lists (one story each)


def _after(page, size=LIST_PAGE_SIZE):
    """The offset cursor of page `page`: the index of the last item before it."""
    return None if page <= 1 else str((page - 1) * size - 1)


def _node_id(kind, number):
    """Quora's Relay node id: base64("<Type>@0:<id>")."""
    return base64.b64encode(f"{kind}@0:{number}".encode()).decode()


def _paged(results, has_next, page, size, **head):
    return {
        **head,
        "results": results,
        "pagination": {"page": page, "items_per_page": size, "has_next": has_next,
                       "total_pages": None, "total_count": None},
    }


def _empty_past_end(items):
    return items or []


# ---- questions ---------------------------------------------------------------

def _question_record(question):
    """Header (merged deferred part) + sidebar + log of one question, keyed
    on the reference; the slug comes from the log when the caller gave a qid."""
    ref = _ref(question, "question")
    log_data = None
    if ref.kind == "id":
        log_data = graphql("ContentLogMainQuery", {"entityType": 1, "oid": int(ref), "first": 1, "after": None},
                           label=f"question {ref} log")
        content = (log_data or {}).get("contentObject") or {}
        slug = content.get("slug")
        if not slug:
            raise QuoraNotFound(f"question {ref} not found")
    else:
        slug = str(ref)
    encoded = quote(slug, safe="-._~")
    header = graphql("QuestionPageHeaderSectionQuery", {"questionSlugEncoded": encoded, "redirectedQid": 0},
                     label=f"question {slug}")
    record = parsers.parse_question_header(header)
    if record is None:
        raise QuoraNotFound(f"question {slug} not found")
    sidebar = parsers.parse_question_sidebar(
        graphql("QuestionDesktopSidebarSectionQuery", {"questionSlugEncoded": encoded}, label=f"question {slug} sidebar"))
    record["stats"]["answers_including_related"] = sidebar["answers_including_related"]
    record["related_questions"] = sidebar["related_questions"]
    if log_data is None and record["id"]:
        log_data = graphql("ContentLogMainQuery", {"entityType": 1, "oid": record["id"], "first": 1, "after": None},
                           label=f"question {slug} log")
    log = parsers.parse_question_log(log_data)
    if log:
        record["stats"]["views"] = log.get("views")
        record["stats"]["merged_questions"] = log.get("merged_questions")
        if record["stats"]["followers"] is None:
            record["stats"]["followers"] = log.get("followers")
        record["created_at"] = log.get("created_at")
        record["last_followed_at"] = log.get("last_followed_at")
        if log.get("asker") and not (record["asker"] or {}).get("name"):
            record["asker"] = log["asker"]
        if record["is_locked"] is None:
            record["is_locked"] = log.get("is_locked")
    return record


def _ref(value, kind):
    """Rebuild the Ref the schema produced (cache keys hold plain strings)."""
    if isinstance(value, Ref):
        return value
    from quora import refs
    resolver = {"question": refs.resolve_question, "answer": refs.resolve_answer, "user": refs.resolve_user,
                "topic": refs.resolve_topic, "space": refs.resolve_space, "post": refs.resolve_post}[kind]
    return resolver(str(value))


def _question(question):
    return cached_call("quora.question", {"question": str(question)}, _question_record, ttl.QUESTION_CACHE)


def _qid(question):
    ref = _ref(question, "question")
    return int(ref) if ref.kind == "id" else _question(question)["id"]


def _question_head(question):
    record = _question(question)
    return {"id": record["id"], "title": record["title"], "link": record["link"],
            "answers": record["stats"]["answers"]}


def question_details(question):
    """The question record: title, asker, topics, exact view / follower /
    answer counts, related questions, creation date."""
    return _question(question)


def _question_answers(question, page):
    qid = _qid(question)
    data = graphql("QuestionAnswerPagedListQuery",
                   {"qid": qid, "first": LIST_PAGE_SIZE, "after": _after(page), "adsData": None,
                    "topAid": None, "forceScoreVersion": None}, label=f"question {qid} answers")
    answers, has_next, card = parsers.parse_question_answers(data)
    if answers is None:
        raise QuoraNotFound(f"question {question} not found")
    head = dict(card or {})
    # The list's own question node carries only the qid: the title and link
    # come from an answer written to this very question (a direct or the AI
    # answer), so no extra upstream call is spent on them.
    own = next((a["question"] for a in answers
                if a.get("question") and a["question"].get("id") == qid and a["question"].get("title")), None)
    for key in ("title", "link"):
        if not head.get(key) and own:
            head[key] = own.get(key)
    if head.get("answers") is None and own:
        head["answers"] = own.get("answers")
    return _paged(answers, has_next, page, LIST_PAGE_SIZE, question={
        "id": head.get("id") or qid, "title": head.get("title"), "link": head.get("link"),
        "answers": head.get("answers")})


def question_answers(**data):
    """Answers as Quora ranks them for a logged-out reader: direct answers,
    answers to equivalent / related questions and Quora's AI answer, each
    tagged with `relation`."""
    return cached_call("quora.question_answers", data, _question_answers, ttl.ANSWERS_CACHE)


def _comments(kind, number, page, label):
    data = graphql("AllCommentsListQuery",
                   {"id": _node_id(kind, number), "first": PEOPLE_PAGE_SIZE, "after": _after(page, PEOPLE_PAGE_SIZE),
                    "commentOrder": None, "topCommentId": None}, label=f"{label} comments")
    comments, has_next, container = parsers.parse_comments(data)
    if comments is None:
        raise QuoraNotFound(f"{label} not found")
    return comments, has_next


def _question_comments(question, page):
    qid = _qid(question)
    comments, has_next = _comments("Question", qid, page, f"question {qid}")
    return _paged(comments, has_next, page, PEOPLE_PAGE_SIZE, question=_question_head(question)
                  if _ref(question, "question").kind != "id" else {"id": qid})


def question_comments(**data):
    return cached_call("quora.question_comments", data, _question_comments, ttl.COMMENTS_CACHE)


def _question_followers(question, page):
    qid = _qid(question)
    data = graphql("QuestionFollowerPagedListQuery", {"qid": qid, "first": PEOPLE_PAGE_SIZE, "after": _after(page, PEOPLE_PAGE_SIZE)},
                   label=f"question {qid} followers")
    users, has_next = parsers.parse_user_list(data, "question", "followersConnection")
    if users is None:
        raise QuoraNotFound(f"question {question} not found")
    return _paged(users, has_next, page, PEOPLE_PAGE_SIZE, question={"id": qid})


def question_followers(**data):
    return cached_call("quora.question_followers", data, _question_followers, ttl.FOLLOWERS_CACHE)


# ---- answers -----------------------------------------------------------------

def _answer_record(answer):
    ref = _ref(answer, "answer")
    if ref.kind == "id":
        data = graphql("AnswerPageLoadableQuery", {"aid": int(ref), "sncid": 0, "includeSidebarRelatedQuestions": False,
                                                   "includeBottomRelatedQuestions": False}, label=f"answer {ref}")
    else:
        html = fetch_page(f"{SITE}/{ref}", f"answer {ref}")
        data = parsers.merged_inline_data(html, "AnswerPageLoadableQuery")
    record = parsers.parse_answer_page(data)
    if record is None or not record.get("id"):
        raise QuoraNotFound(f"answer {ref} not found")
    return record


def _answer(answer):
    return cached_call("quora.answer", {"answer": str(answer)}, _answer_record, ttl.ANSWER_CACHE)


def _aid(answer):
    ref = _ref(answer, "answer")
    return int(ref) if ref.kind == "id" else _answer(answer)["id"]


def answer_details(answer):
    """One answer: full text with its links and images, counts, author,
    question."""
    return _answer(answer)


def _answer_comments(answer, page):
    aid = _aid(answer)
    comments, has_next = _comments("Answer", aid, page, f"answer {aid}")
    return _paged(comments, has_next, page, PEOPLE_PAGE_SIZE, answer={"id": aid})


def answer_comments(**data):
    return cached_call("quora.answer_comments", data, _answer_comments, ttl.COMMENTS_CACHE)


def _answer_upvoters(answer, page):
    aid = _aid(answer)
    data = graphql("UpvoterPagedListQuery", {"nodeId": _node_id("Answer", aid), "first": PEOPLE_PAGE_SIZE,
                                             "after": _after(page, PEOPLE_PAGE_SIZE)}, label=f"answer {aid} upvoters")
    users, has_next = parsers.parse_user_list(data, "node", "upvotersConnection")
    if users is None:
        raise QuoraNotFound(f"answer {answer} not found")
    return _paged(users, has_next, page, PEOPLE_PAGE_SIZE, answer={"id": aid})


def answer_upvoters(**data):
    return cached_call("quora.answer_upvoters", data, _answer_upvoters, ttl.FOLLOWERS_CACHE)


# ---- users -------------------------------------------------------------------

_PROFILE_TABS = {"Combined": False, "Answers": False, "Questions": False, "Posts": False, "Followers": False,
                 "Following": False, "KnowsAbout": False, "Edits": False, "Activity": False, "Published": False}


def _user_record(user):
    ref = _ref(user, "user")
    if ref.kind == "id":
        data = graphql("UserProfilePageLoadableQuery", {"uid": int(ref), "first": 5, **_PROFILE_TABS, "Combined": True},
                       label=f"user {ref}")
    else:
        html = fetch_page(f"{SITE}/profile/{ref}", f"user {ref}")
        data = parsers.merged_inline_data(html, "UserProfilePageLoadableQuery")
    record = parsers.parse_user((data or {}).get("user"))
    if record is None or not record.get("id"):
        raise QuoraNotFound(f"user {ref} not found")
    return record


def _user(user):
    return cached_call("quora.user", {"user": str(user)}, _user_record, ttl.USER_CACHE)


def _uid(user):
    """Always through the cached record: the list operations answer an
    unknown uid with an empty list, not a null root, so only the profile
    record tells an empty tab from an unknown user."""
    return _user(user)["id"]


def _user_head(user):
    record = _user(user)
    return {"id": record["id"], "name": record["name"], "link": record["link"]}


def user_details(user):
    """The public profile: name, credentials, bio, follower / content counts,
    expertise topics, spaces, top-writer years."""
    return _user(user)


def _user_answers(user, sort, page):
    uid = _uid(user)
    op = ("UserProfileAnswersMostViewed_RecentAnswers_Query" if sort == "views"
          else "UserProfileAnswersMostRecent_RecentAnswers_Query")
    data = graphql(op, {"uid": uid, "first": LIST_PAGE_SIZE, "after": _after(page), "answerFilterTid": None},
                   label=f"user {uid} answers")
    answers, has_next = parsers.parse_user_answers(data)
    if answers is None:
        raise QuoraNotFound(f"user {user} not found")
    return _paged(answers, has_next, page, LIST_PAGE_SIZE, user=_user_head(user), sort=sort)


def user_answers(**data):
    return cached_call("quora.user_answers", data, _user_answers, ttl.USER_LISTS_CACHE)


def _user_posts(user, page):
    uid = _uid(user)
    data = graphql("UserProfilePostsList_Posts_Query", {"uid": uid, "order": 1, "first": LIST_PAGE_SIZE,
                                                        "after": _after(page)}, label=f"user {uid} posts")
    posts, has_next = parsers.parse_user_posts(data)
    if posts is None:
        raise QuoraNotFound(f"user {user} not found")
    return _paged(posts, has_next, page, LIST_PAGE_SIZE, user=_user_head(user))


def user_posts(**data):
    return cached_call("quora.user_posts", data, _user_posts, ttl.USER_LISTS_CACHE)


def _user_questions(user, page):
    uid = _uid(user)
    data = graphql("UserProfileQuestionsList_Questions_Query", {"uid": uid, "first": LIST_PAGE_SIZE,
                                                                "after": _after(page)}, label=f"user {uid} questions")
    questions, has_next = parsers.parse_user_questions(data)
    if questions is None:
        raise QuoraNotFound(f"user {user} not found")
    return _paged(questions, has_next, page, LIST_PAGE_SIZE, user=_user_head(user))


def user_questions(**data):
    return cached_call("quora.user_questions", data, _user_questions, ttl.USER_LISTS_CACHE)


def _user_followers(user, page):
    uid = _uid(user)
    data = graphql("UserProfileFollowers_ProfileTopics_Query", {"uid": uid, "first": PEOPLE_PAGE_SIZE,
                                                                "after": _after(page, PEOPLE_PAGE_SIZE)}, label=f"user {uid} followers")
    users, has_next = parsers.parse_user_list(data, "user", "followerUsersConnection")
    if users is None:
        raise QuoraNotFound(f"user {user} not found")
    return _paged(users, has_next, page, PEOPLE_PAGE_SIZE, user=_user_head(user))


def user_followers(**data):
    return cached_call("quora.user_followers", data, _user_followers, ttl.FOLLOWERS_CACHE)


_FOLLOWING_OPS = {"people": "UserProfileFollowingPeople_ProfileTopics_Query",
                  "topics": "UserProfileFollowingTopics_ProfileTopics_Query",
                  "spaces": "UserProfileFollowingSpaces_ProfileTopics_Query"}


def _user_following(user, type, page):
    uid = _uid(user)
    data = graphql(_FOLLOWING_OPS[type], {"uid": uid, "first": PEOPLE_PAGE_SIZE, "after": _after(page, PEOPLE_PAGE_SIZE)},
                   label=f"user {uid} following {type}")
    items, has_next = parsers.parse_user_following(data, type)
    if items is None:
        raise QuoraNotFound(f"user {user} not found")
    return _paged(items, has_next, page, PEOPLE_PAGE_SIZE, user=_user_head(user), type=type)


def user_following(**data):
    return cached_call("quora.user_following", data, _user_following, ttl.FOLLOWERS_CACHE)


# ---- topics ------------------------------------------------------------------

def _topic_record(topic):
    ref = _ref(topic, "topic")
    if ref.kind == "id":
        data = graphql("TopicPageLoadableQuery", {"tid": int(ref)}, label=f"topic {ref}")
    else:
        html = fetch_page(f"{SITE}/topic/{ref}", f"topic {ref}")
        data = parsers.merged_inline_data(html, "TopicPageLoadableQuery")
    record = parsers.parse_topic(data)
    if record is None or not record.get("id"):
        raise QuoraNotFound(f"topic {ref} not found")
    return record


def _topic(topic):
    return cached_call("quora.topic", {"topic": str(topic)}, _topic_record, ttl.TOPIC_CACHE)


def topic_details(topic):
    """The topic: name, follower count, kind flags, most viewed writers."""
    return _topic(topic)


def _feed_builder(base, next_cursor_of):
    def build(cursor, seen):
        return {**base, "multifeedAfter": cursor, "multifeedNumBundlesOnClient": seen}
    build.next_cursor = next_cursor_of
    return build


def _feed_next(data):
    items, has_next, cursor, bundles = parsers.parse_feed(data)
    return cursor, has_next, bundles


def _topic_answers(topic, page):
    record = _topic(topic)
    tid = record["id"]
    build = _feed_builder({"tid": tid, "first": FEED_PAGE_SIZE}, _feed_next)
    data, reached = graphql_walk("TopicReadMultifeedLoggedOut_Query", build, page, label=f"topic {tid} answers")
    items, has_next, _, _ = parsers.parse_feed(data) if reached else ([], False, None, 0)
    head = {"id": tid, "name": record["name"], "link": record["link"]}
    return _paged(_empty_past_end(items), has_next if reached else False, page, FEED_PAGE_SIZE, topic=head)


def topic_answers(**data):
    """Quora's logged-out answer feed for the topic (each answer with its
    question), in feed order."""
    return cached_call("quora.topic_answers", data, _topic_answers, ttl.TOPIC_FEED_CACHE)


# ---- spaces ------------------------------------------------------------------

_SPACE_TABS = {"isAboutTab": False, "isMainTab": False, "isSubmissionsTab": False, "isSuggestionsTab": False,
               "isPeopleTab": False, "isQuestionsTab": False, "isQueueTab": False, "isEarningsTab": False,
               "isSettingsTab": False, "isAdminLogTab": False, "isSuspectedSpamTab": False, "isNotifsTab": False}


def _space_variables(tribe_id, **tabs):
    return {"tribeId": tribe_id, "injectedTribeItemIds": [], "hasInjection": False, "injectionType": None,
            "injectionData": None, "multifeedAfter": None, "first": FEED_PAGE_SIZE, "multifeedNumBundlesOnClient": 0,
            "sncid": 0, "tribeFeedType": "unknown", **_SPACE_TABS, **tabs}


def _space_record(space):
    ref = _ref(space, "space")
    if ref.kind == "id":
        data = graphql("TribeMainPageLoadableQuery", _space_variables(int(ref), isAboutTab=True), label=f"space {ref}")
    else:
        html = fetch_page(space_link(ref) + "/", f"space {ref}", not_found_on_home=True)
        data = parsers.merged_inline_data(html, "TribeMainPageLoadableQuery")
    record = parsers.parse_space(data)
    if record is None or not record.get("id"):
        raise QuoraNotFound(f"space {ref} not found")
    return record


def _space(space):
    return cached_call("quora.space", {"space": str(space)}, _space_record, ttl.SPACE_CACHE)


def space_details(space):
    """The Space: description, rules, follower / member / contributor
    counts, subscription prices, owner and featured people."""
    return _space(space)


def _space_posts(space, page):
    record = _space(space)
    tribe_id = record["id"]
    build = _feed_builder({"multifeedPage": "tribe_top_items", "pageData": str(tribe_id), "first": FEED_PAGE_SIZE,
                           "injectionType": None, "injectionData": None, "filterStoryType": None,
                           "filterStoryOid": None, "showLiveBanner": False}, _feed_next)
    data, reached = graphql_walk("MultifeedQuery", build, page, label=f"space {tribe_id} posts")
    items, has_next, _, _ = parsers.parse_feed(data) if reached else ([], False, None, 0)
    head = {"id": tribe_id, "name": record["name"], "link": record["link"]}
    return _paged(_empty_past_end(items), has_next if reached else False, page, FEED_PAGE_SIZE, space=head)


def space_posts(**data):
    """The Space's post feed as Quora orders it for a logged-out reader."""
    return cached_call("quora.space_posts", data, _space_posts, ttl.SPACE_FEED_CACHE)


def _space_people(space):
    record = _space(space)
    tribe_id = record["id"]
    data = graphql("TribeMainPageLoadableQuery", _space_variables(tribe_id, isPeopleTab=True),
                   label=f"space {tribe_id} people")
    people = parsers.parse_space_people(data)
    if people is None:
        raise QuoraNotFound(f"space {space} not found")
    return {"space": {"id": tribe_id, "name": record["name"], "link": record["link"]},
            "counts": {"admins": record["stats"]["admins"], "moderators": record["stats"]["moderators"],
                       "contributors": record["stats"]["contributors"], "followers": record["stats"]["followers"]},
            **people}


def space_people(**data):
    """Admins, moderators, contributors and the first followers of a Space,
    each with their last-week activity."""
    return cached_call("quora.space_people", data, _space_people, ttl.SPACE_PEOPLE_CACHE)


# ---- posts -------------------------------------------------------------------

def _post_record(post):
    ref = _ref(post, "post")
    if ref.kind == "id":
        data = graphql("NullspacePostPageLoadableQuery", {"pid": int(ref)}, label=f"post {ref}")
    else:
        html = fetch_page(str(ref), f"post {ref}", not_found_on_home=True)
        data = parsers.merged_inline_data(html, "TribeItemPageLoadableQuery") \
            or parsers.merged_inline_data(html, "NullspacePostPageLoadableQuery")
    record = parsers.parse_post_page(data)
    if record is None or not record.get("id"):
        raise QuoraNotFound(f"post {ref} not found")
    return record


def _post(post):
    return cached_call("quora.post", {"post": str(post)}, _post_record, ttl.POST_CACHE)


def _pid(post):
    ref = _ref(post, "post")
    return int(ref) if ref.kind == "id" else _post(post)["id"]


def post_details(post):
    """One Space or profile post: title, full text with links and images,
    counts, author, space."""
    return _post(post)


def _post_comments(post, page):
    pid = _pid(post)
    comments, has_next = _comments("Post", pid, page, f"post {pid}")
    return _paged(comments, has_next, page, PEOPLE_PAGE_SIZE, post={"id": pid})


def post_comments(**data):
    return cached_call("quora.post_comments", data, _post_comments, ttl.COMMENTS_CACHE)
