"""Quora transport: plain curl_cffi with browser-impersonated TLS, no
browser, no login. Everything this package reads is what a logged-out
visitor gets.

Two upstream surfaces (researched 2026-11-03):

  * PAGES    GET www.quora.com/<slug> (question), /profile/<Name>,
             /topic/<Name>, https://<space>.quora.com/ and /<post-slug>,
             /<slug>/answer/<Name>. Server-rendered React pages that embed
             their Relay query results as JSON strings pushed into
             window.ansFrontendGlobals.data.inlineQueryResults.results[<hash>]
             (parsers.inline_results), plus `inlinedQueryVariables` with the
             numeric ids the page resolved from its slug (uid / tid /
             tribeId / aid) — the only slug -> id resolver for users, topics,
             spaces and answer permalinks. An unknown slug answers HTTP 404
             ("Error" title); an unknown Space subdomain 302s to the www
             homepage (fetch_page maps the redirect to NotFound).

  * GRAPHQL  POST www.quora.com/graphql/gql_para_POST?q=<QueryName> with
             Quora's persisted operations: body {queryName, variables,
             extensions: {hash}} (refs.OPS), headers Quora-Formkey +
             Quora-Window-Id read from any page on the same session (the
             session's m-b cookies are the identity). Open logged out for
             every operation this package uses; the site's own search
             (SearchResultsListQuery -> searchConnection null) and typeahead
             are login-only and not served. Operations with @defer / @stream
             answer multipart/mixed; _multipart_data merges the parts back
             into one data tree (path + label semantics of Relay).

Cloudflare: a managed challenge ("Just a moment...", HTTP 403) keyed on the
exit IP and the TLS fingerprint. Only curl_cffi's chrome150 target passes
(chrome136 / safari17_0 / safari184_ios / edge101 / firefox135 are refused on
the SAME exit, 2026-11-03). Pod probe 2026-11-03 (config.py's quora block):
the pod's own IP passes every content page but the homepage; so does one
datacenter port in three and most US residential exits. The homepage is the
most challenged URL on the site, so a session warms on a content page
(WARM_PATH), never on `/`. A block retires the session and the retry rides a
fresh exit (config.QUORA_EXIT_ATTEMPTS tries); after a block on the direct
tier new sessions ride the residential fallback for QUORA_BLOCK_COOLDOWN
seconds (vrbo's ladder).

Sessions live in a process-wide identity_pool.Pool in exclusive mode (since
2026-11-09): a request borrows one for ONE call (a whole cursor walk for
graphql_walk) and hands it back, so the next request on any of the pod's 64
threads reuses its m-b cookies, formkey and window id instead of warming
its own (before, each thread kept a session and warmed it per thread). A
session is retired on a block / transport failure (`dead`), after
QUORA_SESSION_USES calls or QUORA_SESSION_MAX_AGE seconds.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  QuoraUpstreamError  transport failure / 5xx / malformed payload  — retryable
  QuoraBlocked        403 / 429 / the Cloudflare challenge page     — retryable on a fresh exit
  QuoraBadRequest     upstream 400                                 — never retried
  QuoraNotFound       unknown slug / id (HTTP 404, null root)      — never retried
"""
import fastjson
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
import identity_pool
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from quora.refs import OPS, SITE, SITE_HOST
from scraper_utils.pages import page_title

# The generic "chrome" alias maps to a build Cloudflare refuses on some pod
# images (vrbo 2026-11-02); the explicit chrome150 passed every probe.
IMPERSONATE = "chrome150"
PAGE_TIMEOUT = 40       # question pages run to ~280 KB
GRAPHQL_TIMEOUT = 30
BLOCK_RETRY_PAUSE = 0.3   # a block is cured by a fresh exit, not by waiting
# A light content page (96 KB) that carries the formkey + window id a
# GraphQL-only call needs; the homepage is challenged where this is not.
WARM_PATH = "/topic/Machine-Learning"

PAGE_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "upgrade-insecure-requests": "1",
}
GRAPHQL_HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": SITE,
    "referer": SITE + "/",
}

_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)
_FORMKEY_RE = re.compile(r'"formkey":\s*"([0-9a-f]+)"')
_WINDOW_ID_RE = re.compile(r'"windowId":\s*"(\w+)"')
_CHALLENGE_MARKERS = ("just a moment", "cf-chl", "challenge-platform", "attention required")


class QuoraUpstreamError(UpstreamError):
    """Transport failure, 5xx or a malformed payload — retryable."""


class QuoraBlocked(QuoraUpstreamError, Blocked):
    """403 / 429 or the Cloudflare challenge page — retryable on a fresh exit."""


class QuoraBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class QuoraNotFound(NotFound):
    """The question / answer / user / topic / space / post does not exist."""


# ---- pooled sessions ---------------------------------------------------------
# A session keeps its cookie jar (m-b is the logged-out identity the GraphQL
# endpoint expects), its formkey / window id and its sticky exit for its
# lifetime. It owns ONE curl handle, so the pool lends it to one request at a
# time; a retryable failure marks it dead so the retry rides a fresh exit.
# Process-wide: after a block on the direct tier every new session rides the
# residential fallback (config.quora_fallback_proxy()) until this instant.
_fallback_until = 0.0
_fallback_lock = threading.Lock()


def _proxy():
    proxy = config.quora_proxy()
    if proxy is None and time.time() < _fallback_until:
        proxy = config.quora_fallback_proxy()
    return proxy


class _Session(identity_pool.Identity):
    """One curl session on one exit plus the identity it read from its
    first page (formkey, window id). `quora_proxy` is the exit (None =
    the pod's own IP, the direct tier)."""

    def __init__(self, proxy):
        from curl_cffi import requests as curl_requests
        super().__init__(exit=proxy)
        self.curl = curl_requests.Session(impersonate=IMPERSONATE, use_thread_local_curl=False)
        if proxy:
            self.curl.proxies = {"http": proxy, "https": proxy}
        self.curl.headers["accept-language"] = egress.accept_language(proxy)
        self.quora_proxy = proxy
        self.quora_formkey = None
        self.quora_window_id = None
        self.closed = False

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.curl.close()
        except Exception:
            pass


def _mint(key, hint=None):
    """The pool's mint: a cold session on the tier of the moment (warmed by
    its first page, see _warm)."""
    return _Session(_proxy())


_sessions = identity_pool.Pool(
    "quora", _mint, mode="exclusive",
    budget=lambda: config.QUORA_SESSION_USES,
    max_age=lambda: config.QUORA_SESSION_MAX_AGE,
    on_retire=lambda ident, reason: ident.close())


def _note_block(sess):
    """A block on a direct-tier session moves new sessions to the
    residential fallback for QUORA_BLOCK_COOLDOWN seconds."""
    global _fallback_until
    if sess.quora_proxy is None and config.quora_proxy() is None and config.QUORA_BLOCK_COOLDOWN:
        with _fallback_lock:
            _fallback_until = max(_fallback_until, time.time() + config.QUORA_BLOCK_COOLDOWN)


def _on_session(fn):
    """fn(sess) on a borrowed session. A block or any other retryable
    failure marks it dead (retired on give-back, so the retry rides a fresh
    exit); a block also starts the fallback cooldown."""
    sess = _sessions.borrow()
    try:
        return fn(sess)
    except QuoraBlocked:
        _note_block(sess)
        sess.dead = True
        raise
    except QuoraUpstreamError:
        sess.dead = True
        raise
    finally:
        _sessions.give_back(sess)


def _retrying(fn):
    """Run fn() under the retry policy: a block gets config.QUORA_EXIT_ATTEMPTS
    tries on fresh exits with no backoff (the cure is the exit, not time),
    any other upstream failure config.MAX_RETRIES with backoff; NotFound /
    BadRequest surface immediately. The failed call already retired its
    session (_on_session)."""
    last = None
    attempts = max(config.QUORA_EXIT_ATTEMPTS, config.MAX_RETRIES)
    plain_failures = 0
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except QuoraBlocked as e:
            last = e
            if attempt < attempts:
                time.sleep(BLOCK_RETRY_PAUSE)
        except QuoraUpstreamError as e:
            last = e
            plain_failures += 1
            if plain_failures >= config.MAX_RETRIES:
                break
            time.sleep(config.RETRY_BACKOFF * plain_failures)
    raise last


# ---- classification ----------------------------------------------------------


def is_challenge(text):
    head = (text or "")[:4000].lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def is_error_page(text):
    """Quora's own "Error" page (HTTP 404 for unknown slugs)."""
    return page_title(text) == "Error"


def _request(sess, method, url, label, **kw):
    """One request on the session, repeated ONCE on the same session when
    the answer is the Cloudflare challenge: the challenge is often served to
    the first request of a fresh session only (pod probe 2026-11-03: three
    US residential exits refused the warm-up page and passed everything
    after it; Mac: one exit in six). A second refusal is a real block."""
    for attempt in (1, 2):
        try:
            resp = getattr(sess.curl, method)(url, **kw)
        except Exception as e:
            raise QuoraUpstreamError(f"request failed: {type(e).__name__}: {e}")
        if attempt == 1 and resp.status_code in (403, 503) and is_challenge(resp.text):
            time.sleep(BLOCK_RETRY_PAUSE)
            continue
        return resp
    return resp


def _classify(resp, label):
    """Map an HTTP response to the error taxonomy; return the body text."""
    text = resp.text
    if resp.status_code == 404:
        raise QuoraNotFound(f"{label} not found")
    if resp.status_code == 400:
        raise QuoraBadRequest(text[:200])
    if resp.status_code in (401, 403, 429, 503) and is_challenge(text):
        raise QuoraBlocked(f"Cloudflare challenge ({resp.status_code}) for {label}")
    if resp.status_code in (401, 403, 429):
        raise QuoraBlocked(f"HTTP {resp.status_code} for {label}")
    if resp.status_code != 200:
        raise QuoraUpstreamError(f"HTTP {resp.status_code} for {label}")
    if is_challenge(text) and "ansFrontendGlobals" not in text:
        raise QuoraBlocked(f"challenge page for {label}")
    return text


def _remember_identity(sess, html):
    formkey = _FORMKEY_RE.search(html or "")
    window_id = _WINDOW_ID_RE.search(html or "")
    if formkey:
        sess.quora_formkey = formkey.group(1)
    if window_id:
        sess.quora_window_id = window_id.group(1)


# ---- pages -------------------------------------------------------------------

def _host_of(url):
    return (url.split("//", 1)[-1].split("/", 1)[0] or "").lower()


def fetch_page(url, label, not_found_on_home=False):
    """GET a quora.com page -> HTML. `not_found_on_home`: a redirect to the
    www homepage means the entity does not exist (unknown Space subdomain)."""
    def once(sess):
        resp = _request(sess, "get", url, label, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT,
                        allow_redirects=True)
        text = _classify(resp, label)
        if is_error_page(text):
            raise QuoraNotFound(f"{label} not found")
        final = str(resp.url or url)
        if not_found_on_home and _host_of(final) == SITE_HOST and _host_of(url) != SITE_HOST:
            raise QuoraNotFound(f"{label} not found")
        if "ansFrontendGlobals" not in text:
            raise QuoraUpstreamError(f"unexpected page for {label}: {page_title(text)[:80]!r}")
        _remember_identity(sess, text)
        return text
    return _retrying(lambda: _on_session(once))


# ---- GraphQL -----------------------------------------------------------------

def _warm(sess):
    """One content-page load so the session holds its m-b cookies, formkey
    and window id before its first GraphQL call (the homepage is the one
    URL Cloudflare challenges from exits that pass everything else)."""
    if sess.quora_formkey and sess.quora_window_id:
        return
    resp = _request(sess, "get", SITE + WARM_PATH, "warm-up page", headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT)
    text = _classify(resp, "warm-up page")
    _remember_identity(sess, text)
    if not (sess.quora_formkey and sess.quora_window_id):
        raise QuoraUpstreamError("warm-up page carried no formkey / window id")


def _multipart_data(text):
    """A multipart/mixed Relay response (@defer / @stream) -> one data tree.
    Each part is {"data", "label", "path"}: the first is the root; a deferred
    part with path [] merges into the root, a part with a path merges into
    (or is inserted at) that node, like the Relay client does."""
    boundary = text.split("\n", 1)[0].strip()
    if not boundary.startswith("--"):
        raise QuoraUpstreamError("malformed multipart GraphQL response")
    parts = []
    for chunk in text.split(boundary):
        chunk = chunk.strip()
        if not chunk or chunk == "--":
            continue
        body = chunk.split("\n", 1)[1] if chunk.lower().startswith("content-type") else chunk
        body = body.strip()
        if not body.startswith("{"):
            continue
        try:
            parts.append(fastjson.loads(body))
        except ValueError:
            raise QuoraUpstreamError("malformed multipart GraphQL part")
    if not parts:
        raise QuoraUpstreamError("empty multipart GraphQL response")
    root = parts[0]
    data = root.get("data")
    if data is None:
        return root
    for part in parts[1:]:
        _merge_part(data, part)
    return root


def _deep_merge(target, source):
    for key, value in (source or {}).items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def _merge_part(data, part):
    path = part.get("path") or []
    payload = part.get("data")
    if payload is None:
        return
    node = data
    for step in path[:-1]:
        if isinstance(node, dict):
            node = node.get(step)
        elif isinstance(node, list) and isinstance(step, int) and step < len(node):
            node = node[step]
        else:
            return
        if node is None:
            return
    if not path:
        if isinstance(payload, dict):
            _deep_merge(data, payload)
        return
    last = path[-1]
    if isinstance(node, dict):
        if isinstance(node.get(last), dict) and isinstance(payload, dict):
            _deep_merge(node[last], payload)
        else:
            node[last] = payload
    elif isinstance(node, list) and isinstance(last, int):
        if last < len(node):
            if isinstance(node[last], dict) and isinstance(payload, dict):
                _deep_merge(node[last], payload)
            else:
                node[last] = payload
        else:
            node.extend([None] * (last - len(node)))
            node.append(payload)


def parse_graphql_text(text, label="GraphQL"):
    """The response body of a persisted query -> {"data": ...} (plain JSON or
    the merged multipart form). Raises QuoraUpstreamError on GraphQL errors."""
    text = (text or "").lstrip()
    if text.startswith("--"):
        payload = _multipart_data(text)
    else:
        try:
            payload = fastjson.loads(text)
        except ValueError:
            if is_challenge(text):
                raise QuoraBlocked(f"challenge page for {label}")
            raise QuoraUpstreamError(f"non-JSON GraphQL response for {label}: {text[:120]!r}")
    if not isinstance(payload, dict):
        raise QuoraUpstreamError(f"unexpected GraphQL payload for {label}")
    errors = payload.get("errors")
    if errors and payload.get("data") is None:
        message = "; ".join(str((e or {}).get("message", "")) for e in errors if isinstance(e, dict))
        raise QuoraUpstreamError(f"GraphQL error for {label}: {message[:200]}")
    return payload


def graphql(operation, variables, label=None):
    """POST one persisted operation -> its `data` dict (deferred parts merged).
    The borrowed session is warmed on a content page first when it holds no
    formkey yet."""
    label = label or operation
    if operation not in OPS:
        raise ValueError(f"unknown Quora operation {operation}")

    def once(sess):
        return _graphql_once(sess, operation, variables, label)
    return _retrying(lambda: _on_session(once))


def graphql_walk(operation, variables_for, pages, label=None):
    """Page `pages` times through a cursor list whose cursors are only valid
    inside the session that issued them (the multifeed cursors of the topic
    and Space feeds): all hops run on ONE session; a retryable failure
    restarts the whole walk on a fresh exit. `variables_for(cursor, seen)`
    builds the variables of the next hop; returns (data of the last hop,
    cursor of the last hop) through `next_cursor(data) -> (cursor, has_next)`
    supplied by the caller on the variables builder's `.next_cursor`."""
    label = label or operation

    def once(sess):
        cursor, seen = None, 0
        data = {}
        for hop in range(pages):
            data = _graphql_once(sess, operation, variables_for(cursor, seen), label)
            cursor, has_next, count = variables_for.next_cursor(data)
            seen += count
            if hop + 1 < pages and not has_next:
                return {}, False
        return data, True
    return _retrying(lambda: _on_session(once))


def _graphql_once(sess, operation, variables, label):
    """One persisted POST on the borrowed session (no retry: graphql_walk
    retries the whole walk)."""
    _warm(sess)
    headers = dict(GRAPHQL_HEADERS)
    headers["quora-formkey"] = sess.quora_formkey
    headers["quora-window-id"] = sess.quora_window_id
    path = "/graphql/gql_para_POST" if operation.endswith("Query") else "/graphql/gql_POST"
    body = {"queryName": operation, "variables": variables, "extensions": {"hash": OPS[operation]}}
    resp = _request(sess, "post", f"{SITE}{path}?q={operation}", label, json=body, headers=headers,
                    timeout=GRAPHQL_TIMEOUT)
    text = _classify(resp, label)
    return parse_graphql_text(text, label).get("data") or {}
