"""Marshmallow request schemas for every /quora/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair), resolved by quora/refs.py:

    question   a numeric qid, the question's URL slug OR any www.quora.com
               question link (also /unanswered/<slug>, an answer permalink,
               the /log page)
    answer     a numeric aid OR an answer permalink
               (https://www.quora.com/<slug>/answer/<Name>)
    user       a numeric uid, a profile name (Adam-DAngelo) OR a profile link
    topic      a numeric tid, a topic slug (Machine-Learning) OR a topic link
    space      a numeric Space id, a subdomain (humanity) OR the Space link
    post       a numeric pid OR a post link (https://<space>.quora.com/<slug>,
               https://www.quora.com/profile/<Name>/<slug>)

Lists take `page` (1-based). The upstream lists are cursor-paged with no
totals, so responses carry has_next instead of a page count.
"""
from schema_fields import BaseSchema, ChoiceField, PageField, RefField
from quora import refs

# Answer / follower / comment lists: Quora's cursors are plain offsets, so a
# page maps to one upstream call. The feeds (topic answers, Space posts)
# hand out session-bound cursors instead, so page N costs N calls on one
# session — capped lower.
MAX_LIST_PAGE = 200
MAX_FEED_PAGE = 10


class QuestionRefField(RefField):
    resolver = staticmethod(refs.resolve_question)


class AnswerRefField(RefField):
    resolver = staticmethod(refs.resolve_answer)


class UserRefField(RefField):
    resolver = staticmethod(refs.resolve_user)


class TopicRefField(RefField):
    resolver = staticmethod(refs.resolve_topic)


class SpaceRefField(RefField):
    resolver = staticmethod(refs.resolve_space)


class PostRefField(RefField):
    resolver = staticmethod(refs.resolve_post)


_QUESTION = {"description": "question id (116252), its URL slug (What-is-machine-learning) "
                            "or a www.quora.com question link"}
_ANSWER = {"description": "answer id (176847) or an answer permalink "
                          "(https://www.quora.com/<question-slug>/answer/<Author-Name>)"}
_USER = {"description": "user id (335), profile name (Adam-DAngelo) or a profile link "
                        "(https://www.quora.com/profile/Adam-DAngelo)"}
_TOPIC = {"description": "topic id (948), topic slug (Machine-Learning) or a topic link "
                         "(https://www.quora.com/topic/Machine-Learning)"}
_SPACE = {"description": "Space id (1575194), its subdomain (humanity) or its link "
                         "(https://humanity.quora.com/)"}
_POST = {"description": "post id (246876762) or a post link (https://<space>.quora.com/<post-slug>, "
                        "https://www.quora.com/profile/<Name>/<post-slug>)"}


def _page(max_page=MAX_LIST_PAGE, what="results"):
    return PageField(max_page=max_page, metadata={"description": f"page of {what} (1-based)"})


# ---- questions ---------------------------------------------------------------

class QuestionSchema(BaseSchema):
    question = QuestionRefField(metadata=_QUESTION)


class QuestionPageSchema(BaseSchema):
    question = QuestionRefField(metadata=_QUESTION)
    page = _page()


# ---- answers -----------------------------------------------------------------

class AnswerSchema(BaseSchema):
    answer = AnswerRefField(metadata=_ANSWER)


class AnswerPageSchema(BaseSchema):
    answer = AnswerRefField(metadata=_ANSWER)
    page = _page()


# ---- users -------------------------------------------------------------------

class UserSchema(BaseSchema):
    user = UserRefField(metadata=_USER)


class UserPageSchema(BaseSchema):
    user = UserRefField(metadata=_USER)
    page = _page()


class UserAnswersSchema(BaseSchema):
    user = UserRefField(metadata=_USER)
    sort = ChoiceField(["recent", "views"], load_default="recent", metadata={
        "description": "recent (newest first, pinned answers first) or views (most viewed first)"})
    page = _page(what="answers")


class UserFollowingSchema(BaseSchema):
    user = UserRefField(metadata=_USER)
    type = ChoiceField(["people", "topics", "spaces"], load_default="people", metadata={
        "description": "what the user follows: people, topics or spaces"})
    page = _page()


# ---- topics ------------------------------------------------------------------

class TopicSchema(BaseSchema):
    topic = TopicRefField(metadata=_TOPIC)


class TopicFeedSchema(BaseSchema):
    topic = TopicRefField(metadata=_TOPIC)
    page = _page(MAX_FEED_PAGE, "answers")


# ---- spaces ------------------------------------------------------------------

class SpaceSchema(BaseSchema):
    space = SpaceRefField(metadata=_SPACE)


class SpaceFeedSchema(BaseSchema):
    space = SpaceRefField(metadata=_SPACE)
    page = _page(MAX_FEED_PAGE, "posts")


# ---- posts -------------------------------------------------------------------

class PostSchema(BaseSchema):
    post = PostRefField(metadata=_POST)


class PostPageSchema(BaseSchema):
    post = PostRefField(metadata=_POST)
    page = _page()
