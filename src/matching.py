"""Match an arbitrary company string (from a job posting) to a Nasdaq ticker.

Two passes: normalized exact match, then fuzzy (token_sort_ratio) above a
cutoff. Fuzzy matches carry a lower confidence and are flagged so the HTML page
can visually mark "probable" Nasdaq hits vs certain ones.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

from rapidfuzz import process, fuzz

from .nasdaq import Company

_STOP = re.compile(
    r"\b(common stock|class [abcd]|capital stock|ordinary shares?|"
    r"american depositary shares?|depositary shares?|warrants?|units?|rights?|"
    r"inc|incorporated|corporation|corp|co|company|ltd|limited|plc|holdings?|"
    r"group|llc|lp|sa|nv|ag|the)\b"
)


def normalize(name: str) -> str:
    n = name.lower()
    n = _STOP.sub(" ", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


@dataclass
class Match:
    ticker: str
    company: Company
    confidence: int   # 100 = exact normalized, else fuzzy score


class CompanyMatcher:
    def __init__(self, universe: dict[str, Company], fuzzy_cutoff: int = 92):
        self.universe = universe
        self.cutoff = fuzzy_cutoff
        self._by_norm: dict[str, Company] = {}
        for c in universe.values():
            key = normalize(c.name)
            # Prefer the larger-cap company when two normalize identically.
            if key and (key not in self._by_norm
                        or c.market_cap > self._by_norm[key].market_cap):
                self._by_norm[key] = c
        self._choices = list(self._by_norm.keys())
        self._cache: dict[str, Match | None] = {}

    def match(self, company_name: str) -> Match | None:
        if company_name in self._cache:
            return self._cache[company_name]
        q = normalize(company_name)
        result: Match | None = None
        if q in self._by_norm:
            c = self._by_norm[q]
            result = Match(c.ticker, c, 100)
        elif q:
            hit = process.extractOne(
                q, self._choices, scorer=fuzz.token_sort_ratio,
                score_cutoff=self.cutoff,
            )
            if hit:
                c = self._by_norm[hit[0]]
                # Guard against short-token false positives (e.g. one-word names).
                if len(q) >= 4:
                    result = Match(c.ticker, c, int(hit[1]))
        self._cache[company_name] = result
        return result
