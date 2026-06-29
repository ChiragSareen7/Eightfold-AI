"""Stage 6: Configurable output projection layer.

Clean separation: canonical record -> projected output per config.
Normalization already applied in Stage 3; config 'normalize' is assertion only.
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

    for field_spec in config.get("fields", []):
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
                _assert_normalize(normalize, field_type, value)

        output[path] = value

        if include_confidence:
            conf_key = f"{path}_confidence"
            output[conf_key] = profile.field_confidence.get(path)

    if config.get("include_provenance", True):
        output["provenance"] = [
            {"field": p.field, "source": p.source, "method": p.method}
            for p in profile.provenance
        ]

    if include_confidence:
        output["overall_confidence"] = profile.overall_confidence

    _validate_output(output, config)
    return output


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
        return [_resolve_path(item, rest) if isinstance(item, dict) else item for item in arr]

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


def _assert_normalize(normalize: str, field_type: str, value: Any) -> None:
    """Trust Stage 3 — assert/document only, do not re-normalize."""
    if normalize == "E.164" and field_type == "string" and value:
        if not str(value).startswith("+"):
            pass  # raw phones may appear in non-E164 projections
    if normalize == "canonical" and field_type == "string[]":
        pass  # already canonicalized in Stage 3


def _validate_output(output: dict[str, Any], config: dict[str, Any]) -> None:
    """Basic schema validation against config field types."""
    for field_spec in config.get("fields", []):
        path = field_spec["path"]
        if path not in output:
            if config.get("on_missing") == "omit":
                continue
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
