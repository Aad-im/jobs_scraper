"""Score every job against the candidate profile and pick the shortlist.

Five components, each capped by its weight in profile.yaml:

    role       how close the role itself is to what he actually does
    employer   frontier lab > big tech > AI infra > other
    skills     concrete stack overlap found in the title/department/description
    stage      new-grad vs intern, minus quietly-senior requirements
    freshness  a perfect role posted 90 days ago is probably already closed

Location is intentionally not a component — the board has a location filter for
that, and mixing "where" into "how good a fit" makes both harder to reason about.

Every score carries `reasons` (why it ranked) and `flags` (what to watch out for),
so the shortlist explains itself instead of being an opaque number.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .classify import max_years_required
from .matching import normalize


@dataclass
class Fit:
    score: int
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    parts: dict[str, int] = field(default_factory=dict)


_TIER_LABEL = {
    "frontier_lab": "Frontier AI lab",
    "big_tech": "Big tech",
    "ai_infra": "AI infra / tooling",
    "tech": "Established tech",
    "quant": "Quant / trading",
}
_YEAR_RE = re.compile(r"\b(20[2-3]\d)\b")


class FitScorer:
    """Holds the compiled profile so scoring ~50k jobs stays cheap."""

    def __init__(self, profile: dict):
        self.p = profile
        self.w = profile["weights"]
        self.shortlist_cfg = profile["shortlist"]
        self.skills = profile["skills"]["keywords"]
        self.skill_pts = profile["skills"]["points_per_hit"]
        self.stage_cfg = profile["stage"]
        self.freshness = profile["freshness"]
        # company name -> tier, normalized the same way the Nasdaq matcher does
        # so "Meta Platforms, Inc." and "meta" collapse together.
        self._company_tier: dict[str, str] = {}
        for tier, names in (profile.get("company_tiers") or {}).items():
            for n in names:
                self._company_tier.setdefault(normalize(n), tier)
        self._tier_scores = profile["employer_scores"]

    # -- components --------------------------------------------------------
    def _role(self, title: str, description: str) -> tuple[int, list[str]]:
        t = title.lower()
        d = description.lower()
        score, reasons = 0, []
        for tier_name, spec in self.p["role_tiers"].items():
            hit = next((k for k in spec["keywords"] if k in t), None)
            if hit:
                score = spec["score"]
                reasons.append(f"{tier_name.capitalize()} role match · “{hit}”")
                break
            # A description-only hit is real signal but a much weaker one: the
            # word may belong to the team blurb rather than the job itself.
            hit_d = next((k for k in spec["keywords"] if k in d), None)
            if hit_d:
                score = spec["score"] // 2
                reasons.append(f"{tier_name.capitalize()} match in description · “{hit_d}”")
                break
        for pen in self.p["role_penalties"]:
            bad = next((k for k in pen["keywords"] if k in t), None)
            if bad:
                score -= pen["points"]
                reasons.append(f"off-profile · “{bad}”")
                break
        return max(0, min(score, self.w["role"])), reasons

    def tier_for(self, company: str, declared: str) -> str:
        if declared:
            return declared
        return self._company_tier.get(normalize(company), "")

    def _employer(self, tier: str) -> tuple[int, list[str]]:
        raw = self._tier_scores.get(tier, self._tier_scores.get("", 0))
        scaled = round(raw * self.w["employer"] / max(self._tier_scores.values()))
        label = _TIER_LABEL.get(tier)
        return min(scaled, self.w["employer"]), ([label] if label else [])

    def _skills(self, haystack: str) -> tuple[int, list[str]]:
        hits = [k for k in self.skills if k in haystack]
        if not hits:
            return 0, []
        score = min(len(hits) * self.skill_pts, self.w["skills"])
        return score, ["stack: " + ", ".join(hits[:5])]

    def _stage(self, role_type: str, title: str, haystack: str,
               seasons: list[str], years: list[int]) -> tuple[int, list[str], list[str]]:
        cfg = self.stage_cfg
        score = cfg["new_grad"] if role_type == "new_grad" else cfg["intern"]
        reasons = ["new grad / full-time" if role_type == "new_grad" else "internship"]
        flags: list[str] = []

        title_years = {int(y) for y in _YEAR_RE.findall(title)} | set(years or [])
        if title_years & set(cfg["target_years"]):
            score += cfg["target_year_bonus"]
            reasons.append(f"class of {min(title_years & set(cfg['target_years']))}")

        fk = cfg["flag_keywords"]
        pen = cfg["penalties"]
        if any(k in haystack for k in fk["phd"]):
            score -= pen["phd"]
            flags.append("PhD mentioned")
        elif any(k in haystack for k in fk["masters"]):
            score -= pen["masters"]
            flags.append("MS preferred")
        yrs = max_years_required(haystack)
        if yrs >= 3:
            score -= pen["years_3plus"]
            flags.append(f"{yrs}+ yrs experience")
        if any(k in haystack for k in fk["clearance"]):
            flags.append("clearance")
        if seasons and role_type == "intern":
            reasons.append("/".join(seasons))
        return max(-self.w["stage"], min(score, self.w["stage"])), reasons, flags

    def _freshness(self, date_posted, now: int) -> tuple[int, list[str]]:
        try:
            epoch = int(date_posted or 0)
        except (TypeError, ValueError):
            epoch = 0
        if epoch <= 0:
            return self.freshness["unknown_score"], []
        days = max(0, (now - epoch) // 86400)
        for bucket in self.freshness["buckets"]:
            if days <= bucket["max_days"]:
                label = "posted today" if days == 0 else f"posted {days}d ago"
                return bucket["score"], [label]
        return 0, []

    # -- public ------------------------------------------------------------
    def score(self, job: dict, now: int | None = None) -> Fit:
        now = now or int(time.time())
        title = job.get("title", "")
        desc = job.get("description", "") or ""
        hay = " ".join((title, job.get("category", ""), desc)).lower()

        role, r_reasons = self._role(title, desc)
        tier = self.tier_for(job.get("company_name", ""), job.get("employer_tier", ""))
        emp, e_reasons = self._employer(tier)
        skills, s_reasons = self._skills(hay)
        stage, st_reasons, flags = self._stage(
            job.get("role_type", ""), title, hay,
            job.get("seasons") or [], job.get("years") or [])
        fresh, f_reasons = self._freshness(job.get("date_posted"), now)

        total = role + emp + skills + stage + fresh
        return Fit(
            score=max(0, min(100, total)),
            reasons=[*e_reasons, *r_reasons, *s_reasons, *st_reasons, *f_reasons],
            flags=flags,
            parts={"role": role, "employer": emp, "skills": skills,
                   "stage": stage, "freshness": fresh},
        )

    def shortlist(self, jobs: list[dict]) -> list[dict]:
        """Pick the highest-priority roles to actually apply to.

        Only active roles compete, and a per-company cap stops one big board with
        forty near-identical reqs from becoming the entire list. A slice is held
        back for internships: full-time always outscores an internship, so on raw
        score alone the intern path would disappear from the list entirely.
        """
        cfg = self.shortlist_cfg
        max_size, reserve = cfg["max_size"], cfg.get("reserve_intern", 0)
        max_research = cfg.get("max_research")
        research_kw = [k.lower() for k in cfg.get("research_keywords") or []]
        pool = sorted(
            (j for j in jobs if j.get("active") and j.get("fit", 0) >= cfg["min_score"]),
            key=lambda j: (-j["fit"], -int(j.get("date_posted") or 0)),
        )
        per_company: dict[str, int] = {}
        chosen: dict[str, dict] = {}
        n_research = 0

        def is_research(job: dict) -> bool:
            title = job.get("title", "").lower()
            return any(k in title for k in research_kw)

        def take(candidates, limit: int) -> None:
            nonlocal n_research
            for job in candidates:
                if len(chosen) >= limit:
                    return
                if job["key"] in chosen:
                    continue
                key = normalize(job.get("company_name", "")) or job.get("company_name", "")
                if per_company.get(key, 0) >= cfg["max_per_company"]:
                    continue
                research = is_research(job)
                if research and max_research is not None and n_research >= max_research:
                    continue
                per_company[key] = per_company.get(key, 0) + 1
                n_research += research
                chosen[job["key"]] = job

        interns = [j for j in pool if j.get("role_type") == "intern"]
        take(pool, max(0, max_size - reserve))   # best overall, leaving room…
        take(interns, max_size)                  # …for the best internships…
        take(pool, max_size)                     # …then backfill if interns were few
        return sorted(chosen.values(),
                      key=lambda j: (-j["fit"], -int(j.get("date_posted") or 0)))
