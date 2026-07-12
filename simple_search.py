"""Harvest Instagram coach/creator accounts in a follower band via SerpAPI.

Followers come solely from the Google result snippet ("55.3K followers" stats
line); accounts without a parseable count are skipped (unless no_filter).
Resumable: existing --out handles are loaded and skipped, new finds appended.

CLI:
  python simple_search.py --niches "running coach" --gl us --country US \
      --min-followers 20000 --max-followers 500000 --target 100 --out leads.csv

Also exposes harvest() for the Streamlit app (app.py).
"""
from __future__ import annotations

import argparse
import csv
import os
from typing import Callable

from clients import brightdata_profile, brightdata_search
from scrapers.discovery import _handle_from_url
from scrapers.social import build_lead
from utils import infer_country

COLS = ["handle", "name", "followers", "country", "url", "niche", "bio"]

# Two queries per selected keyword ({n} = the niche phrase):
#   1. quoted   -> exact phrase
#   2. unquoted -> catches varied phrasing ("weight loss & transformation coach")
TEMPLATES = [
    '"{n}" site:instagram.com',
    '{n} site:instagram.com',
]


def _fol(v) -> int:
    if isinstance(v, int):
        return v
    s = str(v).strip().lower().replace(",", "")
    try:
        if s.endswith("k"):
            return int(float(s[:-1]) * 1_000)
        if s.endswith("m"):
            return int(float(s[:-1]) * 1_000_000)
        return int(float(s))
    except ValueError:
        return 0


def _load_existing(path: str) -> tuple[list[dict], set[str]]:
    if not path or not os.path.exists(path):
        return [], set()
    rows, seen = [], set()
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
            seen.add(r["handle"].lower())
    return rows, seen


def harvest(niches: list[str], lo: int, hi: int, target: int = 100,
            gl: str = "us", country: str = "US", geo_term: str = "",
            no_filter: bool = False, pages: int = 5, out: str | None = None,
            verify: bool = False, filter_country: str | None = None,
            progress: Callable[[str], None] | None = None) -> list[dict]:
    """Run the harvest. Returns the row list (and writes CSV if `out` given).

    verify=True: skip snippet follower filtering during discovery, then hydrate
    every handle via Bright Data IG Profiles for GUARANTEED follower counts +
    inferred country, and filter on those. filter_country = ISO tag to keep
    (e.g. 'US'); None keeps all.

    progress: optional callback(msg) for live UI updates.
    """
    def log(msg: str) -> None:
        if progress:
            progress(msg)
        else:
            print(msg)

    rows, seen = _load_existing(out) if out else ([], set())
    if rows:
        log(f"resuming {len(rows)} existing in {out}")

    def _mk(t: str, n: str) -> str:
        q = t.format(n=n)
        if not geo_term:
            return q
        if " site:" in q:
            return q.replace(" site:", f" {geo_term} site:")
        return f"{q} {geo_term}"          # no site: operator -> append geo

    # Discover broadly in both modes: verify hydrates all; non-verify (economy)
    # hydrates only the zero-follower rows. Either way we need the 0s captured.
    discover_no_filter = True
    disc_cap = max(target * 2, 60)

    queries = [(n, _mk(t, n)) for n in niches for t in TEMPLATES]
    log(f"{len(queries)} queries x up to {pages} pages | "
        f"{'verify (Bright Data)' if verify else ('no filter' if no_filter else f'{lo:,}-{hi:,}')}"
        f" | geo={country}")

    for niche, q in queries:
        if len(rows) >= disc_cap:
            break
        for pg in range(pages):
            if len(rows) >= disc_cap:
                break
            results = brightdata_search(q, gl=gl, num=20, start=pg * 10)
            if not results:
                break
            new_here = 0
            for r in results:
                url = r.get("url") or r.get("link") or ""
                if "instagram.com" not in url:
                    continue              # non-IG result (from no-site: queries)
                handle = _handle_from_url(url, "instagram")
                if not handle or handle.lower() in seen:
                    continue
                lead = build_lead({
                    "platform": "instagram", "handle": handle,
                    "country": country, "url": url,
                    "title": r.get("title", ""), "snippet": r.get("snippet", ""),
                })
                if not discover_no_filter and not (lo < lead.followers < hi):
                    continue
                seen.add(handle.lower())
                rows.append({
                    "handle": handle, "name": lead.name or "",
                    "followers": lead.followers,
                    "country": lead.country or country,
                    "url": url, "niche": niche,
                    "bio": (lead.bio or "").replace("\n", " ")[:250],
                })
                new_here += 1
                log(f"+ @{handle} ({lead.followers:,}) {niche} "
                    f"{len(rows)}/{disc_cap}")
            if new_here == 0 and pg > 0:
                break

    for r in rows:
        r["followers"] = _fol(r["followers"])

    if verify and rows:
        # Single Bright Data collection for all handles (one snapshot = one
        # startup latency; batching would multiply that). Generous max_wait so
        # large snapshots still finish.
        log(f"hydrating {len(rows)} profiles via Bright Data…")
        profiles = brightdata_profile(
            [r["handle"] for r in rows],
            poll_secs=5, max_wait=900, progress=progress)
        kept = []
        for r in rows:
            p = profiles.get(r["handle"].lower())
            if p:                              # backfill REAL data in place
                r["followers"] = _fol(p.get("followers", r["followers"]))
                r["bio"] = (p.get("biography") or r["bio"] or "")[:250]
                r["name"] = p.get("full_name") or r["name"]
                addr = p.get("business_address") or ""
                r["country"] = (infer_country(r["bio"], str(addr),
                                              str(p.get("business_phone", "")))
                                or r["country"])
                if p.get("email"):
                    r["email"] = p["email"]
            # final list = real followers in band + (optional) country match
            if not (lo < r["followers"] < hi):
                continue
            if filter_country and r["country"] != filter_country:
                continue
            kept.append(r)
        # discovered = ALL found, now with real Bright Data followers, unfiltered
        discovered = sorted((dict(r) for r in rows),
                            key=lambda x: x["followers"], reverse=True)
        rows = sorted(kept, key=lambda x: x["followers"], reverse=True)[:target]
        log(f"after verify: {len(rows)} in band + country "
            f"(of {len(discovered)} discovered)")
    elif rows:
        # economy mode (verify OFF): hydrate ONLY zero-follower accounts to
        # fill their real count. No country, NO band filter — return all.
        zeros = [r for r in rows if r["followers"] == 0]
        if zeros:
            log(f"hydrating {len(zeros)} zero-follower profiles via Bright "
                f"Data (followers only)…")
            profiles = brightdata_profile([r["handle"] for r in zeros],
                                          progress=progress)
            for r in zeros:
                p = profiles.get(r["handle"].lower())
                if p:
                    r["followers"] = _fol(p.get("followers", 0))
        rows.sort(key=lambda x: x["followers"], reverse=True)
        discovered = [dict(r) for r in rows]
        rows = rows[:target]
        log(f"economy: {len(rows)} accounts (zeros hydrated, no filter)")
    else:
        discovered = []

    def _write(path: str, data: list[dict]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)

    if out:
        _write(out, rows)
        log(f"wrote {out} -> {len(rows)} accounts")
        if verify:
            disc_path = out.replace(".csv", "_discovered.csv")
            _write(disc_path, discovered)
            log(f"wrote {disc_path} -> {len(discovered)} discovered (pre-verify)")
    return {"discovered": discovered, "final": rows}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--niches", required=True,
                   help="comma list, e.g. 'strength coach,powerlifting coach'")
    p.add_argument("--target", type=int, default=100)
    p.add_argument("--min-followers", type=int, default=20_000)
    p.add_argument("--max-followers", type=int, default=500_000)
    p.add_argument("--pages", type=int, default=5)
    p.add_argument("--gl", default="us")
    p.add_argument("--country", default="US")
    p.add_argument("--geo-term", default="")
    p.add_argument("--no-follower-filter", action="store_true")
    p.add_argument("--out", default="leads.csv")
    a = p.parse_args()
    niches = [n.strip() for n in a.niches.split(",") if n.strip()]
    harvest(niches, a.min_followers, a.max_followers, target=a.target,
            gl=a.gl, country=a.country, geo_term=a.geo_term,
            no_filter=a.no_follower_filter, pages=a.pages, out=a.out)


if __name__ == "__main__":
    main()
