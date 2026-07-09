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
    json.dump(state, open(path, "w"), indent=0)


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
