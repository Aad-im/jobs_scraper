"""Decide whether a job is early-career, and which track it belongs to.

`early_career_ok` gates what reaches the board at all; `track_of` buckets what
survives, with `dsml` being the track that matters most here. The keyword lists
live in config.yaml so they can be tuned without touching code — this module
only adds the two judgements that keywords can't express: numeric seniority
levels ("Engineer 3", "MLE V") and years-of-experience bars in the job text.
"""
from __future__ import annotations

import re

# "Scientist 5", "Engineer III", "MTS 2" — a trailing level number or numeral is
# seniority, but only at the end of a title, so "Summer 2027" is left alone.
_TRAILING_LEVEL = re.compile(
    r"\b(?:level\s*|l|lvl\s*|grade\s*)?([2-9]|1[0-2]|ii|iii|iv|v|vi|vii)\s*$", re.I)
_ROMAN_SENIOR = {"ii", "iii", "iv", "v", "vi", "vii"}
# "5+ years", "minimum of 3 years", "3-5 years of experience"
_YEARS = re.compile(
    r"(\d+)\s*\+?\s*(?:-|to|–)?\s*(?:\d+)?\s*\+?\s*(?:years?|yrs?)\b[^.]{0,40}?"
    r"(?:experience|exp\b|industry|professional)", re.I)
_INTERNISH = re.compile(r"\b(intern|internship|co-?op|placement|apprentice)\b", re.I)


def _has(text: str, needles) -> bool:
    return any(n in text for n in needles)


def _numeric_seniority(title: str) -> bool:
    m = _TRAILING_LEVEL.search(title.strip())
    if not m:
        return False
    token = m.group(1).lower()
    if token in _ROMAN_SENIOR:
        return True
    return token.isdigit() and int(token) >= 2


def max_years_required(text: str) -> int:
    """Highest years-of-experience figure demanded anywhere in the text (0 if none)."""
    return max((int(m.group(1)) for m in _YEARS.finditer(text or "")), default=0)


def early_career_ok(title: str, category: str, role_type: str, cfg: dict,
                    description: str = "") -> bool:
    """True if the role reads as new-grad / intern rather than experienced."""
    t = f" {title.lower()} "
    if _INTERNISH.search(t) or role_type == "intern":
        # Internships are early-career by definition. Roman numerals are still
        # allowed through because "Intern II" is a returning-intern posting, not
        # a senior role.
        return not _has(t, [b for b in cfg["seniority_block"]
                            if b not in (" ii", " iii", " iv")])
    if _has(t, cfg["seniority_block"]) or _numeric_seniority(title):
        return False
    # A hard experience bar in the posting body overrides an innocent-looking
    # title — plenty of "Machine Learning Engineer" reqs want 5 years.
    if max_years_required(description) >= 3:
        return False
    if _has(t, cfg["early_career_any"]):
        return True
    # Category signal from aggregators (e.g. "AI/ML/Data") plus a non-senior
    # title is treated as new-grad eligible when the title gives no seniority cue.
    return category != ""


def function_ok(title: str, department: str, cfg: dict) -> bool:
    """False for non-technical roles. Direct-ATS boards list every department,
    so without this the loose early-career keywords leak in sales and support."""
    blocked = cfg.get("function_block") or []
    haystack = f" {title.lower()} {department.lower()} "
    return not _has(haystack, blocked)


def track_of(title: str, category: str, cfg: dict) -> str:
    t = title.lower()
    c = category.lower()
    # The title is the strongest signal, so match every track on the title first.
    # Only then fall back to the aggregator's (broad, umbrella-ish) category —
    # otherwise a "Data/AI/ML" category drags plain "Data Engineer" titles into
    # dsml before the data_eng track is ever considered.
    for name, needles in cfg["tracks"].items():
        if _has(t, needles):
            return name
    for name, needles in cfg["tracks"].items():
        if _has(c, needles):
            return name
    # Coarse category fallback when neither title nor track keywords matched.
    if "ai" in c or "ml" in c or "data" in c:
        return "dsml"
    if "software" in c:
        return "swe"
    if "quant" in c:
        return "quant"
    if "hardware" in c:
        return "hardware"
    return "other"
