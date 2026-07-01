# =============================================================================
# FILE: pipeline/sources/text_quality.py
# DOES: Detects binary/garbage resume text and validates person-name shape.
# IN:   raw_text strings from resume_reader / extractor.
# NEXT → pipeline/sources/resume_reader.py, extract/resume_extractor.py, merge/entity_resolution.py
# =============================================================================
"""Text/binary detection helpers for resume ingestion."""

from __future__ import annotations


def is_probably_binary_text(text: str) -> bool:
    """True when content is unlikely to be a human-readable resume."""
    if not text:
        return False
    sample = text[:800]
    if not sample:
        return False

    control = sum(1 for c in sample if ord(c) < 32 and c not in "\n\r\t")
    if control / len(sample) > 0.04:
        return True

    non_printable = sum(1 for c in sample if not c.isprintable() and c not in "\n\r\t")
    return non_printable / len(sample) > 0.12


def looks_like_person_name(value: str | None) -> bool:
    """Reject binary garbage or header lines masquerading as names."""
    if not value:
        return False
    name = value.strip()
    if len(name) < 2 or len(name) > 60:
        return False
    letters = sum(1 for c in name if c.isalpha())
    if letters < 2:
        return False
    allowed = sum(1 for c in name if c.isalpha() or c.isspace() or c in ".-'")
    return allowed / len(name) >= 0.85

# -----------------------------------------------------------------------------
# ROUTE OUT: boolean guards (is_probably_binary_text, looks_like_person_name)
# NEXT FILE → resume_reader.py (skip corrupt) | resume_extractor.py | entity_resolution.py
# -----------------------------------------------------------------------------
