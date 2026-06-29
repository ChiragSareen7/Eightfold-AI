"""FastAPI server for the candidate transformer web UI."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import traceback
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent.parent
STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_CONFIG = ROOT / "pipeline" / "project" / "default_config.json"
CUSTOM_CONFIG = ROOT / "config" / "custom.json"
SAMPLES_DIR = ROOT / "data" / "samples"

app = FastAPI(title="Candidate Transformer", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("webapp")


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
    p = SAMPLES_DIR / "recruiter.csv"
    if not p.exists():
        raise HTTPException(404, "Sample CSV not found — run: python data/samples/generate_samples.py")
    return FileResponse(str(p), media_type="text/csv", filename="recruiter.csv")


@app.get("/api/samples/list")
def list_sample_resumes():
    if not SAMPLES_DIR.exists():
        return {"resumes": []}
    files = [
        {"name": p.name, "size": p.stat().st_size}
        for p in sorted(SAMPLES_DIR.iterdir())
        if p.suffix.lower() in (".pdf", ".docx", ".doc", ".txt")
    ]
    return {"resumes": files}


@app.get("/api/samples/resume/{filename}")
def get_sample_resume(filename: str):
    p = SAMPLES_DIR / filename
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
    """
    Accept CSV + resumes + optional config, run pipeline, return profiles.
    All files are written to a temp directory and cleaned up after the run.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="eightfold_"))
    try:
        # Write CSV
        csv_path = tmpdir / "recruiter.csv"
        csv_path.write_bytes(await csv_file.read())

        # Write resumes
        resumes_dir = tmpdir / "resumes"
        resumes_dir.mkdir()
        for resume in resume_files:
            if not resume.filename:
                continue
            dest = resumes_dir / resume.filename
            dest.write_bytes(await resume.read())

        # Write config
        config_path: Path | None = None
        if config_json:
            try:
                parsed_cfg = json.loads(config_json)
            except json.JSONDecodeError as e:
                raise HTTPException(400, f"Invalid config JSON: {e}")
            config_path = tmpdir / "config.json"
            config_path.write_text(json.dumps(parsed_cfg), encoding="utf-8")

        # Run pipeline (import here so server can start even without pipeline installed yet)
        from pipeline.pipeline import run_pipeline as _run

        results = _run(csv_path, resumes_dir, config_path)

        return JSONResponse({
            "ok": True,
            "profile_count": len(results),
            "profiles": results,
        })

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
    """Run pipeline on the built-in sample data."""
    csv_path = SAMPLES_DIR / "recruiter.csv"
    if not csv_path.exists():
        raise HTTPException(404, "Samples not found — run: python data/samples/generate_samples.py")

    tmpdir: Path | None = None
    try:
        config_path: Path | None = None
        if config_json:
            try:
                parsed_cfg = json.loads(config_json)
            except json.JSONDecodeError as e:
                raise HTTPException(400, f"Invalid config JSON: {e}")
            tmpdir = Path(tempfile.mkdtemp(prefix="eightfold_"))
            config_path = tmpdir / "config.json"
            config_path.write_text(json.dumps(parsed_cfg), encoding="utf-8")

        from pipeline.pipeline import run_pipeline as _run

        results = _run(csv_path, SAMPLES_DIR, config_path)

        return JSONResponse({
            "ok": True,
            "profile_count": len(results),
            "profiles": results,
        })
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Pipeline error: %s\n%s", exc, traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "detail": traceback.format_exc()},
        )
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


@app.get("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("webapp.server:app", host="0.0.0.0", port=8001, reload=True, app_dir=str(ROOT))
