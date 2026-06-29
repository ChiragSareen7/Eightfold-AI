"""Fixed canonical profile schema — every profile has the same keys."""

from __future__ import annotations

from typing import Any

# Default empty values for every canonical field (assignment schema + internal extras).
CANONICAL_FIELD_DEFAULTS: dict[str, Any] = {
    "candidate_id": "",
    "full_name": None,
    "emails": [],
    "phones": [],
    "phones_raw": [],
    "location": None,
    "links": {
        "linkedin": None,
        "github": None,
        "portfolio": None,
        "other": [],
    },
    "headline": None,
    "years_experience": None,
    "skills": [],
    "experience": [],
    "education": [],
    "provenance": [],
    "field_confidence": {},
    "overall_confidence": 0.0,
}

# Fields that are always lists when empty (never null, never omitted).
CANONICAL_ARRAY_FIELDS = frozenset({
    "emails",
    "phones",
    "phones_raw",
    "skills",
    "experience",
    "education",
    "provenance",
})

# Per-field confidence keys emitted in full card / default projection output.
CANONICAL_CONFIDENCE_FIELDS = frozenset({
    "full_name",
    "emails",
    "phones",
    "phones_raw",
    "location",
    "links",
    "headline",
    "years_experience",
    "skills",
    "experience",
    "education",
})


def empty_links() -> dict[str, Any]:
    return {
        "linkedin": None,
        "github": None,
        "portfolio": None,
        "other": [],
    }


def ensure_canonical_shape(data: dict[str, Any]) -> dict[str, Any]:
    """
    Merge partial profile dict onto the full canonical schema.
    Missing keys get explicit null or [] — never omitted.
    """
    out: dict[str, Any] = {}
    for key, default in CANONICAL_FIELD_DEFAULTS.items():
        if key not in data or data[key] is None:
            if key in CANONICAL_ARRAY_FIELDS:
                out[key] = list(default) if isinstance(default, list) else default
            elif key == "links":
                out[key] = empty_links()
            elif key == "field_confidence":
                out[key] = dict(data.get("field_confidence") or {})
            else:
                out[key] = default
        else:
            out[key] = data[key]

    # Preserve candidate_id from input even if empty string default.
    if data.get("candidate_id"):
        out["candidate_id"] = data["candidate_id"]

    return out


def ensure_card_confidence_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Add flat {field}_confidence keys for every canonical field (null if unscored)."""
    fc = data.get("field_confidence") or {}
    for field in sorted(CANONICAL_CONFIDENCE_FIELDS):
        key = f"{field}_confidence"
        if key not in data:
            data[key] = fc.get(field)
    return data
