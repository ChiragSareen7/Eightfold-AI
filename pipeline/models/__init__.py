# =============================================================================
# FILE: pipeline/models/__init__.py
# DOES: Re-exports core dataclasses (Raw*, CanonicalProfile, ProvenanceEntry).
# IN:   Imported by pipeline stages.
# NEXT → pipeline/models/raw.py | pipeline/models/canonical.py
# =============================================================================
from pipeline.models.canonical import CanonicalProfile, FieldMeta, ProvenanceEntry
from pipeline.models.raw import RawCsvRecord, RawResumeRecord

__all__ = [
    "CanonicalProfile",
    "FieldMeta",
    "ProvenanceEntry",
    "RawCsvRecord",
    "RawResumeRecord",
]

# -----------------------------------------------------------------------------
# ROUTE OUT: public model types for import
# NEXT FILE → all pipeline stages use RawCsvRecord, ExtractedResumeFields, CanonicalProfile
# -----------------------------------------------------------------------------
