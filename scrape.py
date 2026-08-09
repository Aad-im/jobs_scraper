#!/usr/bin/env python3
"""tech-jobs — early-career job tracker with a DS/ML focus.

Pipeline:
  1. Build the Nasdaq universe (official membership + industry + market cap).
  2. Fetch every source concurrently:
       · aggregator feeds  (broad recall: Google, Meta, Microsoft, Apple, TikTok…)
       · direct ATS boards (freshness + full detail: Greenhouse, Lever, Ashby,
         Workday, SmartRecruiters, Eightfold)
       · big-tech APIs     (Amazon)
  3. Classify (early-career filter + track), normalize locations, dedupe,
     diff against the last run.
  4. Score every role against profile.yaml and pick the shortlist.
  5. Write jobs.csv, health.json and docs/index.html.

Run:  python scrape.py [--no-net] [--dry-run]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import sys
import time
import traceback

import yaml

from src import locations, render, store
from src.classify import early_career_ok, function_ok, track_of
from src.fit import FitScorer
from src.matching import CompanyMatcher
from src.nasdaq import load_universe
from src.sources import aggregators, ats, bigtech


def job_key(company: str, title: str) -> str:
    # Collapse the same role posted across many single-location rows into one.
    return f"{company}|{title}".lower().strip()


class Health:
    """Per-source outcome for the run, so a silently dead board is visible."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, name: str, kind: str, count: int, error: str = "") -> None:
        self.rows.append({"source": name, "kind": kind, "jobs": count,
                          "ok": not error, "error": error})

    @property
    def failures(self) -> list[dict]:
        return [r for r in self.rows if not r["ok"]]

    @property
    def empties(self) -> list[dict]:
        return [r for r in self.rows if r["ok"] and r["jobs"] == 0]


def fetch_all(cfg: dict, health: Health) -> list[dict]:
    """Pull every configured source concurrently. One bad board never kills a run."""
    tasks: list[tuple[str, str, callable]] = []
    for feed in cfg.get("aggregators", []):
        tasks.append((feed["name"], "aggregator", lambda f=feed: aggregators.fetch(f)))
    for target in cfg.get("ats_targets", []):
        label = f"{target['name']} ({target['ats']})"
        tasks.append((label, "ats", lambda t=target: ats.fetch_target(t)))
    for provider, queries in (cfg.get("bigtech") or {}).items():
        fetcher = bigtech.FETCHERS.get(provider)
        if not fetcher:
            continue
        for q in queries:
            tasks.append((q["name"], "bigtech", lambda f=fetcher, q=q: f(q)))

    raw: list[dict] = []
    workers = int(cfg.get("concurrency", 12))
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn): (name, kind) for name, kind, fn in tasks}
        for fut in cf.as_completed(futures):
            name, kind = futures[fut]
            try:
                items = fut.result()
            except Exception as e:  # noqa: BLE001 — one board must not end the run
                health.record(name, kind, 0, f"{type(e).__name__}: {e}")
                print(f"  ! {name}: {type(e).__name__}: {e}")
                continue
            health.record(name, kind, len(items))
            raw += items
    return raw


def build_jobs(raw: list[dict], cfg: dict, universe: dict, matcher: CompanyMatcher,
               scorer: FitScorer) -> dict[str, dict]:
    ccfg = cfg["classify"]
    jobs: dict[str, dict] = {}
    for r in raw:
        title = (r.get("title") or "").strip()
        company = (r.get("company_name") or "").strip()
        if not title or not company:
            continue

        # Nasdaq membership: forced (direct-ATS layer) or fuzzy-matched (aggregators).
        ticker = r.get("forced_ticker", "")
        conf, comp = 100, universe.get(ticker) if ticker else None
        if not ticker:
            m = matcher.match(company)
            if m:
                ticker, comp, conf = m.ticker, m.company, m.confidence

        role_type = r.get("role_type") or _infer_role(title)
        desc = r.get("description", "") or ""
        if not early_career_ok(title, r.get("category", ""), role_type, ccfg, desc):
            continue
        # Aggregator feeds are pre-scoped to tech; raw ATS boards list every
        # department, so non-technical functions are dropped from that layer only.
        from_board = bool(r.get("source", "").startswith(("ATS:", "Amazon")))
        if from_board and not function_ok(title, r.get("department", ""), ccfg):
            continue
        track = track_of(title, r.get("category", ""), ccfg)
        if from_board and track == "other":
            continue

        key = job_key(company, title)
        locs = [x for x in (r.get("locations") or []) if x]
        if key in jobs:
            _merge(jobs[key], r, locs, ticker, comp, conf)
            continue

        loc = locations.summarize(locs)
        jobs[key] = {
            "key": key, "title": title, "company_name": company,
            "role_type": role_type, "track": track,
            "ticker": ticker, "industry": comp.industry if comp else "",
            "market_cap": comp.market_cap if comp else 0,
            "confidence": conf if ticker else 0,
            "locations": locs, "loc": loc, "remote": loc["remote"],
            "seasons": sorted(r.get("seasons") or []),
            "years": r.get("years") or [],
            "active": bool(r.get("active", True)),
            "date_posted": _epoch(r.get("date_posted")),
            "source": r.get("source", ""), "url": r.get("url", ""),
            "description": desc, "category": r.get("category", ""),
            "department": r.get("department", ""),
            "employer_tier": scorer.tier_for(company, r.get("employer_tier", "")),
        }
    return jobs


def _merge(existing: dict, r: dict, locs: list[str], ticker: str, comp, conf: int) -> None:
    """Fold a duplicate posting into the row we already have."""
    if locs:
        existing["locations"] = sorted(set(existing["locations"]) | set(locs))
        existing["loc"] = locations.summarize(existing["locations"])
        existing["remote"] = existing["loc"]["remote"]
    existing["seasons"] = sorted(set(existing["seasons"]) | set(r.get("seasons") or []))
    existing["years"] = sorted(set(existing["years"]) | set(r.get("years") or []))
    existing["active"] = existing["active"] or bool(r.get("active", True))
    existing["date_posted"] = max(existing["date_posted"], _epoch(r.get("date_posted")))
    # A direct-ATS row carries a description and a canonical URL; an aggregator
    # row usually doesn't. Prefer whichever record actually has the detail.
    if len(r.get("description") or "") > len(existing["description"]):
        existing["description"] = r["description"]
    if r.get("source", "").startswith("ATS:") and not existing["source"].startswith("ATS:"):
        existing.update(source=r["source"], url=r.get("url") or existing["url"])
    if ticker and not existing["ticker"]:
        existing.update(ticker=ticker, industry=comp.industry if comp else "",
                        market_cap=comp.market_cap if comp else 0, confidence=conf)
    if r.get("employer_tier") and not existing["employer_tier"]:
        existing["employer_tier"] = r["employer_tier"]


def _epoch(value) -> int:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return n // 1000 if n > 1e12 else max(0, n)


def _infer_role(title: str) -> str:
    t = title.lower()
    return "intern" if ("intern" in t or "co-op" in t or "co op" in t) else "new_grad"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="run everything but don't write any files")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--profile", default="profile.yaml")
    args = ap.parse_args(argv)

    started = time.time()
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    with open(args.profile, encoding="utf-8") as f:
        profile = yaml.safe_load(f)
    ocfg = cfg["output"]
    scorer = FitScorer(profile)

    print("· building Nasdaq universe…")
    universe = load_universe(**cfg["nasdaq_universe"])
    matcher = CompanyMatcher(universe, cfg["matching"]["fuzzy_cutoff"])
    print(f"  {len(universe)} Nasdaq-listed companies")

    health = Health()
    n_sources = (len(cfg.get("aggregators", [])) + len(cfg.get("ats_targets", []))
                 + sum(len(v) for v in (cfg.get("bigtech") or {}).values()))
    print(f"· fetching {n_sources} sources ({cfg.get('concurrency', 12)}-way)…")
    raw = fetch_all(cfg, health)
    print(f"  {len(raw)} raw postings from {len(health.rows) - len(health.failures)}"
          f"/{len(health.rows)} live sources")

    print("· classifying, matching, deduping…")
    jobs = build_jobs(raw, cfg, universe, matcher, scorer)

    print("· scoring against profile…")
    now = int(time.time())
    for j in jobs.values():
        fit = scorer.score(j, now)
        j["fit"], j["fit_why"], j["fit_flags"] = fit.score, fit.reasons, fit.flags

    state = store.load(ocfg["state_path"])
    state, new_keys = store.reconcile(state, set(jobs), ocfg["keep_stale_days"])
    for k, j in jobs.items():
        j["is_new"] = k in new_keys

    ordered = sorted(jobs.values(), key=lambda j: (
        -j["fit"], j["track"] != "dsml", not j["is_new"], not j["active"],
        -int(j["date_posted"] or 0),
    ))
    picks = scorer.shortlist(ordered)
    pick_keys = {j["key"] for j in picks}
    for j in ordered:
        j["shortlisted"] = j["key"] in pick_keys

    active = [j for j in ordered if j["active"]]
    print(f"· {len(ordered)} early-career roles "
          f"({len(active)} active · {sum(1 for j in ordered if j['track'] == 'dsml')} DS/ML "
          f"· {len(new_keys)} new · {len(picks)} shortlisted)")

    if health.failures:
        print(f"  ! {len(health.failures)} source(s) failed: "
              + ", ".join(r["source"] for r in health.failures[:8]))
    if health.empties:
        print(f"  · {len(health.empties)} source(s) returned nothing: "
              + ", ".join(r["source"] for r in health.empties[:8]))

    if args.dry_run:
        print("· dry run — nothing written")
        return 0

    # A collapse in volume means the sources broke, not that hiring stopped.
    # Publishing that would silently wipe a working board, so refuse instead.
    floor = int(ocfg.get("min_jobs_to_publish", 0))
    if len(active) < floor:
        print(f"! only {len(active)} active roles (floor {floor}); "
              "refusing to overwrite the board. Previous output kept.")
        store.save_health(ocfg.get("health_path", ""), health.rows, len(ordered),
                          len(active), len(picks), time.time() - started, aborted=True)
        return 2

    store.save(ocfg["state_path"], state)
    render.write_csv(ocfg["csv_path"], ordered)
    # The page shows actionable roles only; expired ones stay in the CSV archive.
    render.write_html(ocfg["html_path"], active, picks, ocfg["owner"], health.rows)
    store.save_health(ocfg.get("health_path", ""), health.rows, len(ordered),
                      len(active), len(picks), time.time() - started)
    print(f"· wrote {ocfg['csv_path']} and {ocfg['html_path']} "
          f"in {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:  # noqa: BLE001 — a stack trace beats a bare exit code in CI
        traceback.print_exc()
        sys.exit(1)
