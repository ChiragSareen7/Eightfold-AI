# =============================================================================
# FILE: pipeline/sources/__init__.py
# DOES: Registry of source reader callables (csv, resume; github stub planned).
# IN:   source_type string.
# NEXT → pipeline/sources/csv_reader.py | pipeline/sources/resume_reader.py
# =============================================================================
"""Source reader registry — add new source types here without touching core pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    pass

# Registry pattern: new sources (e.g. GitHub) register a reader callable here.
# See sources/github.py for the future extension point.
SOURCE_READERS: dict[str, str] = {
    "csv": "pipeline.sources.csv_reader.read_csv",
    "resume": "pipeline.sources.resume_reader.read_resume",
    # "github": "pipeline.sources.github.read_github_profile",  # future
}


def get_reader(source_type: str) -> Callable:
    if source_type not in SOURCE_READERS:
        raise ValueError(f"Unknown source type: {source_type}")
    module_path = SOURCE_READERS[source_type]
    module_name, func_name = module_path.rsplit(".", 1)
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, func_name)

# -----------------------------------------------------------------------------
# ROUTE OUT: reader callable for a source type
# NEXT FILE → pipeline/sources/csv_reader.py | pipeline/sources/resume_reader.py
# -----------------------------------------------------------------------------
