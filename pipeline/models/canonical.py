# =============================================================================
# FILE: pipeline/models/canonical.py | STAGE: 4–6 internal truth
# DOES: CanonicalProfile dataclass — full merged candidate before projection.
# IN:   merge/merger.py; enriched by confidence/scoring.py.
# NEXT → pipeline/project/projector.py | CanonicalProfile.to_dict() for API cache
# =============================================================================
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
    best_match: str | None = None
    best_score: float | None = None


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
    field_reasoning: dict[str, str] = field(default_factory=dict)
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    overall_confidence: float = 0.0
    # csv_only | resume_only | merged — which sources built this profile
    source_profile_kind: str = "merged"
    source_notice: str | None = None

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
                    **(
                        {"best_match": s.best_match, "best_score": s.best_score}
                        if s.best_match is not None
                        else {}
                    ),
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
            "field_reasoning": dict(self.field_reasoning),
            "overall_confidence": self.overall_confidence,
            "source_profile_kind": self.source_profile_kind,
            "source_notice": self.source_notice,
        }
        return ensure_canonical_shape(raw)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonicalProfile:
        """Rebuild a canonical profile from to_dict() output (for re-projection)."""
        shaped = ensure_canonical_shape(dict(data))
        skills = [
            CanonicalSkill(
                name=s["name"],
                confidence=float(s.get("confidence", 0.0)),
                sources=list(s.get("sources") or []),
                method=s.get("method") or "",
                best_match=s.get("best_match"),
                best_score=s.get("best_score"),
            )
            for s in shaped.get("skills") or []
            if isinstance(s, dict) and s.get("name")
        ]
        provenance = [
            ProvenanceEntry(
                field=p["field"],
                source=p["source"],
                method=p["method"],
                notes=p.get("notes"),
                candidate_values=p.get("candidate_values"),
            )
            for p in shaped.get("provenance") or []
            if isinstance(p, dict) and p.get("field")
        ]
        return cls(
            candidate_id=shaped["candidate_id"],
            full_name=shaped.get("full_name"),
            emails=list(shaped.get("emails") or []),
            phones=list(shaped.get("phones") or []),
            phones_raw=list(shaped.get("phones_raw") or []),
            location=shaped.get("location"),
            links=dict(shaped.get("links") or empty_links()),
            headline=shaped.get("headline"),
            years_experience=shaped.get("years_experience"),
            skills=skills,
            experience=list(shaped.get("experience") or []),
            education=list(shaped.get("education") or []),
            provenance=provenance,
            field_confidence=dict(shaped.get("field_confidence") or {}),
            field_reasoning=dict(shaped.get("field_reasoning") or {}),
            overall_confidence=float(shaped.get("overall_confidence") or 0.0),
            source_profile_kind=shaped.get("source_profile_kind") or "merged",
            source_notice=shaped.get("source_notice"),
        )

# -----------------------------------------------------------------------------
# ROUTE OUT: CanonicalProfile (to_dict / from_dict for reproject)
# NEXT FILE → pipeline/confidence/scoring.py → pipeline/project/projector.py
# -----------------------------------------------------------------------------
