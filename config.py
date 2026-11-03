"""Configuration for the Quora Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT          port the API listens on (default 8000)
    QUORA_PROXY   proxy URL for every request, e.g. http://user:pass@host:port
                  (default: none — direct). quora.com answers most home and
                  office connections; if one starts answering 403 "Just a
                  moment..." to every call, Cloudflare has flagged its IP —
                  point QUORA_PROXY at a residential proxy and requests leave
                  through it.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# A blocked request (Cloudflare's challenge page) is retried this many times
# on a fresh session.
QUORA_EXIT_ATTEMPTS = 3

# The hosted service moves to a pool of residential exits for a while after
# a block; this kit has one connection, so it stays on it (0 = no fallback
# window).
QUORA_BLOCK_COOLDOWN = 0

QUORA_PROXY = os.environ.get("QUORA_PROXY") or None


def quora_proxy():
    """The proxy for one curl session (None = direct)."""
    return os.environ.get("QUORA_PROXY") or None


def quora_fallback_proxy():
    """The exit used after a block (None = keep the same connection)."""
    return os.environ.get("QUORA_PROXY") or None
