# nasdaq-tech-jobs

A personal, self-updating tracker for **early-career (new-grad + internship) tech
roles at Nasdaq-listed companies**, with a special focus on **data science / ML /
research**. It produces a filterable HTML dashboard and a CSV archive, and can run
itself daily and free on GitHub Actions + GitHub Pages.

## How it works (hybrid pipeline)

1. **Nasdaq universe** — the official Nasdaq-listed symbol file, intersected with a
   screener export that adds industry + market cap. Only true Nasdaq companies survive.
2. **Aggregator layer** *(broad recall)* — pulls the daily-updated SimplifyJobs
   new-grad and internship feeds and matches each posting to a Nasdaq ticker by
   company name (exact + fuzzy).
3. **Direct ATS layer** *(freshness + full detail)* — polls curated company job
   boards straight from public Greenhouse / Lever / Ashby JSON APIs. Membership is
   guaranteed for these, so they never rely on name matching.
4. **Classify + filter** — keeps early-career roles, tags each with a track
   (`dsml`, `data_eng`, `swe`, `quant`, `hardware`, `other`), and diffs against the
   previous run so it can flag what's **new**.
5. **Output** — `data/jobs.csv` (full archive) and `docs/index.html` (dashboard).

## Quick start (local)

```bash
pip install -r requirements.txt
python scrape.py
open docs/index.html          # or double-click it
```

The page filters/sorts entirely in your browser: search box, New-today toggle,
grad/intern, track chips (DS/ML is highlighted), and "Nasdaq-confirmed only /
Remote only / Active only / Hide applied". Click **applied** on a row to grey it
out (remembered in your browser).

## Deploy it to run itself (recommended)

1. Push this folder to a new GitHub repo.
2. **Settings → Pages** → Source: *Deploy from a branch* → branch `main`, folder
   `/docs`. Your board goes live at `https://<you>.github.io/<repo>/`.
3. The included workflow (`.github/workflows/update.yml`) already runs daily at
   13:00 UTC, regenerates everything, and commits it back. Trigger a first run
   manually from the **Actions** tab.

## Expand the direct-ATS list (the good part)

The aggregator layer already covers most big names. To add fast, full-detail
coverage of specific Nasdaq companies, auto-derive verified ATS slugs from live
job URLs:

```bash
python -m src.discover        # writes ats_targets_auto.yaml, ranked by confidence
```

Eyeball the results (watch for name collisions — e.g. an EV "Lucid" vs a software
"Lucid"), then paste the good entries into `ats_targets:` in `config.yaml`.
Greenhouse/Lever/Ashby work out of the box; Workday-based companies need a
per-tenant handler (not included).

## Tuning

Everything lives in `config.yaml` — no code edits needed:
- `classify.tracks` — keywords that define each track. Add terms to catch more
  DS/ML variants (e.g. `"recommendation"`, `"ranking"`, `"speech"`).
- `classify.seniority_block` — titles to exclude as too senior.
- `matching.fuzzy_cutoff` — raise to reduce false Nasdaq matches, lower for recall.
- `output.keep_stale_days` — grace period before a vanished role drops off.

## Notes & limits

- ATS endpoints are public and unauthenticated, but be a reasonable citizen — the
  daily cadence and small target list keep you well within polite use.
- Fuzzy company matches are marked (grey ticker chip + confidence tooltip) so you
  can tell "definitely Nasdaq" from "probably Nasdaq".
- As an incoming MS student you're eligible for both new-grad full-time and
  (grad/research) internships — the tracker keeps both, and "applied scientist /
  research intern" roles are treated as in-focus rather than filtered as senior.

## Layout

```
scrape.py              # entry point / orchestrator
config.yaml            # all sources, keywords, targets, output paths
src/
  nasdaq.py            # build Nasdaq universe
  matching.py          # company name -> ticker
  classify.py          # early-career filter + track detection
  discover.py          # auto-derive ATS slugs from job URLs
  store.py             # new/seen diffing across runs
  render.py            # CSV + HTML dashboard
  sources/
    aggregators.py     # SimplifyJobs feeds
    ats.py             # Greenhouse / Lever / Ashby
docs/index.html        # the dashboard (GitHub Pages serves this)
data/jobs.csv          # full archive
.github/workflows/update.yml
```
