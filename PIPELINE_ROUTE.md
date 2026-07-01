# Pipeline Route Map

Quick reference for how data flows file-to-file. Each source file also has a **top** and **bottom** route comment block.

```
DISK                          STAGE 1              STAGE 2              STAGE 3
────                          ───────              ───────              ───────
recruiter.csv  ──► csv_reader.py ──► RawCsvRecord ──► normalize/__init__.py ──┐
                                                                                 │
resumes/*.pdf  ──► resume_reader.py ──► RawResumeRecord                          │
                      │                                                          │
                      └──► resume_extractor.py ──► ExtractedResumeFields ───────┘
                                    ▲
                           text_quality.py (guards)

STAGE 4                              STAGE 5                 STAGE 6
──────                               ───────                 ───────
entity_resolution.py                 scoring.py              projector.py
  link_csv_resumes_by_manifest         │                       │
  resolve_entities → EntityGroup       │                       │
       │                               │                       │
merger.py → CanonicalProfile ──────────┘                       │
source_annotation.py (UI notices)                              │
       │                                                       ▼
       └──────────────────────────────────────────► projected JSON dict
                                                              │
CLI (cli.py) ◄── pipeline.py (orchestrator)                   │
Web (server.py) ◄─────────────────────────────────────────────┘
       │
       └──► static/index.html (cards, filters, download)
```

## Entry points

| Entry | First file | Last file |
|-------|------------|-----------|
| `python -m pipeline.cli` | `cli.py` | `projector.py` → JSON file |
| `uvicorn webapp.server:app` | `server.py` | `index.html` |
| **Sample input** button | `server.py` → `test_data_v2/` | `index.html` |

## Match rules (entity_resolution.py)

1. **exact_email_and_phone** — normalized email AND phone digits both match  
2. **manifest_resume_link** — CSV `resume_path` + identity validation (email, phone, name, or filename stem)  
3. Otherwise **singleton** (csv_only or resume_only)
