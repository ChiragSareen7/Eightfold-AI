"""Stage 4: Merge records into canonical profile with conflict resolution."""

from __future__ import annotations

from typing import Any

from pipeline.merge.entity_resolution import (
    DEFAULT_SOURCE_PRIORITY,
    EntityGroup,
    SourceRecord,
    YEARS_EXPERIENCE_DISAGREEMENT_THRESHOLD,
    _candidate_id_from_email,
)
from pipeline.models.canonical import CanonicalProfile, CanonicalSkill, ProvenanceEntry


def merge_group(
    group: EntityGroup,
    source_priority: list[str] | None = None,
) -> CanonicalProfile:
    """
    Merge all source records in a group into one canonical profile.

    Conflict policy: configurable source-priority list (default CSV > resume).
    Array fields: union with deduplication, CSV values first.
    """
    priority = source_priority or DEFAULT_SOURCE_PRIORITY
    priority_rank = {s: i for i, s in enumerate(priority)}

    csv_records = [r for r in group.records if r.source_type == "recruiter_csv"]
    resume_records = [r for r in group.records if r.source_type == "resume"]

    # Determine candidate_id from best available email
    primary_email = _pick_primary_email(csv_records, resume_records, priority)
    candidate_id = _candidate_id_from_email(primary_email) if primary_email else f"unknown_{group.records[0].source_id}"

    profile = CanonicalProfile(candidate_id=candidate_id)

    # Scalar fields with conflict resolution
    profile.full_name = _resolve_scalar(
        csv_records, resume_records, "name", "full_name", priority_rank
    )
    profile.headline = _resolve_scalar(
        csv_records, resume_records, None, "headline", priority_rank
    )
    profile.location = _resolve_scalar(
        csv_records, resume_records, None, "location", priority_rank
    )

    # Title from CSV maps to headline if headline missing
    if not profile.headline and csv_records:
        for csv in csv_records:
            if csv.data.get("title"):
                profile.headline = csv.data["title"]
                break

    # years_experience with disagreement handling
    profile.years_experience, ye_provenance = _resolve_years_experience(
        csv_records, resume_records, priority_rank
    )
    if ye_provenance:
        profile.provenance.append(ye_provenance)

    # Array fields: union with dedup, CSV first
    profile.emails = _union_emails(csv_records, resume_records)
    profile.phones, profile.phones_raw = _union_phones(csv_records, resume_records)
    profile.skills = _union_skills(csv_records, resume_records)
    profile.experience = _union_experience(csv_records, resume_records, priority_rank)
    profile.education = _union_education(resume_records)
    profile.links = _merge_links(resume_records)

    # Store merge metadata for confidence stage
    profile.field_meta["_merge"] = type("M", (), {
        "match_method": group.match_method,
        "match_confidence": group.match_confidence,
        "sources": list({r.source_type for r in group.records}),
    })()

    return profile


def _pick_primary_email(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
    priority: list[str],
) -> str | None:
    for source_type in priority:
        if source_type == "recruiter_csv":
            for r in csv_records:
                if r.email:
                    return r.email
        elif source_type == "resume":
            for r in resume_records:
                if r.email:
                    return r.email
    return None


def _resolve_scalar(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
    csv_key: str | None,
    resume_key: str,
    priority_rank: dict[str, int],
) -> Any:
    """Winner by source priority; structured CSV beats resume by default."""
    candidates: list[tuple[str, Any, str]] = []

    for r in csv_records:
        key = csv_key or resume_key
        if csv_key == "name":
            val = r.data.get("name")
        else:
            val = r.data.get(key) if key in r.data else None
        if val is not None:
            candidates.append(("recruiter_csv", val, "direct_field_csv"))

    for r in resume_records:
        val = r.data.get(resume_key)
        if val is not None:
            method = r.data.get("field_methods", {}).get(resume_key, "regex_extraction")
            candidates.append(("resume", val, method))

    if not candidates:
        return None

    candidates.sort(key=lambda c: priority_rank.get(c[0], 99))
    return candidates[0][1]


def _resolve_years_experience(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
    priority_rank: dict[str, int],
) -> tuple[float | None, ProvenanceEntry | None]:
    """
    CSV direct value vs resume calculated/stated value.
    Priority winner kept; if disagreement > 20%, reduce confidence and log both.
    """
    candidates: list[tuple[str, float, str]] = []

    for r in csv_records:
        val = r.data.get("years_experience")
        if val is not None:
            candidates.append(("recruiter_csv", float(val), "direct_field_csv"))

    for r in resume_records:
        val = r.data.get("years_experience")
        if val is not None:
            method = r.data.get("years_experience_method", "regex_extraction")
            candidates.append(("resume", float(val), method))

    if not candidates:
        return None, None

    candidates.sort(key=lambda c: priority_rank.get(c[0], 99))
    winner_source, winner_val, winner_method = candidates[0]

    provenance = ProvenanceEntry(
        field="years_experience",
        source=winner_source,
        method=winner_method,
    )

    if len(candidates) > 1:
        loser_source, loser_val, loser_method = candidates[1]
        if winner_val and loser_val:
            diff_ratio = abs(winner_val - loser_val) / max(winner_val, loser_val, 1)
            if diff_ratio > YEARS_EXPERIENCE_DISAGREEMENT_THRESHOLD:
                provenance.notes = (
                    f"Disagreement: {winner_source}={winner_val} vs "
                    f"{loser_source}={loser_val} ({diff_ratio:.0%} gap)"
                )
                provenance.candidate_values = [
                    {"source": winner_source, "value": winner_val, "method": winner_method},
                    {"source": loser_source, "value": loser_val, "method": loser_method},
                ]
                provenance.method = f"{winner_method}_with_disagreement_penalty"

    return winner_val, provenance


def _union_emails(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for r in csv_records:
        email = r.data.get("email")
        if email:
            key = email.lower()
            if key not in seen:
                seen.add(key)
                result.append(email)
    for r in resume_records:
        for email in r.data.get("emails", []):
            key = email.lower()
            if key not in seen:
                seen.add(key)
                result.append(email)
    return result


def _union_phones(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
) -> tuple[list[str], list[str]]:
    """
    Route phones to normalized (E.164, starts with +) or raw (no country code).
    A phone is only considered normalized if it starts with '+' — no guessing.
    CSV phones that failed normalization are raw, not normalized.
    """
    seen: set[str] = set()
    normalized: list[str] = []
    raw: list[str] = []

    for r in csv_records:
        phone = r.data.get("phone")
        if phone and phone not in seen:
            seen.add(phone)
            # Only treat as normalized if it is actually E.164 (starts with +).
            if phone.startswith("+"):
                normalized.append(phone)
            else:
                raw.append(phone)

    for r in resume_records:
        for phone in r.data.get("phones_normalized", r.data.get("phones", [])):
            if phone and phone not in seen:
                seen.add(phone)
                if phone.startswith("+"):
                    normalized.append(phone)
                else:
                    raw.append(phone)
        for phone in r.data.get("phones_raw", []):
            if phone and phone not in seen:
                seen.add(phone)
                raw.append(phone)

    return normalized, raw


def _union_skills(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
) -> list[CanonicalSkill]:
    seen: set[str] = set()
    skills: list[CanonicalSkill] = []

    for r in resume_records:
        for skill_data in r.data.get("skills", []):
            if isinstance(skill_data, dict):
                name = skill_data.get("name", "")
                confidence = skill_data.get("confidence", 0.7)
                method = skill_data.get("method", "regex_extraction")
            else:
                name = str(skill_data)
                confidence = 0.7
                method = "regex_extraction"
            key = name.lower()
            if key not in seen:
                seen.add(key)
                skills.append(CanonicalSkill(
                    name=name,
                    confidence=confidence,
                    sources=["resume"],
                    method=method,
                ))
    return skills


def _exp_dedup_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    """Stable dedup key for an experience entry: (company, title, start_date)."""
    return (
        (entry.get("company") or "").strip().lower(),
        (entry.get("title") or "").strip().lower(),
        (entry.get("start") or "").strip().lower(),
    )


def _union_experience(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
    priority_rank: dict[str, int],
) -> list[dict[str, Any]]:
    """
    Merge experience from CSV (current role only, no dates) and resume (full history).

    Deduplication: resume entries are kept as authoritative. A CSV entry is only
    added if no resume entry shares the same (company, title, start_date) triple
    (case-insensitive). This prevents the same role appearing twice when the CSV
    current_company/title matches the most-recent resume entry.
    """
    experience: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    # Resume entries first — they carry dates and summaries.
    for r in resume_records:
        for exp in r.data.get("experience", []):
            entry = dict(exp)
            entry["source"] = "resume"
            key = _exp_dedup_key(entry)
            if key not in seen_keys:
                seen_keys.add(key)
                experience.append(entry)

    # CSV current role — only add if it doesn't duplicate a resume entry.
    for r in csv_records:
        company = r.data.get("current_company")
        title = r.data.get("title")
        if company or title:
            csv_entry: dict[str, Any] = {
                "company": company,
                "title": title,
                "start": None,
                "end": None,
                "summary": None,
                "source": "recruiter_csv",
            }
            key = _exp_dedup_key(csv_entry)
            # Also check partial match: same company+title even if start differs.
            company_title_key = (
                (company or "").strip().lower(),
                (title or "").strip().lower(),
            )
            already_present = key in seen_keys or any(
                (e.get("company") or "").strip().lower() == company_title_key[0]
                and (e.get("title") or "").strip().lower() == company_title_key[1]
                for e in experience
            )
            if not already_present:
                seen_keys.add(key)
                experience.append(csv_entry)

    return experience


def _union_education(resume_records: list[SourceRecord]) -> list[dict[str, Any]]:
    education: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in resume_records:
        for edu in r.data.get("education", []):
            key = edu.get("institution", "").lower()
            if key and key not in seen:
                seen.add(key)
                education.append(edu)
    return education


def _merge_links(resume_records: list[SourceRecord]) -> dict[str, Any]:
    links: dict[str, Any] = {
        "linkedin": None,
        "github": None,
        "portfolio": None,
        "other": [],
    }
    for r in resume_records:
        rlinks = r.data.get("links", {})
        for key in ("linkedin", "github", "portfolio"):
            if not links[key] and rlinks.get(key):
                links[key] = rlinks[key]
        for other in rlinks.get("other", []):
            if other not in links["other"]:
                links["other"].append(other)
    return links
