"""Stage 2: Regex-first resume field extraction. LLM fallback on hold."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pipeline.models.raw import ExtractedResumeFields, RawResumeRecord
from pipeline.sources.text_quality import looks_like_person_name

EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}\b"
)
LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+/?",
    re.IGNORECASE,
)
GITHUB_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/[\w-]+/?",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://[\w./?=#&%-]+", re.IGNORECASE)
YEARS_EXPERIENCE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)",
    re.IGNORECASE,
)
DATE_RANGE_RE = re.compile(
    r"(?P<start>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}"
    r"|\d{1,2}/\d{4}|\d{4})\s*[-–—]\s*"
    r"(?P<end>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}"
    r"|\d{1,2}/\d{4}|\d{4}|Present|Current|Now)",
    re.IGNORECASE,
)
SECTION_HEADERS = {
    "experience": re.compile(r"^\s*(?:work\s+)?experience\s*$", re.IGNORECASE | re.MULTILINE),
    "education": re.compile(r"^\s*education\s*$", re.IGNORECASE | re.MULTILINE),
    "skills": re.compile(r"^\s*(?:technical\s+)?skills\s*$", re.IGNORECASE | re.MULTILINE),
}


def extract_fields(resume: RawResumeRecord) -> ExtractedResumeFields:
    """
    Primary path: regex and rule-based heuristics.
    LLM fallback is ON HOLD — see _llm_fallback_extract() stub below.
    """
    text = resume.raw_text
    if not text.strip():
        return ExtractedResumeFields(
            source_id=resume.source_id,
            file_path=resume.file_path,
            warnings=["empty resume text"],
        )

    result = ExtractedResumeFields(
        source_id=resume.source_id,
        file_path=resume.file_path,
    )
    methods: dict[str, str] = {}

    # --- Name: typically first non-empty line ---
    name = _extract_name(text)
    if name:
        result.full_name = name
        methods["full_name"] = "regex_extraction"

    # --- Email ---
    emails = EMAIL_RE.findall(text)
    if emails:
        result.emails = list(dict.fromkeys(emails))  # dedupe, preserve order
        methods["emails"] = "regex_extraction"

    # --- Phone ---
    phones = PHONE_RE.findall(text)
    if phones:
        result.phones = list(dict.fromkeys(p.strip() for p in phones if p.strip()))
        methods["phones"] = "regex_extraction"

    # --- Links ---
    links = _extract_links(text)
    if any(links.get(k) for k in ("linkedin", "github", "portfolio")) or links.get("other"):
        result.links = links
        methods["links"] = "regex_extraction"

    # --- Headline: line after name, before contact block ---
    headline = _extract_headline(text, name)
    if headline:
        result.headline = headline
        methods["headline"] = "regex_extraction"

    # --- Location ---
    location = _extract_location(text)
    if location and any(location.values()):
        result.location = location
        methods["location"] = "regex_extraction"

    # --- Section-scoped extraction ---
    sections = _split_sections(text)

    skills = _extract_skills(sections.get("skills", ""))
    if skills:
        result.skills = skills
        methods["skills"] = "regex_extraction"

    experience = _extract_experience(sections.get("experience", ""))
    if experience:
        result.experience = experience
        methods["experience"] = "regex_extraction"

    education = _extract_education(sections.get("education", ""))
    if education:
        result.education = education
        methods["education"] = "regex_extraction"

    # --- years_experience: calculated from date ranges first, then explicit line ---
    calculated_years = _calculate_years_from_experience(experience)
    if calculated_years is not None:
        result.years_experience = calculated_years
        result.years_experience_method = "calculated_from_date_range"
        methods["years_experience"] = "calculated_from_date_range"
    else:
        explicit = _extract_explicit_years(text)
        if explicit is not None:
            result.years_experience = explicit
            result.years_experience_method = "regex_extraction"
            methods["years_experience"] = "regex_extraction"
        # LLM fallback ON HOLD — would run here only if both above are None.
        # elif _should_llm_fallback("years_experience", result):
        #     llm_value = _llm_fallback_extract(text, "years_experience", sections)
        #     ...

    result.field_methods = methods
    return result


def _extract_name(text: str) -> str | None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    first = lines[0]
    # Skip if first line looks like a section header, email, or binary garbage.
    if EMAIL_RE.search(first) or len(first) > 60:
        return None
    if not looks_like_person_name(first):
        return None
    if re.match(r"^(resume|curriculum vitae|cv)$", first, re.IGNORECASE):
        return lines[1].strip() if len(lines) > 1 else None
    return first


def _extract_headline(text: str, name: str | None) -> str | None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    start_idx = 1 if name and lines[0] == name else 0
    for i in range(start_idx + 1, min(start_idx + 4, len(lines))):
        line = lines[i]
        if EMAIL_RE.search(line) or PHONE_RE.search(line):
            break
        if LINKEDIN_RE.search(line) or GITHUB_RE.search(line):
            break
        if 10 <= len(line) <= 120 and not SECTION_HEADERS["experience"].match(line):
            return line
    return None


def _extract_links(text: str) -> dict[str, Any]:
    links: dict[str, Any] = {
        "linkedin": None,
        "github": None,
        "portfolio": None,
        "other": [],
    }
    for match in LINKEDIN_RE.findall(text):
        links["linkedin"] = match if match.startswith("http") else f"https://{match}"
        break
    for match in GITHUB_RE.findall(text):
        links["github"] = match if match.startswith("http") else f"https://{match}"
        break
    for url in URL_RE.findall(text):
        if "linkedin.com" in url.lower() or "github.com" in url.lower():
            continue
        if links["portfolio"] is None:
            links["portfolio"] = url
        else:
            links["other"].append(url)
    return links


def _extract_location(text: str) -> dict[str, str | None] | None:
    """Heuristic: look for 'City, ST' or 'City, Country' near top of resume."""
    top = "\n".join(text.splitlines()[:8])
    # City, ST (US)
    us_match = re.search(
        r"\b([A-Z][a-zA-Z\s]+),\s*([A-Z]{2})\b",
        top,
    )
    if us_match:
        return {"city": us_match.group(1).strip(), "region": us_match.group(2), "country": "US"}
    # City, Country name
    intl_match = re.search(
        r"\b([A-Z][a-zA-Z\s]+),\s*([A-Z][a-zA-Z\s]+)\b",
        top,
    )
    if intl_match:
        return {
            "city": intl_match.group(1).strip(),
            "region": None,
            "country": None,  # normalized later if country name recognized
        }
    return None


def _split_sections(text: str) -> dict[str, str]:
    """
    Split resume text into sections by common headers.

    Bug fix: store match.end() alongside match.start(). The optional leading whitespace
    in the header regex can match the blank line before the header word (because the
    backslash-s character class includes newlines), making match.start() land on that
    blank line. Using text.find("newline", start) then finds the blank-line newline,
    not the one after the header word -- so the header word itself was leaking into
    the section content (e.g. "SKILLS" showing up as a skill, "EXPERIENCE" as a job
    title). Using match.end() to find where the matched header word ends, then scanning
    for the next newline from there, correctly starts content on the line after the header.
    """
    # Store (match_start, match_end, section_name)
    boundaries: list[tuple[int, int, str]] = []
    for name, pattern in SECTION_HEADERS.items():
        for match in pattern.finditer(text):
            boundaries.append((match.start(), match.end(), name))
    boundaries.sort(key=lambda x: x[0])

    sections: dict[str, str] = {}
    for i, (start, match_end, name) in enumerate(boundaries):
        next_start = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        # Find the newline that terminates the header line itself (past the header word).
        header_line_end = text.find("\n", match_end)
        content_start = header_line_end + 1 if header_line_end != -1 else match_end
        sections[name] = text[content_start:next_start].strip()
    return sections


_SKILL_SECTION_HEADERS = {"skills", "technical skills", "core skills", "key skills"}


def _extract_skills(section_text: str) -> list[str]:
    if not section_text:
        return []
    skills: list[str] = []
    for line in section_text.splitlines():
        line = line.strip().lstrip("•-*·").strip()
        if not line:
            continue
        # Defensive guard: skip if the line IS a section header that leaked in.
        if line.lower() in _SKILL_SECTION_HEADERS:
            continue
        if "," in line:
            skills.extend(s.strip() for s in line.split(",") if s.strip())
        elif "|" in line:
            skills.extend(s.strip() for s in line.split("|") if s.strip())
        elif len(line) < 50:
            skills.append(line)
    return list(dict.fromkeys(skills))


def _extract_experience(section_text: str) -> list[dict[str, Any]]:
    if not section_text:
        return []
    entries: list[dict[str, Any]] = []
    blocks = re.split(r"\n\s*\n", section_text)
    for block in blocks:
        entry = _parse_experience_block(block)
        if entry:
            entries.append(entry)
    return entries


def _parse_experience_block(block: str) -> dict[str, Any] | None:
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if not lines:
        return None

    date_match = DATE_RANGE_RE.search(block)
    start_raw = date_match.group("start") if date_match else None
    end_raw = date_match.group("end") if date_match else None

    title = lines[0]
    company = lines[1] if len(lines) > 1 else None

    # "Acme Corp - Software Engineer" on one line
    if " - " in lines[0] and not DATE_RANGE_RE.search(lines[0]):
        left, right = [p.strip() for p in lines[0].split(" - ", 1)]
        if left and right:
            company, title = left, right

    # If first line has dates, swap heuristic
    if date_match and date_match.start() < 5:
        for ln in lines:
            if not DATE_RANGE_RE.search(ln) and len(ln) > 2:
                if title == lines[0]:
                    title = ln
                elif company is None:
                    company = ln
                break

    summary_lines = [
        ln for ln in lines[2:]
        if not DATE_RANGE_RE.search(ln) and ln not in (title, company)
    ]

    return {
        "company": company,
        "title": title,
        "start": start_raw,
        "end": end_raw,
        "summary": " ".join(summary_lines) if summary_lines else None,
        "is_current": bool(end_raw and re.match(r"present|current|now", end_raw, re.I)),
    }


def _extract_education(section_text: str) -> list[dict[str, Any]]:
    if not section_text:
        return []
    entries: list[dict[str, Any]] = []
    blocks = re.split(r"\n\s*\n", section_text)
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        institution = lines[0]
        degree = None
        field = None
        end_year = None

        for ln in lines[1:]:
            year_match = re.search(r"\b(19|20)\d{2}\b", ln)
            if year_match:
                end_year = int(year_match.group())
            if re.search(r"\b(B\.?S\.?|B\.?A\.?|M\.?S\.?|M\.?A\.?|Ph\.?D\.?|Bachelor|Master|Doctor)\b", ln, re.I):
                degree = ln
            elif field is None and ln != institution:
                field = ln

        entries.append({
            "institution": institution,
            "degree": degree,
            "field": field,
            "end_year": end_year,
        })
    return entries


def _parse_month_year(raw: str) -> datetime | None:
    raw = raw.strip()
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    m = re.match(r"([A-Za-z]+)\.?\s+(\d{4})", raw)
    if m:
        month = month_map.get(m.group(1).lower()[:3])
        if month:
            return datetime(int(m.group(2)), month, 1)
    m = re.match(r"(\d{1,2})/(\d{4})", raw)
    if m:
        return datetime(int(m.group(2)), int(m.group(1)), 1)
    m = re.match(r"^(\d{4})$", raw)
    if m:
        return datetime(int(m.group(1)), 1, 1)
    return None


def _calculate_years_from_experience(experience: list[dict[str, Any]]) -> float | None:
    """Sum role durations from parsed date ranges."""
    if not experience:
        return None
    total_months = 0
    parsed_any = False
    now = datetime.now()

    for role in experience:
        start = role.get("start")
        end = role.get("end")
        if not start:
            continue
        start_dt = _parse_month_year(start)
        if not start_dt:
            continue
        if end and re.match(r"present|current|now", str(end), re.I):
            end_dt = now
        else:
            end_dt = _parse_month_year(str(end)) if end else None
        if not end_dt:
            continue
        months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
        if months > 0:
            total_months += months
            parsed_any = True

    if not parsed_any:
        return None
    return round(total_months / 12.0, 1)


def _extract_explicit_years(text: str) -> float | None:
    match = YEARS_EXPERIENCE_RE.search(text)
    if match:
        return float(match.group(1))
    return None


# ---------------------------------------------------------------------------
# LLM FALLBACK — ON HOLD
# ---------------------------------------------------------------------------
# When enabled, this runs ONLY for fields where regex found NOTHING.
# Hard guard: never call if field is already populated (no contradiction rule).
#
# def _should_llm_fallback(field: str, result: ExtractedResumeFields) -> bool:
#     """Return True only if the specific field has no value from regex."""
#     ...
#
# def _llm_fallback_extract(
#     text: str,
#     field: str,
#     sections: dict[str, str],
# ) -> Any:
#     """
#     Single scoped LLM call for one missing field.
#     Provider/model swappable via LLM_PROVIDER / LLM_MODEL env vars.
#     Returns null on failure after one retry.
#     """
#     raise NotImplementedError("LLM fallback on hold — regex-only mode")
