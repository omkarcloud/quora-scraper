"""quora/fetch.py on the pooled sessions: no network (a fake curl session
inside a real fetch._Session; the pool's mint is faked).

    python -m pytest quora/test_fetch.py -q
"""
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quora import fetch  # noqa: E402
from scraper_utils.testing import hosted_only

OP = "QuestionPageHeaderSectionQuery"
WARM_HTML = ('<html><title>Topic</title><script>window.ansFrontendGlobals = {"formkey": "abc123", '
             '"windowId": "w1"}</script></html>')
CHALLENGE = "<html><title>Just a moment...</title><div id='cf-chl'></div></html>"


class Resp:
    def __init__(self, status=200, text="", url="https://www.quora.com/x"):
        self.status_code, self.text, self.url = status, text, url


class FakeCurl:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kw):
        self.calls.append(("GET", url))
        return self.responses.pop(0)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw.get("headers") or {}))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


@pytest.fixture
def pool(monkeypatch):
    monkeypatch.setattr(fetch.config, "QUORA_EXIT_ATTEMPTS", 1)
    monkeypatch.setattr(fetch.config, "MAX_RETRIES", 1)
    monkeypatch.setattr(fetch.config, "quora_proxy", lambda: None)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    monkeypatch.setattr(fetch, "_fallback_until", 0.0)
    queue, minted = [], []

    def fake_mint(key, hint=None):
        sess = fetch._Session(None)
        sess.curl.close()
        sess.curl = FakeCurl(queue.pop(0) if queue else [])
        minted.append(sess)
        return sess

    p = fetch._sessions
    p.clear()
    p._mint_fn = fake_mint
    p.minted = minted
    p.script = lambda *per_session: queue.extend(list(r) for r in per_session)
    yield p
    p.clear()
    p._mint_fn = fetch._mint


@hosted_only
def test_three_threads_share_one_warmed_session_and_a_block_retires_it(pool):
    """Three sequential GraphQL calls on three different threads ride ONE
    pooled session: the warm-up page (formkey + window id) is loaded once
    (before: once per thread). A Cloudflare challenge then retires it
    (closed, nothing idle) and starts the direct-tier fallback cooldown."""
    pool.script([Resp(text=WARM_HTML)] + [Resp(text='{"data": {"n": %d}}' % i) for i in (1, 2, 3)]
                + [Resp(status=403, text=CHALLENGE), Resp(status=403, text=CHALLENGE)])
    results = []
    for _ in range(3):
        t = threading.Thread(target=lambda: results.append(fetch.graphql(OP, {})))
        t.start()
        t.join()
    assert results == [{"n": 1}, {"n": 2}, {"n": 3}]
    assert len(pool.minted) == 1
    sess = pool.minted[0]
    assert sess.curl.calls[0] == ("GET", "https://www.quora.com" + fetch.WARM_PATH)
    assert [c[0] for c in sess.curl.calls].count("GET") == 1 and sess.quora_formkey == "abc123"
    assert all(c[2]["quora-formkey"] == "abc123" and c[2]["quora-window-id"] == "w1" for c in sess.curl.calls[1:])
    assert pool.stats()["idle"] == 1 and not sess.closed
    with pytest.raises(fetch.QuoraBlocked):     # challenged twice on the same session = a real block
        fetch.graphql(OP, {})
    assert sess.dead and sess.closed and pool.stats()["idle"] == 0
    assert fetch._fallback_until > 0


def test_cursor_walk_runs_on_one_session(pool):
    pool.script([Resp(text=WARM_HTML), Resp(text='{"data": {"c": "a"}}'), Resp(text='{"data": {"c": "b"}}')])

    def variables_for(cursor, seen):
        return {"after": cursor}
    variables_for.next_cursor = lambda data: (data["c"], True, 1)
    data, complete = fetch.graphql_walk(OP, variables_for, 2)
    assert data == {"c": "b"} and complete and len(pool.minted) == 1
    assert len(pool.minted[0].curl.calls) == 3
