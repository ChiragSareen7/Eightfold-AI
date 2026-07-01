# Candidate Profile Transformer

> 🎥 Demo video: (https://drive.google.com/file/d/1Yy_Tvft1jvIg_xafnYJuc5sKYtOTtQI1/view?usp=sharing)

Transforms messy recruiter CSV exports and resume files into clean, trustworthy candidate profiles — with per-field confidence scores, full source provenance, plain-English reasoning for every conflict, and a runtime-configurable JSON output layer.

---

## Screenshots

> **📸 1 — Main UI: <img width="3306" height="500" alt="image" src="https://github.com/user-attachments/assets/eedd3d1d-8dbf-4571-924f-62e0ac439a0e" />
<img width="3420" height="1702" alt="image" src="https://github.com/user-attachments/assets/c9195533-3ced-41e3-bc78-e88e446a04ff" />

> **📸 2 — "Not Asserted" card:** Years experience nulled due to disagreement, reasoning text visible. *(Expand the reasoning section on a flagged candidate.)*
<img width="3312" height="680" alt="image" src="https://github.com/user-attachments/assets/d0efdf1e-bfea-419d-bcbc-44e4b0922b72" />

> **📸 3 — Provenance table:** Expanded field/source/method rows on any merged candidate.
<img width="3348" height="940" alt="image" src="https://github.com/user-attachments/assets/ea169c9b-def7-4810-8eb9-31140a5f0413" />



---

## Quick Start

```bash
pip install -r requirements.txt

# Web UI
uvicorn webapp.server:app --host 0.0.0.0 --port 8001
# then open http://localhost:8001 → click Sample input

# CLI
python -m pipeline.cli \
  --csv test_data_v2/recruiter.csv \
  --resumes test_data_v2/resumes \
  -o out/profiles.json

# Custom config
python -m pipeline.cli ... --config config/custom.json -o out/profiles_custom.json

# Strict mode (errors on missing required fields)
python -m pipeline.cli ... --config test_data_v2/config_strict_v2.json -o out/profiles_strict.json
```

---

## Pipeline

```
① Ingest ──► ② Extract ──► ③ Normalise ──► ④ Resolve + Merge ──► ⑤ Score ──► ⑥ Project
```

Each stage has one job. A corrupted resume in Stage 1 never touches a clean CSV field in Stage 4.

---

## What makes this different

### Matching that doesn't guess
Name-only matching causes false merges on common names. This pipeline requires **both email AND normalized phone** to match (confidence 0.97), or a manifest path with at least one identity signal — email, phone, or name fuzzy ≥85% (confidence 0.88). Name alone never merges two records.

<img width="3306" height="500" alt="image" src="https://github.com/user-attachments/assets/eedd3d1d-8dbf-4571-924f-62e0ac439a0e" />

### Honest about uncertainty
Every design decision asks: *is showing this value more honest than showing null?*

- **Phones without a country code** go into `phones_raw` (confidence 0.30) with a plain-English explanation. The E.164 `phones` array stays empty. The system never guesses `+1` for a bare number.
- **Years of experience** — if CSV and resume disagree by more than 15%, neither wins. The field becomes `null`, both values are logged in provenance, and `field_reasoning` explains the gap.

```json
"years_experience": null,
"field_reasoning": {
  "years_experience": "CSV states 8 years; resume calculates to 11.9 years — a 33% gap exceeding the 15% threshold. Neither value is asserted."
}
```
<img width="3312" height="680" alt="image" src="https://github.com/user-attachments/assets/d0efdf1e-bfea-419d-bcbc-44e4b0922b72" />

### Skills normalisation in three tiers
1. **Alias dictionary** — `ReactJS` → `React`, `py` → `Python`, `NodeJS` → `Node.js`. Zero compute cost.
2. **Fuzzy match** — rapidfuzz token-set ratio ≥85% → canonical name (confidence 0.70). Below 85% → kept as written (confidence 0.55) with a reasoning string naming the best match and its score.
3. **Union, not conflict** — skills from CSV and resume are merged and deduped. Neither source overwrites the other. Junk tokens (`----`, `n/a`, sentence fragments) are filtered before canonicalization.


### Confidence that means something
Overall confidence is a weighted mean, not a flat percentage. Key weights:

| Signal | Score |
|---|---|
| CSV direct field | 0.90 |
| Regex extraction | 0.75 |
| E.164 phone | 0.95 |
| Raw phone (no country code) | 0.30 |
| Skill: alias dict | 0.80 · fuzzy ≥85%: 0.70 · kept original: 0.55 |
| Manifest merge (all fields capped) | ≤0.88 |
| **Single-source profile** | **all scores ×0.85** |

Single-source profiles are penalized — without a second source to cross-check, every value is structurally less trustworthy. `full_name` and `emails` are weighted 1.5× as identity anchors.

### Reproject without re-uploading
The canonical record is built once and cached. The JSON config reshapes output at read-time — no re-extraction, no re-merge. Config edits reflect in ~450ms via `/api/reproject`. A recruiter switches between "full schema" and "name + email only" in under a second on the same already-merged data.

<img width="3420" height="1534" alt="image" src="https://github.com/user-attachments/assets/bc8da560-279f-4f79-b2db-422f931f4ff2" />


### Full source attribution, always
Every field knows where it came from. The provenance table shows `{field, source, method}` — not just "from resume" but specifically `regex_extraction`, `alias_dictionary`, `E164`, `suppressed_disagreement`. Every flag has a `field_reasoning` string in plain English.

<img width="3348" height="940" alt="image" src="https://github.com/user-attachments/assets/ea169c9b-def7-4810-8eb9-31140a5f0413" />

### Batch never crashes
Failures are caught at the record level. A corrupted file (binary quality gate: >4% control characters) produces a CSV-only profile with a notice banner. Empty CSV rows are skipped with a warning. A projection error on one profile goes to `projection_errors` — the rest complete normally.

---

## Repository layout

```
pipeline/          Business logic (Stages 1–6)
webapp/            FastAPI server + single-page UI (vanilla JS, no framework)
config/examples/   01–08: annotated config variants covering every behavior
test_data_v2/      Primary edge-case batch — used by the Sample input button
PROJECT_CONTEXT.md Full architecture reference
FAQ.md             Reviewer Q&A
```

---

## Runtime configuration

```json
{
  "fields": [
    { "path": "name",        "from": "full_name",     "type": "string",   "required": true },
    { "path": "email",       "from": "emails[0]",     "type": "string",   "required": true },
    { "path": "phone",       "from": "phones[0]",     "type": "string",   "normalize": "E164" },
    { "path": "skill_names", "from": "skills[].name", "type": "string[]", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "include_provenance": false,
  "on_missing": "null"
}
```

`on_missing` accepts `null` (insert null) · `omit` (drop key) · `error` (move profile to `projection_errors`). See `config/examples/` for 8 annotated variants.

---

## Deliberate scope decisions

| Decision | Reason |
|---|---|
| No LLM | Determinism is a hard constraint — LLM outputs vary between runs. Stub exists for future use. |
| No country guessing | Guessing `+1` for a bare number is the wrong-but-confident trap this design exists to avoid. |
| Resume wins scalar conflicts | CSV may be stale. Resume is the candidate's own current claim. |
| 15% gap → null years_experience | A small gap might be rounding. A large gap is a real conflict neither source should win. |
| Single-source ×0.85 | Without corroboration, every value is structurally less trustworthy. |
| Name-only matching off | Common names cause false merges. Both signals must agree. |

---

## Known limitations

1. Overlapping job date ranges inflate `years_experience` (naive sum, not union).
2. Config `from` path typos produce silent nulls rather than a load-time error.
3. ISO-3166-alpha2 normalization not implemented in the projector.

---

## Tests

```bash
pytest -v
```

---
