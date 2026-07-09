"""Classify a job by early-career eligibility and track.

`early_career_ok` decides whether the role is kept at all. `track` buckets it,
with the dsml track being the one you care about most. Keyword lists live in
config.yaml so you can tune without touching this file.
"""
from __future__ import annotations


def _has(text: str, needles: list[str]) -> bool:
    return any(n in text for n in needles)


def early_career_ok(title: str, category: str, role_type: str, cfg: dict) -> bool:
    """True if the role reads as new-grad / intern rather than experienced."""
    t = f" {title.lower()} "
    # Internship-sourced rows are early-career by definition.
    if role_type == "intern":
        return not _has(t, [b for b in cfg["seniority_block"] if b not in (" ii", " iii")])
    if _has(t, cfg["seniority_block"]):
        return False
    if _has(t, cfg["early_career_any"]):
        return True
    # Category signal from aggregators (e.g. "AI/ML/Data") plus a non-senior title
    # is treated as new-grad eligible when the title gives no seniority cue.
    return category != "" and not _has(t, ["experienced"])


def track_of(title: str, category: str, cfg: dict) -> str:
    t = title.lower()
    c = category.lower()
    # The title is the strongest signal, so match every track on the title first.
    # Only then fall back to the aggregator's (broad, umbrella-ish) category — otherwise
    # a "Data/AI/ML" category drags plain "Data Engineer" titles into dsml before the
    # data_eng track is ever considered.
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
