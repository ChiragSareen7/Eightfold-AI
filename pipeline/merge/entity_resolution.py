"""Stage 4: Entity resolution — match-key cascade."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from pipeline.logging_config import warn
from pipeline.models.raw import ExtractedResumeFields, RawCsvRecord

# Weakest tier: BOTH name and company must exceed thresholds — never one alone.
NAME_FUZZY_THRESHOLD = 90
COMPANY_FUZZY_THRESHOLD = 85

DEFAULT_SOURCE_PRIORITY = ["recruiter_csv", "resume"]
YEARS_EXPERIENCE_DISAGREEMENT_THRESHOLD = 0.20  # 20%


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
            "current_company": csv.current_company,
            "title": csv.title,
            "years_experience": getattr(csv, "years_experience_value", None),
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


def resolve_entities(records: list[SourceRecord]) -> list[EntityGroup]:
    """
    Match-key cascade:
    1. Exact email match
    2. Exact normalized phone match
    3. Fuzzy name + company (both must pass thresholds)
    """
    groups: list[EntityGroup] = []
    assigned: set[int] = set()

    # Pass 1: email
    email_index: dict[str, list[int]] = {}
    for i, rec in enumerate(records):
        if rec.email:
            email_index.setdefault(rec.email, []).append(i)

    for indices in email_index.values():
        if len(indices) < 2:
            continue
        group = EntityGroup(records=[records[i] for i in indices], match_method="exact_email", match_confidence=0.98)
        groups.append(group)
        assigned.update(indices)

    # Pass 2: phone (unassigned only)
    phone_index: dict[str, list[int]] = {}
    for i, rec in enumerate(records):
        if i in assigned or not rec.phone:
            continue
        phone_index.setdefault(rec.phone, []).append(i)

    for indices in phone_index.values():
        if len(indices) < 2:
            continue
        group = EntityGroup(
            records=[records[i] for i in indices],
            match_method="exact_phone",
            match_confidence=0.92,
        )
        groups.append(group)
        assigned.update(indices)

    # Pass 3: fuzzy name + company (unassigned only)
    remaining = [i for i in range(len(records)) if i not in assigned]
    used_in_fuzzy: set[int] = set()
    for i in remaining:
        if i in used_in_fuzzy:
            continue
        rec_a = records[i]
        if not rec_a.name or not rec_a.company:
            continue
        cluster = [i]
        for j in remaining:
            if j <= i or j in used_in_fuzzy:
                continue
            rec_b = records[j]
            if not rec_b.name or not rec_b.company:
                continue
            name_score = fuzz.ratio(rec_a.name.lower(), rec_b.name.lower())
            company_score = fuzz.ratio(rec_a.company.lower(), rec_b.company.lower())
            if name_score >= NAME_FUZZY_THRESHOLD and company_score >= COMPANY_FUZZY_THRESHOLD:
                cluster.append(j)
        if len(cluster) > 1:
            group = EntityGroup(
                records=[records[k] for k in cluster],
                match_method="fuzzy_name_company",
                match_confidence=0.65,
            )
            groups.append(group)
            used_in_fuzzy.update(cluster)
            assigned.update(cluster)

    # Singletons: each unassigned record is its own group
    for i in range(len(records)):
        if i not in assigned:
            groups.append(EntityGroup(
                records=[records[i]],
                match_method="singleton",
                match_confidence=1.0,
            ))

    return groups


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
    linked_resume_paths: set[str] = set()

    for csv in csv_records:
        all_records.append(csv_to_source_record(csv))
        if csv.resume_path:
            # Always resolve using only the filename — uploaded resumes are stored
            # flat (no subdirectories). This handles CSV files where resume_path
            # contains a folder prefix like "resumes/foo.txt" or "data/foo.txt".
            filename = Path(csv.resume_path).name
            resume_key = str(Path(resumes_base_dir) / filename) if resumes_base_dir else filename
            linked_resume_paths.add(resume_key)
            # Also check by bare filename in case resume_records was keyed without dir
            matched = resume_records.get(resume_key) or resume_records.get(filename)
            if matched:
                all_records.append(resume_to_source_record(matched))
            else:
                warn(f"Resume path in CSV not found or unreadable: {resume_key}")

    for path, extracted in sorted(resume_records.items()):
        if path not in linked_resume_paths:
            all_records.append(resume_to_source_record(extracted))

    return all_records
