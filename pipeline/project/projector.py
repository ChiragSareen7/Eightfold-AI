# =============================================================================
# FILE: pipeline/project/projector.py | STAGE: 6 — Projection
# DOES: Maps CanonicalProfile → config-shaped JSON (field select, rename, normalize, on_missing).
# IN:   CanonicalProfile + projection config JSON.
# NEXT → webapp/static/index.html (cards/JSON) | CLI stdout/file
# =============================================================================
"""Stage 6: Configurable output projection layer.

Clean separation: canonical record -> projected output per config.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pipeline.models.canonical import CanonicalProfile

DEFAULT_CONFIG_PATH = Path(__file__).parent / "default_config.json"


class ProjectionError(Exception):
    """Raised when on_missing='error' and a required field is absent."""


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def project(profile: CanonicalProfile, config: dict[str, Any]) -> dict[str, Any]:
    """Project canonical profile to configured output schema."""
    canonical_dict = profile.to_dict()
    output: dict[str, Any] = {}
    on_missing = config.get("on_missing", "null")
    include_confidence = config.get("include_confidence", True)
    include_provenance = config.get("include_provenance", True)
    field_specs = config.get("fields", [])
    projected_canonical_fields = {
        _canonical_field_for_confidence(spec.get("from", spec["path"]))
        for spec in field_specs
    }

    for field_spec in field_specs:
        path = field_spec["path"]
        from_path = field_spec.get("from", path)
        required = field_spec.get("required", False)
        field_type = field_spec.get("type", "string")
        normalize = field_spec.get("normalize")

        value = _resolve_path(canonical_dict, from_path)

        # Empty arrays are valid values — only None/"" mean "missing".
        if value is None or value == "":
            if required and on_missing == "error":
                raise ProjectionError(f"Required field missing: {path}")
            if on_missing == "omit":
                continue
            value = _null_for_type(field_type)
        else:
            value = _coerce_type(value, field_type)
            if normalize:
                value = _apply_normalize(normalize, field_type, value)

        output[path] = value

        if include_confidence:
            conf_key = f"{path}_confidence"
            canonical_key = _canonical_field_for_confidence(from_path)
            output[conf_key] = profile.field_confidence.get(canonical_key)

    if include_provenance:
        output["provenance"] = [
            {"field": p.field, "source": p.source, "method": p.method}
            for p in profile.provenance
        ]

    if include_confidence:
        reasoning = {
            k: v
            for k, v in profile.field_reasoning.items()
            if k in projected_canonical_fields or k in {spec["path"] for spec in field_specs}
        }
        output["field_reasoning"] = reasoning
        output["overall_confidence"] = profile.overall_confidence

    _validate_output(output, config)
    return output


def _canonical_field_for_confidence(from_path: str) -> str:
    """Map a config from-path to the canonical field_confidence key."""
    if "[]" in from_path:
        return from_path.split("[]", 1)[0].rstrip(".")
    bracket = from_path.find("[")
    if bracket != -1:
        return from_path[:bracket]
    return from_path


def _resolve_path(data: dict[str, Any], path: str) -> Any:
    """
    Resolve simple path notation:
      emails[0], skills[].name, full_name
    """
    if "[]" in path:
        base, rest = path.split("[]", 1)
        rest = rest.lstrip(".")
        arr = _resolve_path(data, base.rstrip("."))
        if not isinstance(arr, list):
            return None
        if not rest:
            return arr
        out = []
        for item in arr:
            if isinstance(item, dict):
                v = _resolve_path(item, rest)
                if v is not None and v != "":
                    out.append(v)
            elif item is not None and item != "":
                out.append(item)
        return out

    parts = re.split(r"\.|\[(\d+)\]", path)
    parts = [p for p in parts if p is not None and p != ""]
    current: Any = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if idx < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _coerce_type(value: Any, field_type: str) -> Any:
    if field_type == "string":
        return str(value) if value is not None else None
    if field_type == "number":
        return float(value) if value is not None else None
    if field_type == "string[]":
        if isinstance(value, list):
            return [str(v) for v in value]
        return [str(value)]
    if field_type == "object[]":
        if isinstance(value, list):
            return value
        return [value] if value is not None else []
    if field_type == "object":
        return value
    return value


def _null_for_type(field_type: str) -> Any:
    if field_type in ("string[]", "object[]"):
        return []
    if field_type == "object":
        return None
    return None


def _normalize_token(normalize: str) -> str:
    return normalize.replace(".", "").replace("-", "").upper()


def _apply_normalize(normalize: str, field_type: str, value: Any) -> Any:
    """Apply per-field normalization requested by projection config."""
    token = _normalize_token(normalize)
    if token == "E164" and field_type == "string" and value:
        from pipeline.normalize.phones import normalize_phone

        result = normalize_phone(str(value))
        return result.e164 or str(value)
    if token == "CANONICAL" and field_type == "string[]" and isinstance(value, list):
        from pipeline.normalize.skills import canonicalize_skill

        return [canonicalize_skill(str(v)).name for v in value]
    return value


def _validate_output(output: dict[str, Any], config: dict[str, Any]) -> None:
    """Validate projected output against requested field types."""
    on_missing = config.get("on_missing", "null")
    for field_spec in config.get("fields", []):
        path = field_spec["path"]
        if path not in output:
            if on_missing == "omit":
                continue
            if field_spec.get("required") and on_missing == "error":
                raise ProjectionError(f"Required field missing: {path}")
            continue
        value = output[path]
        field_type = field_spec.get("type", "string")
        if value is None:
            continue
        if field_type == "string" and not isinstance(value, str):
            raise ProjectionError(f"Field {path} expected string, got {type(value)}")
        if field_type == "number" and not isinstance(value, (int, float)):
            raise ProjectionError(f"Field {path} expected number, got {type(value)}")
        if field_type == "string[]" and not isinstance(value, list):
            raise ProjectionError(f"Field {path} expected string[], got {type(value)}")
        if field_type == "object[]" and not isinstance(value, list):
            raise ProjectionError(f"Field {path} expected object[], got {type(value)}")

# -----------------------------------------------------------------------------
# ROUTE OUT: dict — projected profile JSON (API/download shape)
# NEXT FILE → webapp/static/index.html | CLI -o output file
# -----------------------------------------------------------------------------
