"""Poll company job boards directly via public ATS JSON APIs.

These endpoints are the official, public feeds each ATS exposes so companies can
embed their own boards. No auth, no proxy. One request returns every open role.

  Greenhouse : https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
  Lever      : https://api.lever.co/v0/postings/{slug}?mode=json
  Ashby      : https://api.ashbyhq.com/posting-api/job-board/{slug}
"""
from __future__ import annotations
import time
import requests

_UA = {"User-Agent": "nasdaq-tech-jobs/1.0 (personal job tracker)"}


def _get_json(url: str):
    r = requests.get(url, headers=_UA, timeout=45)
    r.raise_for_status()
    return r.json()


def _greenhouse(slug: str) -> list[dict]:
    data = _get_json(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    )
    rows = []
    for j in data.get("jobs", []):
        rows.append({
            "title": j.get("title", ""),
            "url": j.get("absolute_url", ""),
            "locations": [j.get("location", {}).get("name", "")] if j.get("location") else [],
            "date_posted": _epoch(j.get("updated_at") or j.get("first_published")),
            "ext_id": str(j.get("id", "")),
        })
    return rows


def _lever(slug: str) -> list[dict]:
    data = _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    rows = []
    for j in data:
        cats = j.get("categories", {}) or {}
        loc = cats.get("location") or ""
        rows.append({
            "title": j.get("text", ""),
            "url": j.get("hostedUrl", "") or j.get("applyUrl", ""),
            "locations": [loc] if loc else [],
            "date_posted": int((j.get("createdAt") or 0) / 1000),
            "ext_id": str(j.get("id", "")),
        })
    return rows


def _ashby(slug: str) -> list[dict]:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    rows = []
    for j in data.get("jobs", []):
        rows.append({
            "title": j.get("title", ""),
            "url": j.get("jobUrl", "") or j.get("applyUrl", ""),
            "locations": [j.get("location", "")] if j.get("location") else [],
            "date_posted": _epoch(j.get("publishedAt")),
            "ext_id": str(j.get("id", "")),
        })
    return rows


_HANDLERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


def _epoch(value) -> int:
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value / 1000) if value > 1e12 else int(value)
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def fetch_target(target: dict) -> list[dict]:
    """target = {ticker, name, ats, slug} from config.ats_targets."""
    handler = _HANDLERS.get(target["ats"])
    if not handler:
        return []
    try:
        raw = handler(target["slug"])
    except requests.HTTPError as e:
        print(f"  ! {target['name']} ({target['ats']}:{target['slug']}) HTTP {e.response.status_code}")
        return []
    except Exception as e:  # noqa: BLE001 - keep the run alive on any single board
        print(f"  ! {target['name']} ({target['ats']}:{target['slug']}) {e}")
        return []

    jobs = []
    for row in raw:
        row.update({
            "source": f"ATS:{target['ats']}",
            "role_type": "",          # inferred later from title
            "company_name": target["name"],
            "category": "",
            "active": True,
            "forced_ticker": target["ticker"],  # membership is guaranteed here
        })
        jobs.append(row)
    time.sleep(0.2)  # be polite between boards
    return jobs
