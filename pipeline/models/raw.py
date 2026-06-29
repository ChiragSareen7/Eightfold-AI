"""Plain internal records produced by source readers (Stage 1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawCsvRecord:
    """One row from the recruiter CSV export."""

    source_id: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    current_company: str | None = None
    title: str | None = None
    years_experience: str | None = None
    resume_path: str | None = None
    row_number: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class RawResumeRecord:
    """Raw text extracted from a resume file — no field parsing yet."""

    source_id: str
    file_path: str
    raw_text: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExtractedResumeFields:
    """Structured fields parsed from resume text (Stage 2 output)."""

    source_id: str
    file_path: str
    full_name: str | None = None
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    location: dict[str, str | None] | None = None
    links: dict[str, Any] = field(default_factory=dict)
    headline: str | None = None
    years_experience: float | None = None
    years_experience_method: str | None = None
    skills: list[str] = field(default_factory=list)
    experience: list[dict[str, Any]] = field(default_factory=list)
    education: list[dict[str, Any]] = field(default_factory=list)
    field_methods: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
