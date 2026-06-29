"""Export canonical profiles to full card-view JSON (all fields, confidence, provenance)."""

from __future__ import annotations

from typing import Any

from pipeline.models.canonical import CanonicalProfile
from pipeline.models.schema import ensure_canonical_shape, ensure_card_confidence_keys


def profile_to_card_json(profile: CanonicalProfile) -> dict[str, Any]:
    """
    Serialize everything shown in the web UI card.
    Every canonical schema key is always present (null or [] when empty).
    """
    base = profile.to_dict()
    base["skills"] = [
        {
            "name": s.name,
            "confidence": s.confidence,
            "sources": list(s.sources),
            "method": s.method,
        }
        for s in profile.skills
    ]
    return ensure_card_confidence_keys(ensure_canonical_shape(base))
