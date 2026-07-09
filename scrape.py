#!/usr/bin/env python3
"""nasdaq-tech-jobs — hybrid early-career job tracker for Nasdaq tech companies.

Pipeline:
  1. Build the Nasdaq universe (official membership + industry).
  2. Aggregator layer: pull SimplifyJobs new-grad + internship feeds (broad recall),
     match each posting to a Nasdaq ticker.
  3. Direct ATS layer: poll curated Nasdaq company boards (freshness, full detail);
     membership is guaranteed for these.
  4. Classify (early-career filter + track), dedupe, diff against last run.
  5. Write jobs.csv and docs/index.html.

Run:  python scrape.py
"""
from __future__ import annotations
import sys
import yaml

from src.nasdaq import load_universe
from src.matching import CompanyMatcher
from src.classify import early_career_ok, track_of
from src.sources import aggregators, ats
from src import store, render


def job_key(company: str, title: str, url: str) -> str:
    # Collapse the same role posted across many single-location rows into one.
    return f"{company}|{title}".lower().strip()


def is_remote(locations: list[str]) -> bool:
    return any("remote" in (l or "").lower() for l in locations)


def main() -> int:
    cfg = yaml.safe_load(open("config.yaml"))
    ccfg = cfg["classify"]
    ocfg = cfg["output"]

    print("· building Nasdaq universe…")
    universe = load_universe(**cfg["nasdaq_universe"])
    matcher = CompanyMatcher(universe, cfg["matching"]["fuzzy_cutoff"])
    print(f"  {len(universe)} Nasdaq-listed companies")

    raw: list[dict] = []

    print("· aggregator layer…")
    for feed in cfg["aggregators"]:
        try:
            items = aggregators.fetch(feed)
            raw += items
            print(f"  {feed['name']}: {len(items)}")
        except Exception as e:  # noqa: BLE001
            print(f"  ! {feed['name']} failed: {e}")

    print("· direct ATS layer…")
    for target in cfg.get("ats_targets", []):
        items = ats.fetch_target(target)
        if items:
            print(f"  {target['name']} ({target['ats']}): {len(items)}")
        raw += items

    # ---- normalize, tag, filter -------------------------------------------
    print("· classifying + matching…")
    jobs: dict[str, dict] = {}
    for r in raw:
        title, company = r.get("title", ""), r.get("company_name", "")
        if not title or not company:
            continue

        # Nasdaq membership: forced (ATS layer) or fuzzy-matched (aggregator layer).
        ticker = r.get("forced_ticker", "")
        conf = 100
        comp = universe.get(ticker) if ticker else None
        if not ticker:
            m = matcher.match(company)
            if m:
                ticker, comp, conf = m.ticker, m.company, m.confidence

        role_type = r.get("role_type") or _infer_role(title)
        if not early_career_ok(title, r.get("category", ""), role_type, ccfg):
            continue
        track = track_of(title, r.get("category", ""), ccfg)

        # Aggregator feeds are already scoped to tech; raw ATS boards are not — they
        # list every department, so the loose early-career keywords ("associate", " i ")
        # would otherwise leak warehouse/ops/sales roles in. Keep only tech-track roles
        # from the direct-ATS layer (identified by the forced ticker it stamps).
        if r.get("forced_ticker") and track == "other":
            continue

        key = job_key(company, title, r.get("url", ""))
        locs = r.get("locations") or []
        if key in jobs:
            ex = jobs[key]
            ex["locations"] = sorted(set(ex["locations"]) | set(locs))
            ex["remote"] = ex["remote"] or is_remote(locs)
            ex["active"] = ex["active"] or bool(r.get("active", True))
            if ticker and not ex["ticker"]:      # let ATS/matched record supply ticker
                ex.update(ticker=ticker, industry=comp.industry if comp else "",
                          market_cap=comp.market_cap if comp else 0, confidence=conf)
            continue
        jobs[key] = {
            "key": key, "title": title, "company_name": company,
            "role_type": role_type, "track": track,
            "ticker": ticker, "industry": comp.industry if comp else "",
            "market_cap": comp.market_cap if comp else 0, "confidence": conf if ticker else 0,
            "locations": locs, "remote": is_remote(locs),
            "active": bool(r.get("active", True)),
            "date_posted": r.get("date_posted", 0),
            "source": r.get("source", ""), "url": r.get("url", ""),
        }

    # ---- diff against last run --------------------------------------------
    state = store.load(ocfg["state_path"])
    state, new_keys = store.reconcile(state, set(jobs), ocfg["keep_stale_days"])
    store.save(ocfg["state_path"], state)
    for k, j in jobs.items():
        j["is_new"] = k in new_keys

    # ---- sort: DS/ML first, then new, then newest -------------------------
    ordered = sorted(jobs.values(), key=lambda j: (
        j["track"] != "dsml", not j["is_new"], not j["active"], -int(j["date_posted"] or 0),
    ))

    nasdaq_n = sum(1 for j in ordered if j["ticker"])
    dsml_n = sum(1 for j in ordered if j["track"] == "dsml")
    print(f"· {len(ordered)} early-career roles kept "
          f"({nasdaq_n} at Nasdaq companies · {dsml_n} DS/ML · {len(new_keys)} new)")

    render.write_csv(ocfg["csv_path"], ordered)
    # The page shows actionable roles only; expired ones stay in the CSV archive.
    render.write_html(ocfg["html_path"], [j for j in ordered if j["active"]], ocfg["owner"])
    print(f"· wrote {ocfg['csv_path']} and {ocfg['html_path']}")
    return 0


def _infer_role(title: str) -> str:
    t = title.lower()
    return "intern" if ("intern" in t or "co-op" in t or "co op" in t) else "new_grad"


if __name__ == "__main__":
    sys.exit(main())
