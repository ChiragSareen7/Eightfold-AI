"""Stage 4: Merge records into canonical profile with conflict resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from pipeline.merge.entity_resolution import (
    DEFAULT_SOURCE_PRIORITY,
    EntityGroup,
    SourceRecord,
    YEARS_EXPERIENCE_DISAGREEMENT_THRESHOLD,
    _candidate_id_from_email,
)
from pipeline.models.canonical import CanonicalProfile, CanonicalSkill, ProvenanceEntry


def merge_group(
    group: EntityGroup,
    source_priority: list[str] | None = None,
) -> CanonicalProfile:
    """
    Merge all source records in a group into one canonical profile.

    Conflict policy: CSV and resume are equal; resume wins scalar ties when values differ.
    Array fields: union with deduplication.
    """
    priority = source_priority or DEFAULT_SOURCE_PRIORITY
    priority_rank = {s: 0 for s in priority}
    tie_rank = {s: i for i, s in enumerate(priority)}

    csv_records = [r for r in group.records if r.source_type == "recruiter_csv"]
    resume_records = [r for r in group.records if r.source_type == "resume"]

    # Determine candidate_id from best available email
    primary_email = _pick_primary_email(csv_records, resume_records, priority)
    candidate_id = _candidate_id_from_email(primary_email) if primary_email else f"unknown_{group.records[0].source_id}"

    profile = CanonicalProfile(candidate_id=candidate_id)

    # Scalar fields with conflict resolution
    profile.full_name = _resolve_scalar(
        csv_records, resume_records, "name", "full_name", priority_rank, tie_rank
    )
    profile.headline = _resolve_headline(csv_records, resume_records, priority_rank, tie_rank)

    profile.location = _resolve_scalar(
        csv_records, resume_records, None, "location", priority_rank, tie_rank
    )

    # years_experience with disagreement handling
    profile.years_experience, ye_provenance = _resolve_years_experience(
        csv_records, resume_records, priority_rank, tie_rank
    )
    if ye_provenance:
        profile.provenance.append(ye_provenance)

    # Array fields: union with dedup, CSV first
    profile.emails = _union_emails(csv_records, resume_records)
    profile.phones, profile.phones_raw = _union_phones(csv_records, resume_records)
    profile.field_meta["phones_raw_details"] = _collect_phones_raw_details(
        csv_records, resume_records, profile.phones_raw
    )
    profile.skills = _union_skills(csv_records, resume_records)
    profile.experience = _union_experience(csv_records, resume_records, priority_rank)
    profile.education = _union_education(csv_records, resume_records)
    profile.links = _merge_links(resume_records)

    sources = sorted({r.source_type for r in group.records})
    if len(sources) == 1 and sources[0] == "recruiter_csv":
        profile.source_profile_kind = "csv_only"
    elif len(sources) == 1:
        profile.source_profile_kind = "resume_only"
    else:
        profile.source_profile_kind = "merged"

    manifest_resume = None
    for r in csv_records:
        rp = r.data.get("resume_path")
        if rp:
            manifest_resume = Path(rp).name
            break

    resume_filename = None
    for r in resume_records:
        fp = r.data.get("file_path")
        if fp:
            resume_filename = Path(fp).name
            break

    # Store merge metadata for confidence stage
    profile.field_meta["_merge"] = type("M", (), {
        "match_method": group.match_method,
        "match_confidence": group.match_confidence,
        "sources": sources,
    })()
    if manifest_resume:
        profile.field_meta["manifest_resume"] = manifest_resume
    if resume_filename:
        profile.field_meta["resume_filename"] = resume_filename

    for r in csv_records:
        row_num = r.data.get("row_number")
        if row_num is not None:
            profile.field_meta["csv_row_number"] = row_num
        if r.data.get("manifest_resume_unreadable"):
            profile.field_meta["manifest_resume_unreadable"] = r.data["manifest_resume_unreadable"]
        if r.data.get("manifest_resume_missing"):
            profile.field_meta["manifest_resume_missing"] = r.data["manifest_resume_missing"]

    return profile


def _pick_primary_email(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
    priority: list[str],
) -> str | None:
    for source_type in priority:
        if source_type == "recruiter_csv":
            for r in csv_records:
                if r.email:
                    return r.email
        elif source_type == "resume":
            for r in resume_records:
                if r.email:
                    return r.email
    return None


def _resolve_scalar(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
    csv_key: str | None,
    resume_key: str,
    priority_rank: dict[str, int],
    tie_rank: dict[str, int],
) -> Any:
    """Prefer agreement across sources; on conflict resume wins over CSV."""
    csv_val = None
    for r in csv_records:
        key = csv_key or resume_key
        if csv_key == "name":
            val = r.data.get("name")
        else:
            val = r.data.get(key) if key in r.data else None
        if val is not None:
            csv_val = val
            break

    resume_val = None
    for r in resume_records:
        val = r.data.get(resume_key)
        if val is not None:
            resume_val = val
            break

    if csv_val is not None and resume_val is not None:
        if isinstance(csv_val, str) and isinstance(resume_val, str):
            if csv_val.strip().lower() == resume_val.strip().lower():
                return csv_val
        elif csv_val == resume_val:
            return csv_val
        return resume_val

    if resume_val is not None:
        return resume_val
    if csv_val is not None:
        return csv_val
    return None


def _resolve_headline(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
    priority_rank: dict[str, int],
    tie_rank: dict[str, int],
) -> str | None:
    """Resume role/headline first, then CSV title — CSV is not auto-preferred."""
    for r in resume_records:
        for exp in r.data.get("experience", []):
            if exp.get("title"):
                return exp["title"]
    for r in resume_records:
        if r.data.get("headline"):
            return r.data["headline"]
    for r in csv_records:
        if r.data.get("title"):
            return r.data["title"]
    return None


def _resolve_years_experience(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
    priority_rank: dict[str, int],
    tie_rank: dict[str, int],
) -> tuple[float | None, ProvenanceEntry | None]:
    """
    CSV direct value vs resume calculated/stated value.
    If disagreement <= 15%, average both values (equal weight).
    If disagreement > 15%, value is suppressed (null) but both candidates stay in provenance.
    """
    candidates: list[tuple[str, float, str]] = []

    for r in csv_records:
        val = r.data.get("years_experience")
        if val is not None:
            method = r.data.get("years_experience_method", "direct_field_csv")
            candidates.append(("recruiter_csv", float(val), method))

    for r in resume_records:
        val = r.data.get("years_experience")
        if val is not None:
            method = r.data.get("years_experience_method", "regex_extraction")
            candidates.append(("resume", float(val), method))

    if not candidates:
        return None, None

    if len(candidates) == 1:
        source, val, method = candidates[0]
        return val, ProvenanceEntry(field="years_experience", source=source, method=method)

    csv_val = next((v for s, v, _ in candidates if s == "recruiter_csv"), None)
    resume_val = next((v for s, v, _ in candidates if s == "resume"), None)
    csv_method = next((m for s, _, m in candidates if s == "recruiter_csv"), "direct_field_csv")
    resume_method = next((m for s, _, m in candidates if s == "resume"), "regex_extraction")

    if csv_val is None or resume_val is None:
        source, val, method = candidates[0]
        return val, ProvenanceEntry(field="years_experience", source=source, method=method)

    diff_ratio = abs(csv_val - resume_val) / max(csv_val, resume_val, 1)
    if diff_ratio > YEARS_EXPERIENCE_DISAGREEMENT_THRESHOLD:
        provenance = ProvenanceEntry(
            field="years_experience",
            source="merged",
            method="suppressed_disagreement",
            notes=(
                f"Disagreement: CSV={csv_val} vs resume={resume_val} "
                f"({diff_ratio:.0%} gap) — value suppressed"
            ),
            candidate_values=[
                {"source": "recruiter_csv", "value": csv_val, "method": csv_method},
                {"source": "resume", "value": resume_val, "method": resume_method},
            ],
        )
        return None, provenance

    averaged = round((csv_val + resume_val) / 2, 2)
    provenance = ProvenanceEntry(
        field="years_experience",
        source="merged",
        method="averaged_agreement",
        candidate_values=[
            {"source": "recruiter_csv", "value": csv_val, "method": csv_method},
            {"source": "resume", "value": resume_val, "method": resume_method},
        ],
    )
    return averaged, provenance


def _union_emails(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for r in csv_records:
        email = r.data.get("email")
        if email:
            key = email.lower()
            if key not in seen:
                seen.add(key)
                result.append(email)
    for r in resume_records:
        for email in r.data.get("emails", []):
            key = email.lower()
            if key not in seen:
                seen.add(key)
                result.append(email)
    return result


def _union_phones(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
) -> tuple[list[str], list[str]]:
    """
    Route phones to normalized (E.164, starts with +) or raw (no country code).
    A phone is only considered normalized if it starts with '+' — no guessing.
    CSV phones that failed normalization are raw, not normalized.
    """
    seen: set[str] = set()
    normalized: list[str] = []
    raw: list[str] = []

    for r in csv_records:
        phone = r.data.get("phone")
        if phone and phone not in seen:
            seen.add(phone)
            # Only treat as normalized if it is actually E.164 (starts with +).
            if phone.startswith("+"):
                normalized.append(phone)
            else:
                raw.append(phone)

    for r in resume_records:
        for phone in r.data.get("phones_normalized", r.data.get("phones", [])):
            if phone and phone not in seen:
                seen.add(phone)
                if phone.startswith("+"):
                    normalized.append(phone)
                else:
                    raw.append(phone)
        for phone in r.data.get("phones_raw", []):
            if phone and phone not in seen:
                seen.add(phone)
                raw.append(phone)

    return normalized, raw


def _collect_phones_raw_details(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
    phones_raw: list[str],
) -> list[dict[str, str]]:
    """Map each merged raw phone to its normalization method and source."""
    details: list[dict[str, str]] = []
    seen: set[str] = set()

    for r in csv_records:
        phone = r.data.get("phone")
        method = r.data.get("phone_method")
        if phone and phone in phones_raw and phone not in seen and method:
            seen.add(phone)
            details.append({"value": phone, "method": method, "source": "recruiter_csv"})

    for r in resume_records:
        meta_by_value = {
            m["value"]: m["method"]
            for m in r.data.get("phones_raw_meta", [])
            if m.get("value") and m.get("method")
        }
        for phone in r.data.get("phones_raw", []):
            if phone and phone in phones_raw and phone not in seen:
                seen.add(phone)
                details.append({
                    "value": phone,
                    "method": meta_by_value.get(phone, "unnormalized_no_country_code"),
                    "source": "resume",
                })

    for phone in phones_raw:
        if phone not in seen:
            details.append({
                "value": phone,
                "method": "unnormalized_no_country_code",
                "source": "resume",
            })

    return details


def _union_skills(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
) -> list[CanonicalSkill]:
    seen: set[str] = set()
    skills: list[CanonicalSkill] = []

    def _add(skill_data: Any, source: str) -> None:
        if isinstance(skill_data, dict):
            name = skill_data.get("name", "")
            confidence = skill_data.get("confidence", 0.7)
            method = skill_data.get("method", "regex_extraction")
            best_match = skill_data.get("best_match")
            best_score = skill_data.get("best_score")
        else:
            name = str(skill_data)
            confidence = 0.7
            method = "regex_extraction"
            best_match = None
            best_score = None
        key = name.lower()
        if not key:
            return
        if key in seen:
            for existing in skills:
                if existing.name.lower() == key and source not in existing.sources:
                    existing.sources.append(source)
            return
        seen.add(key)
        skills.append(CanonicalSkill(
            name=name,
            confidence=confidence,
            sources=[source],
            method=method,
            best_match=best_match,
            best_score=best_score,
        ))

    for r in csv_records:
        for skill_data in r.data.get("skills", []):
            _add(skill_data, "recruiter_csv")
    for r in resume_records:
        for skill_data in r.data.get("skills", []):
            _add(skill_data, "resume")
    return skills


def _exp_dedup_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    """Stable dedup key for an experience entry: (company, title, start_date)."""
    return (
        (entry.get("company") or "").strip().lower(),
        (entry.get("title") or "").strip().lower(),
        (entry.get("start") or "").strip().lower(),
    )


def _fuzzy_match(a: str | None, b: str | None, threshold: int = 85) -> bool:
    if not a or not b:
        return False
    return fuzz.ratio(a.strip().lower(), b.strip().lower()) >= threshold


def _union_experience(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
    priority_rank: dict[str, int],
) -> list[dict[str, Any]]:
    """
    Merge resume history with CSV current role.

    When CSV company/title agree with a resume entry, enrich summary from CSV description.
    When they conflict, keep the resume role and add CSV as a separate entry.
    """
    experience: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for r in resume_records:
        for exp in r.data.get("experience", []):
            entry = dict(exp)
            entry["source"] = "resume"
            key = _exp_dedup_key(entry)
            if key not in seen_keys:
                seen_keys.add(key)
                experience.append(entry)

    for r in csv_records:
        company = r.data.get("current_company")
        title = r.data.get("title")
        description = r.data.get("experience_description")
        if not company and not title and not description:
            continue

        matched_idx: int | None = None
        for i, exp in enumerate(experience):
            if _fuzzy_match(exp.get("company"), company) and (
                not title or _fuzzy_match(exp.get("title"), title, threshold=80)
            ):
                matched_idx = i
                break

        if matched_idx is not None:
            entry = experience[matched_idx]
            if company:
                entry["company"] = company
            if title:
                entry["title"] = title
            if description:
                entry["summary"] = description
            entry["source"] = "merged"
            continue

        if experience:
            current = experience[0]
            if company and not _fuzzy_match(current.get("company"), company):
                csv_entry: dict[str, Any] = {
                    "company": company,
                    "title": title,
                    "start": None,
                    "end": None,
                    "summary": description,
                    "source": "recruiter_csv",
                }
                key = _exp_dedup_key(csv_entry)
                if key not in seen_keys:
                    seen_keys.add(key)
                    experience.insert(0, csv_entry)
                continue

        csv_entry = {
            "company": company,
            "title": title,
            "start": None,
            "end": None,
            "summary": description,
            "source": "recruiter_csv",
        }
        key = _exp_dedup_key(csv_entry)
        company_title_key = (
            (company or "").strip().lower(),
            (title or "").strip().lower(),
        )
        already_present = key in seen_keys or any(
            (e.get("company") or "").strip().lower() == company_title_key[0]
            and (e.get("title") or "").strip().lower() == company_title_key[1]
            for e in experience
        )
        if not already_present:
            seen_keys.add(key)
            experience.append(csv_entry)

    return experience


def _union_education(
    csv_records: list[SourceRecord],
    resume_records: list[SourceRecord],
) -> list[dict[str, Any]]:
    education: list[dict[str, Any]] = []
    seen: set[str] = set()

    for r in csv_records:
        for edu in r.data.get("education", []):
            entry = dict(edu)
            entry.setdefault("source", "recruiter_csv")
            key = (entry.get("institution") or "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                education.append(entry)

    for r in resume_records:
        for edu in r.data.get("education", []):
            entry = dict(edu)
            entry.setdefault("source", "resume")
            key = (entry.get("institution") or "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                education.append(entry)
            elif key and key in seen:
                for existing in education:
                    if (existing.get("institution") or "").strip().lower() == key:
                        if not existing.get("degree") and entry.get("degree"):
                            existing["degree"] = entry["degree"]
                        if not existing.get("end_year") and entry.get("end_year"):
                            existing["end_year"] = entry["end_year"]
                        if "resume" not in str(existing.get("source", "")):
                            existing["source"] = "merged"
                        break

    return education


def _merge_links(resume_records: list[SourceRecord]) -> dict[str, Any]:
    links: dict[str, Any] = {
        "linkedin": None,
        "github": None,
        "portfolio": None,
        "other": [],
    }
    for r in resume_records:
        rlinks = r.data.get("links", {})
        for key in ("linkedin", "github", "portfolio"):
            if not links[key] and rlinks.get(key):
                links[key] = rlinks[key]
        for other in rlinks.get("other", []):
            if other not in links["other"]:
                links["other"].append(other)
    return links
