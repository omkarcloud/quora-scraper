"""The one network helper the quora module needs: the Accept-Language its
sessions send. Requests go out direct from your own connection (or through
QUORA_PROXY), so every session announces the plain English list a desktop
browser sends for www.quora.com, the English site."""

ACCEPT_LANGUAGE = "en-US,en;q=0.9"


def site_accept_language(site=None):
    return ACCEPT_LANGUAGE


def accept_language(proxy=None, country=None):
    return ACCEPT_LANGUAGE
