"""Poll company job boards directly via their public ATS JSON APIs.

These are the official feeds each ATS exposes so companies can embed their own
boards. No auth, no proxy, no scraping — one request returns every open role.

  Greenhouse      GET  boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
  Lever           GET  api.lever.co/v0/postings/{slug}?mode=json
  Ashby           GET  api.ashbyhq.com/posting-api/job-board/{slug}
  SmartRecruiters GET  api.smartrecruiters.com/v1/companies/{slug}/postings
  Workday         POST {tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
  Eightfold       GET  {host}/api/apply/v2/jobs?domain={domain}

Workday and SmartRecruiters paginate, so those handlers loop until the board is
exhausted or `max_pages` is hit. Where the API returns a description cheaply we
keep a trimmed copy — `src.fit` scores against it, and it is the difference
between matching a title and matching what the job actually asks for.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone

from ..http import get_json, post_json

# Descriptions are only used for keyword scoring, so a prefix is plenty and keeps
# peak memory sane across ~50k postings.
_DESC_CHARS = 2500
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _text(raw: str | None) -> str:
    if not raw:
        return ""
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", raw))).strip()[:_DESC_CHARS]


def _epoch(value) -> int:
    """Normalize the half-dozen date shapes these APIs use to a UTC epoch."""
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value / 1000) if value > 1e12 else int(value)
    s = str(value).strip()
    if s.isdigit():
        n = int(s)
        return n // 1000 if n > 1e12 else n
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00"))
                   .replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return int(datetime.strptime(_WS.sub(" ", s), fmt)
                       .replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return 0


# --------------------------------------------------------------------------- #
# Handlers. Each takes the target dict and returns normalized rows.
# --------------------------------------------------------------------------- #
def _greenhouse(t: dict) -> list[dict]:
    data = get_json(
        f"https://boards-api.greenhouse.io/v1/boards/{t['slug']}/jobs?content=true",
        expect_nonempty="jobs")
    rows = []
    for j in data.get("jobs", []):
        offices = [o.get("name", "") for o in (j.get("offices") or []) if o.get("name")]
        loc = (j.get("location") or {}).get("name", "")
        depts = [d.get("name", "") for d in (j.get("departments") or []) if d.get("name")]
        rows.append({
            "title": j.get("title", ""),
            "url": j.get("absolute_url", ""),
            "locations": [x for x in ([loc] + offices) if x],
            "date_posted": _epoch(j.get("first_published") or j.get("updated_at")),
            "ext_id": str(j.get("id", "")),
            "department": ", ".join(depts),
            "description": _text(j.get("content")),
        })
    return rows


def _lever(t: dict) -> list[dict]:
    data = get_json(f"https://api.lever.co/v0/postings/{t['slug']}?mode=json",
                    expect_nonempty="")
    rows = []
    for j in data:
        cats = j.get("categories") or {}
        locs = [cats.get("location") or ""] + list(j.get("additionalPlain", []) or [])
        rows.append({
            "title": j.get("text", ""),
            "url": j.get("hostedUrl") or j.get("applyUrl", ""),
            "locations": [x for x in locs if isinstance(x, str) and x],
            "date_posted": _epoch(j.get("createdAt")),
            "ext_id": str(j.get("id", "")),
            "department": " · ".join(x for x in (cats.get("team"), cats.get("department")) if x),
            "description": _text(j.get("descriptionPlain") or j.get("description")),
        })
    return rows


def _ashby(t: dict) -> list[dict]:
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{t['slug']}"
                    "?includeCompensation=false", expect_nonempty="jobs")
    rows = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [
            s.get("location", "") if isinstance(s, dict) else str(s)
            for s in (j.get("secondaryLocations") or [])
        ]
        if j.get("isRemote"):
            locs.append("Remote")
        rows.append({
            "title": j.get("title", ""),
            "url": j.get("jobUrl") or j.get("applyUrl", ""),
            "locations": [x for x in locs if x],
            "date_posted": _epoch(j.get("publishedAt") or j.get("updatedAt")),
            "ext_id": str(j.get("id", "")),
            "department": " · ".join(x for x in (j.get("department"), j.get("team")) if x),
            "description": _text(j.get("descriptionPlain") or j.get("descriptionHtml")),
        })
    return rows


def _smartrecruiters(t: dict) -> list[dict]:
    rows, offset, limit = [], 0, 100
    for _ in range(t.get("max_pages", 12)):
        data = get_json(f"https://api.smartrecruiters.com/v1/companies/{t['slug']}"
                        f"/postings?limit={limit}&offset={offset}")
        page = data.get("content") or []
        for j in page:
            loc = j.get("location") or {}
            parts = [loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()]
            place = ", ".join(p for p in parts if p)
            if loc.get("remote"):
                place = f"{place} (Remote)" if place else "Remote"
            rows.append({
                "title": j.get("name", ""),
                "url": (f"https://jobs.smartrecruiters.com/{t['slug']}/"
                        f"{j.get('id', '')}"),
                "locations": [place] if place else [],
                "date_posted": _epoch(j.get("releasedDate") or j.get("createdOn")),
                "ext_id": str(j.get("id", "")),
                "department": (j.get("department") or {}).get("label", ""),
                "description": "",
            })
        if len(page) < limit:
            break
        offset += limit
    return rows


def _workday(t: dict) -> list[dict]:
    """slug is 'tenant|site|wdN' — the three coordinates a Workday tenant needs.

    Workday caps pages at 20 rows, so walking a 2,000-role board end to end costs
    100 requests per tenant. Instead each target lists `queries`: searchText is
    fuzzy (Salesforce's "intern" matches account executives) but it *relevance
    ranks*, so a few short queries surface the early-career and ML roles in the
    first pages for a fraction of the traffic. Results are deduped by URL because
    the queries deliberately overlap.
    """
    tenant, site, host = t["slug"].split("|")
    base = f"https://{tenant}.{host}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    limit, max_pages = 20, t.get("max_pages", 3)
    queries = t.get("queries") or [""]
    if queries == [""]:                       # whole-board walk for small tenants
        max_pages = t.get("max_pages", 30)

    rows, seen = [], set()
    for query in queries:
        for page_i in range(max_pages):
            data = post_json(api, {"appliedFacets": {}, "limit": limit,
                                   "offset": page_i * limit, "searchText": query})
            page = data.get("jobPostings") or []
            for j in page:
                path = j.get("externalPath") or ""
                url = f"{base}/{site}{path}" if path else base
                if url in seen:
                    continue
                seen.add(url)
                rows.append({
                    "title": j.get("title", ""),
                    "url": url,
                    "locations": _wd_locations(j.get("locationsText") or ""),
                    "date_posted": _wd_posted(j.get("postedOn") or ""),
                    "ext_id": "|".join(j.get("bulletFields") or []) or path,
                    "department": "",
                    "description": "",
                })
            if len(page) < limit or (page_i + 1) * limit >= int(data.get("total") or 0):
                break
    return rows


_WD_MULTI = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)


def _wd_locations(text: str) -> list[str]:
    # Workday collapses multi-site roles to "5 Locations", which carries no place
    # information at all — better to report unknown than to invent one.
    if not text or _WD_MULTI.match(text):
        return []
    return [p.strip() for p in text.split(" and ") if p.strip()]


_WD_AGO = re.compile(r"(\d+)\+?\s*(day|hour|minute|month)", re.I)


def _wd_posted(text: str) -> int:
    """Workday reports 'Posted 30 Days Ago' rather than a date."""
    import time
    now = int(time.time())
    if "today" in text.lower():
        return now
    m = _WD_AGO.search(text)
    if not m:
        return 0
    n, unit = int(m.group(1)), m.group(2).lower()
    secs = {"minute": 60, "hour": 3600, "day": 86400, "month": 2592000}[unit]
    return now - n * secs


def _eightfold(t: dict) -> list[dict]:
    """slug is 'host|domain', e.g. 'explore.jobs.netflix.net|netflix.com'."""
    host, domain = t["slug"].split("|")
    rows, start, num = [], 0, 100
    for _ in range(t.get("max_pages", 12)):
        data = get_json(f"https://{host}/api/apply/v2/jobs"
                        f"?domain={domain}&start={start}&num={num}&sort_by=timestamp")
        page = data.get("positions") or []
        for j in page:
            rows.append({
                "title": j.get("name", ""),
                "url": j.get("canonicalPositionUrl") or
                       f"https://{host}/careers/job/{j.get('id', '')}",
                "locations": j.get("locations") or ([j["location"]] if j.get("location") else []),
                "date_posted": _epoch(j.get("t_create") or j.get("t_update")),
                "ext_id": str(j.get("display_job_id") or j.get("id", "")),
                "department": j.get("department", ""),
                "description": _text(j.get("job_description")),
            })
        if len(page) < num or start + num >= int(data.get("count") or 0):
            break
        start += num
    return rows


HANDLERS = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "smartrecruiters": _smartrecruiters,
    "workday": _workday,
    "eightfold": _eightfold,
}


def fetch_target(target: dict) -> list[dict]:
    """target = {ticker?, name, ats, slug} from config.ats_targets.

    Raises on failure so the caller can record it in the run's health report —
    swallowing errors here is how a board quietly disappears for months.
    """
    handler = HANDLERS.get(target["ats"])
    if not handler:
        raise ValueError(f"unknown ats '{target['ats']}'")
    rows = handler(target)
    for row in rows:
        row.update({
            "source": f"ATS:{target['ats']}",
            "role_type": "",                       # inferred later from the title
            "company_name": target["name"],
            "category": row.get("department", ""),
            "active": True,
            "seasons": [],
            # Membership is guaranteed for a board we polled by hand.
            "forced_ticker": target.get("ticker", ""),
            "employer_tier": target.get("tier", ""),
        })
    return rows
