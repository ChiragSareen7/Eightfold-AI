"""Phone normalization to E.164 — no country guessing."""

from __future__ import annotations

from dataclasses import dataclass

import phonenumbers


@dataclass
class PhoneResult:
    e164: str | None
    raw: str
    confidence: float
    method: str


def normalize_phone(raw: str, default_region: str | None = None) -> PhoneResult:
    """
    Parse phone to E.164 if a country code is present or unambiguous.

    Policy: no default country guess. If we cannot confidently parse,
    keep raw value and assign low confidence — wrong-but-confident is worse
    than honestly-empty (or honestly-raw).
    """
    cleaned = raw.strip()
    if not cleaned:
        return PhoneResult(e164=None, raw=raw, confidence=0.0, method="empty")

    # Only parse without region if number starts with +
    region = default_region  # intentionally None by default

    try:
        if cleaned.startswith("+"):
            parsed = phonenumbers.parse(cleaned, None)
        elif region:
            parsed = phonenumbers.parse(cleaned, region)
        else:
            # No + and no region — do not guess country
            return PhoneResult(
                e164=None,
                raw=cleaned,
                confidence=0.3,
                method="unnormalized_no_country_code",
            )

        if not phonenumbers.is_valid_number(parsed):
            return PhoneResult(
                e164=None,
                raw=cleaned,
                confidence=0.3,
                method="unnormalized_invalid",
            )

        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        return PhoneResult(e164=e164, raw=cleaned, confidence=0.95, method="E164")

    except phonenumbers.NumberParseException:
        return PhoneResult(
            e164=None,
            raw=cleaned,
            confidence=0.3,
            method="unnormalized_parse_error",
        )
