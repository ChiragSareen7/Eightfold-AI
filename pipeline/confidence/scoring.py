"""Stage 5: Confidence & provenance scoring.

Confidence formula (per field):
  base = source_reliability_weight
       * normalization_factor
       * agreement_bonus
       - disagreement_penalty

Source reliability weights (explainable, not LLM-judged):
  - recruiter_csv direct field: 0.90
  - resume regex extraction: 0.75
  - resume calculated (years from dates): 0.70
  - fuzzy entity match metadata reduces match-level confidence
  - phone unnormalized: 0.30
  - skill fuzzy match: score from rapidfuzz / 100

Agreement bonus: 1.0 if single source; 1.05 if multiple sources agree on scalar value.
Disagreement penalty: multiply by 0.7 when years_experience candidates disagree > 20%.

overall_confidence = weighted average of populated field confidences
  (required fields weighted 1.5x: full_name, emails)
"""

from __future__ import annotations

from pipeline.models.canonical import CanonicalProfile, ProvenanceEntry

SOURCE_WEIGHTS = {
    "recruiter_csv": 0.90,
    "resume": 0.75,
    "calculated_from_date_range": 0.70,
    "regex_extraction": 0.75,
    "alias_dictionary": 0.95,
    "fuzzy_match_normalization": 0.80,
    "unnormalized_no_country_code": 0.30,
    "E164": 0.95,
}

REQUIRED_FIELD_WEIGHT = 1.5


def score_profile(profile: CanonicalProfile) -> CanonicalProfile:
    """Compute per-field confidence, provenance entries, and overall score."""
    field_scores: dict[str, float] = {}

    # full_name
    if profile.full_name:
        field_scores["full_name"] = _score_scalar(
            profile, "full_name", has_csv=_has_csv_source(profile)
        )
        _add_provenance(profile, "full_name", _primary_source(profile), "direct_field_csv")

    # emails
    if profile.emails:
        field_scores["emails"] = _score_scalar(profile, "emails", has_csv=True)
        _add_provenance(profile, "emails", "recruiter_csv", "direct_field_csv")

    # phones — E.164 phones in profile.phones score high; raw (no country code)
    # phones in profile.phones_raw score low. Both can exist simultaneously.
    if profile.phones:
        field_scores["phones"] = 0.95  # all phones here start with + (E.164)
        _add_provenance(profile, "phones", _phone_source(profile), "E164")
    if profile.phones_raw:
        # Raw phones are tracked separately so the penalty is always applied.
        field_scores["phones_raw"] = 0.30
        _add_provenance(profile, "phones_raw", "resume", "unnormalized_no_country_code")

    if profile.headline:
        field_scores["headline"] = _score_scalar(profile, "headline", has_csv=False)
        _add_provenance(profile, "headline", "resume", "regex_extraction")

    if profile.location:
        field_scores["location"] = 0.65
        _add_provenance(profile, "location", "resume", "regex_extraction")

    if profile.years_experience is not None:
        ye_score = _score_years_experience(profile)
        field_scores["years_experience"] = ye_score
        # provenance may already exist from merge disagreement

    if profile.skills:
        # Fixed formula — NOT an average of individual skill confidences.
        # Individual skill confidence (stored on each CanonicalSkill) reflects
        # normalization quality and is shown per-chip in the UI.
        # The field-level score uses a fixed tier based on the extraction method:
        #   regex + alias dictionary hit → 0.80 (high: deterministic lookup)
        #   regex + fuzzy match above threshold → 0.70 (medium: approximate)
        #   regex + kept as-is (no match) → 0.55 (lower: unverified label)
        # We pick the tier of the *median* skill to avoid outliers skewing the score.
        tiers = sorted(
            _skill_field_tier(s.method) for s in profile.skills
        )
        mid = tiers[len(tiers) // 2]
        field_scores["skills"] = mid
        _add_provenance(profile, "skills", "resume", "regex_extraction")

    if profile.experience:
        field_scores["experience"] = 0.75
        _add_provenance(profile, "experience", "resume", "regex_extraction")

    if profile.education:
        field_scores["education"] = 0.72
        _add_provenance(profile, "education", "resume", "regex_extraction")

    if profile.links and any(
        profile.links.get(k) for k in ("linkedin", "github", "portfolio")
    ):
        field_scores["links"] = 0.80
        _add_provenance(profile, "links", "resume", "regex_extraction")

    # Apply entity-match confidence cap for fuzzy merges
    merge_meta = profile.field_meta.get("_merge")
    if merge_meta and getattr(merge_meta, "match_method", "") == "fuzzy_name_company":
        cap = getattr(merge_meta, "match_confidence", 0.65)
        field_scores = {k: min(v, cap) for k, v in field_scores.items()}

    profile.field_confidence = {k: round(v, 3) for k, v in field_scores.items()}
    profile.overall_confidence = _overall(field_scores)
    return profile


def _skill_field_tier(method: str) -> float:
    """
    Fixed confidence tier for the skills *field* based on normalization method.
    Three possible values — small, predictable, explainable set:
      alias_dictionary            → 0.80  (exact curated lookup)
      fuzzy_match_normalization   → 0.70  (approximate string match, above threshold)
      kept_original_below_threshold → 0.55 (raw label, no normalization applied)
    """
    if method == "alias_dictionary":
        return 0.80
    if method == "fuzzy_match_normalization":
        return 0.70
    return 0.55  # kept_original_below_threshold or unknown


def _score_scalar(profile: CanonicalProfile, field: str, has_csv: bool) -> float:
    if has_csv:
        return SOURCE_WEIGHTS["recruiter_csv"]
    return SOURCE_WEIGHTS["resume"]


def _score_years_experience(profile: CanonicalProfile) -> float:
    base = SOURCE_WEIGHTS["recruiter_csv"]
    for p in profile.provenance:
        if p.field == "years_experience":
            if p.candidate_values and len(p.candidate_values) > 1:
                return round(base * 0.7, 3)
            if p.source == "resume":
                method = p.method
                return SOURCE_WEIGHTS.get(method, SOURCE_WEIGHTS["resume"])
    return base


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


def _has_csv_source(profile: CanonicalProfile) -> bool:
    merge_meta = profile.field_meta.get("_merge")
    if merge_meta:
        return "recruiter_csv" in getattr(merge_meta, "sources", [])
    return bool(profile.emails)


def _primary_source(profile: CanonicalProfile) -> str:
    merge_meta = profile.field_meta.get("_merge")
    if merge_meta and "recruiter_csv" in getattr(merge_meta, "sources", []):
        return "recruiter_csv"
    return "resume"


def _phone_source(profile: CanonicalProfile) -> str:
    if profile.phones:
        return "recruiter_csv" if _has_csv_source(profile) else "resume"
    return "resume"


def _add_provenance(
    profile: CanonicalProfile,
    field: str,
    source: str,
    method: str,
) -> None:
    if any(p.field == field for p in profile.provenance):
        return
    profile.provenance.append(ProvenanceEntry(field=field, source=source, method=method))
