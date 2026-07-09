"""Ingest SimplifyJobs-style listings.json feeds into a normalized shape.

Schema per entry (observed):
  source, category, company_name, id, title, active, date_updated,
  date_posted, url, locations[], company_url, is_visible, sponsorship, degrees[]
"""
from __future__ import annotations
import requests


def _locations(entry: dict) -> list[str]:
    locs = entry.get("locations") or []
    return [str(x).strip() for x in locs if str(x).strip()]


def fetch(feed: dict) -> list[dict]:
    """feed = {name, url, role_type} from config.aggregators."""
    r = requests.get(feed["url"], timeout=90)
    r.raise_for_status()
    data = r.json()
    out = []
    for e in data:
        if not e.get("is_visible", True):
            continue
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
        })
    return out
