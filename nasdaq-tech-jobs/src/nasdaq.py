"""Build the Nasdaq company universe.

Authoritative membership comes from the official Nasdaq-listed symbol file.
We intersect it with a screener export (Ate329/top-us-stock-tickers) that adds
industry + market cap + a clean company name, keeping only rows whose symbol is
truly Nasdaq-listed. The screener alone spans NYSE/Nasdaq/AMEX, so the
intersection is what makes this "Nasdaq only".
"""
from __future__ import annotations
import csv
import io
from dataclasses import dataclass

import requests


@dataclass
class Company:
    ticker: str
    name: str          # clean-ish name from the screener
    industry: str
    market_cap: float


def _get_csv(url: str) -> list[dict]:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def load_universe(listed_symbols_csv: str, enrichment_csv: str) -> dict[str, Company]:
    listed = _get_csv(listed_symbols_csv)
    nasdaq_symbols = {
        (row.get("Symbol") or row.get("symbol") or "").strip().upper()
        for row in listed
    }
    nasdaq_symbols.discard("")

    universe: dict[str, Company] = {}
    for row in _get_csv(enrichment_csv):
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
