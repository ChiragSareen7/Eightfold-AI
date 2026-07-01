# Candidate Profile Transformer

> **Chirag Sareen · chirag@gmail.com**
> 🔗 GitHub: https://github.com/ChiragSareen7/Eightfold-AI
> 🌐 Live demo: **[ADD DEPLOYED URL HERE]**
> 🎥 Demo video: **[ADD GOOGLE DRIVE / YOUTUBE LINK HERE]**

Transforms messy recruiter CSV exports and resume files into clean, trustworthy
candidate profiles — with per-field confidence scores, full source provenance,
plain-English reasoning for every conflict, and a runtime-configurable JSON
output layer.

---

## Screenshots

> **📸 Screenshot 1 — Main UI: candidate cards with trust scores and source badges**
> *(Take this from the web UI after clicking Sample input — show 3–4 cards side by side
> with different trust scores visible. Best captured at ~1400px wide.)*

> **📸 Screenshot 2 — Years experience "Not Asserted" card**
> *(Find a candidate where years_experience is null due to disagreement. Expand the
> reasoning section so the conflict explanation text is visible.)*

> **📸 Screenshot 3 — Provenance table expanded**
> *(Expand the Provenance & Sources section on any merged candidate — shows field/source/
> method rows. Good for showing transparency.)*

> **📸 Screenshot 4 — Config panel: switching Default → Custom**
> *(Side-by-side if possible, or two screenshots showing the cards reshape without
> re-uploading. Demonstrates the reproject feature.)*

> **📸 Screenshot 5 — CLI output terminal**
> *(Run the default CLI command, capture the terminal showing JSON being written to out/.
> Shows it works outside the browser too.)*

---

## Quick Start

### Prerequisites
```
Python 3.11+
pip install -r requirements.txt
```

### Option A — Web UI
```bash
uvicorn webapp.server:app --host 0.0.0.0 --port 8001
```
Open `http://localhost:8001` and click **Sample input** to run the built-in
edge-case batch instantly — no file upload needed.

### Option B — CLI
```bash
# Default config — full schema output
python -m pipeline.cli \
  --csv test_data_v2/recruiter.csv \
  --resumes test_data_v2/resumes \
  -o out/profiles.json

# Custom config — renamed fields, subset of data
python -m pipeline.cli \
  --csv test_data_v2/recruiter.csv \
  --resumes test_data_v2/resumes \
  --config config/custom.json \
  -o out/profiles_custom.json

# Strict mode — errors loudly on any missing required field
python -m pipeline.cli \
  --csv test_data_v2/recruiter.csv \
  --resumes test_data_v2/resumes \
  --config test_data_v2/config_strict_v2.json \
  -o out/profiles_strict.json

# Debug mode
python -m pipeline.cli --csv ... --resumes ... -v
```

---

## The Pipeline (6 stages)

```
CSV + Resumes
     │
     ▼
① Ingest ──► ② Extract ──► ③ Normalise ──► ④ Resolve + Merge ──► ⑤ Score ──► ⑥ Project
                                                                                    │
                                                                               JSON output
                                                                          (shaped by config)
```

Each stage has one job and one failure mode — a corrupted resume in Stage 1
never touches a clean CSV field in Stage 4.

---

## What makes this different

### 1. Matching that doesn't guess

Most implementations match candidates by name — which fails the moment two
people share a common name. This pipeline requires **both email AND normalized
phone** to match before merging two records (confidence 0.97). If only the
manifest path is available, it still requires at least one identity signal
(email, phone, or name fuzzy ≥85%) to validate the link (confidence 0.88).
Name alone never merges two records.

> **📸 Screenshot: Batch summary banner** — shows the merged/csv-only/resume-only
> count split, demonstrating how many candidates matched vs stayed separate.

---

### 2. Wrong-but-confident is the design enemy

Every design decision asks: *is showing this value more honest than showing
null?* Some examples:

**Phone numbers without a country code** are never silently normalized. A bare
`9876543210` has no provable country, so it goes into `phones_raw` with
confidence 0.30 and a `field_reasoning` string explaining why. The `phones`
array (E.164 only) stays empty. This prevents a recruiter calling a wrong
international number because the system guessed `+1`.

**Years of experience** — when the CSV states one number and the resume's date
ranges calculate to something more than 15% different, neither value is
asserted. The field becomes `null`, both candidate values are preserved in
`provenance`, and `field_reasoning` explains the gap in plain English. The
recruiter sees the conflict instead of a confident wrong number.

```json
"years_experience": null,
"field_reasoning": {
  "years_experience": "CSV states 8 years; resume work history calculates
  to approximately 11.9 years — a 33% gap exceeding our 15% agreement
  threshold. Neither value is asserted; both are preserved in provenance."
}
```

> **📸 Screenshot 2 goes here** — the "Not Asserted" card with reasoning visible.

---

### 3. Skills normalisation that actually works

Skill names from different sources are almost never written identically.
The pipeline handles this in three tiers:

- **Alias dictionary first** — `ReactJS`, `React.js`, `react` all map to
  `React`. `py` → `Python`. `NodeJS` → `Node.js`. Hard-coded for the most
  common variants, zero compute cost.
- **Fuzzy match second** — anything not in the alias dict gets compared
  against canonical names using `rapidfuzz` token-set ratio. A score ≥85%
  maps to the canonical name (confidence 0.70). Below 85%, the skill is kept
  as written with confidence 0.55 and a reasoning string naming the best
  candidate and its actual score.
- **Union, not conflict resolution** — skills from CSV and resume are unioned
  and deduped. A candidate who lists `Python` in the CSV and `Python, Django`
  in the resume ends up with `Python, Django` — not a "CSV wins" override that
  would discard Django.

Junk tokens (`----`, `n/a`, `see resume for full list`, sentence fragments)
are filtered before canonicalization so garbage never enters the skills array.

> **📸 Screenshot: Skill chips on a candidate card** — ideally one showing both
> high-confidence (green dot) and kept-original (amber dot) skills side by side.

---

### 4. Confidence that means something

Overall confidence is a **weighted mean** of per-field scores, not a flat
percentage. The weights reflect what actually matters:

| What happened | Score |
|---|---|
| CSV direct field (human-entered) | 0.90 |
| Regex extraction from resume | 0.75 |
| Phone normalized to E.164 | 0.95 |
| Phone kept raw (no country code) | 0.30 |
| Skill matched via alias dictionary | 0.80 |
| Skill matched via fuzzy ≥85% | 0.70 |
| Skill kept as-written (<85%) | 0.55 |
| Merged via manifest link (all fields capped) | ≤0.88 |
| **Single-source profile (×factor)** | **×0.85** |

The last row is important: a profile that came from only a CSV or only a resume
gets every field score multiplied by 0.85, because without a second source to
cross-check, every value is less trustworthy. This means a recruiter can glance
at an 82% trust score vs a 68% trust score and immediately know the lower one
only has one source and needs verification.

`full_name` and `emails` are weighted 1.5× in the overall calculation because
if the identity anchors are uncertain, the whole profile is suspect.

---

### 5. Reproject without re-uploading

The canonical profile is built once and cached. The JSON config is a read-time
lens — changing it reshapes the output without re-running extraction or merge.
The web UI applies config edits in ~450ms using a debounced call to
`/api/reproject` with the already-cached canonical profiles.

This means a recruiter can switch between "full schema with confidence" and
"name + email only, no metadata" in under a second, on the same already-merged
data.

> **📸 Screenshot 4 goes here** — config panel before and after switching.

---

### 6. Transparent source attribution on every card

Every field in every profile knows where it came from and how. The provenance
table shows `{field, source, method}` per field — not just "came from resume"
but specifically `regex_extraction`, `alias_dictionary`, `E164`,
`suppressed_disagreement`, etc. Every suppression or downgrade also has a
`field_reasoning` string in plain English.

This makes the system auditable: a recruiter can trace any value back to its
origin and understand exactly why it has the confidence score it does.

> **📸 Screenshot 3 goes here** — expanded provenance table.

---

### 7. Batch never crashes

Every stage wraps failures at the record level, not the batch level. A
corrupted resume file (detected by a binary quality gate that checks for >4%
control characters before extraction even begins) produces a CSV-only profile
with a clear notice banner — it does not crash the run or silently corrupt
adjacent profiles. An empty CSV row is skipped with a warning. A projection
config error on one profile moves that profile to a `projection_errors` array
while the rest of the batch completes normally.

---

## Repository layout

```
pipeline/
  pipeline.py          # build_canonical_profiles(), project_profiles(), run_pipeline()
  sources/             # csv_reader, resume_reader, text_quality (binary detection)
  extract/             # resume_extractor (regex; LLM stub commented out)
  normalize/           # phones, skills, dates, countries, csv_fields
  merge/               # entity_resolution, merger, source_annotation
  confidence/          # scoring
  project/             # projector, default_config.json
  models/              # raw, canonical, schema (CanonicalProfile fixed shape)
  reasoning.py         # field_reasoning plain-English templates
webapp/
  server.py            # FastAPI: /api/run, /api/reproject, /api/run/samples
  static/index.html    # Single-page UI (no framework, vanilla JS)
config/
  custom.json          # Assignment-style compact config
  examples/            # 01–08: annotated variants covering every config behavior
test_data_v2/          # Primary edge-case batch (Sample input uses this)
  recruiter.csv        # 17 candidates with deliberate conflicts and corruption
  resumes/             # Matching resume files including empty and corrupted ones
  config_strict_v2.json
  config_lenient_v2.json
PROJECT_CONTEXT.md     # Full architecture reference
FAQ.md                 # Reviewer Q&A
```

---

## Runtime configuration

The pipeline builds the canonical record once. A JSON projection config
reshapes what callers receive — no re-upload, no code changes, no re-extraction:

```json
{
  "fields": [
    { "path": "name",        "from": "full_name",    "type": "string",   "required": true },
    { "path": "email",       "from": "emails[0]",    "type": "string",   "required": true },
    { "path": "phone",       "from": "phones[0]",    "type": "string",   "normalize": "E164" },
    { "path": "skill_names", "from": "skills[].name","type": "string[]", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "include_provenance": false,
  "on_missing": "null"
}
```

| Key | What it controls |
|---|---|
| `path` | Output field name (can differ from canonical — renaming) |
| `from` | Canonical path: `emails[0]`, `skills[].name`, `location.country` |
| `type` | Output validation: `string`, `number`, `string[]`, `object[]` |
| `normalize` | Re-apply `E164` or `canonical` at projection time |
| `required` | Gates field via `on_missing` behavior |
| `include_confidence` | Toggle per-field confidence metadata on/off |
| `include_provenance` | Toggle full provenance table on/off |
| `on_missing: null` | Insert null for missing field |
| `on_missing: omit` | Drop key entirely from output |
| `on_missing: error` | Raise error → profile moves to `projection_errors` |

See `config/examples/` for 8 annotated variants covering every combination.

---

## Sample output

```json
{
  "full_name": "Nikhil Bansal",
  "primary_email": "nikhil.b@gmail.com",
  "phone": "+919876500001",
  "years_experience": null,
  "field_reasoning": {
    "years_experience": "CSV states 8 years; resume work history calculates to
    approximately 11.9 years — a 33% gap exceeding our 15% agreement threshold.
    Neither value is asserted; both are preserved in provenance.",
    "phones_raw": "Phone '9876511111' has no country code and was not normalized
    to E.164. Raw digits preserved in phones_raw. Country was not guessed."
  },
  "provenance": [
    { "field": "years_experience", "source": "recruiter_csv",
      "method": "suppressed_disagreement",
      "candidate_values": [
        { "source": "recruiter_csv", "value": 8.0 },
        { "source": "resume",        "value": 11.9 }
      ]
    },
    { "field": "full_name",  "source": "recruiter_csv", "method": "direct_field_csv" },
    { "field": "phones",     "source": "recruiter_csv", "method": "E164" },
    { "field": "skills",     "source": "resume",        "method": "regex_extraction" }
  ],
  "overall_confidence": 0.73
}
```

---

## Deliberate scope decisions

| Decision | Reason |
|---|---|
| No LLM | Determinism is a hard requirement. LLM outputs vary between runs, even at temperature 0. Stub exists for future fallback on specific fields. |
| No country guessing for phones | Asserting `+1` for a bare 10-digit number when the candidate could be anywhere is the wrong-but-confident trap the whole design avoids. |
| Resume wins scalar conflicts | CSV data is often stale. A title a recruiter entered 6 months ago may have changed. Resume is the candidate's own current claim. |
| 15% gap → suppress years_experience | A 1-year difference on a 10-year career might be rounding. A 4-year difference is a real conflict neither source should win. Null is more honest than a forced pick. |
| Single-source ×0.85 confidence factor | Without two sources cross-checking, every value is structurally less trustworthy. The score reflects that honestly. |
| Name-only matching not implemented | Common names cause false merges. Both signals (email + phone, or manifest + identity) must agree. |
| GitHub/LinkedIn sources | Stub in `pipeline/sources/`. Extension point is there; not implemented within scope. |

---

## Known limitations

1. **Overlapping job date ranges** inflate the `years_experience` calculation
   (naive sum, not union of ranges). Documented — see test_data_v2 candidate D010.
2. **Config `from` path typos** produce silent nulls, not validation errors at load time.
3. **ISO-3166-alpha2** normalization in projection not implemented.
4. **Phone digit mismatch** (e.g., `+91` prefix vs bare local digits for the same
   number) blocks `exact_email_and_phone` — may still merge via manifest path.

---

## Running tests

```bash
pytest -v
```

---

*Built with Python 3.11 · rapidfuzz · phonenumbers · pdfplumber · python-docx · FastAPI*