"""Auto-derive company -> ATS-slug mappings from live job URLs, and verify them.

The aggregator feeds contain real apply URLs like
`boards.greenhouse.io/gitlab/jobs/123` or
`nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/...`. This parses the
ATS coordinates out of those URLs, attaches a Nasdaq ticker where one matches,
and — with `--verify` — actually calls each candidate board so you only paste
working entries into config.ats_targets.

Run:  python -m src.discover [--verify] [--min-jobs N] [--top N]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import re
import sys
from collections import defaultdict

import yaml

from .matching import CompanyMatcher
from .nasdaq import load_universe
from .sources import aggregators, ats

_PATTERNS = [
    ("greenhouse", re.compile(r"(?:job-)?boards\.greenhouse\.io/([a-z0-9][a-z0-9_-]+)")),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board\?for=([a-z0-9][a-z0-9_-]+)")),
    ("lever",      re.compile(r"jobs\.(?:eu\.)?lever\.co/([a-z0-9][a-z0-9_-]+)")),
    ("ashby",      re.compile(r"jobs\.ashbyhq\.com/([a-z0-9][a-z0-9_.-]+)")),
    ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com/([A-Za-z0-9][A-Za-z0-9_-]+)")),
    # Workday needs three coordinates, so its slug is "tenant|site|wdN".
    ("workday", re.compile(
        r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")),
    ("eightfold", re.compile(r"([a-z0-9.-]*eightfold\.ai|[a-z0-9.-]*\.jobs\.[a-z0-9.-]+)/careers")),
]
_SKIP = {"embed", "job_app", "search", "careers", "jobs", "en-us", "job"}


def slug_from_url(url: str):
    """Return (ats, slug) or None. Workday slugs encode tenant|site|host."""
    url = url or ""
    for ats_name, pat in _PATTERNS:
        m = pat.search(url)
        if not m:
            continue
        if ats_name == "workday":
            tenant, host, site = m.group(1), m.group(2), m.group(3)
            if site in _SKIP:
                continue
            return ats_name, f"{tenant}|{site}|{host}"
        slug = m.group(1)
        if slug.lower() in _SKIP:
            continue
        return ats_name, slug
    return None


def verify(candidate: dict) -> tuple[dict, int, str]:
    """Poll a candidate board; return (candidate, job_count, error)."""
    try:
        rows = ats.HANDLERS[candidate["ats"]]({**candidate, "max_pages": 1})
        return candidate, len(rows), ""
    except Exception as e:  # noqa: BLE001
        return candidate, 0, f"{type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true",
                    help="poll each candidate board and keep only the live ones")
    ap.add_argument("--min-jobs", type=int, default=2,
                    help="minimum aggregator URLs backing a slug (default 2)")
    ap.add_argument("--top", type=int, default=0, help="verify only the top N candidates")
    ap.add_argument("--out", default="ats_targets_auto.yaml")
    args = ap.parse_args(argv)

    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    uni = load_universe(**cfg["nasdaq_universe"])
    matcher = CompanyMatcher(uni, cfg["matching"]["fuzzy_cutoff"])
    known = {(t["ats"], t["slug"]) for t in cfg.get("ats_targets", [])}

    # (ats, slug) -> [count, confidence, display_name, ticker]
    found: dict[tuple[str, str], list] = defaultdict(lambda: [0, 0, "", ""])
    for feed in cfg["aggregators"]:
        try:
            items = aggregators.fetch(feed)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {feed['name']}: {e}")
            continue
        for job in items:
            s = slug_from_url(job["url"])
            if not s:
                continue
            rec = found[s]
            rec[0] += 1
            m = matcher.match(job["company_name"])
            if m and m.confidence > rec[1]:
                rec[1], rec[3] = m.confidence, m.ticker
            if not rec[2]:
                rec[2] = job["company_name"]

    candidates = [
        {"name": name.split(" - ")[0].split(",")[0].strip() or slug,
         "ats": ats_name, "slug": slug, "ticker": ticker,
         "_evidence_jobs": count, "_name_confidence": conf}
        for (ats_name, slug), (count, conf, name, ticker) in found.items()
        if count >= args.min_jobs and (ats_name, slug) not in known
    ]
    candidates.sort(key=lambda t: (-t["_evidence_jobs"], -t["_name_confidence"]))
    print(f"{len(candidates)} new candidate boards "
          f"(≥{args.min_jobs} evidence URLs, not already in config)")

    if args.verify:
        pool = candidates[:args.top] if args.top else candidates
        print(f"verifying {len(pool)}…")
        live = []
        with cf.ThreadPoolExecutor(max_workers=cfg.get("concurrency", 12)) as ex:
            for cand, n, err in ex.map(verify, pool):
                if n:
                    cand["_live_jobs"] = n
                    live.append(cand)
                else:
                    print(f"  ✗ {cand['ats']}:{cand['slug']} {err[:70]}")
        candidates = sorted(live, key=lambda t: -t["_live_jobs"])
        print(f"{len(candidates)} live")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# Auto-derived from live job URLs. REVIEW before pasting into config.yaml.\n")
        f.write("# _name_confidence 100 = exact Nasdaq name match; lower = fuzzy.\n")
        f.write("# Watch for name collisions (e.g. an EV 'Lucid' vs a software 'Lucid',\n")
        f.write("# or fintech 'Figure' vs robotics 'Figure AI').\n")
        yaml.safe_dump(candidates, f, sort_keys=False, allow_unicode=True)

    print(f"Wrote {len(candidates)} candidates to {args.out}")
    for t in candidates[:15]:
        n = t.get("_live_jobs", t["_evidence_jobs"])
        print(f"  {t['name'][:30]:30} {t['ats']}:{t['slug'][:40]:40} ({n} jobs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
