"""Persist which jobs we've seen so each run can flag what's NEW.

State is a JSON map: job_key -> {first_seen, last_seen}. A job is "new" the
first run it appears. Jobs missing from the current run are kept for
keep_stale_days (in case a source blips), then dropped.
"""
from __future__ import annotations
import json
import os
import time


def load(path: str) -> dict:
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=0)


def save_health(path: str, rows: list[dict], total: int, active: int,
                shortlisted: int, seconds: float, aborted: bool = False) -> None:
    """Write the per-source outcome of this run.

    Committed alongside the data so a board that quietly starts returning zero
    shows up in the git diff instead of going unnoticed for months.
    """
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "generated": int(time.time()),
        "duration_s": round(seconds, 1),
        "aborted": aborted,
        "totals": {"jobs": total, "active": active, "shortlisted": shortlisted},
        "sources_ok": sum(1 for r in rows if r["ok"]),
        "sources_failed": sum(1 for r in rows if not r["ok"]),
        "sources": sorted(rows, key=lambda r: (r["ok"], -r["jobs"])),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)


def reconcile(state: dict, current_keys: set[str], keep_stale_days: int) -> tuple[dict, set[str]]:
    """Update timestamps; return (new_state, set_of_new_keys)."""
    now = int(time.time())
    new_keys: set[str] = set()
    for key in current_keys:
        if key in state:
            state[key]["last_seen"] = now
        else:
            state[key] = {"first_seen": now, "last_seen": now}
            new_keys.add(key)
    cutoff = now - keep_stale_days * 86400
    for key in list(state):
        if key not in current_keys and state[key]["last_seen"] < cutoff:
            del state[key]
    return state, new_keys
