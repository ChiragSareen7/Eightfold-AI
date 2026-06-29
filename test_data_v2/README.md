# Test Fixture Set v2 — Harder Edge Cases

This batch specifically targets failure modes the first batch (v1) couldn't reach.
Where v1 tested "does the mechanism work," this batch tests "what does the mechanism
do when the right answer is genuinely unclear" — several of these are intentionally
ambiguous, not bugs to fix.

## Files
- `recruiter.csv` — 17 rows
- `resumes/` — includes normal resumes, one 0-byte empty file, one corrupted binary file,
  and one orphan file not referenced by any CSV row
- `config_strict_v2.json` — required fields tightened (phone + years_experience now
  required, errors loudly on anything missing)
- `config_lenient_v2.json` — opposite extreme: nothing required, missing fields omitted
  silently, no confidence/provenance noise

## Candidate-by-candidate

| Ref | Name | What it's testing | Is there a "correct" answer? |
|---|---|---|---|
| D001 | Nikhil Bansal | Name variant ("Nikhil Bansal" vs "Nikhil Bansal Sharma") + phone conflict + years_experience disagreement, all at once | Yes — CSV should win on phone and years_experience per priority; name should still match since email agrees |
| D002 | Rashida Ali | Resume file is genuinely 0 bytes | Yes — must degrade to CSV-only data, never crash |
| D003 | Suresh Pillai | Resume file is corrupted random binary, not real text | Yes — must catch the read error, log it, degrade to CSV-only |
| D004 | Ananya Sharma | Resume has 2 emails + 2 phones, no clear "primary" label | Partially — CSV's email should anchor which one is primary; open question is whether the second email/phone should still appear in the array or get dropped |
| D005 | (blank CSV row) | Fully empty row, no resume, nothing to work with | Yes — should be skipped/logged, not produce a fake profile |
| D006 | Vivek Choudhary | CSV-only candidate, no resume_path at all | Yes — should produce a valid profile from CSV fields alone |
| (unreferenced) | standalone_no_csv.txt | A resume file sitting in the folder with zero matching CSV row | Open — does your pipeline notice/log this, or silently ignore it? Worth a deliberate decision either way |
| D007 + D008 | Mohammed Iqbal / Mohammad Iqbal | Near-identical name spelling, same company/title/start-date, but different email AND phone | **Genuinely ambiguous on purpose** — could be the same person with a typo'd resume re-upload, or two different people. Strongest match signals (email, phone) disagree, so the defensible default is to keep them SEPARATE, not merge on name-similarity alone |
| D009 | Tanvi Desai | No Skills section anywhere in the resume | Yes — skills should come out null/empty, never hallucinated from job descriptions |
| D010 | Yusuf Khan | Two roles with OVERLAPPING date ranges (concurrent jobs) | Open — does years_experience naively sum both durations (inflated, wrong) or compute the union of date ranges (correct)? Worth knowing which your pipeline does |
| D011 | Riya Kapoor | Resume lists a start date in the FUTURE (2027, when "today" is 2026) | Yes — this should be flagged as suspicious/invalid, confidence lowered, not silently accepted as valid |
| D012 | Devika Pillai | No real dates at all ("several years"), CSV says years_experience=0 which is itself implausible for a freelancer | Open — there's no clean date range to calculate from; years_experience should likely stay low-confidence from both sides rather than the LLM fallback inventing a number from "several years" |
| D013 | Sahil Verma | CSV says current_company=Infosys; resume shows he moved to Quark Software, with Infosys now a PAST role | Open — this is a stale-CSV problem, not a clean conflict; CSV still wins by your priority rule, but it's worth noting in your design doc as a known limitation (no source timestamping) |
| D014 | Anjali Bhatt | US-based candidate — US phone format, US location, not India | Yes — tests whether your country/normalization logic is secretly hardcoded to India; country should resolve to US, not IN |
| D015 | Gaurav Saxena | Skills line polluted with empty tokens, stray punctuation, placeholder text, and a non-skill sentence fragment | Yes — junk tokens should be filtered out silently; real skills (Python, Django, REST APIs, AWS, SQL) should still come through cleanly |
| D016, D017 | Komal Rathi, Aditya Joshi | Clean bulk filler | Yes — re-confirm determinism/scale after your v1 bugfixes, nothing special expected |

## How to use this batch
1. Run the full batch through both `config_strict_v2.json` and `config_lenient_v2.json` —
   confirm the SAME engine produces a tightly-validated output vs. a loosely-permissive
   output without any code changes.
2. Specifically check D002 and D003 — confirm the batch completes with 15 other valid
   profiles even though two resumes are unreadable garbage.
3. Specifically check D007 vs D008 — confirm they remain two separate candidate profiles.
   If they merge into one, that's a real bug in your match-key cascade (it would mean
   name-similarity alone is overriding disagreeing email/phone signals).
4. Check D011 (Riya Kapoor) — confirm the future-dated role is flagged, not silently
   trusted.
5. Check D014 (Anjali Bhatt) — confirm her country comes out as US, not India, and her
   phone is treated as already-valid E.164 rather than being mangled.
6. Check D015 (Gaurav Saxena) — confirm his skills array has ONLY real skills, with the
   punctuation/placeholder junk filtered out.
7. Note: D004, D010, D012, D013 don't have one single "correct" expected value — use
   them to see what your pipeline actually decides, then judge whether that decision is
   defensible and write down WHY in your design doc, rather than trying to force a
   specific number out of them.
