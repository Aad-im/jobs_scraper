"""Big-tech career sites that run their own API instead of a third-party ATS.

Only Amazon lives here today. It matters enough to be worth a bespoke handler:
it is one of the largest ML employers, it posts university roles continuously,
and `amazon.jobs` exposes a clean paginated JSON search endpoint.

Deliberately absent, with reasons, so nobody re-litigates this quarterly:
  · Microsoft — gcsservices.careers.microsoft.com refuses connections from
    datacenter IPs (GitHub Actions included), so it can't be polled from CI.
  · Apple     — jobs.apple.com/api/v1/search returns 0 results for most
    multi-word queries; too unreliable to publish from.
  · Google, Meta — no stable public JSON endpoint; both need a rotating GraphQL
    doc_id that breaks without warning.
All four are still covered through the SimplifyJobs aggregator feeds.
"""
from __future__ import annotations

from urllib.parse import urlencode

from ..http import get_json

_AMZ = "https://www.amazon.jobs/en/search.json"
_PAGE = 100


def amazon(query: dict) -> list[dict]:
    """query = {name, base_query?, category?, max_pages?} from config.bigtech.amazon."""
    rows, offset = [], 0
    for _ in range(query.get("max_pages", 8)):
        params = [("result_limit", _PAGE), ("offset", offset), ("sort", "recent"),
                  ("base_query", query.get("base_query", ""))]
        for cat in query.get("categories", []) or []:
            params.append(("category[]", cat))
        data = get_json(f"{_AMZ}?{urlencode(params)}")
        page = data.get("jobs") or []
        for j in page:
            rows.append({
                "title": j.get("title", ""),
                "url": "https://www.amazon.jobs" + (j.get("job_path") or ""),
                "locations": [j.get("normalized_location") or j.get("location") or ""],
                "date_posted": _posted(j),
                "ext_id": str(j.get("id_icims") or j.get("id") or j.get("job_path", "")),
                "department": j.get("job_category", ""),
                # Amazon states the bar in the qualifications, not the blurb —
                # "3+ years" there is what keeps senior roles out of the shortlist.
                "description": " ".join(filter(None, [
                    j.get("basic_qualifications", ""),
                    j.get("preferred_qualifications", ""),
                    j.get("description_short", ""),
                ]))[:2500],
                "source": "Amazon Jobs",
                "role_type": "",
                "company_name": "Amazon",
                "category": j.get("job_category", ""),
                "active": True,
                "seasons": [],
                "forced_ticker": "AMZN",
                "employer_tier": "big_tech",
            })
        if len(page) < _PAGE or offset + _PAGE >= int(data.get("hits") or 0):
            break
        offset += _PAGE
    return rows


def _posted(job: dict) -> int:
    from .ats import _epoch
    return _epoch(job.get("posted_date") or job.get("updated_time"))


FETCHERS = {"amazon": amazon}
