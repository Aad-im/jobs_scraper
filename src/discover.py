"""Auto-derive verified Nasdaq-company -> ATS-slug mappings from job URLs.

The aggregator feeds contain real apply URLs like
`boards.greenhouse.io/gitlab/jobs/123`. We parse the slug out of those URLs,
attach the Nasdaq ticker via the matcher, and write a ranked YAML you can paste
into config.ats_targets after a quick eyeball.

Run:  python -m src.discover
"""
from __future__ import annotations
import re
import sys
from collections import defaultdict

import yaml

from .nasdaq import load_universe
from .matching import CompanyMatcher
from .sources import aggregators

_PATTERNS = [
    ("greenhouse", re.compile(r"boards\.greenhouse\.io/([a-z0-9][a-z0-9_-]+)/jobs")),
    ("greenhouse", re.compile(r"job-boards\.greenhouse\.io/([a-z0-9][a-z0-9_-]+)/jobs")),
    ("lever",      re.compile(r"jobs\.lever\.co/([a-z0-9][a-z0-9_-]+)")),
    ("ashby",      re.compile(r"jobs\.ashbyhq\.com/([a-z0-9][a-z0-9_-]+)")),
]
_SKIP = {"embed", "job_app"}


def slug_from_url(url: str):
    for ats, pat in _PATTERNS:
        m = pat.search(url or "")
        if m and m.group(1) not in _SKIP:
            return ats, m.group(1)
    return None


def main() -> int:
    cfg = yaml.safe_load(open("config.yaml"))
    uni = load_universe(**cfg["nasdaq_universe"])
    matcher = CompanyMatcher(uni, cfg["matching"]["fuzzy_cutoff"])

    # ticker -> (ats,slug) -> [count, confidence, company_name]
    found: dict[str, dict[tuple[str, str], list]] = defaultdict(lambda: defaultdict(lambda: [0, 0, ""]))
    for feed in cfg["aggregators"]:
        for job in aggregators.fetch(feed):
            m = matcher.match(job["company_name"])
            if not m:
                continue
            s = slug_from_url(job["url"])
            if not s:
                continue
            rec = found[m.ticker][s]
            rec[0] += 1
            rec[1] = max(rec[1], m.confidence)
            rec[2] = m.company.name

    targets = []
    for ticker, slugs in found.items():
        (ats, slug), (count, conf, name) = max(slugs.items(), key=lambda kv: kv[1][0])
        targets.append({
            "ticker": ticker, "name": name.split(" - ")[0].split(",")[0].strip(),
            "ats": ats, "slug": slug,
            "_evidence_jobs": count, "_name_confidence": conf,
        })
    targets.sort(key=lambda t: (-t["_name_confidence"], -t["_evidence_jobs"]))

    with open("ats_targets_auto.yaml", "w") as f:
        f.write("# Auto-derived from live job URLs. REVIEW before pasting into config.yaml.\n")
        f.write("# _name_confidence 100 = exact company match; lower = fuzzy (verify the slug).\n")
        f.write("# Watch for name collisions (e.g. an EV 'Lucid' vs a software 'Lucid').\n")
        yaml.safe_dump(targets, f, sort_keys=False, allow_unicode=True)

    print(f"Wrote {len(targets)} candidate targets to ats_targets_auto.yaml")
    print("Top 10 by confidence:")
    for t in targets[:10]:
        print(f"  {t['_name_confidence']:3}  {t['ticker']:6} {t['name'][:28]:28} "
              f"{t['ats']}:{t['slug']}  ({t['_evidence_jobs']} jobs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
