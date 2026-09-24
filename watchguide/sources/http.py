"""One place for outbound requests.

cdn.nba.com fingerprints non-browser TLS stacks, so every request goes through
curl_cffi with a browser impersonation profile. A Referer is needed as well.

Some hosts refuse datacentre IP ranges. Set NBA_PROXY_BASE to the origin of a
plain pass-through proxy (for example a Cloudflare Worker) and requests to
cdn.nba.com are sent there instead, keeping the same path. No key is involved.
"""

from __future__ import annotations

import os

BROWSER_HEADERS = {
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

IMPERSONATE = os.environ.get("WATCH_GUIDE_IMPERSONATE", "chrome")
TIMEOUT = int(os.environ.get("WATCH_GUIDE_TIMEOUT", "90"))


class FetchError(RuntimeError):
    """Raised so a build fails loudly rather than publishing a thin page."""


def proxied(url: str) -> str:
    """Rewrite an nba.com URL onto NBA_PROXY_BASE when one is configured."""
    base = (os.environ.get("NBA_PROXY_BASE") or "").rstrip("/")
    if not base:
        return url
    for origin in ("https://cdn.nba.com", "https://stats.nba.com", "https://ak-static.cms.nba.com"):
        if url.startswith(origin):
            return base + url[len(origin):]
    return url


def get(url: str, *, expect_json: bool = False, headers: dict | None = None) -> "object":
    """GET a URL. Returns parsed JSON when expect_json, otherwise raw bytes."""
    from curl_cffi import requests  # imported lazily so tests run without it

    target = proxied(url)
    merged = dict(BROWSER_HEADERS)
    if headers:
        merged.update(headers)
    try:
        resp = requests.get(target, impersonate=IMPERSONATE, timeout=TIMEOUT, headers=merged)
    except Exception as exc:  # network layer failure
        raise FetchError(f"{target} failed: {type(exc).__name__}: {exc}") from exc
    if resp.status_code != 200:
        raise FetchError(f"{target} returned HTTP {resp.status_code} ({len(resp.content)} bytes)")
    if not expect_json:
        return resp.content
    try:
        return resp.json()
    except Exception as exc:
        raise FetchError(f"{target} did not return JSON: {type(exc).__name__}") from exc
