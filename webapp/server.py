# =============================================================================
# FILE: webapp/server.py | HTTP API + static UI host
# DOES: FastAPI app — /api/run, /api/reproject, /api/run/samples (test_data_v2), config presets.
# IN:   Multipart uploads or cached canonical_profiles JSON from browser.
# NEXT → pipeline/pipeline.py → webapp/static/index.html (JSON response)
# =============================================================================
"""FastAPI server for the candidate transformer web UI."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import traceback
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent.parent
STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_CONFIG = ROOT / "pipeline" / "project" / "default_config.json"
CUSTOM_CONFIG = ROOT / "config" / "custom.json"
SAMPLE_INPUT_DIR = ROOT / "test_data_v2"
SAMPLE_CSV = SAMPLE_INPUT_DIR / "recruiter.csv"
SAMPLE_RESUMES_DIR = SAMPLE_INPUT_DIR / "resumes"

app = FastAPI(title="Candidate Transformer", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("webapp")


class ReprojectRequest(BaseModel):
    canonical_profiles: list[dict[str, Any]] = Field(..., min_length=1)
    config: dict[str, Any] | None = None


def _parse_config_json(config_json: str | None) -> dict[str, Any]:
    from pipeline.project.projector import load_config

    if config_json and config_json.strip():
        try:
            return json.loads(config_json)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"Invalid config JSON: {e}") from e
    return load_config(None)


def _batch_summary_from_canonical(profiles) -> dict[str, int]:
    kinds = [p.source_profile_kind for p in profiles]
    mismatches = sum(
        1 for p in profiles
        if p.source_notice and "do not match" in p.source_notice
    )
    return {
        "csv_only": kinds.count("csv_only"),
        "resume_only": kinds.count("resume_only"),
        "merged": kinds.count("merged"),
        "manifest_mismatches": mismatches,
    }


def _run_and_project(csv_path: Path, resumes_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    from pipeline.pipeline import build_canonical_profiles, project_profiles

    profiles = build_canonical_profiles(csv_path, resumes_dir)
    projected, profile_meta, errors = project_profiles(profiles, config=config)
    canonical_json = [p.to_dict() for p in profiles]
    return {
        "ok": True,
        "profile_count": len(projected),
        "profiles": projected,
        "profile_meta": profile_meta,
        "canonical_profiles": canonical_json,
        "projection_errors": errors,
        "batch_summary": _batch_summary_from_canonical(profiles),
    }


# ── Static files ──────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=FileResponse)
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ── Config presets ────────────────────────────────────────────────────────────

@app.get("/api/config/default")
def get_default_config():
    return JSONResponse(json.loads(DEFAULT_CONFIG.read_text()))


@app.get("/api/config/custom")
def get_custom_config():
    return JSONResponse(json.loads(CUSTOM_CONFIG.read_text()))


# ── Sample data ───────────────────────────────────────────────────────────────

@app.get("/api/samples/csv")
def get_sample_csv():
    if not SAMPLE_CSV.exists():
        raise HTTPException(404, "Sample CSV not found at test_data_v2/recruiter.csv")
    return FileResponse(str(SAMPLE_CSV), media_type="text/csv", filename="recruiter.csv")


@app.get("/api/samples/list")
def list_sample_resumes():
    if not SAMPLE_RESUMES_DIR.exists():
        return {"resumes": []}
    files = [
        {"name": p.name, "size": p.stat().st_size}
        for p in sorted(SAMPLE_RESUMES_DIR.iterdir())
        if p.suffix.lower() in (".pdf", ".docx", ".doc", ".txt")
    ]
    return {"resumes": files}


@app.get("/api/samples/resume/{filename}")
def get_sample_resume(filename: str):
    p = SAMPLE_RESUMES_DIR / filename
    if not p.exists() or p.suffix.lower() not in (".pdf", ".docx", ".doc", ".txt"):
        raise HTTPException(404, "Resume not found")
    media_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".txt": "text/plain",
    }
    mt = media_types.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(str(p), media_type=mt, filename=filename)


# ── Pipeline run ──────────────────────────────────────────────────────────────

@app.post("/api/run")
async def run_pipeline(
    csv_file: UploadFile = File(..., description="Recruiter CSV export"),
    resume_files: list[UploadFile] = File(..., description="Resume PDF/DOCX files"),
    config_json: str | None = Form(None, description="Projection config JSON string"),
):
    """Run merge pipeline, then project canonical records with the supplied config."""
    tmpdir = Path(tempfile.mkdtemp(prefix="eightfold_"))
    try:
        csv_path = tmpdir / "recruiter.csv"
        csv_path.write_bytes(await csv_file.read())

        resumes_dir = tmpdir / "resumes"
        resumes_dir.mkdir()
        for resume in resume_files:
            if not resume.filename:
                continue
            dest = resumes_dir / resume.filename
            dest.write_bytes(await resume.read())

        config = _parse_config_json(config_json)
        return JSONResponse(_run_and_project(csv_path, resumes_dir, config))

    except HTTPException:
        raise
    except Exception as exc:
        log.error("Pipeline error: %s\n%s", exc, traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "detail": traceback.format_exc()},
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.post("/api/run/samples")
async def run_on_samples(config_json: str | None = Form(None)):
    """Run pipeline on built-in test_data_v2 sample batch."""
    if not SAMPLE_CSV.exists() or not SAMPLE_RESUMES_DIR.exists():
        raise HTTPException(404, "Sample data not found — expected test_data_v2/recruiter.csv and resumes/")

    try:
        config = _parse_config_json(config_json)
        return JSONResponse(_run_and_project(SAMPLE_CSV, SAMPLE_RESUMES_DIR, config))
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Pipeline error: %s\n%s", exc, traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "detail": traceback.format_exc()},
        )


@app.post("/api/reproject")
async def reproject(body: ReprojectRequest):
    """Re-project cached canonical profiles when only the config changes."""
    from pipeline.models.canonical import CanonicalProfile
    from pipeline.pipeline import project_profiles

    try:
        profiles = [CanonicalProfile.from_dict(item) for item in body.canonical_profiles]
        config = body.config if body.config is not None else _parse_config_json(None)
        projected, profile_meta, errors = project_profiles(profiles, config=config)
        return JSONResponse({
            "ok": True,
            "profile_count": len(projected),
            "profiles": projected,
            "profile_meta": profile_meta,
            "projection_errors": errors,
            "batch_summary": _batch_summary_from_canonical(profiles),
        })
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Reproject error: %s\n%s", exc, traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "detail": traceback.format_exc()},
        )


@app.get("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("webapp.server:app", host="0.0.0.0", port=8001, reload=True, app_dir=str(ROOT))

# -----------------------------------------------------------------------------
# ROUTE OUT: JSON { profiles, profile_meta, canonical_profiles, batch_summary }
# NEXT FILE → webapp/static/index.html (render cards / raw JSON)
# -----------------------------------------------------------------------------
