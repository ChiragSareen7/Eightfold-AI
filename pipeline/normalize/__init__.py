"""Stage 3: Normalization — phones, dates, countries, skills."""

from __future__ import annotations

import re
from typing import Any

from pipeline.normalize.countries import normalize_country
from pipeline.normalize.dates import normalize_date, normalize_end_date
from pipeline.normalize.phones import normalize_phone
from pipeline.normalize.skills import canonicalize_skill


def normalize_extracted_resume(fields: Any) -> Any:
    """Apply normalization to extracted resume fields in place."""
    # Phones
    normalized_phones: list[str] = []
    raw_phones: list[str] = []
    for phone in fields.phones:
        result = normalize_phone(phone)
        if result.e164:
            normalized_phones.append(result.e164)
        else:
            raw_phones.append(result.raw)
    fields.phones = list(dict.fromkeys(normalized_phones + raw_phones))
    fields.phones_normalized = normalized_phones
    fields.phones_raw = raw_phones

    # Location country
    if fields.location:
        country = fields.location.get("country")
        if country and len(country) > 2:
            fields.location["country"] = normalize_country(country)

    # Experience dates
    for exp in fields.experience:
        if exp.get("start"):
            exp["start"] = normalize_date(exp["start"])
        if exp.get("end"):
            exp["end"] = normalize_end_date(exp["end"])

    # Education end_year stays as int

    # Skills canonicalization
    canonical_skills: list[dict[str, Any]] = []
    for skill in fields.skills:
        result = canonicalize_skill(skill)
        canonical_skills.append({
            "name": result.name,
            "confidence": result.confidence,
            "method": result.method,
            "original": skill,
        })
    fields.skills = canonical_skills

    return fields


def normalize_csv_record(record: Any) -> Any:
    """Normalize CSV record fields."""
    if record.phone:
        result = normalize_phone(record.phone)
        record.phone_normalized = result.e164
        record.phone_raw = result.raw if not result.e164 else None
        record.phone = result.e164 or result.raw

    if record.years_experience:
        try:
            record.years_experience_value = float(
                re.sub(r"[^\d.]", "", str(record.years_experience))
            )
        except (ValueError, TypeError):
            record.years_experience_value = None
    else:
        record.years_experience_value = None

    return record
