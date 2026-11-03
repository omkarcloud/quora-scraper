"""Offline tests for the /quora/* request schemas.

    python -m pytest quora/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quora import schemas  # noqa: E402


def _load(schema, data):
    return schema().load(data)


def test_question_schema_accepts_id_slug_and_links():
    assert _load(schemas.QuestionSchema, {"question": " 116252 "}) == {"question": "116252"}
    assert _load(schemas.QuestionSchema, {"question": "What-is-machine-learning"}) == \
        {"question": "What-is-machine-learning"}
    loaded = _load(schemas.QuestionSchema, {"question": "https://www.quora.com/What-is-machine-learning?share=1"})
    assert loaded == {"question": "What-is-machine-learning"}
    assert loaded["question"].kind == "slug"
    loaded = _load(schemas.QuestionPageSchema, {"question": "116252", "page": "3"})
    assert loaded["page"] == 3 and loaded["question"].kind == "id"


@pytest.mark.parametrize("value", ["", "what is ml", "https://example.com/x", "https://es.quora.com/Que-es"])
def test_question_schema_rejects(value):
    with pytest.raises(ValidationError) as err:
        _load(schemas.QuestionSchema, {"question": value})
    assert "question" in err.value.messages


def test_question_schema_rejects_sibling_params():
    with pytest.raises(ValidationError):
        _load(schemas.QuestionSchema, {"question": "116252", "url": "https://www.quora.com/x"})
    with pytest.raises(ValidationError):
        _load(schemas.QuestionSchema, {})


def test_language_network_link_message():
    with pytest.raises(ValidationError) as err:
        _load(schemas.QuestionSchema, {"question": "https://es.quora.com/Que-es-el-machine-learning"})
    assert "language network" in str(err.value.messages["question"])


def test_answer_schema():
    assert _load(schemas.AnswerSchema, {"answer": "176847"}) == {"answer": "176847"}
    loaded = _load(schemas.AnswerPageSchema, {
        "answer": "https://www.quora.com/What-is-machine-learning/answer/Vaibhav-Mallya"})
    assert loaded["answer"] == "What-is-machine-learning/answer/Vaibhav-Mallya"
    assert loaded["answer"].kind == "path" and loaded["page"] == 1
    with pytest.raises(ValidationError) as err:
        _load(schemas.AnswerSchema, {"answer": "https://www.quora.com/What-is-machine-learning"})
    assert "permalink" in str(err.value.messages["answer"])


def test_user_schema():
    assert _load(schemas.UserSchema, {"user": "335"})["user"].kind == "id"
    assert _load(schemas.UserSchema, {"user": "https://www.quora.com/profile/Adam-DAngelo/posts"}) == \
        {"user": "Adam-DAngelo"}
    loaded = _load(schemas.UserAnswersSchema, {"user": "Adam-DAngelo", "sort": "Views"})
    assert loaded == {"user": "Adam-DAngelo", "sort": "views", "page": 1}
    assert _load(schemas.UserAnswersSchema, {"user": "335"})["sort"] == "recent"
    with pytest.raises(ValidationError) as err:
        _load(schemas.UserAnswersSchema, {"user": "335", "sort": "oldest"})
    assert "sort" in err.value.messages
    loaded = _load(schemas.UserFollowingSchema, {"user": "335", "type": "Spaces", "page": "2"})
    assert loaded == {"user": "335", "type": "spaces", "page": 2}
    assert _load(schemas.UserFollowingSchema, {"user": "335"})["type"] == "people"
    with pytest.raises(ValidationError):
        _load(schemas.UserFollowingSchema, {"user": "335", "type": "questions"})
    with pytest.raises(ValidationError):
        _load(schemas.UserSchema, {"user": "adam d'angelo"})


def test_topic_space_post_schemas():
    assert _load(schemas.TopicSchema, {"topic": "https://www.quora.com/topic/Machine-Learning"}) == \
        {"topic": "Machine-Learning"}
    loaded = _load(schemas.TopicFeedSchema, {"topic": "948", "page": "10"})
    assert loaded["page"] == 10
    with pytest.raises(ValidationError) as err:
        _load(schemas.TopicFeedSchema, {"topic": "948", "page": "11"})
    assert "page" in err.value.messages
    assert _load(schemas.SpaceSchema, {"space": "https://humanity.quora.com/"}) == {"space": "humanity"}
    assert _load(schemas.SpaceFeedSchema, {"space": "Humanity"}) == {"space": "humanity", "page": 1}
    with pytest.raises(ValidationError):
        _load(schemas.SpaceSchema, {"space": "https://www.quora.com/What-is-machine-learning"})
    assert _load(schemas.PostSchema, {"post": "https://quorablog.quora.com/Update"}) == \
        {"post": "https://quorablog.quora.com/Update"}
    assert _load(schemas.PostPageSchema, {"post": "246876762", "page": "2"}) == {"post": "246876762", "page": 2}
    with pytest.raises(ValidationError):
        _load(schemas.PostSchema, {"post": "Update"})


def test_page_bounds():
    with pytest.raises(ValidationError):
        _load(schemas.QuestionPageSchema, {"question": "116252", "page": "0"})
    with pytest.raises(ValidationError):
        _load(schemas.QuestionPageSchema, {"question": "116252", "page": "201"})
    with pytest.raises(ValidationError):
        _load(schemas.QuestionPageSchema, {"question": "116252", "page": "two"})


def test_every_field_is_documented():
    for name in dir(schemas):
        cls = getattr(schemas, name)
        if isinstance(cls, type) and issubclass(cls, schemas.BaseSchema) and cls is not schemas.BaseSchema:
            for field_name, field in cls().fields.items():
                assert field.metadata.get("description"), f"{name}.{field_name} has no description"
