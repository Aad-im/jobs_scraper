"""Build the Nasdaq company universe.

Authoritative membership comes from the official Nasdaq-listed symbol file.
We intersect it with a screener export (Ate329/top-us-stock-tickers) that adds
industry + market cap + a clean company name, keeping only rows whose symbol is
truly Nasdaq-listed. The screener alone spans NYSE/Nasdaq/AMEX, so the
intersection is what makes this "Nasdaq only".
"""
from __future__ import annotations
import csv
import hashlib
import io
import os
import time
from dataclasses import dataclass

from .http import session


@dataclass
class Company:
    ticker: str
    name: str          # clean-ish name from the screener
    industry: str
    market_cap: float


def _get_csv(url: str, cache_dir: str = "", cache_hours: float = 0) -> list[dict]:
    """Fetch a CSV, optionally through an on-disk cache.

    These two files change slowly, so a cache turns "GitHub raw is having a bad
    morning" from a failed run into a run that uses yesterday's universe. A stale
    cache is also used as a last resort when the network fails outright.
    """
    path = ""
    if cache_dir and cache_hours:
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, hashlib.sha1(url.encode()).hexdigest() + ".csv")
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < cache_hours * 3600:
            with open(path, encoding="utf-8") as f:
                return list(csv.DictReader(f))
    try:
        r = session().get(url, timeout=60)
        r.raise_for_status()
        text = r.text
    except Exception:
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return list(csv.DictReader(f))
        raise
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return list(csv.DictReader(io.StringIO(text)))


def load_universe(listed_symbols_csv: str, enrichment_csv: str,
                  cache_hours: float = 0, cache_dir: str = "") -> dict[str, Company]:
    listed = _get_csv(listed_symbols_csv, cache_dir, cache_hours)
    nasdaq_symbols = {
        (row.get("Symbol") or row.get("symbol") or "").strip().upper()
        for row in listed
    }
    nasdaq_symbols.discard("")

    universe: dict[str, Company] = {}
    for row in _get_csv(enrichment_csv, cache_dir, cache_hours):
        sym = (row.get("symbol") or "").strip().upper()
        if sym not in nasdaq_symbols:
            continue
        try:
            cap = float(row.get("marketCap") or 0)
        except ValueError:
            cap = 0.0
        universe[sym] = Company(
            ticker=sym,
            name=(row.get("name") or "").strip(),
            industry=(row.get("industry") or "Uncategorized").strip() or "Uncategorized",
            market_cap=cap,
        )
    if not universe:
        raise RuntimeError(
            "Nasdaq universe is empty. Check the two CSV URLs in config.yaml "
            "(schema may have changed upstream)."
        )
    return universe
