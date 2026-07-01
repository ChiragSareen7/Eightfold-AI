"""Recruiter CSV export reader (Stage 1 — structured source)."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from pipeline.logging_config import warn
from pipeline.models.raw import RawCsvRecord

# Case-insensitive alias map: header -> internal field name.
# Real recruiter exports use inconsistent column names; tolerate common variants.
COLUMN_ALIASES: dict[str, str] = {
    "name": "name",
    "full_name": "name",
    "fullname": "name",
    "full name": "name",
    "candidate_name": "name",
    "email": "email",
    "email_address": "email",
    "e-mail": "email",
    "phone": "phone",
    "phone_number": "phone",
    "mobile": "phone",
    "telephone": "phone",
    "current_company": "current_company",
    "company": "current_company",
    "employer": "current_company",
    "current employer": "current_company",
    "title": "title",
    "job_title": "title",
    "current_title": "title",
    "position": "title",
    "years_experience": "years_experience",
    "years of experience": "years_experience",
    "experience_years": "years_experience",
    "yoe": "years_experience",
    "experience_months": "experience_months",
    "experience months": "experience_months",
    "months_experience": "experience_months",
    "experience_description": "experience_description",
    "experience description": "experience_description",
    "role_description": "experience_description",
    "job_description": "experience_description",
    "skills": "skills",
    "skill": "skills",
    "technical skills": "skills",
    "education": "education",
    "degree": "education",
    "qualification": "education",
    "company_name": "current_company",
    "resume_path": "resume_path",
    "resume": "resume_path",
    "resume_file": "resume_path",
}


def _normalize_header(header: str) -> str:
    return re.sub(r"\s+", " ", header.strip().lower())


def _map_headers(fieldnames: list[str] | None) -> dict[str, str]:
    """Map CSV headers to internal field names."""
    mapping: dict[str, str] = {}
    if not fieldnames:
        return mapping
    for header in fieldnames:
        normalized = _normalize_header(header)
        if normalized in COLUMN_ALIASES:
            mapping[header] = COLUMN_ALIASES[normalized]
    return mapping


def _clean_cell(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _is_effectively_empty_row(record: RawCsvRecord) -> bool:
    """Skip wholly blank CSV rows that carry no candidate identity."""
    return not any(
        [
            record.name,
            record.email,
            record.phone,
            record.current_company,
            record.title,
            record.resume_path,
            record.years_experience,
            record.skills,
            record.education,
        ]
    )


def read_csv(csv_path: str | Path) -> list[RawCsvRecord]:
    """
    Read recruiter CSV into plain internal records.

    Handles missing columns, empty cells, and malformed rows without crashing.
    Logs warnings and continues for bad rows.
    """
    path = Path(csv_path)
    if not path.exists():
        warn(f"CSV file not found: {path}")
        return []

    records: list[RawCsvRecord] = []

    try:
        # utf-8-sig handles BOM transparently.
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header_map = _map_headers(reader.fieldnames)

            if not header_map:
                warn(f"CSV has no recognizable columns: {path}")
                return []

            for row_num, row in enumerate(reader, start=2):
                try:
                    record = _parse_row(row, header_map, row_num)
                    if _is_effectively_empty_row(record):
                        warn(f"CSV row {row_num} skipped: empty row (no name, email, phone, or resume link)")
                        continue
                    records.append(record)
                except Exception as exc:
                    warn(f"CSV row {row_num} skipped: {exc}")
                    continue
    except Exception as exc:
        warn(f"Failed to read CSV {path}: {exc}")
        return []

    return records


def _parse_row(
    row: dict[str, str | None],
    header_map: dict[str, str],
    row_num: int,
) -> RawCsvRecord:
    data: dict[str, str | None] = {}
    warnings: list[str] = []

    for csv_header, internal_field in header_map.items():
        data[internal_field] = _clean_cell(row.get(csv_header))

    email = data.get("email")
    if not email:
        warnings.append(f"Row {row_num}: missing email — record kept but match key weakened")

    source_id = f"csv_row_{row_num}"
    if email:
        source_id = f"csv_{email.lower()}"

    return RawCsvRecord(
        source_id=source_id,
        name=data.get("name"),
        email=email,
        phone=data.get("phone"),
        current_company=data.get("current_company"),
        title=data.get("title"),
        years_experience=data.get("years_experience"),
        experience_months=data.get("experience_months"),
        experience_description=data.get("experience_description"),
        skills=data.get("skills"),
        education=data.get("education"),
        resume_path=data.get("resume_path"),
        row_number=row_num,
        warnings=warnings,
    )
