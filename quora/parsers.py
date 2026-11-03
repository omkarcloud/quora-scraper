"""Raw Quora pages / GraphQL payloads -> clean dicts for every /quora/*
endpoint. Pure functions, no I/O.

Quora's data is Relay JSON (fetch.py): the same node shapes come back from
the server-rendered pages (inline_results) and from the persisted GraphQL
operations, so one parser per node type serves both.

Value conventions (shared with the other scraper packages):
  * ids      the site's numeric ids (qid / aid / uid / tid / tribeId / pid),
             never the opaque Relay node ids
  * text     Quora's "qtext" documents ({"sections": [{"spans": [...]}]})
             become plain text (paragraphs joined by newlines, list items
             prefixed) plus the embedded links and images, see qtext()
  * dates    the site's microsecond epochs -> ISO 8601 UTC ("2010-12-11T03:35:39Z")
  * keys     snake_case; `link` not `url`; booleans as questions
  * absent   null, never "" — a paywalled Space answer/post comes as a cut
             preview with is_preview = true

Fixtures captured 2026-11-03 (quora/fixtures/): a question page with
direct, related and AI answers, an unanswered question page (no direct
answers), a profile, a topic, a Space, a Space post page, a profile post
page, an answer permalink page, the 404 "Error" page, a Cloudflare
challenge page; GraphQL: answers page 1 + 2, question log, question header
(multipart), question sidebar, answer by id, comments on an answer / a
question / a post (empty), comment replies, question followers, answer
upvoters, a user record, a user's recent answers, posts, questions,
followers, following people / topics / spaces, a topic record, the topic
answer feed, the Space main + people records, the Space post feed, a Space
post, a profile post, and the null-root not-found payloads. The pages'
`window.ansFrontendRelayWebpackManifest` asset map (JS chunk URLs, read by
no parser) is emptied in the fixtures to keep them small.
"""
import json
import re
from datetime import datetime, timezone

from quora.refs import abs_link, profile_link, question_link, topic_link

# ---- scalars -----------------------------------------------------------------

def micros_to_iso(value):
    """Quora's microsecond epoch -> ISO 8601 UTC; 0 / None / junk -> None."""
    try:
        micros = int(value)
    except (TypeError, ValueError):
        return None
    if micros <= 0:
        return None
    try:
        return datetime.fromtimestamp(micros / 1_000_000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _str(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _bool(value):
    return value if isinstance(value, bool) else None


def _year(value):
    """Credential years: "-1" means "present" -> None; "2015" -> 2015."""
    year = _int(value)
    return year if year and year > 0 else None


# ---- qtext documents -----------------------------------------------------------

def _qtext_doc(value):
    """A qtext document given as its JSON string, a dict, or a
    {"legacyJson": "..."} wrapper -> dict | None."""
    if value is None:
        return None
    if isinstance(value, dict):
        if "sections" in value:
            return value
        if "legacyJson" in value:
            return _qtext_doc(value.get("legacyJson"))
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.startswith("{"):
            try:
                return _qtext_doc(json.loads(text))
            except ValueError:
                return {"sections": [{"spans": [{"text": text}], "type": "plain"}]}
        return {"sections": [{"spans": [{"text": text}], "type": "plain"}]}
    return None


def qtext(value):
    """A qtext document -> {"text", "links", "images"}; None when empty."""
    doc = _qtext_doc(value)
    if not doc:
        return None
    lines, links, images = [], [], []
    ordered = 0
    for section in doc.get("sections") or []:
        if not isinstance(section, dict):
            continue
        parts = []
        for span in section.get("spans") or []:
            if not isinstance(span, dict):
                continue
            text = span.get("text") or ""
            mods = span.get("modifiers") or {}
            if isinstance(mods, dict):
                link = mods.get("link")
                if isinstance(link, dict) and link.get("url"):
                    links.append({"text": text.strip() or None, "link": link.get("url"),
                                  "type": link.get("type")})
                image = mods.get("image")
                if isinstance(image, str) and image:
                    images.append(mods.get("master_url") or image)
                embed = mods.get("embed")
                if isinstance(embed, dict) and embed.get("url"):
                    links.append({"text": text.strip() or None, "link": embed["url"], "type": "embed"})
            parts.append(text)
        line = "".join(parts).replace(" ", " ").strip("\n")
        kind = section.get("type") or "plain"
        if kind == "ordered-list":
            ordered += 1
            line = f"{ordered}. {line}"
        else:
            ordered = 0
            if kind == "unordered-list":
                line = f"- {line}"
            elif section.get("quoted"):
                line = f"> {line}"
        lines.append(line)
    text = "\n".join(lines).strip()
    if not text and not images and not links:
        return None
    return {"text": text or None, "links": links, "images": images}


def plain_text(value):
    """A qtext document (question titles, credentials) -> its plain text."""
    doc = qtext(value)
    return doc["text"] if doc else None


# ---- users -------------------------------------------------------------------

def _name(user):
    names = user.get("names") or []
    first = names[0] if names and isinstance(names[0], dict) else {}
    given, family = _str(first.get("givenName")), _str(first.get("familyName"))
    if first.get("reverseOrder"):
        given, family = family, given
    full = " ".join(p for p in (given, family) if p)
    if not full:
        admin = user.get("adminNames") or []
        if admin and isinstance(admin[0], dict):
            full = " ".join(p for p in (_str(admin[0].get("givenName")), _str(admin[0].get("familyName"))) if p)
    return full or None


def _credential_text(cred):
    """A credential node (bestCredential / profileCredential / authorCredential
    / credentialWithDefault) -> its printed line."""
    if not isinstance(cred, dict):
        return None
    for key in ("translatedString", "experience", "description"):
        if _str(cred.get(key)):
            return _str(cred.get(key))
    return None


def parse_user_card(user, credential=None):
    """The compact author / follower card every list carries."""
    if not isinstance(user, dict) or not user:
        return None
    anonymous = bool(user.get("isAnon"))
    name = None if anonymous else _name(user)
    link = None if anonymous else abs_link(user.get("profileUrl"))
    card = {
        "id": _int(user.get("uid")),
        "name": name or ("Anonymous" if anonymous else None),
        "link": link,
        "image": _str(user.get("profileImageUrl")),
        "credential": _credential_text(credential) or _credential_text(user.get("bestCredential"))
        or _credential_text(user.get("profileCredential")),
        "followers": _int(user.get("followerCount")),
        "is_anonymous": anonymous,
        "is_verified": _bool(user.get("isVerified")),
        "is_ai_account": _bool(user.get("isAiAccount")) or _bool(user.get("isMachineAnswerBot")) or False,
    }
    if card["id"] == 0 and anonymous:
        card["id"] = None
    return card


def _credentials(user):
    out = {"profile": _credential_text(user.get("profileCredential"))}
    work = []
    for cred in user.get("workCredentials") or []:
        if not isinstance(cred, dict):
            continue
        company = cred.get("company") or {}
        work.append({"position": _str(cred.get("position")),
                     "company": _str(cred.get("companyName")) or _str(company.get("name")),
                     "start_year": _year(cred.get("startYear")), "end_year": _year(cred.get("endYear")),
                     "is_current": cred.get("endYear") in ("-1", -1),
                     "text": _credential_text(cred)})
    school = []
    for cred in user.get("schoolCredentials") or []:
        if not isinstance(cred, dict):
            continue
        sch = cred.get("school") or {}
        conc = cred.get("concentration") or {}
        school.append({"school": _str(sch.get("name")) or _str(cred.get("schoolName")),
                       "degree": _str(cred.get("degree")),
                       "concentration": _str(cred.get("concentrationName")) or _str(conc.get("name")) if isinstance(conc, dict) else _str(cred.get("concentrationName")),
                       "end_year": _year(cred.get("endYear")), "text": _credential_text(cred)})
    location = []
    for cred in user.get("locationCredentials") or []:
        if not isinstance(cred, dict):
            continue
        loc = cred.get("location") or {}
        location.append({"location": _str(cred.get("locationName")) or _str(loc.get("name")),
                         "start_year": _year(cred.get("startYear")), "end_year": _year(cred.get("endYear")),
                         "is_current": cred.get("endYear") in ("-1", -1), "text": _credential_text(cred)})
    languages = []
    for cred in user.get("languageCredentials") or []:
        if isinstance(cred, dict):
            lang = cred.get("language") or {}
            languages.append(_str(cred.get("languageName")) or _str(lang.get("name")) or _credential_text(cred))
    out.update({"work": work, "education": school, "locations": location,
                "languages": [l for l in languages if l]})
    return out


def _topic_card(topic):
    if not isinstance(topic, dict):
        return None
    return {"id": _int(topic.get("tid")), "name": _str(topic.get("name")),
            "link": abs_link(topic.get("url")), "image": _str(topic.get("photoUrl")),
            "followers": _int(topic.get("numFollowers"))}


def _space_card(tribe):
    if not isinstance(tribe, dict):
        return None
    return {"id": _int(tribe.get("tribeId")), "name": _str(tribe.get("nameString")),
            "link": _str(tribe.get("url")), "image": _str(tribe.get("iconUrl")),
            "description": _str(tribe.get("descriptionString")),
            "followers": _int(tribe.get("numFollowers")),
            "members": _int(tribe.get("tribeUserCount"))}


def _edges(connection):
    if not isinstance(connection, dict):
        return []
    return [e.get("node") if isinstance(e, dict) else None for e in connection.get("edges") or []]


def _page_info(connection):
    info = (connection or {}).get("pageInfo") if isinstance(connection, dict) else None
    info = info or {}
    return {"has_next": bool(info.get("hasNextPage")), "end_cursor": _str(info.get("endCursor"))}


def parse_user(user):
    """The full profile record (UserProfilePageLoadableQuery / the profile page)."""
    if not isinstance(user, dict) or not user:
        return None
    card = parse_user_card(user)
    bio = qtext(user.get("descriptionQtextDocument"))
    expertise = [_topic_card(n) for n in _edges(user.get("expertiseTopicsConnection")) if n]
    for item in expertise:
        item.pop("followers", None)
    knows_nodes = _edges(user.get("expertiseTopicsConnection"))
    for item, node in zip(expertise, knows_nodes):
        item["answers"] = _int((node or {}).get("numPublicAnswersOfUser"))
    spaces = []
    for node in _edges(user.get("followingTribesConnection")):
        if not node:
            continue
        spaces.append({"id": _int(node.get("tribeId")), "name": _str(node.get("nameString")),
                       "link": _str(node.get("url")), "image": _str(node.get("iconUrl")),
                       "posts_by_user": _int(node.get("numItemsOfUser"))})
    publishers = [_str(p.get("publisherName")) for p in user.get("publishers") or [] if isinstance(p, dict)]
    record = {
        "id": card["id"],
        "name": card["name"],
        "link": card["link"],
        "image": card["image"],
        "credential": card["credential"],
        "bio": bio["text"] if bio else None,
        "credentials": _credentials(user),
        "stats": {
            "followers": _int(user.get("followerCount")),
            "following": _int(user.get("followingCount")),
            "answers": _int(user.get("numPublicAnswers")),
            "questions": _int(user.get("numProfileQuestions")),
            "posts": _int(user.get("postsCount")),
            "spaces": _int(user.get("numCanContributeTribes")),
            "content_views": _int(user.get("allTimePublicContentViews")),
            "answer_views": _int(user.get("allTimePublicAnswerViews")),
            "content_views_last_month": _int(user.get("lastMonthPublicContentViews")),
            "prize_winning_answers": _int(user.get("numPrizeWinningAnswers")),
            "award_winning_answers": _int(user.get("numAwardWinningAnswers")),
        },
        "top_writer_years": sorted((y for y in (user.get("topWriterYears") or []) if isinstance(y, int)), reverse=True),
        "top_asker_years": sorted((y for y in (user.get("topAskerYears") or []) if isinstance(y, int)), reverse=True),
        "publishers": [p for p in publishers if p],
        "knows_about": expertise,
        "spaces": spaces,
        "is_verified": _bool(user.get("isVerified")),
        "is_anonymous": card["is_anonymous"],
        "is_ai_account": card["is_ai_account"],
        "is_notable": _bool(user.get("isNotable")),
        "is_deceased": _bool(user.get("isDeceased")),
        "is_deactivated": _bool(user.get("deactivated")),
        "is_banned": _bool(user.get("isUserBanned")),
        "has_premium_badge": _bool(user.get("showPremiumProfileBadge")),
        "joined_at": micros_to_iso(user.get("creationTime")),
    }
    return record


# ---- questions ---------------------------------------------------------------

def parse_question_card(question):
    """The compact question reference lists and answers carry."""
    if not isinstance(question, dict) or not question:
        return None
    return {
        "id": _int(question.get("qid")),
        "title": plain_text(question.get("title")),
        "link": abs_link(question.get("url")) or question_link(question.get("slug")),
        "answers": _int(question.get("answerCount")),
    }


def parse_question_list_item(question):
    """A question in a user's asked-questions list."""
    card = parse_question_card(question)
    if not card:
        return None
    card.update({
        "followers": _int(question.get("followerCount")),
        "comments": _int(question.get("numDisplayComments")),
        "is_locked": _bool(question.get("isLocked")),
        "created_at": micros_to_iso(question.get("creationTime")),
        "last_followed_at": micros_to_iso(question.get("lastFollowTime")),
        "asker": parse_user_card(question.get("asker")) if isinstance(question.get("asker"), dict)
        and question["asker"].get("names") else None,
    })
    return card


def parse_question_header(data):
    """QuestionPageHeaderSectionQuery (merged deferred parts) -> the question
    record head; None when the slug is unknown."""
    data = data or {}
    question = data.get("question") or data.get("redirectedQuestion")
    if not isinstance(question, dict) or not question:
        return None
    topics = [{"id": _int(t.get("tid")), "name": _str(t.get("name")), "link": abs_link(t.get("url"))}
              for t in question.get("topics") or [] if isinstance(t, dict)]
    if not topics:
        topics = [{"id": None, "name": _str(t.get("name")), "link": abs_link(t.get("url"))}
                  for t in question.get("navigationTopics") or [] if isinstance(t, dict)]
    asker = question.get("asker") if isinstance(question.get("asker"), dict) else None
    return {
        "id": _int(question.get("qid")),
        "title": plain_text(question.get("title")),
        "link": abs_link(question.get("url")) or question_link(question.get("slug")),
        "slug": _str(question.get("slug")),
        "asker": parse_user_card(asker) if asker and (asker.get("names") or asker.get("profileUrl")) else
        ({"id": _int(asker.get("uid"))} if asker and _int(asker.get("uid")) else None),
        "topics": topics,
        "stats": {
            "answers": _int(question.get("answerCount")),
            "answers_including_related": None,
            "followers": _int(question.get("followerCount")),
            "views": None,
            "comments": _int(question.get("numDisplayComments")),
            "merged_questions": None,
        },
        "related_questions": [],
        "is_locked": _bool(question.get("isLocked")),
        "is_deleted": _bool(question.get("isDeleted")),
        "is_comments_disabled": _bool(question.get("isCommentsDisabled")),
        "is_limited_distribution": _bool(question.get("isLimdisted")),
        "has_adult_topic": _bool(question.get("hasUserAddedAdultTopic")),
        "created_at": None,
        "last_followed_at": None,
    }


def parse_question_sidebar(data):
    """QuestionDesktopSidebarSectionQuery -> {answers_including_related,
    related_questions}."""
    question = (data or {}).get("question") or {}
    info = question.get("rightHandSideRelatedQuestionsInfo") or {}
    related = [parse_question_card(q) for q in info.get("relatedQuestions") or [] if isinstance(q, dict)]
    for item in related:
        if item:
            item.pop("answers", None)
    return {"answers_including_related": _int(question.get("mixRankedAnswersCount")),
            "related_questions": [r for r in related if r]}


def parse_question_log(data):
    """ContentLogMainQuery -> the exact stats the question page itself hides."""
    obj = (data or {}).get("contentObject") or {}
    if not obj:
        return {}
    return {
        "views": _int(obj.get("viewCount")),
        "followers": _int(obj.get("followerCount")),
        "merged_questions": _int(obj.get("numMergesInto")),
        "created_at": micros_to_iso(obj.get("creationTime")),
        "last_followed_at": micros_to_iso(obj.get("lastFollowTime")),
        "asker": parse_user_card(obj.get("asker")) if isinstance(obj.get("asker"), dict) else None,
        "is_locked": _bool(obj.get("isLocked")),
    }


# ---- answers -----------------------------------------------------------------

_RELATION = {
    "QuestionAnswerItem2": "direct",
    "QuestionMachineAnswerItem": "ai",
    "QuestionRelevantAnswerItem2": "related",
}


def parse_answer(answer, relation=None, related_question=None):
    """An Answer node (question list item, profile list, feed story,
    AnswerPageLoadableQuery) -> the answer record."""
    if not isinstance(answer, dict) or not answer:
        return None
    body = qtext(answer.get("content")) or qtext(answer.get("contentQtextDocument"))
    author = answer.get("author") if isinstance(answer.get("author"), dict) else None
    question = answer.get("question") if isinstance(answer.get("question"), dict) else None
    link = abs_link(answer.get("permaUrl") or answer.get("url"))
    has_access = answer.get("viewerHasAccess")
    is_ai = bool(answer.get("isMachineAnswer"))
    if relation is None:
        relation = "ai" if is_ai else "direct"
    return {
        "id": _int(answer.get("aid")),
        "link": link,
        "text": body["text"] if body else None,
        "links": body["links"] if body else [],
        "images": body["images"] if body else [],
        "created_at": micros_to_iso(answer.get("creationTime")),
        "updated_at": micros_to_iso(answer.get("updatedTime")),
        "stats": {
            "upvotes": _int(answer.get("numUpvotes")),
            "views": _int(answer.get("numViews")),
            "shares": _int(answer.get("numShares")),
            "comments": _int(answer.get("numDisplayComments")),
        },
        "author": parse_user_card(author, answer.get("authorCredential")) if author else None,
        "question": parse_question_card(question),
        "relation": relation,
        "related_question": parse_question_card(related_question) if related_question else None,
        "space": _space_with_link(answer["tribe"], link) if isinstance(answer.get("tribe"), dict) else None,
        "access": _str(answer.get("effectiveAccessOption")),
        "is_preview": (has_access is False),
        "is_ai_generated": is_ai,
        "is_collapsed": bool(answer.get("isCollapsedForViewer")) or bool(answer.get("moderationCollapseType")),
        "is_pinned": _bool(answer.get("isPinned")),
        "is_comments_disabled": _bool(answer.get("isCommentsDisabled")),
        "is_deleted": _bool(answer.get("isDeleted")),
    }


def parse_question_answers(data):
    """QuestionAnswerPagedListQuery -> (answers, has_next, question card).
    The list interleaves ad / header / related-question filler items with
    the answers: only the answer items are returned, each tagged with its
    relation to the question (direct, related, equivalent, ai)."""
    question = (data or {}).get("question")
    if not isinstance(question, dict) or not question:
        return None, False, None
    connection = question.get("pagedListDataConnection") or question.get("answers") or {}
    answers = []
    for node in _edges(connection):
        if not isinstance(node, dict) or not isinstance(node.get("answer"), dict):
            continue
        kind = node.get("__typename")
        relation = _RELATION.get(kind)
        if relation is None:
            continue
        related = None
        if relation == "related":
            relation = "equivalent" if node.get("isEquivalentAnswer") else "related"
            related = node.get("relatedQuestion") if isinstance(node.get("relatedQuestion"), dict) else None
        parsed = parse_answer(node["answer"], relation=relation, related_question=related)
        if parsed:
            answers.append(parsed)
    info = _page_info(connection)
    return answers, info["has_next"], parse_question_card(question)


def parse_answer_page(data):
    """AnswerPageLoadableQuery (GraphQL or the permalink page) -> the answer
    record; None when the aid is unknown."""
    answer = (data or {}).get("answer")
    if not isinstance(answer, dict) or not answer:
        return None
    return parse_answer(answer)


def parse_user_answers(data):
    """UserProfileAnswersMostRecent / MostViewed -> (answers, has_next)."""
    user = (data or {}).get("user")
    if not isinstance(user, dict) or not user:
        return None, False
    connection = user.get("recentPublicAndPinnedAnswersConnection") or user.get("publicAnswersByViewsConnection") or {}
    answers = [parse_answer(n) for n in _edges(connection) if isinstance(n, dict)]
    return [a for a in answers if a], _page_info(connection)["has_next"]


# ---- comments ----------------------------------------------------------------

def parse_comment(node):
    if not isinstance(node, dict) or not node:
        return None
    body = qtext(node.get("contentQtextDocument")) or qtext(node.get("content"))
    replies = node.get("repliesConnection") if isinstance(node.get("repliesConnection"), dict) else None
    reply_nodes = [parse_comment(n) for n in _edges(replies)] if replies else []
    user = node.get("user") if isinstance(node.get("user"), dict) else None
    return {
        "id": _int(node.get("commentId")),
        "link": abs_link(node.get("url")),
        "text": body["text"] if body else None,
        "links": body["links"] if body else [],
        "images": body["images"] if body else [],
        "created_at": micros_to_iso(node.get("creationTime")),
        "upvotes": _int(node.get("numUpvotes")),
        "author": parse_user_card(user) if user else None,
        "is_reply": _bool(node.get("isReply")),
        "is_deleted": _bool(node.get("isDeleted")),
        "replies": [r for r in reply_nodes if r],
        "has_more_replies": _page_info(replies)["has_next"] if replies else False,
    }


def parse_comments(data):
    """AllCommentsListQuery -> (comments, has_next, container type); container
    None when the node id is unknown."""
    node = (data or {}).get("node")
    if not isinstance(node, dict) or not node:
        return None, False, None
    connection = node.get("allCommentsConnection") or {}
    comments = [parse_comment(n) for n in _edges(connection)]
    return [c for c in comments if c], _page_info(connection)["has_next"], _str(node.get("__typename"))


def parse_comment_replies(data):
    comment = (data or {}).get("comment")
    if not isinstance(comment, dict) or not comment:
        return None, False
    connection = comment.get("repliesConnection") or {}
    replies = [parse_comment(n) for n in _edges(connection)]
    return [r for r in replies if r], _page_info(connection)["has_next"]


# ---- user lists --------------------------------------------------------------

def parse_user_list(data, root, connection_key):
    """A paged list of User nodes under data[root][connection_key] ->
    (cards, has_next); (None, False) when the root is unknown."""
    owner = (data or {}).get(root)
    if not isinstance(owner, dict) or not owner:
        return None, False
    connection = owner.get(connection_key) or {}
    cards = [parse_user_card(n) for n in _edges(connection) if isinstance(n, dict)]
    return [c for c in cards if c], _page_info(connection)["has_next"]


def parse_user_questions(data):
    user = (data or {}).get("user")
    if not isinstance(user, dict) or not user:
        return None, False
    connection = user.get("recentPublicQuestionsConnection") or {}
    if not connection:
        connection = next((v for v in user.values() if isinstance(v, dict) and "edges" in v), {})
    items = [parse_question_list_item(n) for n in _edges(connection) if isinstance(n, dict)]
    return [q for q in items if q], _page_info(connection)["has_next"]


def parse_user_following(data, kind):
    """UserProfileFollowing{People,Topics,Spaces}_ProfileTopics_Query -> (items, has_next)."""
    user = (data or {}).get("user")
    if not isinstance(user, dict) or not user:
        return None, False
    if kind == "people":
        connection = user.get("followingUsersConnection") or {}
        items = [parse_user_card(n) for n in _edges(connection) if isinstance(n, dict)]
    elif kind == "topics":
        connection = user.get("profileTopicsConnection") or {}
        items = [_topic_card(n) for n in _edges(connection) if isinstance(n, dict)]
    else:
        connection = user.get("profileFollowingTribesConnection") or {}
        items = [_space_card(n) for n in _edges(connection) if isinstance(n, dict)]
    return [i for i in items if i], _page_info(connection)["has_next"]


# ---- posts -------------------------------------------------------------------

def parse_post(post):
    if not isinstance(post, dict) or not post:
        return None
    body = qtext(post.get("content")) or qtext(post.get("contentQtextDocument"))
    author = post.get("author") if isinstance(post.get("author"), dict) else None
    tribe = post.get("tribe") if isinstance(post.get("tribe"), dict) else None
    if tribe is None and isinstance(post.get("tribeItem"), dict):
        tribe = post["tribeItem"].get("tribe") if isinstance(post["tribeItem"].get("tribe"), dict) else None
    has_access = post.get("viewerHasAccess")
    return {
        "id": _int(post.get("pid")),
        "title": plain_text(post.get("title")),
        "link": abs_link(post.get("url")),
        "text": body["text"] if body else None,
        "links": body["links"] if body else [],
        "images": body["images"] if body else [],
        "created_at": micros_to_iso(post.get("creationTime")),
        "updated_at": micros_to_iso(post.get("updatedTime")),
        "stats": {
            "upvotes": _int(post.get("numUpvotes")),
            "views": _int(post.get("numViews")),
            "shares": _int(post.get("numShares")),
            "comments": _int(post.get("numDisplayComments")),
        },
        "author": parse_user_card(author, post.get("authorCredential")) if author else None,
        "space": _space_with_link(tribe, post.get("url")) if tribe else None,
        "question": parse_question_card(post.get("question")) if isinstance(post.get("question"), dict) else None,
        "access": _str(post.get("effectiveAccessOption")),
        "is_preview": (has_access is False),
        "is_comments_disabled": _bool(post.get("isCommentsDisabled")),
        "is_deleted": _bool(post.get("isDeleted")),
    }


def _space_with_link(tribe, post_url):
    """A Space card whose link falls back to the post's own host
    (https://<space>.quora.com) when the fragment carries no url."""
    card = _space_card(tribe)
    if card and not card["link"] and isinstance(post_url, str) and ".quora.com/" in post_url:
        host = post_url.split("//", 1)[-1].split("/", 1)[0]
        if host and not host.startswith("www."):
            card["link"] = f"https://{host}"
    return card


def parse_post_page(data):
    """NullspacePostPageLoadableQuery / TribeItemPageLoadableQuery -> the post
    record; None when the pid / tribe item is unknown."""
    data = data or {}
    post = data.get("post")
    if not isinstance(post, dict):
        item = data.get("tribeItem") if isinstance(data.get("tribeItem"), dict) else {}
        post = item.get("post")
    if not isinstance(post, dict) or not post:
        return None
    record = parse_post(post)
    if record and record["space"] is None and isinstance(data.get("tribeItem"), dict):
        tribe = data["tribeItem"].get("tribe")
        record["space"] = _space_card(tribe) if isinstance(tribe, dict) else None
    return record


def parse_user_posts(data):
    user = (data or {}).get("user")
    if not isinstance(user, dict) or not user:
        return None, False
    connection = user.get("postsConnection") or {}
    posts = [parse_post(n) for n in _edges(connection) if isinstance(n, dict)]
    return [p for p in posts if p], _page_info(connection)["has_next"]


# ---- topics ------------------------------------------------------------------

_TOPIC_KINDS = ("academic_topic", "professional_topic", "universal_concept", "named_entity",
                "location", "person", "company_topic", "school", "product_and_services_topic",
                "activity", "one_time_event", "recurring_event", "quora_profile", "adult")


def parse_topic(data):
    """TopicPageLoadableQuery / the topic page -> the topic record; None when
    the tid is unknown."""
    topic = (data or {}).get("topic")
    if not isinstance(topic, dict) or not topic:
        return None
    writers = []
    for item in topic.get("mostViewedAuthors") or []:
        if not isinstance(item, dict) or not isinstance(item.get("user"), dict):
            continue
        card = parse_user_card(item["user"])
        if card:
            card["topic_views"] = _int(item.get("numViews"))
            card["topic_answers"] = _int(item.get("numPublicMostViewedAnswers"))
            writers.append(card)
    related = [_topic_card(t) for t in topic.get("relatedTopics") or [] if isinstance(t, dict)]
    return {
        "id": _int(topic.get("tid")),
        "name": _str(topic.get("name")),
        "link": abs_link(topic.get("url")),
        "image": _str(topic.get("photoUrl")),
        "followers": _int(topic.get("numFollowers")),
        "kinds": [k for k in _TOPIC_KINDS if topic.get(k) is True],
        "is_adult": _bool(topic.get("adult")),
        "is_locked": _bool(topic.get("isLocked")),
        "has_leaderboard": _bool(topic.get("hasLeaderboard")),
        "related_topics": [t for t in related if t],
        "most_viewed_writers": writers,
    }


def parse_feed(data):
    """A multifeed (topic answers, Space posts) -> (items, has_next, cursor,
    bundles seen). Answers and posts are returned in feed order."""
    feed = (data or {}).get("multifeedObject")
    if not isinstance(feed, dict) or not feed:
        return None, False, None, 0
    connection = feed.get("multifeedConnection") or {}
    items = []
    bundles = 0
    for bundle in _edges(connection):
        if not isinstance(bundle, dict):
            continue
        bundles += 1
        stories = list(bundle.get("stories") or [])
        inner = bundle.get("bundleConnection")
        if isinstance(inner, dict):
            stories = _edges(inner) + [s for s in stories if isinstance(s, dict) and ("answer" in s or "post" in s)]
        seen = set()
        for story in stories:
            if not isinstance(story, dict):
                continue
            if isinstance(story.get("answer"), dict):
                parsed = parse_answer(story["answer"])
                key = ("a", parsed["id"]) if parsed else None
            elif isinstance(story.get("post"), dict):
                parsed = parse_post(story["post"])
                key = ("p", parsed["id"]) if parsed else None
            else:
                continue
            if parsed and key not in seen:
                seen.add(key)
                items.append(parsed)
    info = _page_info(connection)
    return items, info["has_next"], info["end_cursor"], bundles


# ---- spaces ------------------------------------------------------------------

_PERMISSION = {4: "owner", 3: "admin", 2: "moderator", 1: "contributor", 0: "follower"}


def parse_space(data):
    """TribeMainPageLoadableQuery / the Space page -> the Space record; None
    when the tribeId is unknown."""
    tribe = (data or {}).get("tribe")
    if not isinstance(tribe, dict) or not tribe:
        return None
    settings = tribe.get("settings") if isinstance(tribe.get("settings"), dict) else {}
    rules = qtext(settings.get("rules"))
    owner = tribe.get("owner") if isinstance(tribe.get("owner"), dict) else None
    tabs = [_str(t.get("tabType")) for t in tribe.get("pageTabs") or [] if isinstance(t, dict)]
    contributors = []
    for item in tribe.get("contributorsOrHigher") or []:
        if isinstance(item, dict) and isinstance(item.get("user"), dict):
            card = parse_user_card(item["user"])
            if card:
                card["role"] = _PERMISSION.get(_int(item.get("permission")))
                contributors.append(card)
    return {
        "id": _int(tribe.get("tribeId")),
        "name": _str(tribe.get("nameString")),
        "link": _str(tribe.get("url")),
        "description": _str(tribe.get("descriptionString")),
        "rules": rules["text"] if rules else None,
        "icon": _str(tribe.get("iconRetinaUrl")) or _str(tribe.get("iconUrl")),
        "cover_image": _str(tribe.get("coverPhotoRetinaUrl")) or _str(tribe.get("coverPhotoUrl")),
        "color": _str(tribe.get("colorHex")),
        "stats": {
            "followers": _int(tribe.get("numFollowers")),
            "members": _int(tribe.get("tribeUserCount")),
            "contributors": _int(tribe.get("numContributors")),
            "moderators": _int(tribe.get("numModerators")),
            "admins": _int(tribe.get("numAdmins")),
            "posts": _int(tribe.get("numItems")),
        },
        "subscription": {
            "is_enabled": _str(tribe.get("producerDirectStatus")) == "enabled",
            "monthly_price_usd": _float(tribe.get("directSubscriptionMonthlyPriceDollar")),
            "yearly_price_usd": _float(tribe.get("directSubscriptionYearlyPriceDollar")),
        },
        "owner": parse_user_card(owner) if owner else None,
        "featured_people": contributors,
        "tabs": [t for t in tabs if t],
        "is_deleted": _bool(tribe.get("isDeleted")),
    }


def _float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _tribe_users(connection):
    out = []
    for node in _edges(connection):
        if not isinstance(node, dict) or not isinstance(node.get("user"), dict):
            continue
        card = parse_user_card(node["user"], node.get("credentialWithDefault"))
        if not card:
            continue
        card["role"] = _PERMISSION.get(_int(node.get("permission")))
        card["last_week"] = {"posts": _int(node.get("numItemsLastWeek")),
                             "views": _int(node.get("numViewsLastWeek")),
                             "upvotes": _int(node.get("numUpvotesLastWeek"))}
        card["posts_last_month"] = _int(node.get("numItemsLastMonth"))
        card["is_subscriber"] = _bool(node.get("isDirectSubscriber"))
        out.append(card)
    return out


def parse_space_people(data):
    """TribeMainPageLoadableQuery with the people tab -> the four role lists."""
    tribe = (data or {}).get("tribe")
    if not isinstance(tribe, dict) or not tribe:
        return None
    return {
        "admins": _tribe_users(tribe.get("tribeAdminList")),
        "moderators": _tribe_users(tribe.get("tribeModeratorList")),
        "contributors": _tribe_users(tribe.get("tribeContributorList")),
        "followers": _tribe_users(tribe.get("tribeFollowerList")),
        "has_more": {
            "admins": _page_info(tribe.get("tribeAdminList"))["has_next"],
            "moderators": _page_info(tribe.get("tribeModeratorList"))["has_next"],
            "contributors": _page_info(tribe.get("tribeContributorList"))["has_next"],
            "followers": _page_info(tribe.get("tribeFollowerList"))["has_next"],
        },
    }


# ---- the server-rendered pages ---------------------------------------------------

_INLINE_RE = re.compile(
    r"timing-(\w+?)(\d*)-end[^;]*;.*?inlineQueryResults\.results\[\"([0-9a-f]+)\"\]\.push\((\"(?:[^\"\\]|\\.)*\")\)",
    re.S)
_VARIABLES_MARK = "inlinedQueryVariables"


def _balanced_json(text, start):
    """The JSON object starting at text[start] == "{" (string-aware)."""
    depth, index, in_string, escaped = 0, start, False, False
    while index < len(text):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
        index += 1
    return None


def inline_results(html):
    """The page's embedded Relay payloads: {QueryName: [payload, ...]} in
    page order (deferred / streamed parts of one query share its name)."""
    out = {}
    for name, _, _, literal in _INLINE_RE.findall(html or ""):
        try:
            text = json.loads(literal)        # the JS string literal
            payload = json.loads(text) if isinstance(text, str) else text
        except ValueError:
            continue
        if isinstance(payload, dict):
            out.setdefault(name, []).append(payload)
    return out


def inline_variables(html):
    """The page's `inlinedQueryVariables`: {QueryName: {variables}}."""
    html = html or ""
    position = html.find(_VARIABLES_MARK)
    while position >= 0:
        start = html.find("{", position + len(_VARIABLES_MARK))
        if start < 0:
            return {}
        text = _balanced_json(html, start)
        if text:
            try:
                value = json.loads(text)
            except ValueError:
                value = None
            if isinstance(value, dict) and value:
                return value
        position = html.find(_VARIABLES_MARK, position + len(_VARIABLES_MARK))
    return {}


def merged_inline_data(html, query_name):
    """The merged `data` tree of one inline query: the root payload with its
    deferred / streamed parts folded in by `path` (same rules as the
    multipart GraphQL responses)."""
    from quora.fetch import _merge_part   # the one merge, shared
    parts = inline_results(html).get(query_name) or []
    root = None
    for part in parts:
        if root is None:
            if part.get("path") or part.get("label"):
                continue
            root = part
            continue
        data = root.get("data")
        if isinstance(data, dict):
            _merge_part(data, part)
    return (root or {}).get("data") or {}
