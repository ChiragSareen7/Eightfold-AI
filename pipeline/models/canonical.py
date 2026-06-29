"""Internal canonical profile model — separate from projected output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.models.schema import empty_links, ensure_canonical_shape


@dataclass
class ProvenanceEntry:
    """Matches assignment schema: { field, source, method }."""

    field: str
    source: str
    method: str
    notes: str | None = None
    candidate_values: list[dict[str, Any]] | None = None


@dataclass
class FieldMeta:
    """Per-field confidence and extraction metadata."""

    confidence: float
    sources: list[str] = field(default_factory=list)
    method: str = ""


@dataclass
class CanonicalSkill:
    name: str
    confidence: float
    sources: list[str] = field(default_factory=list)
    method: str = ""


@dataclass
class CanonicalProfile:
    """Full internal canonical record before projection."""

    candidate_id: str
    full_name: str | None = None
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    phones_raw: list[str] = field(default_factory=list)
    location: dict[str, str | None] | None = None
    links: dict[str, Any] = field(default_factory=empty_links)
    headline: str | None = None
    years_experience: float | None = None
    skills: list[CanonicalSkill] = field(default_factory=list)
    experience: list[dict[str, Any]] = field(default_factory=list)
    education: list[dict[str, Any]] = field(default_factory=list)
    provenance: list[ProvenanceEntry] = field(default_factory=list)
    field_confidence: dict[str, float] = field(default_factory=dict)
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    overall_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize canonical record; always includes every schema key."""
        raw = {
            "candidate_id": self.candidate_id,
            "full_name": self.full_name,
            "emails": list(self.emails),
            "phones": list(self.phones),
            "phones_raw": list(self.phones_raw),
            "location": self.location,
            "links": dict(self.links) if self.links else empty_links(),
            "headline": self.headline,
            "years_experience": self.years_experience,
            "skills": [
                {
                    "name": s.name,
                    "confidence": s.confidence,
                    "sources": list(s.sources),
                    "method": s.method,
                }
                for s in self.skills
            ],
            "experience": list(self.experience),
            "education": list(self.education),
            "provenance": [
                {
                    "field": p.field,
                    "source": p.source,
                    "method": p.method,
                    **({"notes": p.notes} if p.notes else {}),
                    **(
                        {"candidate_values": p.candidate_values}
                        if p.candidate_values
                        else {}
                    ),
                }
                for p in self.provenance
            ],
            "field_confidence": dict(self.field_confidence),
            "overall_confidence": self.overall_confidence,
        }
        return ensure_canonical_shape(raw)
