# Candidate Transformer

Eightfold take-home: pipeline that consolidates messy candidate sources into one canonical profile per person.

## Sources (current build)

| Source | Type | Status |
|--------|------|--------|
| Recruiter CSV | Structured | Implemented |
| Resume (PDF/DOCX) | Unstructured | Implemented |
| GitHub API | Structured | Extension point only (`pipeline/sources/github.py`) |

New sources register via `SOURCE_READERS` in `pipeline/sources/__init__.py`.

## Quick start

```bash
# Python 3.11+
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e ".[dev,webapp]"

# Generate sample DOCX resumes (once)
python data/samples/generate_samples.py

# Run pipeline (default full schema) — writes to out/ (gitignored)
python -m pipeline.cli \
  --csv data/samples/recruiter.csv \
  --resumes data/samples \
  --output out/profiles.json

# Custom projection config
python -m pipeline.cli \
  --csv data/samples/recruiter.csv \
  --resumes data/samples \
  --config config/custom.json \
  --output out/custom_profiles.json \
  --stdout

# Web UI + API (http://localhost:8000)
uvicorn webapp.server:app --host 0.0.0.0 --port 8000 --reload

# Run tests
pytest -v

# Export v2 test batch JSON to out/test_data_v2/
python tests/test_test_data_v2.py
```

## Test fixtures

| Folder | Purpose |
|--------|---------|
| `data/samples/` | Small demo CSV + resumes |
| `test_data/` | v1 edge-case batch |
| `test_data_v2/` | v2 harder edge cases + strict/lenient configs |

Generated output goes to `out/` — this folder is gitignored. Regenerate after clone.

## Push to GitHub

```bash
git init
git add .
git status          # confirm out/, .venv/, __pycache__/ are NOT listed
git commit -m "Initial commit: candidate transformer pipeline"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

## Pipeline stages

1. **Source readers** — CSV + resume text extraction (no field parsing for resumes)
2. **Field extraction** — Regex-first resume parsing (LLM fallback on hold)
3. **Normalization** — E.164 phones (no country guessing), YYYY-MM dates, ISO countries, skill canonicalization
4. **Merge** — Email → phone → fuzzy name+company cascade; CSV wins conflicts by default
5. **Confidence** — Explainable per-field formula (see `pipeline/confidence/scoring.py`)
6. **Projection** — Config-driven output reshaping separate from canonical record

## Design decisions

- **Wrong-but-confident is worse than honestly-empty** — phones without country codes stay raw with low confidence
- **CSV > resume** for scalar conflicts (structured human-entered beats machine-parsed)
- **Array fields union** with deduplication (emails, phones, skills)
- **`candidate_id`** — SHA-256 of normalized primary email
- **LLM fallback** — commented out in `pipeline/extract/resume_extractor.py`, ready to enable per field

## Assumptions / descoped

- LLM fallback not wired (regex-only for resume gaps)
- GitHub, LinkedIn, ATS JSON, recruiter notes not implemented
- CLI + optional web UI (`webapp/`) for testing; core pipeline is CLI-first
