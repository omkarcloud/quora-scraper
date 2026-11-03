"""The 20 Quora endpoints. Every path is served with and without the `/quora`
prefix, so code generated against the hosted API on RapidAPI (paths like
/questions/answers) runs unchanged against this server.

Params are validated by the marshmallow schemas in quora/schemas.py (ONE param
per input: `question` takes a question ID, URL slug or quora.com link; `answer`
an answer ID or permalink; `user` a user ID, profile name or profile link;
`topic` a topic ID, slug or link; `space` a Space ID, subdomain or link; `post`
a post ID or link); unknown params are rejected."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from quora import api, schemas


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The request query as unicode strings (bottle 0.12's .get() hands back
    latin-1 decoded bytes, so getunicode is mandatory)."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    scheme, host = request.urlparts.scheme, request.urlparts.netloc
    return f"{scheme}://{host}{path}?{urlencode(query, doseq=True)}"


def paginate(result, path, params):
    """Lift the `pagination` block into the flat shape the hosted API
    returns: count / per_page / current_page / total_pages / next / previous.
    Quora publishes no totals, so every list sets `has_next`: total_pages is
    then null and the next link follows has_next."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)   # per-page count; `count` is the total
    page = _as_int(pagination.get("page")) or _as_int(params.get("page")) or 1
    if "has_next" in pagination:
        has_next = bool(pagination["has_next"])
        total_pages = pagination.get("total_pages")
        if total_pages is not None:
            total_pages = _as_int(total_pages, None)
    else:
        total_pages = max(_as_int(pagination.get("total_pages")), 0)
        has_next = page < total_pages
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, params, page + 1 if has_next else None),
        "previous": _page_link(path, params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(label, schema_cls, impl, paginated=False):
    """Validate, run, map errors: bad params -> 400, missing entity -> 404,
    blocks / transport -> 502, anything else -> 500."""
    raw = query_dict()
    data, error = load_query(schema_cls, raw)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"quora rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Blocked as e:
        return json_response({"error": f"quora blocked the request, retry later: {e}"}, 502)
    except UpstreamError as e:
        return json_response({"error": f"quora {label} failed: {e}"}, 502)
    except Exception as e:                 # parser surprises
        return json_response({"error": f"quora {label} failed: {type(e).__name__}: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


ENDPOINTS = [
    ("/questions/answers", schemas.QuestionPageSchema, api.question_answers, True),
    ("/questions/details", schemas.QuestionSchema, api.question_details, False),
    ("/questions/comments", schemas.QuestionPageSchema, api.question_comments, True),
    ("/questions/followers", schemas.QuestionPageSchema, api.question_followers, True),
    ("/answers/details", schemas.AnswerSchema, api.answer_details, False),
    ("/answers/comments", schemas.AnswerPageSchema, api.answer_comments, True),
    ("/answers/upvoters", schemas.AnswerPageSchema, api.answer_upvoters, True),
    ("/users/details", schemas.UserSchema, api.user_details, False),
    ("/users/answers", schemas.UserAnswersSchema, api.user_answers, True),
    ("/users/posts", schemas.UserPageSchema, api.user_posts, True),
    ("/users/questions", schemas.UserPageSchema, api.user_questions, True),
    ("/users/followers", schemas.UserPageSchema, api.user_followers, True),
    ("/users/following", schemas.UserFollowingSchema, api.user_following, True),
    ("/topics/details", schemas.TopicSchema, api.topic_details, False),
    ("/topics/answers", schemas.TopicFeedSchema, api.topic_answers, True),
    ("/spaces/details", schemas.SpaceSchema, api.space_details, False),
    ("/spaces/posts", schemas.SpaceFeedSchema, api.space_posts, True),
    ("/spaces/people", schemas.SpaceSchema, api.space_people, False),
    ("/posts/details", schemas.PostSchema, api.post_details, False),
    ("/posts/comments", schemas.PostPageSchema, api.post_comments, True),
]


def mount(path, schema_cls, impl, paginated):
    """Serve a handler at /path and /quora/path."""
    label = path.strip("/")

    def handler():
        return call(label, schema_cls, impl, paginated)

    handler.__name__ = "quora_" + label.replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/quora" + path, method="GET")(handler)


for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
