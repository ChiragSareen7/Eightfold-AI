# =============================================================================
# FILE: pipeline/normalize/csv_fields.py | STAGE: 3 — Normalize (CSV extras)
# DOES: Parses CSV skills, education strings, experience_months → years.
# IN:   Raw CSV column strings from RawCsvRecord.
# NEXT → pipeline/normalize/__init__.py (normalize_csv_record)
# =============================================================================
"""Parse and normalize extra recruiter CSV fields (skills, education, experience)."""

from __future__ import annotations

import re
from typing import Any

from pipeline.normalize.skills import canonicalize_skill


def parse_csv_skills(raw: str | None) -> list[dict[str, Any]]:
    """Split comma-separated skills and canonicalize each."""
    if not raw or not raw.strip():
        return []
    parts = [p.strip() for p in re.split(r"[,;|]", raw) if p.strip()]
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for part in parts:
        result = canonicalize_skill(part)
        key = result.name.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "name": result.name,
            "confidence": result.confidence,
            "method": result.method,
            "original": part,
            "best_match": result.best_match,
            "best_score": result.best_score,
        })
    return results


def parse_csv_education(raw: str | None) -> list[dict[str, Any]]:
    """
    Parse a single education line like:
      'BITS Pilani - B.E. Computer Science, 2021'
    """
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    end_year = None
    year_match = re.search(r"\b(19|20)\d{2}\b", text)
    if year_match:
        end_year = int(year_match.group())
        text = text[: year_match.start()].rstrip(" ,")

    institution = text
    degree = None
    field = None
    if " - " in text:
        institution, rest = text.split(" - ", 1)
        institution = institution.strip()
        degree = rest.strip() or None
    elif "," in text:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        institution = parts[0]
        if len(parts) > 1:
            degree = parts[1]

    return [{
        "institution": institution,
        "degree": degree,
        "field": field,
        "end_year": end_year,
        "source": "recruiter_csv",
    }]


def parse_experience_months(raw: str | None) -> float | None:
    if not raw or not str(raw).strip():
        return None
    try:
        months = float(re.sub(r"[^\d.]", "", str(raw)))
    except (ValueError, TypeError):
        return None
    if months <= 0:
        return None
    return round(months / 12.0, 1)


def parse_years_experience_string(raw: str | None) -> float | None:
    if not raw or not str(raw).strip():
        return None
    try:
        return float(re.sub(r"[^\d.]", "", str(raw)))
    except (ValueError, TypeError):
        return None


def resolve_csv_years_experience(
    months_raw: str | None,
    years_raw: str | None,
) -> tuple[float | None, str | None]:
    """
    Prefer experience_months when present; fall back to years_experience column.
    Returns (value_in_years, method_tag).
    """
    from_months = parse_experience_months(months_raw)
    if from_months is not None:
        return from_months, "direct_field_csv_months"
    from_years = parse_years_experience_string(years_raw)
    if from_years is not None:
        return from_years, "direct_field_csv"
    return None, None

# -----------------------------------------------------------------------------
# ROUTE OUT: skills_normalized[], education_normalized[], years_experience_value
# NEXT FILE → pipeline/normalize/__init__.py → merge/entity_resolution.py
# -----------------------------------------------------------------------------
