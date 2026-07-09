"""Write outputs: a flat CSV and a self-contained, filterable HTML dashboard.

The HTML embeds the jobs as a JSON blob and does all filtering/sorting/search
client-side in vanilla JS, so it works as a static file on GitHub Pages or
opened locally. It uses localStorage only to remember which jobs you've marked
applied.
"""
from __future__ import annotations
import csv
import json
import os
import time
from datetime import datetime, timezone

CSV_FIELDS = [
    "new", "role_type", "track", "company", "ticker", "industry",
    "title", "location", "remote", "nasdaq", "confidence",
    "active", "posted", "source", "url",
]


def write_csv(path: str, jobs: list[dict]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for j in jobs:
            w.writerow({
                "new": "YES" if j["is_new"] else "",
                "role_type": j["role_type"],
                "track": j["track"],
                "company": j["company_name"],
                "ticker": j.get("ticker", ""),
                "industry": j.get("industry", ""),
                "title": j["title"],
                "location": " | ".join(j.get("locations") or []),
                "remote": "YES" if j["remote"] else "",
                "nasdaq": "YES" if j.get("ticker") else "",
                "confidence": j.get("confidence", ""),
                "active": "YES" if j["active"] else "",
                "posted": _date(j.get("date_posted")),
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


def write_html(path: str, jobs: list[dict], owner: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = [{
        "new": bool(j["is_new"]),
        "role": j["role_type"],
        "track": j["track"],
        "company": j["company_name"],
        "ticker": j.get("ticker", ""),
        "industry": j.get("industry", ""),
        "cap": j.get("market_cap", 0),
        "title": j["title"],
        "loc": ", ".join(j.get("locations") or []) or "—",
        "remote": bool(j["remote"]),
        "nasdaq": bool(j.get("ticker")),
        "conf": j.get("confidence", 0),
        "active": bool(j["active"]),
        "posted": _date(j.get("date_posted")),
        "source": j["source"],
        "url": j["url"],
        "id": j["key"],
    } for j in jobs]

    meta = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "total": len(rows),
        "new": sum(r["new"] for r in rows),
        "dsml": sum(1 for r in rows if r["track"] == "dsml" and r["active"]),
        "companies": len({r["ticker"] for r in rows if r["ticker"]}),
    }
    html = (_TEMPLATE
            .replace("__OWNER__", owner)
            .replace("__META__", json.dumps(meta))
            .replace("__DATA__", json.dumps(rows, ensure_ascii=False)))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


# --------------------------------------------------------------------------- #
# Self-contained page. Design: a light "market terminal" — monospace data,
# a scrolling ticker-tape summary strip (the signature), DS/ML rows accented.
# --------------------------------------------------------------------------- #
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__OWNER__ · Nasdaq early-career tech roles</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#F5F6F8; --surface:#FFFFFF; --ink:#141922; --muted:#5B6675;
    --hair:#E3E7EC; --primary:#0B5FA5; --up:#0E9F6E; --dsml:#6D45C7;
    --warn:#C2410C; --shadow:0 1px 2px rgba(20,25,34,.05),0 8px 24px rgba(20,25,34,.05);
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
  .tape{overflow:hidden;margin-top:14px;border-top:1px solid #262E3A;
    border-bottom:1px solid #262E3A;background:#0E141C}
  .tape ul{display:flex;gap:0;margin:0;padding:0;list-style:none;
    white-space:nowrap;animation:scroll 34s linear infinite;width:max-content}
  .tape li{font-family:var(--mono);font-size:12px;color:#B7C2CE;padding:9px 26px;
    border-right:1px solid #1B2430}
  .tape b{color:#fff;font-weight:500}
  .tape .g{color:#3FD79A}.tape .v{color:#B79CF0}
  @keyframes scroll{from{transform:translateX(0)}to{transform:translateX(-50%)}}
  @media (prefers-reduced-motion:reduce){.tape ul{animation:none}}

  .controls{position:sticky;top:0;z-index:20;background:var(--surface);
    border-bottom:1px solid var(--hair);padding:12px 22px;box-shadow:var(--shadow)}
  .row1{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  #q{flex:1 1 260px;min-width:180px;font-family:var(--body);font-size:14px;
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
    font-size:13px;color:var(--muted)}
  .toggles label{display:inline-flex;gap:6px;align-items:center;cursor:pointer}
  .count{font-family:var(--mono);font-size:12px;color:var(--muted);margin-left:auto;align-self:center}

  main{padding:0 14px 60px}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  thead th{position:sticky;top:0;text-align:left;font-family:var(--mono);
    font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
    color:var(--muted);padding:14px 12px 8px;cursor:pointer;white-space:nowrap}
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
  .ttl{max-width:520px}
  .badge{font-family:var(--mono);font-size:10.5px;padding:2px 7px;border-radius:999px;
    text-transform:uppercase;letter-spacing:.04em}
  .b-dsml{background:rgba(109,69,199,.12);color:var(--dsml)}
  .b-swe{background:rgba(11,95,165,.10);color:var(--primary)}
  .b-oth{background:#EEF1F4;color:var(--muted)}
  .b-new{background:var(--up);color:#fff}
  .rt{font-family:var(--mono);font-size:11px;color:var(--muted)}
  .rem{color:var(--up);font-weight:600}
  .posted{font-family:var(--mono);font-size:12px;color:var(--muted);white-space:nowrap}
  .age{font-family:var(--mono);font-size:12px;color:var(--muted);white-space:nowrap}
  .age.fresh{color:var(--up);font-weight:600}
  .apply{font-family:var(--mono);font-size:12px}
  .mark{border:1px solid var(--hair);background:#fff;border-radius:6px;
    font-size:11px;padding:3px 8px;cursor:pointer;color:var(--muted)}
  .empty{padding:80px 20px;text-align:center;color:var(--muted)}
  .empty b{font-family:var(--disp);font-size:18px;color:var(--ink);display:block;margin-bottom:6px}
  @media(max-width:720px){
    .ttl{max-width:none}.posted,.rt{font-size:11px}
    thead th:nth-child(5),td:nth-child(5){display:none}
  }
</style>
</head>
<body>
<header>
  <div class="wm">
    <span class="dot"></span>
    <h1>__OWNER__</h1>
    <span style="font-family:var(--mono);font-size:12px;color:#8A97A6">early-career · Nasdaq tech · DS/ML focus</span>
    <span class="stamp" id="stamp"></span>
  </div>
  <div class="tape"><ul id="tape"></ul></div>
</header>

<div class="controls">
  <div class="row1">
    <input id="q" type="search" placeholder="Search title, company, ticker, location…" autocomplete="off">
    <div class="seg" id="newseg">
      <button data-v="all" aria-pressed="true">All</button>
      <button data-v="new">New today</button>
    </div>
    <div class="seg" id="roleseg">
      <button data-v="all" aria-pressed="true">Grad + Intern</button>
      <button data-v="new_grad">New grad</button>
      <button data-v="intern">Intern</button>
    </div>
    <div class="seg" id="ageseg" title="Filter by how recently the role was posted">
      <button data-v="0" aria-pressed="true">Any age</button>
      <button data-v="7">≤7d</button>
      <button data-v="14">≤14d</button>
      <button data-v="30">≤30d</button>
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
    <label><input type="checkbox" id="fActive" checked> Active only</label>
    <label><input type="checkbox" id="fHideApplied"> Hide applied</label>
    <button class="mark" id="share" title="Copy a link to this filtered view">🔗 copy link</button>
    <span class="count" id="count"></span>
  </div>
</div>

<main>
  <table>
    <thead><tr>
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
</main>

<script>
const DATA = __DATA__;
const META = __META__;
const TRACK_LABEL = {dsml:"DS/ML",data_eng:"Data Eng",swe:"SWE",quant:"Quant",hardware:"HW",other:"—"};
const applied = new Set(JSON.parse(localStorage.getItem("applied")||"[]"));

document.getElementById("stamp").textContent = "updated " + META.generated;
const tape = [
  ["NEW TODAY", META.new, "g"], ["ACTIVE DS/ML", META.dsml, "v"],
  ["NASDAQ COMPANIES", META.companies, ""], ["TOTAL ROLES", META.total, ""],
];
document.getElementById("tape").innerHTML =
  [...tape, ...tape].map(([k,v,c])=>`<li>${k} <b class="${c}">${v}</b></li>`).join("");

const ALL_TRACKS = ["dsml","data_eng","swe","quant","hardware","other"];
const state = {q:"", nw:"all", role:"all", maxAge:0, sort:"new", dir:1,
  tracks:new Set(ALL_TRACKS),
  nasdaq:false, remote:false, active:true, hideApplied:false};

// Age in whole days from the posted date (UTC) to now; null if no/invalid date.
function ageDays(posted){
  if(!posted) return null;
  const t = Date.parse(posted + "T00:00:00Z");
  if(isNaN(t)) return null;
  return Math.floor((Date.now() - t) / 86400000);
}
function ageLabel(a){ return a===null ? "—" : a<=0 ? "today" : a+"d"; }

function pass(r){
  if(state.nw==="new" && !r.new) return false;
  if(state.role!=="all" && r.role!==state.role) return false;
  if(!state.tracks.has(r.track)) return false;
  if(state.nasdaq && !r.nasdaq) return false;
  if(state.remote && !r.remote) return false;
  if(state.active && !r.active) return false;
  if(state.maxAge){ const a=ageDays(r.posted); if(a===null || a>state.maxAge) return false; }
  if(state.hideApplied && applied.has(r.id)) return false;
  if(state.q){
    const h=(r.title+" "+r.company+" "+r.ticker+" "+r.loc+" "+r.industry).toLowerCase();
    if(!h.includes(state.q)) return false;
  }
  return true;
}
function cmp(a,b){
  const k=state.sort; let x=a[k],y=b[k];
  if(k==="new"){x=(a.new?1:0)+(a.track==="dsml"?0.5:0);y=(b.new?1:0)+(b.track==="dsml"?0.5:0);}
  if(typeof x==="string"){x=x.toLowerCase();y=(y||"").toLowerCase();}
  return (x<y?-1:x>y?1:0)*state.dir;
}
function badge(t){const c=t==="dsml"?"b-dsml":t==="swe"?"b-swe":"b-oth";
  return `<span class="badge ${c}">${TRACK_LABEL[t]}</span>`;}

function render(){
  const list = DATA.filter(pass).sort(cmp);
  const tb=document.getElementById("rows");
  tb.innerHTML = list.map(r=>{
    const tk = r.ticker ? `<span class="tk ${r.conf<100?'fuzzy':''}" title="${r.conf<100?'fuzzy match ('+r.conf+') — verify':'Nasdaq: '+r.ticker}">${r.ticker}</span>`:"";
    const nb = r.new ? `<span class="badge b-new">new</span>`:"";
    const loc = r.remote ? `<span class="rem">Remote</span>${r.loc&&r.loc!=="—"?" · "+r.loc:""}` : r.loc;
    const ap = applied.has(r.id);
    const age = ageDays(r.posted);
    return `<tr class="${r.new?'new':''} ${r.track==='dsml'?'dsml':''} ${ap?'applied':''}">
      <td>${nb}</td>
      <td><span class="co">${esc(r.company)}</span>${tk}</td>
      <td class="ttl">${esc(r.title)}</td>
      <td>${badge(r.track)}</td>
      <td>${esc(loc)}</td>
      <td class="rt">${r.role==='intern'?'intern':'new grad'}</td>
      <td class="posted">${r.posted||"—"}</td>
      <td class="age ${age!==null&&age<=7?'fresh':''}">${ageLabel(age)}</td>
      <td class="apply"><a href="${r.url}" target="_blank" rel="noopener">apply →</a></td>
      <td><button class="mark" data-id="${r.id}">${ap?'undo':'applied'}</button></td>
    </tr>`;
  }).join("");
  document.getElementById("empty").style.display = list.length?"none":"block";
  document.getElementById("count").textContent =
    `${list.length} shown · ${DATA.filter(r=>r.track==='dsml'&&pass(r)).length} DS/ML`;
  writeHash();
}

// ---- shareable filter state (URL hash) ------------------------------------
function writeHash(){
  const p = new URLSearchParams();
  if(state.q) p.set("q", state.q);
  if(state.nw!=="all") p.set("new", state.nw);
  if(state.role!=="all") p.set("role", state.role);
  if(state.maxAge) p.set("age", state.maxAge);
  if(state.tracks.size!==ALL_TRACKS.length) p.set("tracks", [...state.tracks].join(","));
  if(state.nasdaq) p.set("nasdaq","1");
  if(state.remote) p.set("remote","1");
  if(!state.active) p.set("active","0");
  if(state.hideApplied) p.set("hide","1");
  if(state.sort!=="new") p.set("sort", state.sort);
  if(state.dir!==1) p.set("dir","-1");
  const s = p.toString();
  try{ history.replaceState(null,"", s ? "#"+s : location.pathname+location.search); }catch(_){}
}
function readHash(){
  const p = new URLSearchParams(location.hash.slice(1));
  if(![...p.keys()].length) return;
  if(p.has("q")) state.q = p.get("q").toLowerCase();
  if(p.has("new")) state.nw = p.get("new");
  if(p.has("role")) state.role = p.get("role");
  if(p.has("age")) state.maxAge = parseInt(p.get("age"))||0;
  if(p.has("tracks")) state.tracks = new Set(p.get("tracks").split(",").filter(Boolean));
  state.nasdaq = p.get("nasdaq")==="1";
  state.remote = p.get("remote")==="1";
  if(p.has("active")) state.active = p.get("active")!=="0";
  state.hideApplied = p.get("hide")==="1";
  if(p.has("sort")) state.sort = p.get("sort");
  if(p.has("dir")) state.dir = p.get("dir")==="-1" ? -1 : 1;
}
function setSeg(id,v){const el=document.getElementById(id);
  [...el.children].forEach(b=>b.setAttribute("aria-pressed", b.dataset.v===String(v)));}
function syncUI(){
  document.getElementById("q").value = state.q;
  setSeg("newseg", state.nw); setSeg("roleseg", state.role); setSeg("ageseg", state.maxAge);
  document.querySelectorAll("#tracks .chip")
    .forEach(c=>c.setAttribute("aria-pressed", state.tracks.has(c.dataset.t)));
  document.getElementById("fNasdaq").checked = state.nasdaq;
  document.getElementById("fRemote").checked = state.remote;
  document.getElementById("fActive").checked = state.active;
  document.getElementById("fHideApplied").checked = state.hideApplied;
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}

// wiring
document.getElementById("q").addEventListener("input",e=>{state.q=e.target.value.toLowerCase().trim();render();});
seg("newseg",v=>state.nw=v); seg("roleseg",v=>state.role=v);
seg("ageseg",v=>state.maxAge=parseInt(v)||0);
function seg(id,set){const el=document.getElementById(id);
  el.addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;
    [...el.children].forEach(x=>x.setAttribute("aria-pressed",x===b));set(b.dataset.v);render();});}
document.getElementById("tracks").addEventListener("click",e=>{
  const c=e.target.closest(".chip");if(!c)return;
  const on=c.getAttribute("aria-pressed")==="true";c.setAttribute("aria-pressed",!on);
  on?state.tracks.delete(c.dataset.t):state.tracks.add(c.dataset.t);render();});
[["fNasdaq","nasdaq"],["fRemote","remote"],["fActive","active"],["fHideApplied","hideApplied"]]
  .forEach(([id,key])=>document.getElementById(id).addEventListener("change",e=>{state[key]=e.target.checked;render();}));
document.querySelector("thead").addEventListener("click",e=>{
  const th=e.target.closest("th");if(!th||!th.dataset.k)return;
  if(state.sort===th.dataset.k)state.dir*=-1;else{state.sort=th.dataset.k;state.dir=1;}render();});
document.getElementById("rows").addEventListener("click",e=>{
  const b=e.target.closest(".mark");if(!b)return;const id=b.dataset.id;
  applied.has(id)?applied.delete(id):applied.add(id);
  localStorage.setItem("applied",JSON.stringify([...applied]));render();});
document.getElementById("share").addEventListener("click",()=>{
  const b=document.getElementById("share"), url=location.href;
  const ok=()=>{const o=b.textContent;b.textContent="✓ copied";setTimeout(()=>b.textContent=o,1200);};
  if(navigator.clipboard) navigator.clipboard.writeText(url).then(ok).catch(()=>prompt("Copy this link:",url));
  else prompt("Copy this link:",url);});

readHash(); syncUI(); render();
</script>
</body>
</html>"""
