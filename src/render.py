"""Write outputs: a flat CSV archive and a self-contained HTML dashboard.

The HTML embeds the jobs as a JSON blob and does all filtering, sorting and
searching client-side in vanilla JS, so it works as a static file on GitHub
Pages or opened straight off disk. localStorage is used only to remember which
roles you've marked applied.

Two views share one dataset: **Top picks** (the profile-scored shortlist, as
cards that explain their own ranking) and **All roles** (the full filterable
table).
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone

CSV_FIELDS = [
    "new", "shortlisted", "fit", "role_type", "track", "company", "ticker", "tier",
    "industry", "title", "location", "metros", "country", "remote", "nasdaq",
    "confidence", "active", "posted", "seasons", "flags", "source", "url",
]


def write_csv(path: str, jobs: list[dict]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for j in jobs:
            loc = j.get("loc") or {}
            w.writerow({
                "new": "YES" if j.get("is_new") else "",
                "shortlisted": "YES" if j.get("shortlisted") else "",
                "fit": j.get("fit", 0),
                "role_type": j["role_type"],
                "track": j["track"],
                "company": j["company_name"],
                "ticker": j.get("ticker", ""),
                "tier": j.get("employer_tier", ""),
                "industry": j.get("industry", ""),
                "title": j["title"],
                "location": " | ".join(j.get("locations") or []),
                "metros": " | ".join(loc.get("metros") or []),
                "country": " | ".join(loc.get("countries") or []),
                "remote": "YES" if j.get("remote") else "",
                "nasdaq": "YES" if j.get("ticker") else "",
                "confidence": j.get("confidence", ""),
                "active": "YES" if j["active"] else "",
                "posted": _date(j.get("date_posted")),
                "seasons": "/".join(j.get("seasons") or []),
                "flags": "; ".join(j.get("fit_flags") or []),
                "source": j["source"],
                "url": j["url"],
            })


def _date(epoch) -> str:
    try:
        if epoch:
            return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        pass
    return ""


def _row(j: dict) -> dict:
    loc = j.get("loc") or {}
    labels = loc.get("labels") or []
    picked = bool(j.get("shortlisted"))
    row = {
        "new": bool(j.get("is_new")),
        "role": j["role_type"],
        "track": j["track"],
        "company": j["company_name"],
        "ticker": j.get("ticker", ""),
        "industry": j.get("industry", ""),
        "cap": j.get("market_cap", 0),
        "tier": j.get("employer_tier", ""),
        "title": j["title"],
        "loc": ", ".join(labels[:3]) + ("…" if len(labels) > 3 else "") or "—",
        "metros": loc.get("metros") or [],
        "ctry": loc.get("countries") or [],
        "remote": bool(j.get("remote")),
        "nasdaq": bool(j.get("ticker")),
        "conf": j.get("confidence", 0),
        "active": bool(j["active"]),
        "posted": _date(j.get("date_posted")),
        "seasons": j.get("seasons") or [],
        "source": j["source"],
        "url": j["url"],
        "id": j["key"],
        "fit": j.get("fit", 0),
        "pick": picked,
    }
    # Only the Top-picks cards render the explanation, and carrying it for all
    # ~5k rows costs about a megabyte of page weight for nothing.
    if picked:
        row["why"] = (j.get("fit_why") or [])[:4]
        row["flags"] = j.get("fit_flags") or []
    return row


def write_html(path: str, jobs: list[dict], picks: list[dict], owner: str,
               health: list[dict] | None = None) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = [_row(j) for j in jobs]
    pick_ids = [j["key"] for j in picks]

    metro_counts: dict[str, int] = {}
    country_counts: dict[str, int] = {}
    for r in rows:
        for m in r["metros"]:
            metro_counts[m] = metro_counts.get(m, 0) + 1
        for c in r["ctry"]:
            country_counts[c] = country_counts.get(c, 0) + 1

    health = health or []
    meta = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "total": len(rows),
        "new": sum(r["new"] for r in rows),
        "dsml": sum(1 for r in rows if r["track"] == "dsml"),
        "picks": len(pick_ids),
        "companies": len({r["company"] for r in rows}),
        "metros": sorted(metro_counts.items(), key=lambda kv: (-kv[1], kv[0])),
        "countries": sorted(country_counts.items(), key=lambda kv: (-kv[1], kv[0])),
        "sources_ok": sum(1 for h in health if h["ok"]),
        "sources_total": len(health),
        "failed": [h["source"] for h in health if not h["ok"]][:12],
    }

    html = (_TEMPLATE
            .replace("__OWNER__", owner)
            .replace("__META__", _js(meta))
            .replace("__PICKS__", _js(pick_ids))
            .replace("__DATA__", _js(rows)))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def _js(obj) -> str:
    """JSON for embedding in a <script> block: `</` must never appear verbatim."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


# --------------------------------------------------------------------------- #
# Self-contained page. Design: a light "market terminal" — monospace data,
# a scrolling ticker-tape summary strip (the signature), DS/ML rows accented.
# --------------------------------------------------------------------------- #
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__OWNER__ · early-career tech &amp; ML roles</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#F5F6F8; --surface:#FFFFFF; --ink:#141922; --muted:#5B6675;
    --hair:#E3E7EC; --primary:#0B5FA5; --up:#0E9F6E; --dsml:#6D45C7;
    --warn:#C2410C; --gold:#B4801A;
    --shadow:0 1px 2px rgba(20,25,34,.05),0 8px 24px rgba(20,25,34,.05);
    --disp:'Space Grotesk',system-ui,sans-serif;
    --body:'Inter',system-ui,-apple-system,sans-serif;
    --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--body);
    font-size:14px;line-height:1.45;-webkit-font-smoothing:antialiased}
  a{color:var(--primary);text-decoration:none}
  a:hover{text-decoration:underline}

  header{background:var(--ink);color:#EAF0F6;padding:18px 22px 0}
  .wm{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
  .wm h1{font-family:var(--disp);font-weight:700;font-size:20px;letter-spacing:-.01em;margin:0}
  .wm .dot{width:8px;height:8px;border-radius:50%;background:var(--up);
    box-shadow:0 0 0 3px rgba(14,159,110,.25);align-self:center}
  .wm .stamp{font-family:var(--mono);font-size:11px;color:#8A97A6;margin-left:auto}

  /* signature: ticker-tape summary */
  .tape{overflow:hidden;margin-top:14px;border-top:1px solid #262E3A;background:#0E141C}
  .tape ul{display:flex;gap:0;margin:0;padding:0;list-style:none;
    white-space:nowrap;animation:scroll 40s linear infinite;width:max-content}
  .tape li{font-family:var(--mono);font-size:12px;color:#B7C2CE;padding:9px 26px;
    border-right:1px solid #1B2430}
  .tape b{color:#fff;font-weight:500}
  .tape .g{color:#3FD79A}.tape .v{color:#B79CF0}.tape .y{color:#F0C674}
  @keyframes scroll{from{transform:translateX(0)}to{transform:translateX(-50%)}}
  @media (prefers-reduced-motion:reduce){.tape ul{animation:none}}

  /* view tabs */
  .tabs{display:flex;gap:2px;background:#0E141C;padding:0 22px;border-top:1px solid #1B2430}
  .tabs button{font-family:var(--disp);font-weight:500;font-size:14px;letter-spacing:.01em;
    background:none;border:0;border-bottom:2px solid transparent;color:#8A97A6;
    padding:11px 16px;cursor:pointer}
  .tabs button:hover{color:#D6DEE7}
  .tabs button[aria-selected=true]{color:#fff;border-bottom-color:var(--up)}
  .tabs .n{font-family:var(--mono);font-size:11px;opacity:.75;margin-left:6px}

  .controls{position:sticky;top:0;z-index:30;background:var(--surface);
    border-bottom:1px solid var(--hair);padding:12px 22px;box-shadow:var(--shadow)}
  .row1{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .row1+.row1{margin-top:10px}
  #q{flex:1 1 240px;min-width:170px;font-family:var(--body);font-size:14px;
    padding:9px 12px;border:1px solid var(--hair);border-radius:9px;background:#fff}
  #q:focus{outline:2px solid var(--primary);outline-offset:1px}
  .seg{display:inline-flex;border:1px solid var(--hair);border-radius:9px;overflow:hidden}
  .seg button{font-family:var(--body);font-size:13px;padding:8px 13px;border:0;
    background:#fff;color:var(--muted);cursor:pointer}
  .seg button[aria-pressed=true]{background:var(--ink);color:#fff}
  .chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}
  .chip{font-family:var(--mono);font-size:11.5px;letter-spacing:.02em;
    padding:6px 11px;border:1px solid var(--hair);border-radius:999px;background:#fff;
    color:var(--muted);cursor:pointer;user-select:none}
  .chip[aria-pressed=true]{color:#fff;border-color:transparent}
  .chip.dsml[aria-pressed=true]{background:var(--dsml)}
  .chip.on[aria-pressed=true]{background:var(--primary)}
  .toggles{display:flex;gap:16px;flex-wrap:wrap;margin-top:10px;
    font-size:13px;color:var(--muted);align-items:center}
  .toggles label{display:inline-flex;gap:6px;align-items:center;cursor:pointer}
  .count{font-family:var(--mono);font-size:12px;color:var(--muted);margin-left:auto;align-self:center}

  /* ---- location filter ---- */
  .locwrap{position:relative}
  .locbtn{display:inline-flex;align-items:center;gap:8px;font-family:var(--body);
    font-size:13px;padding:8px 13px;border:1px solid var(--hair);border-radius:9px;
    background:#fff;color:var(--ink);cursor:pointer}
  .locbtn:hover{border-color:#C6CFD9}
  .locbtn .pin{color:var(--primary)}
  .locbtn .badge2{font-family:var(--mono);font-size:11px;background:var(--primary);
    color:#fff;border-radius:999px;padding:1px 7px}
  .locpop{position:absolute;top:calc(100% + 6px);left:0;z-index:60;width:330px;
    background:#fff;border:1px solid var(--hair);border-radius:12px;
    box-shadow:0 10px 40px rgba(20,25,34,.16);padding:12px;display:none}
  .locpop[data-open=true]{display:block}
  .locpop h4{font-family:var(--disp);font-size:12px;text-transform:uppercase;
    letter-spacing:.06em;color:var(--muted);margin:0 0 8px}
  .locpop select,.locpop input[type=search]{width:100%;font-family:var(--body);
    font-size:13px;padding:8px 10px;border:1px solid var(--hair);border-radius:8px;
    background:#fff;margin-bottom:9px}
  .metrolist{max-height:260px;overflow-y:auto;border-top:1px solid var(--hair);
    padding-top:8px;display:flex;flex-direction:column;gap:1px}
  .metrolist label{display:flex;align-items:center;gap:8px;font-size:13px;
    padding:5px 6px;border-radius:6px;cursor:pointer}
  .metrolist label:hover{background:#F2F5F8}
  .metrolist .mc{margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--muted)}
  .locfoot{display:flex;gap:8px;margin-top:10px;padding-top:10px;border-top:1px solid var(--hair)}
  .locfoot button{flex:1;font-family:var(--body);font-size:12.5px;padding:7px;
    border:1px solid var(--hair);border-radius:8px;background:#fff;cursor:pointer;color:var(--muted)}
  .locfoot button:hover{background:#F2F5F8;color:var(--ink)}
  .selchips{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
  .selchip{font-family:var(--mono);font-size:11px;background:#EEF3F8;color:var(--primary);
    border:1px solid #D6E3EE;border-radius:999px;padding:4px 8px;cursor:pointer}
  .selchip:hover{background:#E1EBF4}
  .selchip::after{content:" ×";opacity:.6}

  main{padding:0 14px 60px}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  thead th{text-align:left;font-family:var(--mono);font-weight:500;font-size:11px;
    text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
    padding:14px 12px 8px;cursor:pointer;white-space:nowrap}
  thead th:hover{color:var(--ink)}
  tbody tr{border-top:1px solid var(--hair);background:var(--surface)}
  tbody tr.new{background:linear-gradient(90deg,rgba(14,159,110,.06),transparent 60%)}
  tbody tr.dsml td:first-child{box-shadow:inset 3px 0 0 var(--dsml)}
  tbody tr.applied{opacity:.42}
  td{padding:11px 12px;vertical-align:top}
  .co{font-weight:600}
  .tk{font-family:var(--mono);font-size:11px;color:#fff;background:var(--primary);
    padding:1px 6px;border-radius:5px;margin-left:6px}
  .tk.fuzzy{background:var(--muted)}
  .ttl{max-width:460px}
  .badge{font-family:var(--mono);font-size:10.5px;padding:2px 7px;border-radius:999px;
    text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
  .b-dsml{background:rgba(109,69,199,.12);color:var(--dsml)}
  .b-swe{background:rgba(11,95,165,.10);color:var(--primary)}
  .b-oth{background:#EEF1F4;color:var(--muted)}
  .b-new{background:var(--up);color:#fff}
  .b-pick{background:rgba(180,128,26,.14);color:var(--gold)}
  .rt{font-family:var(--mono);font-size:11px;color:var(--muted)}
  .rem{color:var(--up);font-weight:600}
  .posted,.age{font-family:var(--mono);font-size:12px;color:var(--muted);white-space:nowrap}
  .age.fresh{color:var(--up);font-weight:600}
  .apply{font-family:var(--mono);font-size:12px}
  .mark{border:1px solid var(--hair);background:#fff;border-radius:6px;
    font-size:11px;padding:3px 8px;cursor:pointer;color:var(--muted)}
  .mark:hover{background:#F2F5F8;color:var(--ink)}
  .fitcell{font-family:var(--mono);font-size:12px;color:var(--muted);white-space:nowrap}
  .empty{padding:80px 20px;text-align:center;color:var(--muted)}
  .empty b{font-family:var(--disp);font-size:18px;color:var(--ink);display:block;margin-bottom:6px}

  /* ---- Top picks cards ---- */
  .picksintro{max-width:900px;margin:22px auto 6px;padding:0 8px;color:var(--muted);font-size:13.5px}
  .picksintro b{font-family:var(--disp);font-size:17px;color:var(--ink);display:block;margin-bottom:4px}
  .cards{max-width:900px;margin:14px auto;display:flex;flex-direction:column;gap:10px}
  .card{background:var(--surface);border:1px solid var(--hair);border-radius:12px;
    padding:14px 16px;display:grid;grid-template-columns:44px 1fr auto;gap:14px;
    box-shadow:var(--shadow)}
  .card.applied{opacity:.45}
  .card .rank{font-family:var(--disp);font-weight:700;font-size:19px;color:var(--muted);
    text-align:right;padding-top:2px}
  .card.top3 .rank{color:var(--gold)}
  .card h3{margin:0 0 3px;font-family:var(--disp);font-size:15.5px;font-weight:500;line-height:1.3}
  .card .sub{font-size:13px;color:var(--muted);margin-bottom:8px}
  .card .sub b{color:var(--ink);font-weight:600}
  .why{display:flex;gap:6px;flex-wrap:wrap}
  .why span{font-family:var(--mono);font-size:10.5px;background:#F2F5F8;color:var(--muted);
    border-radius:999px;padding:3px 9px}
  .why span.flag{background:rgba(194,65,12,.10);color:var(--warn)}
  .card .right{text-align:right;display:flex;flex-direction:column;gap:8px;align-items:flex-end}
  .meter{width:82px}
  .meter .num{font-family:var(--mono);font-size:16px;font-weight:500;color:var(--ink)}
  .meter .num small{font-size:10px;color:var(--muted)}
  .meter .bar{height:5px;background:var(--hair);border-radius:3px;overflow:hidden;margin-top:3px}
  .meter .bar i{display:block;height:100%;background:var(--dsml);border-radius:3px}
  .go{font-family:var(--mono);font-size:12px;border:1px solid var(--primary);color:var(--primary);
    border-radius:8px;padding:5px 12px;white-space:nowrap}
  .go:hover{background:var(--primary);color:#fff;text-decoration:none}

  footer{max-width:900px;margin:0 auto;padding:24px 14px 50px;color:var(--muted);
    font-size:12px;font-family:var(--mono);text-align:center}
  footer .bad{color:var(--warn)}

  @media(max-width:760px){
    .ttl{max-width:none}.posted,.rt{font-size:11px}
    thead th:nth-child(5),td:nth-child(5),
    thead th:nth-child(7),td:nth-child(7){display:none}
    .card{grid-template-columns:30px 1fr;gap:10px}
    .card .right{grid-column:1/-1;flex-direction:row;align-items:center;
      justify-content:space-between;text-align:left}
    .locpop{width:min(330px,calc(100vw - 44px))}
  }
</style>
</head>
<body>
<header>
  <div class="wm">
    <span class="dot"></span>
    <h1>__OWNER__</h1>
    <span style="font-family:var(--mono);font-size:12px;color:#8A97A6">early-career · DS/ML focus</span>
    <span class="stamp" id="stamp"></span>
  </div>
  <div class="tape"><ul id="tape"></ul></div>
  <div class="tabs" role="tablist">
    <button id="tabPicks" role="tab" aria-selected="true">★ Top picks<span class="n" id="nPicks"></span></button>
    <button id="tabAll" role="tab" aria-selected="false">All roles<span class="n" id="nAll"></span></button>
  </div>
</header>

<div class="controls">
  <div class="row1">
    <input id="q" type="search" placeholder="Search title, company, ticker, location…" autocomplete="off">

    <div class="locwrap">
      <button class="locbtn" id="locBtn" aria-expanded="false">
        <span class="pin">◉</span><span id="locLabel">All locations</span>
        <span class="badge2" id="locCount" hidden>0</span>
      </button>
      <div class="locpop" id="locPop" data-open="false">
        <h4>Country</h4>
        <select id="ctrySel"><option value="">Any country</option></select>
        <h4>Metro area</h4>
        <input type="search" id="metroSearch" placeholder="Filter metros…" autocomplete="off">
        <div class="metrolist" id="metroList"></div>
        <div class="locfoot">
          <button id="locUS">US only</button>
          <button id="locRemote">Remote</button>
          <button id="locClear">Clear</button>
        </div>
      </div>
    </div>

    <div class="seg" id="newseg">
      <button data-v="all" aria-pressed="true">All</button>
      <button data-v="new">New today</button>
    </div>
    <div class="seg" id="roleseg">
      <button data-v="all" aria-pressed="true">Grad + Intern</button>
      <button data-v="new_grad">New grad</button>
      <button data-v="intern">Intern</button>
    </div>
  </div>

  <div class="row1">
    <div class="seg" id="ageseg" title="Filter by how recently the role was posted">
      <button data-v="0" aria-pressed="true">Any age</button>
      <button data-v="7">≤7d</button>
      <button data-v="14">≤14d</button>
      <button data-v="30">≤30d</button>
    </div>
    <div class="seg" id="capseg" title="Company size by market cap (Nasdaq-confirmed companies only)">
      <button data-v="0" aria-pressed="true">Any size</button>
      <button data-v="10">$10B+</button>
      <button data-v="100">$100B+</button>
      <button data-v="1000">$1T+</button>
    </div>
    <div class="seg" id="seasonseg" title="Internship season (from the feed's term tags)">
      <button data-v="all" aria-pressed="true">All seasons</button>
      <button data-v="Summer">Summer</button>
      <button data-v="Fall">Fall</button>
      <button data-v="Winter">Winter</button>
      <button data-v="Spring">Spring</button>
    </div>
  </div>

  <div class="chips" id="tracks">
    <span class="chip dsml" data-t="dsml" aria-pressed="true">DS / ML / Research</span>
    <span class="chip on" data-t="data_eng" aria-pressed="true">Data Eng</span>
    <span class="chip on" data-t="swe" aria-pressed="true">SWE</span>
    <span class="chip on" data-t="quant" aria-pressed="true">Quant</span>
    <span class="chip on" data-t="hardware" aria-pressed="true">Hardware</span>
    <span class="chip on" data-t="other" aria-pressed="true">Other</span>
  </div>
  <div class="toggles">
    <label><input type="checkbox" id="fNasdaq"> Nasdaq-confirmed only</label>
    <label><input type="checkbox" id="fRemote"> Remote only</label>
    <label><input type="checkbox" id="fHideApplied"> Hide applied</label>
    <button class="mark" id="share" title="Copy a link to this filtered view">🔗 copy link</button>
    <span class="count" id="count"></span>
  </div>
  <div class="selchips" id="selchips"></div>
</div>

<main>
  <div id="picksView">
    <div class="picksintro">
      <b>Your highest-priority applications</b>
      Ranked by fit against your profile — role match, employer tier, stack overlap,
      new-grad eligibility and how recently it was posted. Location is not scored;
      use the location filter above to narrow by place.
    </div>
    <div class="cards" id="cards"></div>
    <div class="empty" id="picksEmpty" style="display:none">
      <b>No shortlisted roles match those filters.</b>
      Clear a filter, or switch to <em>All roles</em> to browse everything.
    </div>
  </div>

  <div id="allView" hidden>
    <table>
      <thead><tr>
        <th data-k="fit">Fit</th>
        <th data-k="new">New</th>
        <th data-k="company">Company</th>
        <th data-k="title">Role</th>
        <th data-k="track">Track</th>
        <th data-k="loc">Location</th>
        <th data-k="role">Type</th>
        <th data-k="posted">Posted</th>
        <th data-k="posted">Age</th>
        <th></th><th></th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
    <div class="empty" id="empty" style="display:none">
      <b>Nothing matches those filters.</b>
      Loosen a filter or clear the search to see more roles.
    </div>
  </div>
</main>

<footer id="foot"></footer>

<script>
const DATA = __DATA__;
const META = __META__;
const PICK_IDS = new Set(__PICKS__);
const TRACK_LABEL = {dsml:"DS/ML",data_eng:"Data Eng",swe:"SWE",quant:"Quant",hardware:"HW",other:"—"};
const applied = new Set(JSON.parse(localStorage.getItem("applied")||"[]"));

document.getElementById("stamp").textContent = "updated " + META.generated;
const tape = [
  ["TOP PICKS", META.picks, "y"], ["NEW TODAY", META.new, "g"],
  ["ACTIVE DS/ML", META.dsml, "v"], ["COMPANIES", META.companies, ""],
  ["TOTAL ROLES", META.total, ""],
  ["SOURCES LIVE", META.sources_ok + "/" + META.sources_total, ""],
];
document.getElementById("tape").innerHTML =
  [...tape, ...tape].map(([k,v,c])=>`<li>${k} <b class="${c}">${v}</b></li>`).join("");

const ALL_TRACKS = ["dsml","data_eng","swe","quant","hardware","other"];
const state = {view:"picks", q:"", nw:"all", role:"all", maxAge:0, capB:0, season:"all",
  sort:"fit", dir:-1, tracks:new Set(ALL_TRACKS), metros:new Set(), ctry:"",
  nasdaq:false, remote:false, hideApplied:false};

function fmtCap(c){
  if(!c) return "";
  if(c>=1e12) return "$"+(c/1e12).toFixed(c<1e13?1:0)+"T";
  if(c>=1e9)  return "$"+Math.round(c/1e9)+"B";
  return "$"+Math.round(c/1e6)+"M";
}
function ageDays(posted){
  if(!posted) return null;
  const t = Date.parse(posted + "T00:00:00Z");
  if(isNaN(t)) return null;
  return Math.floor((Date.now() - t) / 86400000);
}
function ageLabel(a){ return a===null ? "—" : a<=0 ? "today" : a+"d"; }
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}

function pass(r){
  if(state.nw==="new" && !r.new) return false;
  if(state.role!=="all" && r.role!==state.role) return false;
  if(!state.tracks.has(r.track)) return false;
  if(state.nasdaq && !r.nasdaq) return false;
  if(state.remote && !r.remote) return false;
  if(state.maxAge){ const a=ageDays(r.posted); if(a===null || a>state.maxAge) return false; }
  if(state.capB && (!r.cap || r.cap < state.capB*1e9)) return false;
  if(state.season!=="all" && !(r.seasons||[]).includes(state.season)) return false;
  if(state.hideApplied && applied.has(r.id)) return false;
  if(state.ctry && !(r.ctry||[]).includes(state.ctry)) return false;
  // A role passes the location filter if ANY of its locations is selected —
  // multi-site postings should show up under each city they list.
  if(state.metros.size && !(r.metros||[]).some(m=>state.metros.has(m))) return false;
  if(state.q){
    const h=(r.title+" "+r.company+" "+r.ticker+" "+r.loc+" "+(r.metros||[]).join(" ")+" "+r.industry).toLowerCase();
    if(!h.includes(state.q)) return false;
  }
  return true;
}
function cmp(a,b){
  const k=state.sort; let x=a[k],y=b[k];
  if(k==="new"){x=(a.new?1:0)+(a.track==="dsml"?0.5:0);y=(b.new?1:0)+(b.track==="dsml"?0.5:0);}
  if(typeof x==="string"){x=x.toLowerCase();y=(y||"").toLowerCase();}
  if(x===y) return b.fit-a.fit;
  return (x<y?-1:1)*state.dir;
}
function badge(t){const c=t==="dsml"?"b-dsml":t==="swe"?"b-swe":"b-oth";
  return `<span class="badge ${c}">${TRACK_LABEL[t]}</span>`;}

// ---- location filter -------------------------------------------------------
function buildLocationUI(){
  const sel = document.getElementById("ctrySel");
  META.countries.forEach(([c,n])=>{
    const o=document.createElement("option"); o.value=c; o.textContent=`${c} (${n})`;
    sel.appendChild(o);
  });
  renderMetroList("");
}
function renderMetroList(filter){
  const f = filter.toLowerCase();
  document.getElementById("metroList").innerHTML = META.metros
    .filter(([m])=>!f || m.toLowerCase().includes(f))
    .map(([m,n])=>`<label><input type="checkbox" data-m="${esc(m)}"
        ${state.metros.has(m)?"checked":""}><span>${esc(m)}</span>
        <span class="mc">${n}</span></label>`).join("")
    || `<div style="padding:10px;color:var(--muted);font-size:13px">No metro matches “${esc(filter)}”.</div>`;
}
function syncLocationUI(){
  const n = state.metros.size + (state.ctry?1:0);
  const badge = document.getElementById("locCount");
  badge.hidden = !n; badge.textContent = n;
  const label = state.metros.size===1 ? [...state.metros][0]
    : state.metros.size>1 ? `${state.metros.size} metros`
    : state.ctry ? state.ctry : "All locations";
  document.getElementById("locLabel").textContent = label;
  document.getElementById("ctrySel").value = state.ctry;
  document.getElementById("selchips").innerHTML =
    [...(state.ctry?[["ctry",state.ctry]]:[]), ...[...state.metros].map(m=>["metro",m])]
    .map(([k,v])=>`<span class="selchip" data-k="${k}" data-v="${esc(v)}">${esc(v)}</span>`).join("");
}

// ---- rendering -------------------------------------------------------------
function renderCards(list){
  const wrap=document.getElementById("cards");
  wrap.innerHTML = list.map((r,i)=>{
    const ap=applied.has(r.id);
    const why=(r.why||[]).map(w=>`<span>${esc(w)}</span>`).join("")
            + (r.flags||[]).map(f=>`<span class="flag">${esc(f)}</span>`).join("");
    const age=ageDays(r.posted);
    return `<div class="card ${i<3?'top3':''} ${ap?'applied':''}">
      <div class="rank">${i+1}</div>
      <div>
        <h3>${esc(r.title)}</h3>
        <div class="sub"><b>${esc(r.company)}</b>${r.ticker?` · ${esc(r.ticker)}`:""}
          · ${esc(r.loc)} · ${r.role==='intern'?'internship':'new grad'}
          · ${ageLabel(age)}${r.new?' · <span style="color:var(--up);font-weight:600">new</span>':''}</div>
        <div class="why">${why}</div>
      </div>
      <div class="right">
        <div class="meter">
          <div class="num">${r.fit}<small>/100</small></div>
          <div class="bar"><i style="width:${r.fit}%"></i></div>
        </div>
        <a class="go" href="${esc(r.url)}" target="_blank" rel="noopener">apply →</a>
        <button class="mark" data-id="${esc(r.id)}">${ap?'undo':'applied'}</button>
      </div>
    </div>`;
  }).join("");
  document.getElementById("picksEmpty").style.display = list.length?"none":"block";
}

function renderTable(list){
  document.getElementById("rows").innerHTML = list.map(r=>{
    const capt = r.cap ? " · "+fmtCap(r.cap) : "";
    const tk = r.ticker ? `<span class="tk ${r.conf<100?'fuzzy':''}" title="${r.conf<100?'fuzzy match ('+r.conf+') — verify'+capt:'Nasdaq: '+r.ticker+capt}">${esc(r.ticker)}</span>`:"";
    const nb = r.new ? `<span class="badge b-new">new</span>`:"";
    const pk = r.pick ? `<span class="badge b-pick">★</span>`:"";
    const loc = r.remote ? `<span class="rem">Remote</span>${r.loc&&r.loc!=="—"?" · "+esc(r.loc):""}` : esc(r.loc);
    const ap = applied.has(r.id);
    const age = ageDays(r.posted);
    const seas = (r.seasons||[]).join("/");
    return `<tr class="${r.new?'new':''} ${r.track==='dsml'?'dsml':''} ${ap?'applied':''}">
      <td class="fitcell">${r.fit}</td>
      <td>${nb}${pk}</td>
      <td><span class="co">${esc(r.company)}</span>${tk}</td>
      <td class="ttl">${esc(r.title)}</td>
      <td>${badge(r.track)}</td>
      <td>${loc}</td>
      <td class="rt">${r.role==='intern'?'intern':'new grad'}${seas?' · '+esc(seas):''}</td>
      <td class="posted">${r.posted||"—"}</td>
      <td class="age ${age!==null&&age<=7?'fresh':''}">${ageLabel(age)}</td>
      <td class="apply"><a href="${esc(r.url)}" target="_blank" rel="noopener">apply →</a></td>
      <td><button class="mark" data-id="${esc(r.id)}">${ap?'undo':'applied'}</button></td>
    </tr>`;
  }).join("");
  document.getElementById("empty").style.display = list.length?"none":"block";
}

function render(){
  const picksMode = state.view==="picks";
  const pool = picksMode ? DATA.filter(r=>PICK_IDS.has(r.id)) : DATA;
  const list = pool.filter(pass).sort(picksMode ? (a,b)=>b.fit-a.fit || (a.posted<b.posted?1:-1) : cmp);

  document.getElementById("picksView").hidden = !picksMode;
  document.getElementById("allView").hidden = picksMode;
  document.getElementById("tabPicks").setAttribute("aria-selected", picksMode);
  document.getElementById("tabAll").setAttribute("aria-selected", !picksMode);
  picksMode ? renderCards(list) : renderTable(list);

  document.getElementById("nPicks").textContent = META.picks;
  document.getElementById("nAll").textContent = META.total;
  document.getElementById("count").textContent =
    `${list.length} shown · ${list.filter(r=>r.track==='dsml').length} DS/ML`;
  syncLocationUI();
  writeHash();
}

// ---- shareable filter state (URL hash) ------------------------------------
function writeHash(){
  const p = new URLSearchParams();
  if(state.view!=="picks") p.set("view", state.view);
  if(state.q) p.set("q", state.q);
  if(state.nw!=="all") p.set("new", state.nw);
  if(state.role!=="all") p.set("role", state.role);
  if(state.maxAge) p.set("age", state.maxAge);
  if(state.capB) p.set("cap", state.capB);
  if(state.season!=="all") p.set("season", state.season);
  if(state.tracks.size!==ALL_TRACKS.length) p.set("tracks", [...state.tracks].join(","));
  if(state.metros.size) p.set("metros", [...state.metros].join("~"));
  if(state.ctry) p.set("ctry", state.ctry);
  if(state.nasdaq) p.set("nasdaq","1");
  if(state.remote) p.set("remote","1");
  if(state.hideApplied) p.set("hide","1");
  if(state.sort!=="fit") p.set("sort", state.sort);
  if(state.dir!==-1) p.set("dir", state.dir);
  const s = p.toString();
  try{ history.replaceState(null,"", s ? "#"+s : location.pathname+location.search); }catch(_){}
}
function readHash(){
  const p = new URLSearchParams(location.hash.slice(1));
  if(![...p.keys()].length) return;
  if(p.has("view")) state.view = p.get("view");
  if(p.has("q")) state.q = p.get("q").toLowerCase();
  if(p.has("new")) state.nw = p.get("new");
  if(p.has("role")) state.role = p.get("role");
  if(p.has("age")) state.maxAge = parseInt(p.get("age"))||0;
  if(p.has("cap")) state.capB = parseInt(p.get("cap"))||0;
  if(p.has("season")) state.season = p.get("season");
  if(p.has("tracks")) state.tracks = new Set(p.get("tracks").split(",").filter(Boolean));
  if(p.has("metros")) state.metros = new Set(p.get("metros").split("~").filter(Boolean));
  if(p.has("ctry")) state.ctry = p.get("ctry");
  state.nasdaq = p.get("nasdaq")==="1";
  state.remote = p.get("remote")==="1";
  state.hideApplied = p.get("hide")==="1";
  if(p.has("sort")) state.sort = p.get("sort");
  if(p.has("dir")) state.dir = parseInt(p.get("dir"))===1 ? 1 : -1;
}
function setSeg(id,v){const el=document.getElementById(id);
  [...el.children].forEach(b=>b.setAttribute("aria-pressed", b.dataset.v===String(v)));}
function syncUI(){
  document.getElementById("q").value = state.q;
  setSeg("newseg", state.nw); setSeg("roleseg", state.role); setSeg("ageseg", state.maxAge);
  setSeg("capseg", state.capB); setSeg("seasonseg", state.season);
  document.querySelectorAll("#tracks .chip")
    .forEach(c=>c.setAttribute("aria-pressed", state.tracks.has(c.dataset.t)));
  document.getElementById("fNasdaq").checked = state.nasdaq;
  document.getElementById("fRemote").checked = state.remote;
  document.getElementById("fHideApplied").checked = state.hideApplied;
}

// ---- wiring ----------------------------------------------------------------
function seg(id,set){const el=document.getElementById(id);
  el.addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;
    [...el.children].forEach(x=>x.setAttribute("aria-pressed",x===b));set(b.dataset.v);render();});}

document.getElementById("q").addEventListener("input",e=>{state.q=e.target.value.toLowerCase().trim();render();});
seg("newseg",v=>state.nw=v); seg("roleseg",v=>state.role=v);
seg("ageseg",v=>state.maxAge=parseInt(v)||0);
seg("capseg",v=>state.capB=parseInt(v)||0);
seg("seasonseg",v=>state.season=v);
document.getElementById("tabPicks").addEventListener("click",()=>{state.view="picks";render();});
document.getElementById("tabAll").addEventListener("click",()=>{state.view="all";render();});
document.getElementById("tracks").addEventListener("click",e=>{
  const c=e.target.closest(".chip");if(!c)return;
  const on=c.getAttribute("aria-pressed")==="true";c.setAttribute("aria-pressed",!on);
  on?state.tracks.delete(c.dataset.t):state.tracks.add(c.dataset.t);render();});
[["fNasdaq","nasdaq"],["fRemote","remote"],["fHideApplied","hideApplied"]]
  .forEach(([id,key])=>document.getElementById(id).addEventListener("change",e=>{state[key]=e.target.checked;render();}));
document.querySelector("thead").addEventListener("click",e=>{
  const th=e.target.closest("th");if(!th||!th.dataset.k)return;
  if(state.sort===th.dataset.k)state.dir*=-1;else{state.sort=th.dataset.k;state.dir=th.dataset.k==="fit"?-1:1;}
  render();});
document.querySelector("main").addEventListener("click",e=>{
  const b=e.target.closest(".mark");if(!b)return;const id=b.dataset.id;
  applied.has(id)?applied.delete(id):applied.add(id);
  localStorage.setItem("applied",JSON.stringify([...applied]));render();});
document.getElementById("share").addEventListener("click",()=>{
  const b=document.getElementById("share"), url=location.href;
  const ok=()=>{const o=b.textContent;b.textContent="✓ copied";setTimeout(()=>b.textContent=o,1200);};
  if(navigator.clipboard) navigator.clipboard.writeText(url).then(ok).catch(()=>prompt("Copy this link:",url));
  else prompt("Copy this link:",url);});

// location popover
const locPop=document.getElementById("locPop"), locBtn=document.getElementById("locBtn");
function toggleLoc(open){
  locPop.dataset.open = open; locBtn.setAttribute("aria-expanded", open);
}
locBtn.addEventListener("click",e=>{e.stopPropagation();
  toggleLoc(locPop.dataset.open!=="true");});
locPop.addEventListener("click",e=>e.stopPropagation());
document.addEventListener("click",()=>toggleLoc(false));
document.addEventListener("keydown",e=>{if(e.key==="Escape")toggleLoc(false);});
document.getElementById("metroSearch").addEventListener("input",e=>renderMetroList(e.target.value));
document.getElementById("metroList").addEventListener("change",e=>{
  const cb=e.target.closest("input[type=checkbox]");if(!cb)return;
  cb.checked?state.metros.add(cb.dataset.m):state.metros.delete(cb.dataset.m);render();});
document.getElementById("ctrySel").addEventListener("change",e=>{state.ctry=e.target.value;render();});
document.getElementById("locUS").addEventListener("click",()=>{
  state.ctry="United States";state.metros.clear();renderMetroList(document.getElementById("metroSearch").value);render();});
document.getElementById("locRemote").addEventListener("click",()=>{
  state.metros=new Set(["Remote"]);state.ctry="";renderMetroList(document.getElementById("metroSearch").value);render();});
document.getElementById("locClear").addEventListener("click",()=>{
  state.metros.clear();state.ctry="";renderMetroList(document.getElementById("metroSearch").value);render();});
document.getElementById("selchips").addEventListener("click",e=>{
  const c=e.target.closest(".selchip");if(!c)return;
  c.dataset.k==="ctry" ? state.ctry="" : state.metros.delete(c.dataset.v);
  renderMetroList(document.getElementById("metroSearch").value);render();});

document.getElementById("foot").innerHTML =
  `${META.sources_ok}/${META.sources_total} sources responded`
  + (META.failed.length ? ` · <span class="bad">failed: ${META.failed.map(esc).join(", ")}</span>` : "")
  + ` · generated ${META.generated}`;

buildLocationUI(); readHash(); syncUI(); render();
</script>
</body>
</html>"""
