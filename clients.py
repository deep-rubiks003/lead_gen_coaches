"""Thin HTTP clients for OpenWebNinja (native API), SerpAPI, Hunter.

OpenWebNinja native API:
  base   https://api.openwebninja.com
  auth   header  x-api-key: ak_...
  search GET /realtime-web-search/search?q=&gl=&hl=&num=

Native catalog has no IG/TikTok/Twitter/Reddit profile scrapers, so ALL
discovery (incl. reddit) runs through web search with `site:` filters. Bio =
result snippet; emails come from snippet + website scrape + Hunter.

Degrades gracefully: missing key -> [] (skipped), error -> [] + warning.
"""
from __future__ import annotations

import httpx
from rich import print as rprint

from utils import env, RateLimiter

_TIMEOUT = 25.0
_rl = RateLimiter(min_interval=1.5)   # free tier is rate-limited; keep spaced

# --- OpenWebNinja native API -------------------------------------------------
OWN_BASE = "https://api.openwebninja.com"
# Web-search product slug. If you subscribed to a different search product,
# change this to its slug (e.g. "realtime-google-search").
OWN_SEARCH_SLUG = "realtime-web-search"
# Website Contacts Scraper: domain/url -> emails, phones, socials.
OWN_CONTACTS_SLUG = "website-contacts-scraper"


# product paths that exhausted quota this run -> skip immediately
_DEAD_PATHS: set[str] = set()


def _own_get(path: str, params: dict) -> dict | None:
    key = env("OPENWEBNINJA_API_KEY")
    if not key:
        rprint("[yellow]skip OpenWebNinja: no OPENWEBNINJA_API_KEY[/]")
        return None
    base_path = path.rsplit("/", 1)[0]
    if base_path in _DEAD_PATHS:
        return None
    for attempt in range(3):
        _rl.wait()
        try:
            r = httpx.get(f"{OWN_BASE}{path}", headers={"x-api-key": key},
                          params=params, timeout=_TIMEOUT)
            if r.status_code == 403:
                rprint(f"[red]OpenWebNinja 403[/] not subscribed to product "
                       f"for path {path} — subscribe (free) on openwebninja.com")
                return None
            if r.status_code == 429:           # rate limited -> back off + retry
                if attempt < 2:
                    import time
                    time.sleep(3 * (attempt + 1))   # 3s, 6s backoff
                    continue
                _DEAD_PATHS.add(base_path)       # quota gone -> skip rest of run
                rprint(f"[yellow]OpenWebNinja 429 quota exhausted, skipping "
                       f"{base_path} for rest of run[/]")
                return None
            r.raise_for_status()
            return r.json()
        except httpx.TimeoutException:
            if attempt < 2:
                rprint(f"[yellow]timeout {path}, retry {attempt + 1}/2[/]")
                continue
            rprint(f"[red]OpenWebNinja timeout (gave up) {path}[/]")
            return None
        except Exception as e:  # noqa: BLE001
            rprint(f"[red]OpenWebNinja error {path}:[/] {e}")
            return None
    return None


def own_google_search(query: str, gl: str = "us", num: int = 20,
                      start: int = 0) -> list[dict]:
    params = {"q": query, "gl": gl, "hl": "en", "num": num}
    if start:
        params["start"] = start
    data = _own_get(f"/{OWN_SEARCH_SLUG}/search", params)
    if not data:
        return []
    # native shape: {"status":"OK","data":{"organic_results":[...]}} or
    #               {"data":[...]} — handle both.
    d = data.get("data", data)
    if isinstance(d, dict):
        items = (d.get("organic_results") or d.get("results")
                 or d.get("organic") or [])
    elif isinstance(d, list):
        items = d
    else:
        items = []
    return items


def own_website_contacts(domain_or_url: str) -> dict | None:
    """OpenWebNinja Website Contacts Scraper. domain/url -> emails+phones+socials.

    Returns dict with at least {'emails': [...], 'phones': [...], ...} or None.
    """
    if not domain_or_url:
        return None
    data = _own_get(f"/{OWN_CONTACTS_SLUG}/scrape-contacts",
                    {"query": domain_or_url})
    if not data:
        return None
    d = data.get("data", data)
    if isinstance(d, list):
        d = d[0] if d else {}
    return d if isinstance(d, dict) else None



# --- Bright Data Instagram Profiles dataset ---------------------------------
# Standard IG-profiles dataset id; override with BRIGHTDATA_IG_DATASET in .env.
_IG_DATASET_DEFAULT = "gd_l1vikfch901nx3by4"


def brightdata_profile(handles: list[str], poll_secs: int = 10,
                       max_wait: int = 300,
                       progress=None) -> dict[str, dict]:
    """Hydrate IG handles via Bright Data IG Profiles dataset.

    Triggers a collection, polls the snapshot until ready, returns
    {handle_lower: {followers, biography, business_address, business_phone,
    full_name, is_business}}. Needs BRIGHTDATA_API_TOKEN (+ optional
    BRIGHTDATA_IG_DATASET) in .env.
    """
    import time

    token = env("BRIGHTDATA_API_TOKEN")
    dataset = env("BRIGHTDATA_IG_DATASET") or _IG_DATASET_DEFAULT
    if not token or not handles:
        return {}

    def log(m):
        (progress or rprint)(m)

    hdr = {"Authorization": f"Bearer {token}",
           "Content-Type": "application/json"}
    rows = [{"url": f"https://www.instagram.com/{h.lstrip('@')}/"}
            for h in handles]
    try:
        t = httpx.post("https://api.brightdata.com/datasets/v3/trigger",
                       headers=hdr,
                       params={"dataset_id": dataset, "include_errors": "true"},
                       json=rows, timeout=60.0)
        t.raise_for_status()
        snap = t.json().get("snapshot_id")
        if not snap:
            log(f"[red]Bright Data trigger: no snapshot_id ({t.text[:120]})[/]")
            return {}
        log(f"profile collection started ({len(handles)} handles)…")
    except Exception as e:  # noqa: BLE001
        rprint(f"[red]Bright Data trigger error:[/] {e}")
        return {}

    # poll
    waited = 0
    while waited < max_wait:
        time.sleep(poll_secs)
        waited += poll_secs
        try:
            p = httpx.get(
                f"https://api.brightdata.com/datasets/v3/progress/{snap}",
                headers=hdr, timeout=30.0).json()
        except Exception:  # noqa: BLE001
            continue
        status = p.get("status")
        log(f"profile status: {status} ({waited}s)")
        if status == "ready":
            break
        if status in ("failed", "error"):
            rprint(f"[red]Bright Data snapshot {status}[/]")
            return {}
    else:
        rprint("[yellow]Bright Data profile poll timed out[/]")
        return {}

    # download — progress=ready does NOT mean the snapshot file is ready; the
    # download endpoint may still return {"status":"building"}. Retry until it
    # returns the actual JSON array.
    data = None
    for _ in range(12):                      # up to ~2 min extra
        try:
            d = httpx.get(
                f"https://api.brightdata.com/datasets/v3/snapshot/{snap}",
                headers=hdr, params={"format": "json"}, timeout=120.0)
            d.raise_for_status()
            j = d.json()
        except Exception as e:  # noqa: BLE001
            rprint(f"[red]Bright Data snapshot download error:[/] {e}")
            return {}
        if isinstance(j, list):
            data = j
            break
        if isinstance(j, dict) and j.get("status") in ("building", "running"):
            log("snapshot still building, waiting 10s…")
            time.sleep(10)
            continue
        data = j                              # unexpected shape -> handle below
        break
    if not isinstance(data, list):
        rprint("[yellow]Bright Data snapshot never became downloadable[/]")
        return {}

    out: dict[str, dict] = {}
    for it in (data if isinstance(data, list) else []):
        h = (it.get("account") or it.get("user_name") or it.get("username")
             or "").lstrip("@").lower()
        if not h:
            url = it.get("url") or it.get("input_url") or ""
            h = url.rstrip("/").rsplit("/", 1)[-1].lower()
        if not h:
            continue
        out[h] = {
            "followers": it.get("followers") or it.get("followers_count") or 0,
            "biography": it.get("biography") or it.get("bio") or "",
            "full_name": it.get("full_name") or it.get("profile_name") or "",
            "business_address": it.get("business_address_json")
            or it.get("business_address") or "",
            "business_phone": it.get("business_phone_number")
            or it.get("business_phone") or "",
            "is_business": it.get("is_business_account", False),
            "email": it.get("business_email") or it.get("email") or "",
        }
    return out


# --- Bright Data SERP API (Direct API) --------------------------------------
def brightdata_search(query: str, gl: str = "us", num: int = 20,
                      start: int = 0) -> list[dict]:
    """Bright Data SERP via Direct API. Needs BRIGHTDATA_API_TOKEN +
    BRIGHTDATA_ZONE in .env. Sends a Google URL with brd_json=1 -> parsed SERP;
    normalizes organic results to {title, url, snippet}. Retries on
    timeout / empty / bad-JSON."""
    import json as _json
    from urllib.parse import urlencode
    token, zone = env("BRIGHTDATA_API_TOKEN"), env("BRIGHTDATA_ZONE")
    if not token or not zone:
        return []
    g = urlencode({"q": query, "gl": gl, "hl": "en",
                   "num": num, "start": start, "brd_json": 1})
    target = f"https://www.google.com/search?{g}"
    for attempt in range(3):
        try:
            r = httpx.post(
                "https://api.brightdata.com/request",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json={"zone": zone, "url": target, "format": "raw"},
                timeout=90.0)
            r.raise_for_status()
            body = r.text.strip()
            if not body:
                raise ValueError("empty body")
            data = _json.loads(body)
            if isinstance(data, dict) and "body" in data:
                data = _json.loads(data["body"]) \
                    if isinstance(data["body"], str) else data["body"]
            org = (data or {}).get("organic") or (data or {}).get("results") or []
            return [{"title": it.get("title", ""),
                     "url": it.get("link") or it.get("url", ""),
                     "snippet": it.get("description") or it.get("snippet", "")}
                    for it in org]
        except (httpx.TimeoutException, ValueError, _json.JSONDecodeError) as e:
            if attempt < 2:
                rprint(f"[yellow]Bright Data retry {attempt+1}/2 ({type(e).__name__})[/]")
                continue
            rprint(f"[red]Bright Data SERP gave up:[/] {e}")
            return []
        except Exception as e:  # noqa: BLE001
            rprint(f"[red]Bright Data SERP error:[/] {e}")
            return []
    return []


# --- SerpAPI (Google search) ------------------------------------------------
def serpapi_search(query: str, gl: str = "us", num: int = 20,
                   start: int = 0) -> list[dict]:
    """SerpAPI Google search. Returns organic_results normalized to
    {title, url, snippet}. Paginate with start=0,10,20..."""
    key = env("SERPAPI_KEY")
    if not key:
        return []
    _rl.wait()
    params = {"q": query, "gl": gl, "num": num,
              "engine": "google", "api_key": key}
    if start:
        params["start"] = start
    try:
        r = httpx.get("https://serpapi.com/search", params=params,
                      timeout=_TIMEOUT)
        r.raise_for_status()
        org = r.json().get("organic_results", []) or []
        return [{"title": it.get("title", ""),
                 "url": it.get("link") or it.get("url", ""),
                 "snippet": it.get("snippet") or it.get("description", "")}
                for it in org]
    except Exception as e:  # noqa: BLE001
        rprint(f"[red]SerpAPI error:[/] {e}")
        return []


# --- Hunter.io ---------------------------------------------------------------
def hunter_find(domain: str, first: str = "", last: str = "") -> dict | None:
    key = env("HUNTER_API_KEY")
    if not key or not domain:
        return None
    _rl.wait()
    try:
        r = httpx.get(
            "https://api.hunter.io/v2/email-finder",
            params={"domain": domain, "first_name": first,
                    "last_name": last, "api_key": key},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("data")
    except Exception as e:  # noqa: BLE001
        rprint(f"[red]Hunter error:[/] {e}")
        return None


def hunter_verify(email: str) -> str | None:
    """Return status string: deliverable|undeliverable|risky|unknown."""
    key = env("HUNTER_API_KEY")
    if not key or not email:
        return None
    _rl.wait()
    try:
        r = httpx.get(
            "https://api.hunter.io/v2/email-verifier",
            params={"email": email, "api_key": key},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("status")
    except Exception as e:  # noqa: BLE001
        rprint(f"[red]Hunter verify error:[/] {e}")
        return None
