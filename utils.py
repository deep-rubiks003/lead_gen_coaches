"""Shared helpers: config load, email regex, geo + role match, rate limit."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

load_dotenv()

_CFG_CACHE = None

# Matches emails, including obfuscated "name (at) domain (dot) com" lightly.
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
OBFUSCATED_RE = re.compile(
    r"([a-zA-Z0-9._%+\-]+)\s*(?:\(at\)|\[at\]|\sat\s)\s*"
    r"([a-zA-Z0-9.\-]+)\s*(?:\(dot\)|\[dot\]|\sdot\s)\s*([a-zA-Z]{2,})",
    re.IGNORECASE,
)


def cfg() -> dict:
    global _CFG_CACHE
    if _CFG_CACHE is None:
        path = Path(__file__).parent / "config.yaml"
        _CFG_CACHE = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _CFG_CACHE


def env(key: str) -> Optional[str]:
    v = os.getenv(key)
    return v if v else None


# Template/placeholder emails that show up in site themes — never real leads.
JUNK_EMAILS = {
    "user@domain.com", "youremail@email.com", "email@example.com",
    "name@example.com", "you@example.com", "info@example.com",
    "example@example.com", "your@email.com", "test@test.com",
    "admin@admin.com", "sample@email.com", "email@domain.com",
    "john@doe.com", "yourname@email.com", "hello@example.com",
}
JUNK_DOMAINS = {"example.com", "domain.com", "email.com", "test.com",
                "sentry.io", "wixpress.com", "godaddy.com",
                # coaching-software vendors / directories (not the coach)
                "inspire360.com", "strengthcoachnetwork.com",
                "strengthcoach.com", "trainerize.com", "truecoach.co",
                "everfit.io", "mailchimp.com", "squarespace.com"}
# infra/vendor addresses, not the coach
JUNK_LOCALPARTS = {"security", "abuse", "postmaster", "no-reply", "noreply",
                   "wordpress", "sentry", "service", "support", "billing",
                   "privacy", "legal", "webmaster", "hostmaster"}


def is_junk_email(email: str) -> bool:
    e = email.lower()
    if e in JUNK_EMAILS:
        return True
    try:
        local, domain = e.split("@", 1)
    except ValueError:
        return True
    if domain in JUNK_DOMAINS:
        return True
    if local in JUNK_LOCALPARTS:
        return True
    if "@mail.instagram.com" in e or "@sentry" in e:
        return True
    return False


def find_emails(text: str) -> list[str]:
    """Pull all emails from text, incl. light deobfuscation. Deduped, no junk."""
    if not text:
        return []
    found = set(m.lower() for m in EMAIL_RE.findall(text))
    for u, d, t in OBFUSCATED_RE.findall(text):
        found.add(f"{u}@{d}.{t}".lower())
    bad_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
    return [e for e in found
            if not e.endswith(bad_ext) and not is_junk_email(e)]


def match_role(text: str) -> Optional[str]:
    """Return first ICP role keyword present in text, else None."""
    if not text:
        return None
    low = text.lower()
    for role in cfg()["icp"]["roles"]:
        if role in low:
            return role
    return None


def match_country(text: str) -> Optional[str]:
    """Return ISO tag (US/UK/...) if any country marker present."""
    if not text:
        return None
    low = text.lower()
    for iso, markers in cfg()["icp"]["countries"].items():
        for m in markers:
            if m in low:
                return iso
    return None


# Major-city -> country, to catch bios that name a city but not the country.
CITY_COUNTRY = {
    "US": ["new york", "los angeles", "chicago", "houston", "miami", "dallas",
           "boston", "seattle", "atlanta", "denver", "austin", "phoenix",
           "san diego", "san francisco", "nyc", "nashville", "philadelphia"],
    "UK": ["london", "manchester", "birmingham", "leeds", "glasgow",
           "liverpool", "edinburgh", "bristol", "england", "scotland", "wales"],
    "CA": ["toronto", "vancouver", "montreal", "calgary", "ottawa", "edmonton"],
    "AU": ["sydney", "melbourne", "brisbane", "perth", "adelaide", "gold coast"],
    "NZ": ["auckland", "wellington", "christchurch"],
    "ZA": ["johannesburg", "cape town", "durban", "pretoria"],
    "IN": ["mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai",
           "pune", "kolkata", "ahmedabad", "gurgaon", "noida"],
    "IE": ["dublin", "cork", "galway"],
}


COUNTRY_NAMES = {
    "US": "USA", "UK": "UK", "CA": "Canada", "AU": "Australia",
    "NZ": "New Zealand", "ZA": "South Africa", "IN": "India", "IE": "Ireland",
}


def geo_query_clause(iso: str, max_cities: int = 8) -> str:
    """Build an OR-clause of country + major cities for stronger geo discovery,
    e.g. (India OR Mumbai OR Delhi OR Bangalore ...). Catches locals who name a
    city but not the country."""
    terms = [COUNTRY_NAMES.get(iso, iso)]
    terms += [c.title() for c in CITY_COUNTRY.get(iso, [])[:max_cities]]
    return "(" + " OR ".join(terms) + ")"


def infer_country(*texts: str) -> Optional[str]:
    """Best-effort country from bio / business address / phone text.
    Checks explicit country markers first, then major cities."""
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None
    hit = match_country(blob)
    if hit:
        return hit
    for iso, cities in CITY_COUNTRY.items():
        for c in cities:
            if c in blob:
                return iso
    return None


def first_url(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"https?://[^\s)]+", text)
    return m.group(0) if m else None


class RateLimiter:
    """Crude per-process spacing between calls."""

    def __init__(self, min_interval: float = 1.0):
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self):
        elapsed = time.time() - self._last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.time()
