"""Resume file reader (Stage 1 — unstructured source). Text extraction only."""

from __future__ import annotations

from pathlib import Path

from pipeline.logging_config import warn
from pipeline.models.raw import RawResumeRecord
from pipeline.sources.text_quality import is_probably_binary_text

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}


def read_resume(file_path: str | Path) -> RawResumeRecord | None:
    """
    Extract raw text from a PDF, DOCX, or TXT resume.

    This stage ONLY extracts text — no field parsing.
    Corrupted/unreadable files are logged and return None.
    """
    path = Path(file_path)
    source_id = f"resume_{path.stem}"

    if not path.exists():
        warn(f"Resume file not found: {path}")
        return None

    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            text = _extract_pdf(path)
        elif suffix in (".docx", ".doc"):
            if suffix == ".doc":
                warn(f".doc format not fully supported, attempting DOCX read: {path}")
            text = _extract_docx(path)
        elif suffix == ".txt":
            text = _extract_txt(path)
        else:
            warn(f"Unsupported resume format: {path}")
            return None
    except Exception as exc:
        warn(f"Failed to read resume {path}: {exc}")
        return None

    if not text or not text.strip():
        warn(f"Resume is empty or unreadable: {path}")
        return RawResumeRecord(
            source_id=source_id,
            file_path=str(path),
            raw_text="",
            warnings=["empty or unreadable file"],
        )

    if is_probably_binary_text(text):
        warn(f"Resume appears to be binary/corrupted, skipping parse: {path}")
        return RawResumeRecord(
            source_id=source_id,
            file_path=str(path),
            raw_text="",
            warnings=["binary or corrupted file"],
        )

    return RawResumeRecord(
        source_id=source_id,
        file_path=str(path),
        raw_text=text,
    )


def read_resumes_from_paths(paths: list[str | Path]) -> list[RawResumeRecord]:
    """Read multiple resume files, skipping failures."""
    records: list[RawResumeRecord] = []
    for p in paths:
        record = read_resume(p)
        if record is not None:
            records.append(record)
    return records


def read_resumes_from_directory(directory: str | Path) -> list[RawResumeRecord]:
    """Read all PDF/DOCX/TXT resume files in a directory."""
    dir_path = Path(directory)
    if not dir_path.is_dir():
        warn(f"Resume directory not found: {dir_path}")
        return []

    paths = sorted(
        p for p in dir_path.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return read_resumes_from_paths(paths)


def _extract_pdf(path: Path) -> str:
    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                pages.append(page_text)
    return "\n".join(pages)


def _extract_docx(path: Path) -> str:
    from docx import Document

    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def _extract_txt(path: Path) -> str:
    # Try UTF-8 first, fall back to latin-1 (covers most recruiter-exported txt files).
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode text file with any supported encoding: {path}")
