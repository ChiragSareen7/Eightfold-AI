# =============================================================================
# FILE: pipeline/normalize/dates.py | STAGE: 3 — Normalize (dates)
# DOES: Normalizes job start/end dates to YYYY-MM; handles Present as ongoing.
# IN:   Raw date strings from resume experience blocks.
# NEXT → pipeline/normalize/__init__.py (normalize_extracted_resume)
# =============================================================================
"""Date normalization to YYYY-MM."""

from __future__ import annotations

import re

MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def normalize_date(raw: str | None) -> str | None:
    """
    Normalize start dates to YYYY-MM.
    Handles: Jan 2020, 01/2020, 2020, full dates.
    """
    if not raw:
        return None
    raw = raw.strip()

    m = re.match(r"([A-Za-z]+)\.?\s+(\d{4})", raw)
    if m:
        month = MONTH_MAP.get(m.group(1).lower()[:3])
        if month:
            return f"{m.group(2)}-{month}"

    m = re.match(r"(\d{1,2})/(\d{4})", raw)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"

    m = re.match(r"^(\d{4})$", raw)
    if m:
        return f"{m.group(1)}-01"

    m = re.match(r"(\d{4})-(\d{2})", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    return None


def normalize_end_date(raw: str | None) -> str | None:
    """
    Normalize end dates. 'Present'/'Current' → null with is_current marker
    handled by caller — not treated as missing data.
    """
    if not raw:
        return None
    if re.match(r"present|current|now", raw.strip(), re.IGNORECASE):
        return None  # ongoing role — caller sets is_current=True
    return normalize_date(raw)

# -----------------------------------------------------------------------------
# ROUTE OUT: YYYY-MM strings or None for Present
# NEXT FILE → pipeline/normalize/__init__.py → merge/merger.py (experience[])
# -----------------------------------------------------------------------------
