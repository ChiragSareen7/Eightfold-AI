"""Source profile labels and user-facing notices for CSV vs resume attribution."""

from __future__ import annotations

from pipeline.models.canonical import CanonicalProfile
from pipeline.sources.text_quality import looks_like_person_name

CSV_ONLY_NOTICE = (
    "CSV-only profile: no matching resume was merged into this card. "
    "All fields below are from the recruiter CSV."
)

RESUME_ONLY_NOTICE = (
    "Resume-only profile: no matching CSV row was merged into this card. "
    "All fields below are from the resume file."
)

MANIFEST_MISMATCH_CSV = (
    "CSV and resume do not match: a resume file was listed for this CSV row in the "
    "manifest, but identity validation failed (email, phone, name, or filename), so "
    "this card shows CSV data only. The resume is shown as a separate profile."
)

MANIFEST_MISMATCH_RESUME = (
    "CSV and resume do not match: this resume was listed in the CSV manifest for "
    "another candidate, but identity validation failed. This card shows resume data only."
)

UNREADABLE_MANIFEST_RESUME = (
    "CSV lists resume file '{filename}' for this row, but that file was empty, "
    "corrupted, or had no readable identity fields. This card shows CSV data only."
)

MISSING_MANIFEST_RESUME = (
    "CSV lists resume file '{filename}' for this row, but that file was not found "
    "or could not be read. This card shows CSV data only."
)

MERGED_NOTICE = (
    "Matched profile: CSV and resume refer to the same candidate and were merged. "
    "Fields follow source-priority rules; conflicts may be suppressed with reasoning."
)


def apply_source_notices(profiles: list[CanonicalProfile]) -> None:
    """Attach human-readable banners after merge, using per-profile field_meta."""
    manifest_files: set[str] = set()
    for p in profiles:
        fn = p.field_meta.get("manifest_resume")
        if fn:
            manifest_files.add(fn)

    for p in profiles:
        kind = p.source_profile_kind
        manifest_resume = p.field_meta.get("manifest_resume")
        unreadable = p.field_meta.get("manifest_resume_unreadable")
        missing = p.field_meta.get("manifest_resume_missing")
        resume_filename = p.field_meta.get("resume_filename")

        if kind == "merged":
            p.source_notice = None
        elif kind == "csv_only" and unreadable:
            p.source_notice = UNREADABLE_MANIFEST_RESUME.format(filename=unreadable)
        elif kind == "csv_only" and missing:
            p.source_notice = MISSING_MANIFEST_RESUME.format(filename=missing)
        elif kind == "csv_only" and manifest_resume:
            p.source_notice = MANIFEST_MISMATCH_CSV
        elif kind == "csv_only":
            p.source_notice = CSV_ONLY_NOTICE
        elif kind == "resume_only" and resume_filename in manifest_files:
            p.source_notice = MANIFEST_MISMATCH_RESUME
        elif kind == "resume_only":
            p.source_notice = RESUME_ONLY_NOTICE

        _annotate_data_quality(p)


def _annotate_data_quality(profile: CanonicalProfile) -> None:
    """Explain sparse/unknown cards in plain language."""
    kind = profile.source_profile_kind
    notices: list[str] = []

    if not profile.full_name or not looks_like_person_name(profile.full_name):
        if kind == "csv_only":
            row = profile.field_meta.get("csv_row_number")
            row_hint = f" (CSV row {row})" if row else ""
            notices.append(
                f"No candidate name on CSV{row_hint}. "
                f"{'Email/phone also missing — this row had almost no data.' if not profile.emails and not profile.phones else 'Other CSV fields may still appear below.'}"
            )
        elif kind == "resume_only":
            file_hint = profile.field_meta.get("resume_filename") or "resume file"
            notices.append(
                f"Resume '{file_hint}' had no readable name, email, or phone — "
                "likely empty, corrupted, or not a real resume."
            )
        else:
            notices.append("Name could not be resolved from CSV or resume.")

    if profile.field_meta.get("manifest_resume_unreadable"):
        notices.append(
            f"Linked resume '{profile.field_meta['manifest_resume_unreadable']}' "
            "was empty or corrupted — not merged into this card."
        )

    if notices:
        profile.field_meta["data_quality_notice"] = " ".join(notices)


def profile_card_meta(profile: CanonicalProfile) -> dict[str, object | None]:
    """Metadata for UI cards (separate from strict projection output)."""
    return {
        "candidate_id": profile.candidate_id,
        "source_profile_kind": profile.source_profile_kind,
        "source_notice": profile.source_notice,
        "data_quality_notice": profile.field_meta.get("data_quality_notice"),
        "resume_filename": profile.field_meta.get("resume_filename"),
        "manifest_resume": profile.field_meta.get("manifest_resume"),
        "csv_row_number": profile.field_meta.get("csv_row_number"),
    }
