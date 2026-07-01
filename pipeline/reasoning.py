# =============================================================================
# FILE: pipeline/reasoning.py
# DOES: Builds plain-English field_reasoning strings for UI (years, phones, skills).
# IN:   Conflict metadata from merge/scoring stages.
# NEXT → pipeline/confidence/scoring.py (field_reasoning on CanonicalProfile)
# =============================================================================
"""Plain-English reasoning strings for suppressed or downgraded field values."""

from __future__ import annotations

from pipeline.merge.entity_resolution import YEARS_EXPERIENCE_DISAGREEMENT_THRESHOLD
from pipeline.normalize.skills import FUZZY_THRESHOLD


def years_experience_suppressed(
    csv_val: float,
    resume_val: float,
    diff_ratio: float,
) -> str:
    pct = int(round(diff_ratio * 100))
    threshold_pct = int(round(YEARS_EXPERIENCE_DISAGREEMENT_THRESHOLD * 100))
    resume_display = _format_years(resume_val)
    return (
        f"CSV states {csv_val:g} years; resume's work history calculates to "
        f"approximately {resume_display} years — a {pct}% gap, which exceeds our "
        f"{threshold_pct}% agreement threshold, so no value is being asserted for "
        f"this field."
    )


def phone_no_country_code(value: str) -> str:
    return (
        f"Phone number '{value}' has no country code, so it could not be normalized "
        f"to E.164. We do not guess a country, so the raw digits are kept in "
        f"phones_raw rather than asserting a normalized number."
    )


def phone_invalid(value: str) -> str:
    return (
        f"The value '{value}' is not a valid phone number, so it was discarded "
        f"rather than treated as real data."
    )


def phone_parse_error(value: str) -> str:
    return (
        f"The phone parser failed on this value ('{value}'), so it was not "
        f"normalized and is kept only in phones_raw."
    )


def skill_kept_below_threshold(
    skill: str,
    best_match: str | None,
    best_score: float | None,
) -> str:
    threshold_pct = int(FUZZY_THRESHOLD)
    if best_match and best_score is not None:
        score_pct = int(round(best_score))
        return (
            f"The skill '{skill}' did not match any canonical skill name above our "
            f"{threshold_pct}% similarity threshold (best match: '{best_match}' at "
            f"{score_pct}%), so it was kept as originally written rather than being "
            f"force-mapped."
        )
    return (
        f"The skill '{skill}' did not match any canonical skill name above our "
        f"{threshold_pct}% similarity threshold, so it was kept as originally written "
        f"rather than being force-mapped."
    )


def phone_reasoning_for_method(method: str, value: str) -> str:
    if method == "unnormalized_no_country_code":
        return phone_no_country_code(value)
    if method == "unnormalized_invalid":
        return phone_invalid(value)
    if method == "unnormalized_parse_error":
        return phone_parse_error(value)
    return phone_no_country_code(value)


def _format_years(value: float) -> str:
    rounded = round(value, 1)
    return f"{rounded:g}"

# -----------------------------------------------------------------------------
# ROUTE OUT: human-readable reasoning strings
# NEXT FILE → pipeline/confidence/scoring.py → CanonicalProfile.field_reasoning → UI cards
# -----------------------------------------------------------------------------
