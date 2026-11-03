"""Cache TTL per /quora/* endpoint (cache.py, keyed on the validated params).
Quora content is slow-moving: answers and posts gain views and upvotes
over days, profiles and topics change rarely, lists reorder as new content
lands. Endpoints that slice one upstream record share ONE cached record
(quora/api.py): question details + answers + comments + followers share the
question's resolved id, the answer endpoints share the answer record, the
user endpoints the profile record, and so on.
"""
from datetime import timedelta

# One row per question: header + sidebar + log merged (views, followers, topics).
QUESTION_CACHE = timedelta(hours=6)
# A page of answers: upvote / view counts drift slowly; new answers are rare.
ANSWERS_CACHE = timedelta(hours=6)
# Comments on a question / answer / post: short threads, new comments are rare.
COMMENTS_CACHE = timedelta(hours=6)
# Follower / upvoter lists: append-only, reorder slowly.
FOLLOWERS_CACHE = timedelta(hours=12)
# The answer record (text + counts), also the aid behind a permalink.
ANSWER_CACHE = timedelta(hours=6)
# The profile record (also the uid behind a profile name).
USER_CACHE = timedelta(hours=12)
# A user's answers / posts / questions / following lists.
USER_LISTS_CACHE = timedelta(hours=6)
# The topic record: name, followers, top writers (a weekly leaderboard).
TOPIC_CACHE = timedelta(hours=24)
# The topic answer feed: Quora re-ranks it, but the top of it moves slowly.
TOPIC_FEED_CACHE = timedelta(hours=3)
# The Space record (also the tribeId behind a subdomain).
SPACE_CACHE = timedelta(hours=12)
# The Space post feed: new posts land daily on active Spaces.
SPACE_FEED_CACHE = timedelta(hours=2)
# The Space people lists: weekly stats per member.
SPACE_PEOPLE_CACHE = timedelta(hours=12)
# The post record (text + counts), also the pid behind a post link.
POST_CACHE = timedelta(hours=6)
