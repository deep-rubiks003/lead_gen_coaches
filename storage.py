"""Persistent run history for the Bright Data app — isolated from harvest core.

Saves harvested leads to runs/<COUNTRY>/<keyword>.csv, one file per
(country, keyword), accumulating + deduping by handle across runs. Pure
file I/O; the harvest pipeline does not depend on this module.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path(__file__).parent / "runs"
COLS = ["handle", "name", "followers", "country", "url", "niche", "bio",
        "saved_at"]

FLAGS = {"US": "🇺🇸", "CA": "🇨🇦", "UK": "🇬🇧", "AU": "🇦🇺",
         "NZ": "🇳🇿", "ZA": "🇿🇦", "IN": "🇮🇳", "IE": "🇮🇪"}


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "misc"


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def save_results(rows: list[dict], country_label: str,
                 kind: str = "verified") -> int:
    """Split rows by their `niche` keyword; append+dedupe into per-keyword CSVs
    under runs/<COUNTRY>/<kind>/. kind = 'verified' or 'discovered'.
    Returns number of new (non-duplicate) rows saved."""
    if not rows or not country_label:
        return 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    by_kw: dict[str, list[dict]] = {}
    for r in rows:
        by_kw.setdefault(r.get("niche") or "misc", []).append(r)

    new_total = 0
    for kw, group in by_kw.items():
        path = RUNS_DIR / country_label / kind / f"{_slug(kw)}.csv"
        existing = _read(path)
        seen = {r["handle"].lower() for r in existing}
        merged = list(existing)
        for r in group:
            h = (r.get("handle") or "").lower()
            if not h or h in seen:
                continue
            seen.add(h)
            row = {c: r.get(c, "") for c in COLS}
            row["niche"] = kw
            row["saved_at"] = now
            merged.append(row)
            new_total += 1
        merged.sort(key=lambda x: int(x.get("followers") or 0), reverse=True)
        _write(path, merged)
    return new_total


def list_countries() -> list[dict]:
    """[{country, flag, verified, discovered}] for every country with data."""
    if not RUNS_DIR.exists():
        return []
    out = []
    for d in sorted(RUNS_DIR.iterdir()):
        if not d.is_dir():
            continue
        v = sum(_count(f) for f in (d / "verified").glob("*.csv")) \
            if (d / "verified").exists() else 0
        dc = sum(_count(f) for f in (d / "discovered").glob("*.csv")) \
            if (d / "discovered").exists() else 0
        if v or dc:
            out.append({"country": d.name, "flag": FLAGS.get(d.name, "🏳️"),
                        "verified": v, "discovered": dc})
    return out


def _count(path: Path) -> int:
    try:
        with path.open(encoding="utf-8") as f:
            return max(sum(1 for _ in f) - 1, 0)   # minus header
    except OSError:
        return 0


def list_keyword_files(country_label: str, kind: str = "verified") -> list[dict]:
    """[{keyword, path, count, csv_bytes, filename}] for a country+kind."""
    d = RUNS_DIR / country_label / kind
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.csv")):
        rows = _read(f)
        kw = rows[0]["niche"] if rows else f.stem.replace("-", " ")
        out.append({"keyword": kw, "path": f, "count": len(rows),
                    "csv_bytes": f.read_bytes(), "filename": f.name})
    out.sort(key=lambda x: x["count"], reverse=True)
    return out
