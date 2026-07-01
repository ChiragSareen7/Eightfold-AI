# =============================================================================
# FILE: pipeline/merge/entity_resolution.py | STAGE: 4 — Entity resolution
# DOES: Links CSV rows to resumes; matches by email+phone or manifest validation.
# IN:   Normalized RawCsvRecord + ExtractedResumeFields as SourceRecord list.
# NEXT → pipeline/merge/merger.py (merge_group per EntityGroup)
# =============================================================================
"""Stage 4: Entity resolution — email + phone identity match."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from pipeline.logging_config import warn
from pipeline.models.raw import ExtractedResumeFields, RawCsvRecord
from pipeline.sources.text_quality import looks_like_person_name

# Both sources treated equally at merge time (tie-break favors resume over CSV).
DEFAULT_SOURCE_PRIORITY = ["resume", "recruiter_csv"]
YEARS_EXPERIENCE_DISAGREEMENT_THRESHOLD = 0.15  # 15%

NAME_MANIFEST_VALIDATION_THRESHOLD = 85
FILENAME_STEM_VALIDATION_THRESHOLD = 90


@dataclass
class SourceRecord:
    """Unified wrapper for records from any source before merge."""

    source_type: str
    source_id: str
    email: str | None = None
    phone: str | None = None
    name: str | None = None
    company: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class EntityGroup:
    """Records believed to belong to the same person."""

    records: list[SourceRecord] = field(default_factory=list)
    match_method: str = ""
    match_confidence: float = 1.0


def _normalize_email(email: str | None) -> str | None:
    return email.strip().lower() if email else None


def _normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    return re.sub(r"\D", "", phone)


def _candidate_id_from_email(email: str) -> str:
    normalized = _normalize_email(email) or ""
    return hashlib.sha256(normalized.encode()).hexdigest()


def csv_to_source_record(csv: RawCsvRecord) -> SourceRecord:
    return SourceRecord(
        source_type="recruiter_csv",
        source_id=csv.source_id,
        email=_normalize_email(csv.email),
        phone=_normalize_phone(csv.phone),
        name=csv.name,
        company=csv.current_company,
        data={
            "name": csv.name,
            "email": csv.email,
            "phone": csv.phone,
            "phone_method": getattr(csv, "phone_method", None),
            "current_company": csv.current_company,
            "title": csv.title,
            "years_experience": getattr(csv, "years_experience_value", None),
            "years_experience_method": getattr(csv, "years_experience_method", None),
            "experience_months": getattr(csv, "experience_months", None),
            "experience_description": getattr(csv, "experience_description", None),
            "skills": getattr(csv, "skills_normalized", []),
            "education": getattr(csv, "education_normalized", []),
            "resume_path": csv.resume_path,
            "row_number": csv.row_number,
        },
    )


def resume_to_source_record(extracted: ExtractedResumeFields) -> SourceRecord:
    primary_email = extracted.emails[0] if extracted.emails else None
    primary_phone = extracted.phones[0] if extracted.phones else None
    company = None
    if extracted.experience:
        company = extracted.experience[0].get("company")

    return SourceRecord(
        source_type="resume",
        source_id=extracted.source_id,
        email=_normalize_email(primary_email),
        phone=_normalize_phone(primary_phone),
        name=extracted.full_name,
        company=company,
        data={
            "full_name": extracted.full_name,
            "emails": extracted.emails,
            "phones": extracted.phones,
            "phones_normalized": getattr(extracted, "phones_normalized", []),
            "phones_raw": getattr(extracted, "phones_raw", []),
            "phones_raw_meta": getattr(extracted, "phones_raw_meta", []),
            "location": extracted.location,
            "links": extracted.links,
            "headline": extracted.headline,
            "years_experience": extracted.years_experience,
            "years_experience_method": extracted.years_experience_method,
            "skills": extracted.skills,
            "experience": extracted.experience,
            "education": extracted.education,
            "field_methods": extracted.field_methods,
            "file_path": extracted.file_path,
        },
    )


def _identity_key(rec: SourceRecord) -> tuple[str, str] | None:
    """Both email and normalized phone must be present to participate in matching."""
    if rec.email and rec.phone:
        return (rec.email, rec.phone)
    return None


def _manifest_filename(rec: SourceRecord) -> str | None:
    if rec.source_type != "recruiter_csv":
        return None
    resume_path = rec.data.get("resume_path")
    return Path(resume_path).name if resume_path else None


def _resume_filename(rec: SourceRecord) -> str | None:
    if rec.source_type != "resume":
        return None
    file_path = rec.data.get("file_path")
    return Path(file_path).name if file_path else None


def _filename_stem(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").replace("-", " ")


def _manifest_validates(csv_rec: SourceRecord, resume_rec: SourceRecord) -> bool:
    """
    CSV resume_path must point at this resume file, plus at least one identity check:
    matching email, matching phone, fuzzy name agreement, or filename stem matching
    both CSV name and resume name (recruiter named the file after the candidate).
    """
    manifest_fn = _manifest_filename(csv_rec)
    resume_fn = _resume_filename(resume_rec)
    if not manifest_fn or manifest_fn != resume_fn:
        return False

    email_ok = bool(
        csv_rec.email and resume_rec.email and csv_rec.email == resume_rec.email
    )
    phone_ok = bool(
        csv_rec.phone and resume_rec.phone and csv_rec.phone == resume_rec.phone
    )
    if email_ok or phone_ok:
        return True

    name_ok = False
    if csv_rec.name and resume_rec.name:
        name_ok = (
            fuzz.ratio(csv_rec.name.lower(), resume_rec.name.lower())
            >= NAME_MANIFEST_VALIDATION_THRESHOLD
        )
    if name_ok:
        return True

    stem = _filename_stem(manifest_fn).lower()
    stem_matches_csv = False
    stem_matches_resume = False
    if csv_rec.name:
        stem_matches_csv = (
            fuzz.partial_ratio(csv_rec.name.lower(), stem) >= FILENAME_STEM_VALIDATION_THRESHOLD
        )
    if resume_rec.name:
        stem_matches_resume = (
            fuzz.partial_ratio(resume_rec.name.lower(), stem)
            >= FILENAME_STEM_VALIDATION_THRESHOLD
        )
    return stem_matches_csv and stem_matches_resume


def resolve_entities(records: list[SourceRecord]) -> list[EntityGroup]:
    """
    Merge when:
    1. Normalized email AND phone both match, or
    2. CSV resume_path names a resume file AND manifest validation approves the pair.

    Email-only, phone-only, or name+company similarity never merge by themselves.
    """
    groups: list[EntityGroup] = []
    assigned: set[int] = set()

    identity_index: dict[tuple[str, str], list[int]] = {}
    for i, rec in enumerate(records):
        key = _identity_key(rec)
        if key:
            identity_index.setdefault(key, []).append(i)

    for indices in identity_index.values():
        if len(indices) < 2:
            continue
        group = EntityGroup(
            records=[records[i] for i in indices],
            match_method="exact_email_and_phone",
            match_confidence=0.97,
        )
        groups.append(group)
        assigned.update(indices)

    for i, csv_rec in enumerate(records):
        if i in assigned or csv_rec.source_type != "recruiter_csv":
            continue
        manifest_fn = _manifest_filename(csv_rec)
        if not manifest_fn:
            continue
        for j, resume_rec in enumerate(records):
            if j in assigned or resume_rec.source_type != "resume":
                continue
            if _resume_filename(resume_rec) != manifest_fn:
                continue
            if not _manifest_validates(csv_rec, resume_rec):
                warn(
                    f"Manifest resume '{manifest_fn}' for CSV row "
                    f"{csv_rec.data.get('row_number')} failed identity validation — not merged"
                )
                continue
            groups.append(EntityGroup(
                records=[csv_rec, resume_rec],
                match_method="manifest_resume_link",
                match_confidence=0.88,
            ))
            assigned.update({i, j})
            break

    for i in range(len(records)):
        if i not in assigned:
            groups.append(EntityGroup(
                records=[records[i]],
                match_method="singleton",
                match_confidence=1.0,
            ))

    return groups


def resume_has_usable_identity(extracted: ExtractedResumeFields) -> bool:
    """Skip resume source records with nothing reliable to match or display."""
    if extracted.emails:
        return True
    if extracted.phones:
        return True
    if looks_like_person_name(extracted.full_name):
        return True
    return False


def link_csv_resumes_by_manifest(
    csv_records: list[RawCsvRecord],
    resume_records: dict[str, ExtractedResumeFields],
    resumes_base_dir: str | None = None,
) -> list[SourceRecord]:
    """
    Build source records from CSV rows and linked resumes via resume_path column.
    Also includes unlinked resumes as standalone records for batch cascade matching.
    """
    from pathlib import Path

    all_records: list[SourceRecord] = []
    linked_filenames: set[str] = set()

    for csv in csv_records:
        rec = csv_to_source_record(csv)
        if csv.resume_path:
            filename = Path(csv.resume_path).name
            linked_filenames.add(filename)
            resume_key = str(Path(resumes_base_dir) / filename) if resumes_base_dir else filename
            matched = resume_records.get(resume_key) or resume_records.get(filename)
            if matched and resume_has_usable_identity(matched):
                all_records.append(resume_to_source_record(matched))
            elif matched:
                warn(
                    f"Resume linked in CSV row {csv.row_number} has no usable identity "
                    f"(empty or corrupted): {filename}"
                )
                rec.data["manifest_resume_unreadable"] = filename
            else:
                warn(f"Resume path in CSV not found or unreadable: {resume_key}")
                rec.data["manifest_resume_missing"] = filename
        all_records.append(rec)

    seen_filenames: set[str] = set()
    for path, extracted in sorted(resume_records.items()):
        filename = Path(path).name
        if filename in seen_filenames:
            continue
        seen_filenames.add(filename)
        if filename in linked_filenames:
            continue
        if not resume_has_usable_identity(extracted):
            warn(f"Skipping resume with no usable identity: {filename}")
            continue
        all_records.append(resume_to_source_record(extracted))

    return all_records

# -----------------------------------------------------------------------------
# ROUTE OUT: list[EntityGroup] with match_method (exact_email_and_phone | manifest_resume_link | singleton)
# NEXT FILE → pipeline/merge/merger.py (merge_group)
# -----------------------------------------------------------------------------
