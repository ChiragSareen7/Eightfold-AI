# =============================================================================
# FILE: pipeline/normalize/countries.py | STAGE: 3 — Normalize (location)
# DOES: Maps country names/aliases to ISO-3166 alpha-2 codes.
# IN:   Country string from resume location.
# NEXT → pipeline/normalize/__init__.py (normalize_extracted_resume)
# =============================================================================
"""Country normalization to ISO-3166 alpha-2 via static lookup."""

from __future__ import annotations

# Static lookup — no API calls. Covers common country names/aliases.
COUNTRY_LOOKUP: dict[str, str] = {
    "us": "US",
    "usa": "US",
    "united states": "US",
    "united states of america": "US",
    "uk": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "england": "GB",
    "india": "IN",
    "in": "IN",
    "canada": "CA",
    "ca": "CA",
    "australia": "AU",
    "au": "AU",
    "germany": "DE",
    "de": "DE",
    "france": "FR",
    "fr": "FR",
    "japan": "JP",
    "jp": "JP",
    "china": "CN",
    "cn": "CN",
    "singapore": "SG",
    "sg": "SG",
}


def normalize_country(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    if len(key) == 2 and key.upper() in set(COUNTRY_LOOKUP.values()):
        return key.upper()
    return COUNTRY_LOOKUP.get(key)

# -----------------------------------------------------------------------------
# ROUTE OUT: ISO alpha-2 code or None
# NEXT FILE → pipeline/normalize/__init__.py → CanonicalProfile.location
# -----------------------------------------------------------------------------
