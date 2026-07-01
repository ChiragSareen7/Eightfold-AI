# =============================================================================
# FILE: pipeline/confidence/scoring.py | STAGE: 5 — Confidence & provenance
# DOES: Per-field confidence, provenance entries, field_reasoning, overall_confidence.
# IN:   CanonicalProfile from merger (pre-scoring).
# NEXT → pipeline/project/projector.py (project) | webapp UI (trust % display)
# =============================================================================
"""Stage 5: Confidence & provenance scoring.

Provenance source tags always reflect which sources actually contributed to each
field — never label resume when the profile is CSV-only (or vice versa).
"""

from __future__ import annotations

from pipeline.models.canonical import CanonicalProfile, ProvenanceEntry
from pipeline.reasoning import (
    phone_reasoning_for_method,
    skill_kept_below_threshold,
    years_experience_suppressed,
)

SOURCE_WEIGHTS = {
    "recruiter_csv": 0.90,
    "resume": 0.75,
    "calculated_from_date_range": 0.70,
    "regex_extraction": 0.75,
    "alias_dictionary": 0.95,
    "fuzzy_match_normalization": 0.80,
    "unnormalized_no_country_code": 0.30,
    "unnormalized_invalid": 0.30,
    "unnormalized_parse_error": 0.30,
    "E164": 0.95,
    "merged": 0.82,
    "direct_field_csv": 0.90,
    "direct_field_csv_months": 0.90,
}

REQUIRED_FIELD_WEIGHT = 1.5

# Profiles built from one source only lack cross-source corroboration.
SINGLE_SOURCE_CONFIDENCE_FACTOR = 0.85


def score_profile(profile: CanonicalProfile) -> CanonicalProfile:
    """Compute per-field confidence, provenance entries, reasoning, and overall score."""
    field_scores: dict[str, float] = {}
    field_reasoning: dict[str, str] = {}
    sources = _group_sources(profile)

    if profile.full_name:
        src, method = _attrib(profile, "full_name")
        field_scores["full_name"] = SOURCE_WEIGHTS.get(
            method, SOURCE_WEIGHTS[src] if src in SOURCE_WEIGHTS else 0.75
        )
        _add_provenance(profile, "full_name", src, method)

    if profile.emails:
        src, method = _attrib(profile, "emails")
        field_scores["emails"] = SOURCE_WEIGHTS["recruiter_csv"] if src == "recruiter_csv" else SOURCE_WEIGHTS["resume"]
        _add_provenance(profile, "emails", src, method)

    if profile.phones:
        field_scores["phones"] = 0.95
        src, method = _phone_normalized_source(profile)
        _add_provenance(profile, "phones", src, method)

    if profile.phones_raw:
        field_scores["phones_raw"] = 0.30
        raw_details = _phones_raw_details(profile)
        primary_method = raw_details[0]["method"] if raw_details else "unnormalized_no_country_code"
        primary_source = raw_details[0]["source"] if raw_details else "resume"
        _add_provenance(profile, "phones_raw", primary_source, primary_method)
        field_reasoning["phones_raw"] = _phones_raw_reasoning(raw_details)

    if profile.headline:
        src, method = _attrib(profile, "headline")
        field_scores["headline"] = SOURCE_WEIGHTS["recruiter_csv"] if src == "recruiter_csv" else SOURCE_WEIGHTS["resume"]
        _add_provenance(profile, "headline", src, method)

    if profile.location:
        if "resume" in sources:
            field_scores["location"] = 0.65
            _add_provenance(profile, "location", "resume", "regex_extraction")

    ye_prov = _years_experience_provenance(profile)
    if ye_prov and ye_prov.method == "suppressed_disagreement":
        field_scores["years_experience"] = 0.0
        field_reasoning["years_experience"] = _years_disagreement_reasoning(ye_prov)
    elif profile.years_experience is not None:
        field_scores["years_experience"] = _score_years_experience(profile)
        if not ye_prov:
            src, method = _attrib(profile, "years_experience")
            _add_provenance(profile, "years_experience", src, method)

    if profile.skills:
        tiers = sorted(_skill_field_tier(s.method) for s in profile.skills)
        mid = tiers[len(tiers) // 2]
        field_scores["skills"] = mid
        src, method = _skills_field_source(profile)
        _add_provenance(profile, "skills", src, method)
        skills_reasoning = _skills_below_threshold_reasoning(profile.skills)
        if skills_reasoning:
            field_reasoning["skills"] = skills_reasoning

    if profile.experience:
        field_scores["experience"] = 0.75
        src, method = _experience_field_source(profile)
        _add_provenance(profile, "experience", src, method)

    if profile.education:
        field_scores["education"] = 0.72
        src, method = _education_field_source(profile)
        _add_provenance(profile, "education", src, method)

    if profile.links and any(
        profile.links.get(k) for k in ("linkedin", "github", "portfolio")
    ):
        field_scores["links"] = 0.80
        _add_provenance(profile, "links", "resume", "regex_extraction")

    merge_meta = profile.field_meta.get("_merge")
    if merge_meta and getattr(merge_meta, "match_method", "") == "manifest_resume_link":
        cap = getattr(merge_meta, "match_confidence", 0.88)
        field_scores = {k: min(v, cap) for k, v in field_scores.items()}

    if profile.source_profile_kind in ("csv_only", "resume_only"):
        field_scores = {
            k: round(v * SINGLE_SOURCE_CONFIDENCE_FACTOR, 3)
            for k, v in field_scores.items()
        }

    profile.field_confidence = {k: round(v, 3) for k, v in field_scores.items()}
    profile.field_reasoning = field_reasoning
    profile.overall_confidence = _overall(field_scores)
    return profile


def _group_sources(profile: CanonicalProfile) -> set[str]:
    merge_meta = profile.field_meta.get("_merge")
    if merge_meta:
        return set(getattr(merge_meta, "sources", []))
    if profile.source_profile_kind == "csv_only":
        return {"recruiter_csv"}
    if profile.source_profile_kind == "resume_only":
        return {"resume"}
    return {"recruiter_csv", "resume"}


def _only_csv(profile: CanonicalProfile) -> bool:
    return profile.source_profile_kind == "csv_only"


def _only_resume(profile: CanonicalProfile) -> bool:
    return profile.source_profile_kind == "resume_only"


def _attrib(profile: CanonicalProfile, field: str) -> tuple[str, str]:
    """Return (provenance source, method) for a scalar field."""
    if _only_csv(profile):
        if field == "years_experience":
            for p in profile.provenance:
                if p.field == "years_experience":
                    return p.source, p.method
            return "recruiter_csv", "direct_field_csv"
        return "recruiter_csv", "direct_field_csv"
    if _only_resume(profile):
        if field == "years_experience":
            return "resume", "calculated_from_date_range"
        if field == "headline":
            return "resume", "regex_extraction"
        if field == "full_name":
            return "resume", "regex_extraction"
        if field == "emails":
            return "resume", "regex_extraction"
        return "resume", "regex_extraction"
    # merged — CSV wins scalars per merge policy
    if field in ("full_name", "emails", "headline", "years_experience"):
        if field == "years_experience":
            for p in profile.provenance:
                if p.field == "years_experience":
                    return p.source, p.method
        return "recruiter_csv", "direct_field_csv"
    return "resume", "regex_extraction"


def _skills_field_source(profile: CanonicalProfile) -> tuple[str, str]:
    skill_sources: set[str] = set()
    for s in profile.skills:
        skill_sources.update(s.sources)
    if skill_sources == {"recruiter_csv"}:
        return "recruiter_csv", "direct_field_csv"
    if skill_sources == {"resume"}:
        return "resume", "regex_extraction"
    if "recruiter_csv" in skill_sources and "resume" in skill_sources:
        return "merged", "union_csv_resume"
    return "resume", "regex_extraction"


def _experience_field_source(profile: CanonicalProfile) -> tuple[str, str]:
    entry_sources = {(e.get("source") or "resume") for e in profile.experience}
    if entry_sources <= {"recruiter_csv"}:
        return "recruiter_csv", "direct_field_csv"
    if entry_sources <= {"resume"}:
        return "resume", "regex_extraction"
    return "merged", "union_csv_resume"


def _education_field_source(profile: CanonicalProfile) -> tuple[str, str]:
    entry_sources = {(e.get("source") or "resume") for e in profile.education}
    if entry_sources <= {"recruiter_csv"}:
        return "recruiter_csv", "direct_field_csv"
    if entry_sources <= {"resume", "merged"}:
        if entry_sources == {"merged"}:
            return "merged", "union_csv_resume"
        return "resume", "regex_extraction"
    return "merged", "union_csv_resume"


def _phone_normalized_source(profile: CanonicalProfile) -> tuple[str, str]:
    if _only_resume(profile):
        return "resume", "E164"
    if _only_csv(profile):
        return "recruiter_csv", "E164"
    return _phone_source(profile), "E164"


def _skill_field_tier(method: str) -> float:
    if method == "alias_dictionary":
        return 0.80
    if method == "fuzzy_match_normalization":
        return 0.70
    return 0.55


def _score_years_experience(profile: CanonicalProfile) -> float:
    for p in profile.provenance:
        if p.field == "years_experience":
            if p.source == "resume":
                return SOURCE_WEIGHTS.get(p.method, SOURCE_WEIGHTS["resume"])
            return SOURCE_WEIGHTS.get(p.method, SOURCE_WEIGHTS["recruiter_csv"])
    if _only_resume(profile):
        return SOURCE_WEIGHTS["resume"]
    return SOURCE_WEIGHTS["recruiter_csv"]


def _years_experience_provenance(profile: CanonicalProfile) -> ProvenanceEntry | None:
    for p in profile.provenance:
        if p.field == "years_experience":
            return p
    return None


def _years_disagreement_reasoning(provenance: ProvenanceEntry) -> str:
    csv_val = None
    resume_val = None
    for candidate in provenance.candidate_values or []:
        if candidate.get("source") == "recruiter_csv":
            csv_val = float(candidate["value"])
        elif candidate.get("source") == "resume":
            resume_val = float(candidate["value"])
    if csv_val is None or resume_val is None:
        values = provenance.candidate_values or []
        if len(values) >= 2:
            csv_val = float(values[0]["value"])
            resume_val = float(values[1]["value"])
    if csv_val is None or resume_val is None:
        return (
            "CSV and resume disagree on years of experience by more than our "
            "agreement threshold, so no value is being asserted for this field."
        )
    diff_ratio = abs(csv_val - resume_val) / max(csv_val, resume_val, 1)
    return years_experience_suppressed(csv_val, resume_val, diff_ratio)


def _phones_raw_details(profile: CanonicalProfile) -> list[dict[str, str]]:
    meta = profile.field_meta.get("phones_raw_details")
    if meta:
        return meta
    src = "resume" if _only_resume(profile) else "recruiter_csv"
    return [{"value": p, "method": "unnormalized_no_country_code", "source": src} for p in profile.phones_raw]


def _phones_raw_reasoning(details: list[dict[str, str]]) -> str:
    return " ".join(phone_reasoning_for_method(d["method"], d["value"]) for d in details)


def _skills_below_threshold_reasoning(skills) -> str | None:
    flagged = [s for s in skills if s.method == "kept_original_below_threshold"]
    if not flagged:
        return None
    return " ".join(
        skill_kept_below_threshold(s.name, s.best_match, s.best_score) for s in flagged
    )


def _overall(field_scores: dict[str, float]) -> float:
    if not field_scores:
        return 0.0
    total = 0.0
    weight_sum = 0.0
    for field, score in sorted(field_scores.items()):
        w = REQUIRED_FIELD_WEIGHT if field in ("full_name", "emails") else 1.0
        total += score * w
        weight_sum += w
    return round(total / weight_sum, 3)


def _phone_source(profile: CanonicalProfile) -> str:
    if _only_csv(profile):
        return "recruiter_csv"
    if _only_resume(profile):
        return "resume"
    details = profile.field_meta.get("phones_raw_details") or []
    csv_phones = [d for d in details if d.get("source") == "recruiter_csv"]
    if profile.phones and not csv_phones:
        return "recruiter_csv" if _group_sources(profile) == {"recruiter_csv"} else "resume"
    return "recruiter_csv" if "recruiter_csv" in _group_sources(profile) else "resume"


def _add_provenance(
    profile: CanonicalProfile,
    field: str,
    source: str,
    method: str,
) -> None:
    if any(p.field == field for p in profile.provenance):
        return
    profile.provenance.append(ProvenanceEntry(field=field, source=source, method=method))

# -----------------------------------------------------------------------------
# ROUTE OUT: CanonicalProfile with field_confidence, provenance, field_reasoning, overall_confidence
# NEXT FILE → pipeline/project/projector.py | pipeline/merge/source_annotation.py
# -----------------------------------------------------------------------------
