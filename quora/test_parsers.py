"""Offline tests for the Quora parsers, reference resolvers, the multipart
GraphQL merge and the page classifiers.

    python -m pytest quora/test_parsers.py -q

Fixtures are real www.quora.com pages / GraphQL payloads captured
2026-11-03 (quora/fixtures/, listed in parsers.py's docstring). No network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quora import parsers as P, refs  # noqa: E402
from quora.fetch import is_challenge, is_error_page, page_title, parse_graphql_text  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


def gql(name):
    """The `data` tree of a GraphQL fixture (plain JSON or multipart)."""
    text = fixture(name) if name.endswith(".multipart") else None
    if text is not None:
        return parse_graphql_text(text, name)["data"]
    return fixture(name)["data"]


# ---- refs ---------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected,kind", [
    ("116252", "116252", "id"),
    ("What-is-machine-learning", "What-is-machine-learning", "slug"),
    ("https://www.quora.com/What-is-machine-learning", "What-is-machine-learning", "slug"),
    ("https://www.quora.com/unanswered/How-can-we-learn-Python-for-intermediate-coders",
     "How-can-we-learn-Python-for-intermediate-coders", "slug"),
    ("https://www.quora.com/What-is-machine-learning/answer/Some-One?share=1", "What-is-machine-learning", "slug"),
    ("https://quora.com/What-is-machine-learning/log", "What-is-machine-learning", "slug"),
])
def test_resolve_question(value, expected, kind):
    ref = refs.resolve_question(value)
    assert ref == expected and ref.kind == kind


@pytest.mark.parametrize("value", [
    "", "what is ml", "https://example.com/What-is-machine-learning",
    "https://humanity.quora.com/She-was-the-quiet-strength", "https://es.quora.com/Que-es-el-machine-learning",
    "https://www.quora.com/profile/Adam-DAngelo", "profile",
])
def test_resolve_question_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_question(value)


@pytest.mark.parametrize("value,expected,kind", [
    ("176847", "176847", "id"),
    ("https://www.quora.com/What-is-machine-learning/answer/Vaibhav-Mallya",
     "What-is-machine-learning/answer/Vaibhav-Mallya", "path"),
    ("What-is-machine-learning/answer/Vaibhav-Mallya", "What-is-machine-learning/answer/Vaibhav-Mallya", "path"),
    ("https://www.quora.com/What-is-machine-learning/answers/1477743883240664", "1477743883240664", "id"),
    # Quora's own permaUrl for some answers carries a handle segment (2026-11-03)
    ("https://www.quora.com/What-is-it-like-to-work-at-Google-What-are-the-culture-people-and-benefits-like"
     "/answer/ix_/Ashish-Kedia",
     "What-is-it-like-to-work-at-Google-What-are-the-culture-people-and-benefits-like/answer/ix_/Ashish-Kedia", "path"),
    ("https://www.quora.com/What-is-machine-learning/answer/Vaibhav-Mallya/log",
     "What-is-machine-learning/answer/Vaibhav-Mallya", "path"),
    ("What-is-machine-learning/answer/ix_/Ashish-Kedia", "What-is-machine-learning/answer/ix_/Ashish-Kedia", "path"),
])
def test_resolve_answer(value, expected, kind):
    ref = refs.resolve_answer(value)
    assert ref == expected and ref.kind == kind


@pytest.mark.parametrize("value", ["", "Vaibhav-Mallya", "https://www.quora.com/What-is-machine-learning",
                                   "https://example.com/x/answer/y"])
def test_resolve_answer_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_answer(value)


@pytest.mark.parametrize("value,expected,kind", [
    ("335", "335", "id"),
    ("Adam-DAngelo", "Adam-DAngelo", "name"),
    ("https://www.quora.com/profile/Adam-DAngelo", "Adam-DAngelo", "name"),
    ("https://www.quora.com/profile/Adam-DAngelo/answers?x=1", "Adam-DAngelo", "name"),
])
def test_resolve_user(value, expected, kind):
    ref = refs.resolve_user(value)
    assert ref == expected and ref.kind == kind


@pytest.mark.parametrize("value", ["", "adam d'angelo", "https://www.quora.com/topic/Machine-Learning"])
def test_resolve_user_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_user(value)


def test_resolve_topic_space_post():
    assert refs.resolve_topic("948").kind == "id"
    assert refs.resolve_topic("https://www.quora.com/topic/Machine-Learning/writers") == "Machine-Learning"
    assert refs.resolve_space("https://humanity.quora.com/people") == "humanity"
    assert refs.resolve_space("Humanity") == "humanity"
    assert refs.resolve_space("humanity.quora.com") == "humanity"
    assert refs.resolve_space("1575194").kind == "id"
    assert refs.resolve_post("246876762").kind == "id"
    assert refs.resolve_post("https://quorablog.quora.com/Update?ch=1") == "https://quorablog.quora.com/Update"
    assert refs.resolve_post("https://www.quora.com/profile/Adam-DAngelo/We-re-going-2") == \
        "https://www.quora.com/profile/Adam-DAngelo/We-re-going-2"
    for bad in ("", "https://www.quora.com/", "https://www.quora.com/profile/Adam-DAngelo/answers"):
        with pytest.raises(ValueError):
            refs.resolve_post(bad)
    for bad in ("", "https://www.quora.com/What-is-machine-learning", "www"):
        with pytest.raises(ValueError):
            refs.resolve_space(bad)


# ---- scalars / qtext ----------------------------------------------------------------------

def test_micros_to_iso():
    assert P.micros_to_iso(1292034641948342) == "2010-12-11T02:30:41Z"
    assert P.micros_to_iso("1292034641948342") == "2010-12-11T02:30:41Z"
    assert P.micros_to_iso(0) is None
    assert P.micros_to_iso(None) is None
    assert P.micros_to_iso("x") is None


def test_qtext_lists_links_images():
    doc = {"sections": [
        {"spans": [{"text": "Intro", "modifiers": {}}], "type": "plain"},
        {"spans": [{"text": "one", "modifiers": {}}], "type": "unordered-list"},
        {"spans": [{"text": "see ", "modifiers": {}},
                   {"text": "Q", "modifiers": {"link": {"type": "question", "url": "https://www.quora.com/Q"}}}],
         "type": "ordered-list"},
        {"spans": [{"text": "", "modifiers": {"image": "https://qph.cf2.quoracdn.net/x-lq",
                                                 "master_url": "https://qph.cf2.quoracdn.net/x"}}], "type": "plain"},
    ]}
    out = P.qtext(json.dumps(doc))
    assert out["text"] == "Intro\n- one\n1. see Q"
    assert out["links"] == [{"text": "Q", "link": "https://www.quora.com/Q", "type": "question"}]
    assert out["images"] == ["https://qph.cf2.quoracdn.net/x"]
    assert P.qtext(None) is None
    assert P.qtext("") is None
    assert P.qtext({"legacyJson": json.dumps(doc)})["images"] == ["https://qph.cf2.quoracdn.net/x"]
    assert P.plain_text("just text") == "just text"


# ---- questions ----------------------------------------------------------------------------

def test_question_header_multipart_merge():
    data = gql("gql_question_header.multipart")
    record = P.parse_question_header(data)
    assert record["id"] == 109931
    assert record["slug"] == "What-is-machine-learning"
    assert record["title"] == "What is machine learning?"
    assert record["link"] == "https://www.quora.com/What-is-machine-learning"
    # the deferred subheader part carries the counts and the topic list
    assert record["stats"]["followers"] is not None
    assert record["stats"]["answers"] is not None
    assert any(t["name"] == "Machine Learning" and t["id"] == 948 for t in record["topics"])
    assert record["is_locked"] is False


def test_question_by_qid_resolves_slug():
    data = gql("gql_question_by_qid.multipart")
    assert data["question"] is None
    assert data["redirectedQuestion"]["slug"] == "What-is-machine-learning"
    record = P.parse_question_header(data)
    assert record["id"] == 109931 and record["slug"] == "What-is-machine-learning"


def test_question_not_found_header():
    data = gql("gql_not_found_question.multipart")
    assert P.parse_question_header(data) is None


def test_question_sidebar_and_log():
    side = P.parse_question_sidebar(gql("gql_question_sidebar.json"))
    assert side["answers_including_related"] == 60
    assert len(side["related_questions"]) == 6
    assert side["related_questions"][0]["id"] and side["related_questions"][0]["title"]
    assert side["related_questions"][0]["link"].startswith("https://www.quora.com/")
    log = P.parse_question_log(gql("gql_question_log.json"))
    assert log["views"] == 13026
    assert log["followers"] == 55
    assert log["merged_questions"] == 1
    assert log["created_at"] == "2010-12-11T02:30:41Z"
    assert log["asker"]["name"] == "Jackson Bierfeldt" and log["asker"]["id"] == 362388
    assert P.parse_question_log({"contentObject": None}) == {}


def test_question_answers_pages():
    answers, has_next, head = P.parse_question_answers(gql("gql_question_answers_page1.json"))
    assert has_next is True
    assert head["id"] == 116252
    assert [a["id"] for a in answers] == [176847, 1477743883240664, 10594440, 126256368, 22329188]
    first = answers[0]
    assert first["relation"] == "direct"
    assert first["author"]["name"] == "Vaibhav Mallya"
    assert first["author"]["link"] == "https://www.quora.com/profile/Vaibhav-Mallya"
    assert first["stats"] == {"upvotes": 53, "views": 11675, "shares": 2, "comments": 1}
    assert first["created_at"] == "2010-12-11T02:55:39Z"
    assert first["text"].startswith("It sounds like you've already finished Step 1")
    assert any(l["type"] == "question" for l in first["links"])
    assert first["link"].endswith("/answer/Vaibhav-Mallya")
    assert first["is_ai_generated"] is False and first["is_preview"] is False
    ai = answers[1]
    assert ai["relation"] == "ai" and ai["is_ai_generated"] is True
    related = answers[3]
    assert related["relation"] in ("related", "equivalent")
    assert related["question"]["id"] == 34854024
    assert related["related_question"]["id"] == 34854024
    page2, has_next2, _ = P.parse_question_answers(gql("gql_question_answers_page2.json"))
    assert has_next2 is True and page2 and page2[0]["id"] not in {a["id"] for a in answers}


def test_question_answers_not_found():
    assert P.parse_question_answers(gql("gql_not_found_question_answers.json")) == (None, False, None)


# ---- answers / comments / users lists --------------------------------------------------

def test_answer_page():
    record = P.parse_answer_page(gql("gql_answer.json"))
    assert record["id"] == 176847
    assert record["stats"]["views"] == 11675 and record["stats"]["upvotes"] == 53
    assert record["question"]["id"] == 116252
    assert record["author"]["name"] == "Vaibhav Mallya"
    assert record["access"] == "free"
    assert P.parse_answer_page(gql("gql_not_found_answer.json")) is None


def test_comments():
    comments, has_next, container = P.parse_comments(gql("gql_answer_comments.json"))
    assert container == "Answer" and has_next is False
    assert len(comments) == 1
    c = comments[0]
    assert c["id"] == 139151
    assert c["text"] == "Thank you! I'll be sure to check out those PEP guides."
    assert c["author"]["id"] == 362388 and c["author"]["name"] == "Jackson Bierfeldt"
    assert c["created_at"] == "2010-12-11T02:58:17Z"
    assert c["replies"] == [] and c["has_more_replies"] is False
    assert c["upvotes"] == 0
    comments, _, container = P.parse_comments(gql("gql_question_comments.json"))
    assert container == "Question" and comments
    comments, has_next, container = P.parse_comments(gql("gql_post_comments_empty.json"))
    assert comments == [] and has_next is False and container == "Post"
    assert P.parse_comments(gql("gql_not_found_comments.json")) == (None, False, None)
    replies, has_next = P.parse_comment_replies(gql("gql_comment_replies.json"))
    assert replies == [] and has_next is False


def test_user_lists():
    users, has_next = P.parse_user_list(gql("gql_question_followers.json"), "question", "followersConnection")
    assert has_next is True and len(users) == 10
    assert users[0]["id"] == 362388 and users[0]["credential"] == "worked at University of Chicago"
    assert users[0]["followers"] == 177
    users, has_next = P.parse_user_list(gql("gql_answer_upvoters.json"), "node", "upvotersConnection")
    assert has_next is True and users[0]["id"] == 3187899677
    assert users[0]["credential"] == "Studying FRM from Quintedge"
    assert P.parse_user_list(gql("gql_not_found_user.json"), "user", "followerUsersConnection") == (None, False)
    users, has_next = P.parse_user_list(gql("gql_user_followers.json"), "user", "followerUsersConnection")
    assert users[0]["id"] == 3120675443 and users[0]["name"] == "Courtney Shanelle"


def test_user_record():
    record = P.parse_user(gql("gql_user.json")["user"])
    assert record["id"] == 335
    assert record["name"] == "Adam D'Angelo"
    assert record["link"] == "https://www.quora.com/profile/Adam-DAngelo"
    assert record["credential"] == "Quora CEO"
    assert record["credentials"]["profile"] == "Quora CEO"
    assert record["credentials"]["work"][0]["position"] == "CEO"
    assert record["credentials"]["work"][0]["company"] == "Quora (company)"
    assert record["credentials"]["work"][0]["is_current"] is True
    assert record["credentials"]["locations"][0]["location"] == "Mountain View, CA"
    assert record["stats"]["followers"] == 545911
    assert record["stats"]["following"] == 699
    assert record["stats"]["answers"] == 998
    assert record["stats"]["questions"] == 1053
    assert record["stats"]["posts"] == 212
    assert record["stats"]["content_views"] == 42677249
    assert record["top_writer_years"] == [2018, 2017, 2016, 2015, 2014, 2013]
    assert record["publishers"] == ["Forbes"]
    assert record["knows_about"][0]["name"] == "Computer Science" and record["knows_about"][0]["answers"] == 64
    assert record["spaces"][0]["name"] == "Travel Illustrated"
    assert record["is_verified"] is True and record["is_anonymous"] is False
    assert record["joined_at"] == "2009-10-05T23:20:05Z"
    assert record["bio"] is None   # an empty qtext document
    assert P.parse_user(gql("gql_not_found_user.json")["user"]) is None


def test_user_answers_posts_questions():
    answers, has_next = P.parse_user_answers(gql("gql_user_answers_recent.json"))
    assert has_next is True and len(answers) == 20
    assert answers[0]["id"] == 309711880
    assert answers[0]["question"]["id"] == 100826960
    assert answers[0]["link"].startswith("https://quoraleadership.quora.com/")
    assert answers[0]["stats"]["views"] == 30205
    assert P.parse_user_answers(gql("gql_not_found_user.json")) == (None, False)
    posts, has_next = P.parse_user_posts(gql("gql_user_posts.json"))
    assert has_next is True and posts[0]["id"] == 246876762
    assert posts[0]["title"] == "Update"
    assert posts[0]["space"]["name"] == "The Quora Blog"
    assert posts[0]["stats"]["views"] == 45814
    questions, has_next = P.parse_user_questions(gql("gql_user_questions.json"))
    assert has_next is True and questions[0]["id"] == 113951779
    assert questions[0]["answers"] == 23 and questions[0]["followers"] == 12
    assert questions[0]["created_at"] == "2022-03-23T16:35:42Z"


def test_user_following():
    people, has_next = P.parse_user_following(gql("gql_user_following_people.json"), "people")
    assert people[0]["id"] == 939583965
    topics, _ = P.parse_user_following(gql("gql_user_following_topics.json"), "topics")
    assert topics[0] == {"id": 2379, "name": "Technology Companies",
                         "link": "https://www.quora.com/topic/Technology-Companies",
                         "image": topics[0]["image"], "followers": 1645810}
    spaces, has_next = P.parse_user_following(gql("gql_user_following_spaces.json"), "spaces")
    assert has_next is True and spaces[0]["id"] == 6428921 and spaces[0]["name"] == "Quora Knowledge Contests"
    assert spaces[0]["link"] == "https://contests.quora.com"
    assert P.parse_user_following(gql("gql_not_found_user.json"), "topics") == (None, False)


# ---- topics / spaces / posts -------------------------------------------------------------

def test_topic():
    record = P.parse_topic(gql("gql_topic.json"))
    assert record["id"] == 948 and record["name"] == "Machine Learning"
    assert record["link"] == "https://www.quora.com/topic/Machine-Learning"
    assert record["followers"] == 2491347
    assert "academic_topic" in record["kinds"] and "adult" not in record["kinds"]
    assert len(record["most_viewed_writers"]) == 10
    writer = record["most_viewed_writers"][0]
    assert writer["id"] == 78281907 and writer["name"] == "Terry Lambert"
    assert writer["topic_views"] == 38941 and writer["topic_answers"] == 508
    assert P.parse_topic(gql("gql_not_found_topic.json")) is None


def test_topic_feed():
    items, has_next, cursor, bundles = P.parse_feed(gql("gql_topic_answers.json"))
    assert has_next is True and cursor and bundles == 10
    assert len(items) == 10
    assert items[0]["id"] == 1477743916640439
    assert items[0]["question"]["id"] == 227610821 and items[0]["question"]["answers"] == 17
    assert items[0]["stats"]["comments"] == 83
    assert P.parse_feed({"multifeedObject": None}) == (None, False, None, 0)


def test_space_record_and_people():
    record = P.parse_space(gql("gql_space_people.json"))
    assert record["id"] == 1575194 and record["name"] == "Humanity"
    assert record["link"] == "https://humanity.quora.com"
    assert record["stats"]["followers"] == 331954 and record["stats"]["members"] == 332679
    assert record["stats"]["admins"] == 14 and record["stats"]["contributors"] == 704
    assert record["subscription"]["monthly_price_usd"] == 1.0
    assert record["rules"] is None or isinstance(record["rules"], str)
    assert record["featured_people"] and record["featured_people"][0]["role"] in ("admin", "moderator", "contributor", "owner")
    people = P.parse_space_people(gql("gql_space_people.json"))
    assert len(people["admins"]) == 14 and len(people["moderators"]) == 5
    assert len(people["contributors"]) == 20 and len(people["followers"]) == 20
    assert people["has_more"]["followers"] is True and people["has_more"]["admins"] is False
    assert people["admins"][0]["role"] == "admin" and "last_week" in people["admins"][0]
    assert P.parse_space(gql("gql_not_found_space.json")) is None
    assert P.parse_space_people(gql("gql_not_found_space.json")) is None


def test_space_feed_and_posts():
    items, has_next, cursor, bundles = P.parse_feed(gql("gql_space_posts.json"))
    assert bundles == 20 and has_next is True
    assert items[0]["id"] == 258386231
    assert items[0]["author"]["name"] == "Saum Prad"
    assert items[0]["space"]["name"] == "Humanity"
    post = P.parse_post_page(gql("gql_post.json"))
    assert post["id"] == 246876762 and post["title"] == "Update"
    assert post["stats"] == {"upvotes": 273, "views": 45814, "shares": 29, "comments": 0}
    assert post["author"]["id"] == 335
    assert post["space"]["name"] == "The Quora Blog" and post["space"]["link"] == "https://quorablog.quora.com"
    assert post["created_at"] == "2026-04-16T22:09:57Z"
    assert post["is_comments_disabled"] is True
    assert post["text"].startswith("Today is a hard day at Quora.")
    space_post = P.parse_post_page(gql("gql_space_post.json"))
    assert space_post["id"] == 258386231 and space_post["space"]["id"] == 1575194
    assert P.parse_post_page(gql("gql_not_found_post.json")) is None


# ---- the server-rendered pages -------------------------------------------------------------

def test_inline_results_and_variables_profile_page():
    html = fixture("page_profile.html")
    assert P.inline_variables(html)["UserProfilePageLoadableQuery"]["uid"] == 335
    data = P.merged_inline_data(html, "UserProfilePageLoadableQuery")
    record = P.parse_user(data["user"])
    assert record["id"] == 335 and record["name"] == "Adam D'Angelo"
    assert record["stats"]["followers"] == 545911


def test_question_page_inline():
    html = fixture("page_question.html")
    header = P.parse_question_header(P.merged_inline_data(html, "QuestionPageHeaderSectionQuery"))
    assert header["id"] == 116252
    assert header["stats"]["followers"] == 55 and header["stats"]["answers"] == 4
    assert header["topics"] and header["topics"][0]["id"]
    area = P.merged_inline_data(html, "QuestionAnswerAreaSectionQuery")
    answers, has_next, head = P.parse_question_answers(area)
    assert has_next is True and head["id"] == 116252
    assert [a["id"] for a in answers][:2] == [176847, 1477743883240664]
    assert {a["relation"] for a in answers} >= {"direct", "ai"}


def test_unanswered_question_page_has_only_related_answers():
    html = fixture("page_question_unanswered.html")
    header = P.parse_question_header(P.merged_inline_data(html, "QuestionPageHeaderSectionQuery"))
    assert header["id"] == 83173335 and header["stats"]["answers"] == 0
    answers, _, _ = P.parse_question_answers(P.merged_inline_data(html, "QuestionAnswerAreaSectionQuery"))
    assert answers and all(a["relation"] in ("related", "equivalent") for a in answers)


def test_topic_space_answer_and_post_pages():
    topic = P.parse_topic(P.merged_inline_data(fixture("page_topic.html"), "TopicPageLoadableQuery"))
    assert topic["id"] == 948 and len(topic["most_viewed_writers"]) == 10
    html = fixture("page_space.html")
    assert P.inline_variables(html)["TribeMainPageLoadableQuery"]["tribeId"] == 1575194
    space = P.parse_space(P.merged_inline_data(html, "TribeMainPageLoadableQuery"))
    assert space["id"] == 1575194 and space["stats"]["posts"] == 125051
    answer = P.parse_answer_page(P.merged_inline_data(fixture("page_answer.html"), "AnswerPageLoadableQuery"))
    assert answer["id"] == 176847 and answer["author"]["name"] == "Vaibhav Mallya"
    post = P.parse_post_page(P.merged_inline_data(fixture("page_space_post.html"), "TribeItemPageLoadableQuery"))
    assert post["id"] == 236224913 and post["space"]["name"] == "The Quora Blog"
    assert post["stats"]["views"] == 56428
    profile_post = P.parse_post_page(
        P.merged_inline_data(fixture("page_profile_post.html"), "NullspacePostPageLoadableQuery"))
    assert profile_post["id"] and profile_post["author"]["id"] == 335


def test_page_classifiers():
    assert page_title(fixture("page_not_found.html")) == "Error"
    assert is_error_page(fixture("page_not_found.html"))
    assert is_challenge(fixture("page_challenge.html"))
    assert not is_challenge(fixture("page_topic.html"))
    assert P.inline_results(fixture("page_not_found.html")).get("UserProfilePageLoadableQuery") is None
    assert P.merged_inline_data(fixture("page_challenge.html"), "TopicPageLoadableQuery") == {}


def test_parse_graphql_text_plain_and_errors():
    assert parse_graphql_text('{"data": {"x": 1}}')["data"] == {"x": 1}
    with pytest.raises(Exception):
        parse_graphql_text('{"errors": [{"message": "Server Error"}], "data": null}')
    with pytest.raises(Exception):
        parse_graphql_text("<html>Just a moment...</html>")
