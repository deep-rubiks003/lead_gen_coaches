"""Stage 1b: build Lead from a web-search result (snippet-based).

Native OpenWebNinja has no per-platform profile API, so we derive everything we
can from the Google result itself: title (often "Name (@handle) • Instagram"),
snippet (bio text, sometimes email), and any URL in the snippet (linktree/site).
Follower counts aren't reliably in snippets, so scoring leans on role/geo/
monetization keywords + email presence instead.
"""
from __future__ import annotations

import re

from models import Lead
from utils import find_emails, first_url, match_country, match_role

# "Jane Fit (@janefit) • Instagram photos and videos" -> "Jane Fit"
_NAME_RE = re.compile(r"^(.*?)\s*[\(\|•\-–]")
# extract follower hints like "12.3k followers" if present in snippet
_FOLLOWERS_RE = re.compile(r"([\d.,]+)\s*([kKmM]?)\s*[Ff]ollowers")


def _parse_name(title: str) -> str | None:
    if not title:
        return None
    m = _NAME_RE.match(title)
    name = (m.group(1) if m else title).strip()
    return name or None


def _parse_followers(text: str) -> int:
    m = _FOLLOWERS_RE.search(text or "")
    if not m:
        return 0
    num = m.group(1).replace(",", "")
    try:
        val = float(num)
    except ValueError:
        return 0
    mult = {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1)
    return int(val * mult)


def build_lead(result: dict) -> Lead | None:
    """result = {platform, handle, country, url, snippet, title}."""
    platform = result["platform"]
    handle = result["handle"]
    title = result.get("title", "") or ""
    snippet = result.get("snippet", "") or ""
    blob = f"{title} {snippet}"

    lead = Lead(
        platform=platform,
        handle=handle,
        name=_parse_name(title),
        profile_url=result.get("url"),
        bio=snippet,
        followers=_parse_followers(blob),
        website=first_url(snippet),
        country=result.get("country"),
    )
    emails = find_emails(blob)
    if emails:
        lead.email = emails[0]
        lead.email_source = "snippet"
    lead.role_matched = match_role(blob)
    lead.country = match_country(blob) or lead.country
    return lead
