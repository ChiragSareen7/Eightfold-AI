# Test Fixture Set — Eightfold Candidate Profile Pipeline

This folder is a deliberately engineered batch, not random sample data. Every row
and resume exists to exercise a specific, named edge case. Use this README as your
own cheat sheet when recording the demo video or defending design decisions.

## Files
- `recruiter.csv` — 22 rows (structured source)
- `resumes/` — 21 matching resume text files (unstructured source)
- `config_minimal.json` — narrow projection: name, email, phone, skills only, no confidence, omit missing
- `config_strict.json` — fuller projection: confidence ON, errors loudly on missing required fields

## Candidate-by-candidate, what each one proves

| Ref | Name | Edge case under test |
|---|---|---|
| C001 | Aditi Verma | Happy path — CSV and resume fully agree, should yield high confidence everywhere |
| C002 | Rohan Mehta | Phone conflict — CSV phone differs from resume phone; CSV must win per source-priority policy |
| C003 | Priya Nair | `years_experience` disagreement — CSV says 1.2, resume date ranges sum to ~5 years; expect CSV value retained but confidence visibly reduced, both candidates logged in provenance |
| C004 | Karan Singh | Missing email — absent in BOTH CSV and resume; tests `on_missing: null / omit / error` behavior |
| C005 | (blank/garbage row) | Malformed CSV row — empty name, invalid phone, no `resume_path` at all; must be skipped/logged, must NOT crash the batch |
| C006 + C007 | Sandeep Kumar (x2) | Identity ambiguity — same name, but different email/phone/company/city; must NOT be merged into one person despite matching name |
| C008 | Meera Joshi | Skill canonicalization — resume lists "ReactJS", "React.js", "Node", "NodeJS", "py", "JS" deliberately, to test alias dictionary + fuzzy matching |
| C009 | Arjun Das | Unnormalized phone — bare 10-digit number, no country code anywhere; must NOT guess a country, should stay raw/low-confidence |
| C010 | Fatima Sheikh | Date edge cases — "Present" as an end date, and year-only dates with no month, across two roles |
| C011–C022 | Bulk filler (12 candidates) | Pure scale/determinism check — clean, simple, no special logic; run the batch twice and diff the output to confirm identical results (order-independence, no randomness) |

## How to use this for your demo video
1. Run the full batch through the CLI with the default config — show the JSON output.
2. Re-run with `config_minimal.json` — show the output reshapes without touching the engine.
3. Re-run with `config_strict.json` — show it correctly errors on Karan Singh's missing email.
4. Point at Priya Nair's profile — show the reduced confidence + both candidate values in provenance.
5. Point at the two Sandeep Kumars — show they were correctly kept as two separate candidates.
6. Point at Meera Joshi's skills — show "ReactJS"/"React.js" both canonicalized to "React".
7. Point at Arjun Das's phone — show it was NOT force-normalized with a guessed country code.
8. Run the whole batch twice, diff the two output files — show they're byte-identical (determinism proof).
