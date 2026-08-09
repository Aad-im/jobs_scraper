# tech-jobs

A personal, self-updating tracker for **early-career (new-grad + internship) tech
roles**, with a heavy focus on **AI / ML / research**. It polls ~150 job sources,
scores every role against your résumé, and publishes a filterable dashboard with
a ranked **Top picks** shortlist. Runs itself daily and free on GitHub Actions +
GitHub Pages.

```bash
pip install -r requirements.txt
python scrape.py
open docs/index.html
```

## What the page gives you

**★ Top picks** — the shortlist. Every role scored 0-100 against `profile.yaml`
and ranked, as cards that explain themselves: employer tier, why the role
matched, which of your skills the posting mentions, and warning flags
("PhD mentioned", "5+ yrs experience"). Slots are reserved for internships so
the intern path doesn't get buried under full-time roles.

**All roles** — the full table, filterable by:

| Filter | What it does |
|---|---|
| **Location** | Country dropdown + searchable metro list with live counts, plus *US only* / *Remote* / *Clear* shortcuts. A role shows up under every metro it lists. |
| Search | title, company, ticker, location, industry |
| New today · Grad/Intern · Age · Market cap · Season | as before |
| Track chips | DS/ML · Data Eng · SWE · Quant · Hardware · Other |
| Nasdaq-confirmed · Remote · Hide applied | toggles |

Every filter is encoded in the URL hash, so **🔗 copy link** shares the exact
view. Marking a role *applied* is remembered in your browser.

## How it works

1. **Nasdaq universe** — the official Nasdaq symbol file intersected with a
   screener export for industry + market cap. Cached on disk (`cache_hours`) so
   a bad upstream day can't take the run down. Membership is a *tag*, not a
   gate — private AI labs are first-class here.
2. **Aggregator layer** *(broad recall)* — five daily SimplifyJobs-style feeds.
   This is how Google, Meta, Microsoft, Apple and TikTok get covered.
3. **Direct ATS layer** *(freshness + detail)* — ~130 company boards polled
   straight from public JSON APIs across **six** platforms:
   Greenhouse · Lever · Ashby · Workday · SmartRecruiters · Eightfold.
4. **Big-tech APIs** — Amazon's `amazon.jobs` search endpoint.
5. **Classify** — early-career gate (including numeric levels like "Engineer 3"
   and years-of-experience bars found in the body), a non-technical function
   filter for raw ATS boards, and a track label.
6. **Normalize locations** — every raw string (`"US, CA, Santa Clara"`,
   `"USA - Remote"`, `"Bellevue, Washington"`) collapses onto one of ~150 metro
   buckets. See `src/locations.py`.
7. **Score + shortlist** — `src/fit.py` against `profile.yaml`.
8. **Output** — `data/jobs.csv` (archive), `data/health.json` (per-source
   outcome), `docs/index.html` (dashboard).

All sources are fetched concurrently; a single dead board never ends a run.

## Tuning the shortlist

Everything lives in **`profile.yaml`** — no code changes needed:

- `weights` — the five components (role 45, employer 25, skills 20, stage 10,
  freshness 10). Location is deliberately not scored; that's what the location
  filter is for.
- `role_tiers` / `role_penalties` — which titles are a bullseye and which are
  off-profile.
- `company_tiers` — maps employers to `frontier_lab` / `big_tech` / `ai_infra` /
  `tech` / `quant`. Needed because aggregator feeds carry no tier of their own.
- `skills` — the stack keywords worth points when a posting mentions them.
- `shortlist` — `min_score`, `max_size`, `max_per_company`, `reserve_intern`.

Re-run `python scrape.py` to see the effect. `--dry-run` writes nothing.

## Adding more sources

The discovery tool parses real apply URLs out of the aggregator feeds, derives
ATS coordinates, and (with `--verify`) actually calls each board:

```bash
python -m src.discover --verify --min-jobs 4
```

That currently finds **~1,450 live boards** beyond what's already configured.
Review `ats_targets_auto.yaml` and paste the good ones into `ats_targets:` in
`config.yaml` with a `tier`. Watch for name collisions — `greenhouse:figure` is
a fintech, `greenhouse:figureai` is the robotics company.

Workday targets need `tenant|site|wdN` as the slug and a `queries:` list;
Workday caps pages at 20 rows, so a few relevance-ranked searches beat walking a
2,000-role board. Eightfold slugs are `host|domain`.

### Sources deliberately not used

- **Microsoft** — `gcsservices.careers.microsoft.com` refuses connections from
  datacenter IPs, so it can't be polled from CI.
- **Apple** — `jobs.apple.com/api/v1/search` returns 0 results for most
  multi-word queries.
- **Google / Meta** — no stable public JSON endpoint; both need a rotating
  GraphQL `doc_id` that breaks without warning.

All four are still covered through the aggregator feeds.

## Robustness

- Retries with exponential backoff on 429/5xx, plus a retry when a board
  returns **200 with an empty body** (Ashby does this intermittently).
- Per-source health written to `data/health.json` and surfaced in the page
  footer and the Actions run summary — a board that quietly starts returning
  zero shows up in the git diff.
- `output.min_jobs_to_publish` — if a run collects fewer than that many active
  roles, it **refuses to overwrite** the board and exits 2. Sources breaking
  should never silently wipe a working site.
- On-disk cache for the Nasdaq CSVs, used as a fallback if the network fails.
- `python -m pytest tests/ -q` — 69 offline tests over location parsing,
  classification and fit scoring. CI runs them before the scrape.

## Deploy

1. Push to a GitHub repo.
2. **Settings → Pages** → Deploy from a branch → `main` / `/docs`.
3. `.github/workflows/update.yml` runs daily at 13:00 UTC, tests, regenerates,
   and commits. Kick off the first run from the **Actions** tab.
