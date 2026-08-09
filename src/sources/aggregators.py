"""Ingest SimplifyJobs-style listings.json feeds into a normalized shape.

These community feeds are the broad-recall layer: they cover companies whose ATS
we don't poll directly (Google, Meta, Microsoft, Apple, TikTok…) and they update
daily. Schema per entry (observed):

  source, category, company_name, id, title, active, date_updated, date_posted,
  url, locations[], company_url, is_visible, sponsorship, degrees[], terms[]
"""
from __future__ import annotations

from ..http import get_json

_SEASON_WORDS = ("Summer", "Fall", "Winter", "Spring")


def _locations(entry: dict) -> list[str]:
    locs = entry.get("locations") or []
    if isinstance(locs, str):
        locs = [locs]
    return [str(x).strip() for x in locs if str(x).strip()]


def _seasons(terms) -> list[str]:
    """Reduce a feed's `terms`/`season` field (e.g. ["Fall 2026", "Summer 2027"])
    to the distinct season words present, so roles can be filtered off-season."""
    if not terms:
        return []
    if isinstance(terms, str):
        terms = [terms]
    out: list[str] = []
    for t in terms:
        low = str(t).lower()
        for w in _SEASON_WORDS:
            if w.lower() in low and w not in out:
                out.append(w)
    return out


def _years(terms) -> list[int]:
    """Pull the calendar years out of the same field, so a Summer 2027 internship
    can be told apart from a Summer 2026 one that has already been filled."""
    if not terms:
        return []
    if isinstance(terms, str):
        terms = [terms]
    out: list[int] = []
    for t in terms:
        for chunk in str(t).replace("/", " ").split():
            if chunk.isdigit() and 2020 <= int(chunk) <= 2035 and int(chunk) not in out:
                out.append(int(chunk))
    return sorted(out)


def fetch(feed: dict) -> list[dict]:
    """feed = {name, url, role_type} from config.aggregators."""
    data = get_json(feed["url"], timeout=120, expect_nonempty="")
    if not isinstance(data, list):
        raise ValueError(f"{feed['name']}: expected a JSON list, got {type(data).__name__}")
    out = []
    for e in data:
        if not isinstance(e, dict) or not e.get("is_visible", True):
            continue
        terms = e.get("terms") or e.get("season")
        out.append({
            "source": feed["name"],
            "role_type": feed["role_type"],
            "company_name": (e.get("company_name") or "").strip(),
            "title": (e.get("title") or "").strip(),
            "category": (e.get("category") or "").strip(),
            "url": e.get("url") or e.get("company_url") or "",
            "locations": _locations(e),
            "active": bool(e.get("active", True)),
            "date_posted": e.get("date_posted") or e.get("date_updated") or 0,
            "ext_id": str(e.get("id") or ""),
            "seasons": _seasons(terms),
            "years": _years(terms),
            "sponsorship": (e.get("sponsorship") or "").strip(),
            "department": "",
            "description": "",
            "employer_tier": "",
        })
    return out
