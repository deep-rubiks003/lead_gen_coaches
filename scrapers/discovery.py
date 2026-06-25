"""Stage 1: Google discovery -> social profile URLs.

Builds queries from ICP roles x platforms x countries, runs them through
OpenWebNinja google (or SerpAPI fallback), parses social handles out of the
result links.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from clients import own_google_search, serpapi_search
from utils import cfg

_GL = {"US": "us", "UK": "uk", "CA": "ca", "ZA": "za", "AU": "au", "NZ": "nz"}

_SITE = {
    "instagram": "instagram.com",
    "tiktok": "tiktok.com",
    "twitter": "twitter.com",
    "reddit": "reddit.com",
}


def build_queries() -> list[tuple[str, str, str]]:
    """Return (platform, country_iso, query) tuples."""
    c = cfg()
    roles = c["icp"]["roles"]
    countries = list(c["icp"]["countries"].keys())
    out = []
    for plat in c["platforms"]:
        site = _SITE.get(plat)
        if not site:
            continue
        for iso in countries:
            for role in roles:
                q = f'"{role}" site:{site}'
                out.append((plat, iso, q))
    return out


def build_targeted_queries(roles: list[str], countries: list[str],
                           platforms: list[str]) -> list[tuple[str, str, str]]:
    """Queries for a specific ICP slice.

    NOTE: no geo term in the query string. Adding "USA" etc. makes Google return
    bio-format snippets (no follower count); the plain `"<role>" site:<plat>`
    form returns the stats-line snippet ("55.3K followers ...") we parse counts
    from. Geo bias is applied via the `gl` param per-country in discover().
    """
    out = []
    for plat in platforms:
        site = _SITE.get(plat)
        if not site:
            continue
        for iso in countries:
            for role in roles:
                out.append((plat, iso, f'"{role}" site:{site}'))
    return out


def _handle_from_url(url: str, platform: str) -> str | None:
    try:
        path = urlparse(url).path.strip("/")
    except Exception:  # noqa: BLE001
        return None
    if not path:
        return None
    seg = path.split("/")
    if platform == "instagram":
        skip = {"p", "reel", "reels", "explore", "stories", "tv"}
        if seg[0] in skip:
            return None
        return seg[0]
    if platform == "tiktok":
        m = re.match(r"@([\w.]+)", seg[0])
        return m.group(1) if m else None
    if platform == "twitter":
        skip = {"i", "search", "hashtag", "home", "explore"}
        if seg[0] in skip:
            return None
        return seg[0]
    if platform == "reddit":
        # /user/<name> -> person; /r/<sub>/comments/<id>/<slug> -> post
        if seg[0] in ("user", "u") and len(seg) > 1:
            return seg[1]
        if seg[0] == "r" and "comments" in seg:
            i = seg.index("comments")
            # use post slug as handle so post-based leads dedup cleanly
            if len(seg) > i + 2:
                return f"{seg[1]}-{seg[i + 2][:40]}"
            return f"{seg[1]}-{seg[i + 1][:12]}"
        return None
    return None


def discover(max_queries: int | None = None,
             queries: list[tuple[str, str, str]] | None = None) -> list[dict]:
    """Run discovery. Returns list of {platform, handle, country, url, snippet}.

    Pass `queries` to target a specific ICP slice; else uses the full config grid.
    """
    if queries is None:
        queries = build_queries()
    budget = cfg()["budgets"]["serpapi_searches"]
    if max_queries:
        budget = min(budget, max_queries)
    queries = queries[:budget]

    seen: set[str] = set()
    found: list[dict] = []
    for plat, iso, q in queries:
        gl = _GL.get(iso, "us")
        results = own_google_search(q, gl=gl) or serpapi_search(q, gl=gl)
        for r in results:
            link = r.get("link") or r.get("url") or ""
            if not link:
                continue
            handle = _handle_from_url(link, plat)
            if not handle:
                continue
            key = f"{plat}:{handle.lower()}"
            if key in seen:
                continue
            seen.add(key)
            found.append({
                "platform": plat,
                "handle": handle,
                "country": iso,
                "url": link,
                "title": r.get("title") or r.get("name") or "",
                "snippet": (r.get("snippet") or r.get("description")
                            or r.get("snippet_highlighted_words") or ""),
            })
    return found
