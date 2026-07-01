# =============================================================================
# FILE: pipeline/pipeline.py | STAGE: Orchestrator (coordinates stages 1→6)
# DOES: build_canonical_profiles() runs ingest→merge→score; project_profiles() reshapes output.
# IN:   csv_path, resumes_dir, optional config and source_priority.
# NEXT → Called by cli.py and webapp/server.py; delegates to each stage module below.
# =============================================================================
"""End-to-end pipeline orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.confidence.scoring import score_profile
from pipeline.extract.resume_extractor import extract_fields
from pipeline.merge.entity_resolution import link_csv_resumes_by_manifest, resolve_entities
from pipeline.merge.merger import merge_group
from pipeline.merge.source_annotation import apply_source_notices, profile_card_meta
from pipeline.models.canonical import CanonicalProfile
from pipeline.models.raw import ExtractedResumeFields
from pipeline.normalize import normalize_csv_record, normalize_extracted_resume
from pipeline.project.projector import load_config, project
from pipeline.sources.csv_reader import read_csv
from pipeline.sources.resume_reader import read_resume, read_resumes_from_directory


def build_canonical_profiles(
    csv_path: str | Path,
    resumes_dir: str | Path,
    source_priority: list[str] | None = None,
) -> list[CanonicalProfile]:
    """Run pipeline through merge + confidence; return canonical profiles (pre-projection)."""
    csv_records = read_csv(csv_path)
    for rec in csv_records:
        normalize_csv_record(rec)

    resume_dir = Path(resumes_dir)
    resume_files = read_resumes_from_directory(resume_dir)

    manifest_paths: set[str] = set()
    for csv in csv_records:
        if csv.resume_path:
            filename = Path(csv.resume_path).name
            manifest_paths.add(str(resume_dir / filename))

    resume_records: dict[str, ExtractedResumeFields] = {}
    for raw in resume_files:
        extracted = extract_fields(raw)
        normalize_extracted_resume(extracted)
        resume_records[raw.file_path] = extracted
        resume_records[str(Path(raw.file_path).name)] = extracted

    for mp in sorted(manifest_paths):
        if mp not in resume_records:
            raw = read_resume(mp)
            if raw:
                extracted = extract_fields(raw)
                normalize_extracted_resume(extracted)
                resume_records[mp] = extracted
                resume_records[str(Path(mp).name)] = extracted

    source_records = link_csv_resumes_by_manifest(
        csv_records, resume_records, str(resume_dir)
    )
    groups = resolve_entities(source_records)

    profiles: list[CanonicalProfile] = []
    for group in groups:
        merged = merge_group(group, source_priority)
        scored = score_profile(merged)
        profiles.append(scored)
    apply_source_notices(profiles)
    return profiles


def project_profiles(
    profiles: list[CanonicalProfile],
    config_path: str | Path | None = None,
    config: dict[str, Any] | None = None,
    *,
    skip_on_error: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Project canonical profiles with runtime config.

    Returns (projected_profiles, projection_errors).
    """
    from pipeline.logging_config import warn as _warn

    cfg = config if config is not None else load_config(config_path)
    results: list[dict[str, Any]] = []
    meta: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for p in profiles:
        try:
            results.append(project(p, cfg))
            meta.append(profile_card_meta(p))
        except Exception as exc:
            err = {
                "candidate_id": p.candidate_id,
                "full_name": p.full_name,
                "error": str(exc),
            }
            errors.append(err)
            if skip_on_error:
                _warn(f"Projection failed for profile {p.candidate_id}: {exc} — skipped")
            else:
                raise
    return results, meta, errors


def run_pipeline(
    csv_path: str | Path,
    resumes_dir: str | Path,
    config_path: str | Path | None = None,
    source_priority: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Run full pipeline: read -> extract -> normalize -> merge -> score -> project.

    Returns JSON-serializable list of projected profiles.
    """
    profiles = build_canonical_profiles(csv_path, resumes_dir, source_priority)
    results, _, _ = project_profiles(profiles, config_path=config_path)
    return results

# -----------------------------------------------------------------------------
# ROUTE OUT: build_canonical_profiles → list[CanonicalProfile]
#              run_pipeline → list[dict] projected JSON
# NEXT FILE → sources/* (stage 1) → extract → normalize → merge → confidence → project/projector.py
# -----------------------------------------------------------------------------
