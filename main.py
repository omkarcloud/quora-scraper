"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. Params go through the same schemas the API uses, so defaults
are filled in and an ID, a slug or a quora.com link all work.
"""
import json
import os

from quora import api, schemas

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


def run(schema_cls, fn, **params):
    return fn(**schema_cls().load(params))


if __name__ == "__main__":
    # every answer to a question — full text, author, upvotes and views
    save("answers_work_at_spacex.json",
         run(schemas.QuestionPageSchema, api.question_answers, question="What-is-it-like-to-work-at-SpaceX"))

    # the question itself — exact view count, followers, topics and related questions
    save("question_work_at_spacex.json",
         run(schemas.QuestionSchema, api.question_details, question="What-is-it-like-to-work-at-SpaceX"))

    # a full profile — credentials, follower and content counts, expertise topics
    save("user_adam_dangelo.json",
         run(schemas.UserSchema, api.user_details, user="Adam-DAngelo"))
