"""Stage 9: Pipeline tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.extract.resume_extractor import extract_fields
from pipeline.merge.entity_resolution import (
    csv_to_source_record,
    resolve_entities,
    resume_to_source_record,
)
from pipeline.merge.merger import merge_group
from pipeline.models.raw import RawCsvRecord, RawResumeRecord
from pipeline.normalize import normalize_csv_record, normalize_extracted_resume
from pipeline.pipeline import run_pipeline
from pipeline.project.projector import ProjectionError, load_config, project
from pipeline.confidence.scoring import score_profile
from pipeline.sources.csv_reader import read_csv
from pipeline.sources.resume_reader import read_resume

SAMPLES = Path(__file__).parent.parent / "data" / "samples"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def generate_sample_resumes():
    """Ensure sample DOCX files exist."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_samples", SAMPLES / "generate_samples.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.write_resume("jane_doe.docx", mod.JANE_RESUME)
    mod.write_resume("john_smith.docx", mod.JOHN_RESUME)
    mod.write_resume("alice_johnson.docx", mod.ALICE_RESUME)


class TestHappyPath:
    def test_csv_and_resume_merge(self):
        results = run_pipeline(SAMPLES / "recruiter.csv", SAMPLES)
        assert len(results) >= 3
        jane = next(r for r in results if "jane" in r.get("full_name", "").lower())
        assert jane["full_name"] == "Jane Doe"
        assert "jane.doe@example.com" in jane["emails"]
        assert jane["candidate_id"]
        assert jane["overall_confidence"] > 0


class TestConflictResolution:
    def test_csv_wins_over_resume_on_scalar(self):
        csv = RawCsvRecord(
            source_id="csv_test",
            name="Jane Doe",
            email="jane.doe@example.com",
            phone="+14155551234",
            current_company="Acme Corp",
            title="Senior Software Engineer",
        )
        normalize_csv_record(csv)
        resume_text = "Janet Doe\njanet.different@example.com\n"
        raw = RawResumeRecord(source_id="r1", file_path="t.docx", raw_text=resume_text)
        extracted = extract_fields(raw)
        normalize_extracted_resume(extracted)

        from pipeline.merge.entity_resolution import EntityGroup

        records = [csv_to_source_record(csv), resume_to_source_record(extracted)]
        group = EntityGroup(records=records, match_method="exact_email")
        merged = merge_group(group)
        scored = score_profile(merged)

        assert scored.full_name == "Jane Doe"


class TestOnMissing:
    def test_on_missing_null(self):
        from pipeline.models.canonical import CanonicalProfile
        profile = CanonicalProfile(candidate_id="x", full_name=None)
        config = {
            "fields": [{"path": "full_name", "type": "string", "required": True}],
            "on_missing": "null",
            "include_confidence": False,
            "include_provenance": False,
        }
        out = project(profile, config)
        assert out["full_name"] is None

    def test_on_missing_omit(self):
        from pipeline.models.canonical import CanonicalProfile
        profile = CanonicalProfile(candidate_id="x", full_name="Test")
        config = {
            "fields": [
                {"path": "full_name", "type": "string", "required": True},
                {"path": "headline", "type": "string", "required": False},
            ],
            "on_missing": "omit",
            "include_confidence": False,
            "include_provenance": False,
        }
        out = project(profile, config)
        assert "headline" not in out
        assert out["full_name"] == "Test"

    def test_on_missing_error(self):
        from pipeline.models.canonical import CanonicalProfile
        profile = CanonicalProfile(candidate_id="x", full_name=None)
        config = {
            "fields": [{"path": "full_name", "type": "string", "required": True}],
            "on_missing": "error",
            "include_confidence": False,
            "include_provenance": False,
        }
        with pytest.raises(ProjectionError, match="full_name"):
            project(profile, config)


class TestMalformedSource:
    def test_corrupted_resume_does_not_crash(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not a real pdf")
        result = read_resume(bad)
        assert result is None or result.raw_text == ""

        csv = tmp_path / "test.csv"
        csv.write_text(
            "name,email,phone,current_company,title,resume_path\n"
            "Bad User,bad@example.com,,Co,Title,bad.pdf\n",
            encoding="utf-8",
        )
        results = run_pipeline(csv, tmp_path)
        assert isinstance(results, list)


class TestYearsExperienceDisagreement:
    def test_disagreement_reduces_confidence_and_logs_provenance(self):
        csv = RawCsvRecord(
            source_id="csv_ye",
            name="Test User",
            email="test@example.com",
            years_experience="10",
        )
        normalize_csv_record(csv)

        resume_text = """
Test User
test@example.com

Experience
Engineer
Corp A
Jan 2020 - Present

Skills
Python
"""
        raw = RawResumeRecord(source_id="r", file_path="t.docx", raw_text=resume_text)
        extracted = extract_fields(raw)
        normalize_extracted_resume(extracted)

        records = [csv_to_source_record(csv), resume_to_source_record(extracted)]
        groups = resolve_entities(records)
        merged = merge_group(groups[0])
        scored = score_profile(merged)

        assert scored.years_experience == 10.0
        ye_prov = [p for p in scored.provenance if p.field == "years_experience"]
        assert len(ye_prov) >= 1
        if ye_prov[0].candidate_values:
            assert len(ye_prov[0].candidate_values) == 2
            assert scored.field_confidence.get("years_experience", 1.0) < 0.9


class TestIdentityAmbiguity:
    def test_similar_names_different_emails_not_merged(self):
        csv1 = RawCsvRecord(
            source_id="c1", name="Jon Smith", email="jon@example.com",
            current_company="Acme Corp",
        )
        csv2 = RawCsvRecord(
            source_id="c2", name="John Smith", email="john.smith@other.com",
            current_company="Acme Corporation",
        )
        records = [csv_to_source_record(csv1), csv_to_source_record(csv2)]
        groups = resolve_entities(records)
        singleton_groups = [g for g in groups if len(g.records) == 1]
        assert len(singleton_groups) >= 2


class TestCsvReader:
    def test_column_aliases(self, tmp_path):
        csv = tmp_path / "aliases.csv"
        csv.write_text(
            "Full Name,E-mail,Phone,Company,Job Title\n"
            "Alias Test,alias@test.com,+14155550000,Co,Eng\n",
            encoding="utf-8",
        )
        records = read_csv(csv)
        assert len(records) == 1
        assert records[0].name == "Alias Test"
        assert records[0].email == "alias@test.com"


class TestPhoneNormalization:
    def test_no_country_code_stays_raw(self):
        from pipeline.normalize.phones import normalize_phone
        result = normalize_phone("(415) 555-1234")
        assert result.e164 is None
        assert result.confidence == 0.3

    def test_e164_preserved(self):
        from pipeline.normalize.phones import normalize_phone
        result = normalize_phone("+14155551234")
        assert result.e164 == "+14155551234"
        assert result.confidence == 0.95


class TestSkillCanonicalization:
    def test_react_alias(self):
        from pipeline.normalize.skills import canonicalize_skill
        result = canonicalize_skill("ReactJS")
        assert result.name == "React"
        assert result.confidence >= 0.9

    def test_low_similarity_kept(self):
        from pipeline.normalize.skills import canonicalize_skill
        result = canonicalize_skill("TotallyUnknownSkillXYZ")
        assert result.name == "TotallyUnknownSkillXYZ"
        assert result.method == "kept_original_below_threshold"


# ── Bug-fix regression tests ──────────────────────────────────────────────────

class TestNoHeaderLeakInSkills:
    """Bug 1: section header word 'SKILLS' must never appear as a skill entry."""

    HEADER_WORDS = {"skills", "experience", "education", "technical skills"}

    def _make_resume(self, text: str):
        from pipeline.models.raw import RawResumeRecord
        return RawResumeRecord(source_id="r", file_path="t.txt", raw_text=text)

    def test_skills_header_not_in_skills_list(self):
        raw = self._make_resume(
            "Jane Doe\njane@x.com\n\nSKILLS\nPython, SQL, Docker\n\nEXPERIENCE\nEng\nCo\nJan 2020 - Present\n"
        )
        ext = extract_fields(raw)
        names_lower = {s.lower() for s in ext.skills}
        assert not names_lower & self.HEADER_WORDS, (
            f"Section header leaked into skills: {names_lower & self.HEADER_WORDS}"
        )

    def test_experience_header_not_as_job_title(self):
        raw = self._make_resume(
            "Jane Doe\njane@x.com\n\nEXPERIENCE\nSoftware Engineer\nAcme Corp\nJan 2021 - Present\n"
        )
        ext = extract_fields(raw)
        titles = [e.get("title", "").lower() for e in ext.experience]
        assert "experience" not in titles, f"'EXPERIENCE' header became a job title: {titles}"

    def test_full_batch_no_header_leak(self):
        """Run against the full test fixture batch — no profile may have a leaked header."""
        import json
        from pathlib import Path
        batch = Path("out/test_batch_run1.json")
        if not batch.exists():
            pytest.skip("test batch output not generated yet")
        profiles = json.loads(batch.read_text())
        for p in profiles:
            skills = p.get("skills") or []
            names = {
                (s["name"] if isinstance(s, dict) else s).lower()
                for s in skills if s
            }
            leaked = names & self.HEADER_WORDS
            assert not leaked, (
                f"Profile '{p.get('full_name')}' has header word in skills: {leaked}"
            )


class TestNoDuplicateExperience:
    """Bug 2: no two experience entries in a profile may share (company, title, start)."""

    def test_single_role_resume_no_duplicate(self):
        csv = RawCsvRecord(
            source_id="c1",
            name="Jane Doe",
            email="jane@x.com",
            current_company="Acme",
            title="Engineer",
        )
        resume_text = (
            "Jane Doe\njane@x.com\n\nEXPERIENCE\nEngineer\nAcme\nJan 2022 - Present\n"
            "Worked on things.\n\nSKILLS\nPython\n"
        )
        raw = RawResumeRecord(source_id="r1", file_path="t.txt", raw_text=resume_text)
        extracted = extract_fields(raw)
        normalize_extracted_resume(extracted)

        from pipeline.merge.entity_resolution import EntityGroup
        records = [csv_to_source_record(csv), resume_to_source_record(extracted)]
        group = EntityGroup(records=records, match_method="exact_email")
        merged = merge_group(group)
        scored = score_profile(merged)

        keys = [
            (
                (e.get("company") or "").lower(),
                (e.get("title") or "").lower(),
                (e.get("start") or "").lower(),
            )
            for e in scored.experience
        ]
        assert len(keys) == len(set(keys)), f"Duplicate experience entries: {scored.experience}"

    def test_full_batch_no_duplicate_experience(self):
        import json
        from pathlib import Path
        batch = Path("out/test_batch_run1.json")
        if not batch.exists():
            pytest.skip("test batch output not generated yet")
        profiles = json.loads(batch.read_text())
        for p in profiles:
            exp = p.get("experience") or []
            keys = [
                ((e.get("company") or "").lower(), (e.get("title") or "").lower(), (e.get("start") or "").lower())
                for e in exp
            ]
            assert len(keys) == len(set(keys)), (
                f"Profile '{p.get('full_name')}' has duplicate experience entries"
            )


class TestRawPhonePenalty:
    """Bug 3: a profile with an unnormalized phone must have visibly lower overall_confidence
    than an equivalent clean profile."""

    def test_raw_phone_lowers_overall_confidence(self):
        """Clean profile (E.164 phone) vs raw-phone profile — overall must differ by >= 5%."""
        clean_csv = RawCsvRecord(
            source_id="clean", name="Clean Person", email="clean@x.com", phone="+14155551234"
        )
        raw_csv = RawCsvRecord(
            source_id="raw", name="Raw Person", email="raw@x.com", phone="9090909090"
        )
        normalize_csv_record(clean_csv)
        normalize_csv_record(raw_csv)

        from pipeline.merge.entity_resolution import EntityGroup
        from pipeline.merge.merger import merge_group

        clean_group = EntityGroup(records=[csv_to_source_record(clean_csv)], match_method="singleton")
        raw_group = EntityGroup(records=[csv_to_source_record(raw_csv)], match_method="singleton")
        clean_profile = score_profile(merge_group(clean_group))
        raw_profile = score_profile(merge_group(raw_group))

        assert clean_profile.overall_confidence > raw_profile.overall_confidence, (
            "Raw phone profile should have lower overall_confidence"
        )
        gap = clean_profile.overall_confidence - raw_profile.overall_confidence
        assert gap >= 0.05, (
            f"Expected >= 5% gap, got {gap:.1%}. "
            f"Clean={clean_profile.overall_confidence}, Raw={raw_profile.overall_confidence}"
        )


class TestSkillConfidenceTiers:
    """Bug 4: skill field confidence must come from the fixed three-tier formula."""

    VALID_TIERS = {0.80, 0.70, 0.55}

    def test_skill_field_confidence_is_fixed_tier(self):
        resume_text = (
            "Dev Person\ndev@x.com\n\nSKILLS\nPython, ReactJS, TotallyUnknownSkillXYZ\n"
        )
        raw = RawResumeRecord(source_id="r", file_path="t.txt", raw_text=resume_text)
        extracted = extract_fields(raw)
        normalize_extracted_resume(extracted)

        from pipeline.merge.entity_resolution import EntityGroup
        records = [resume_to_source_record(extracted)]
        group = EntityGroup(records=records, match_method="singleton")
        merged = merge_group(group)
        scored = score_profile(merged)

        skills_conf = round(scored.field_confidence.get("skills", 0), 2)
        assert skills_conf in self.VALID_TIERS, (
            f"skills confidence {skills_conf} is not a valid tier {self.VALID_TIERS}"
        )


class TestSchemaCompleteness:
    """Every profile must expose the full canonical schema — null/[] not omitted keys."""

    REQUIRED_CANONICAL_KEYS = {
        "candidate_id", "full_name", "emails", "phones", "phones_raw",
        "location", "links", "headline", "years_experience",
        "skills", "experience", "education", "provenance",
        "field_confidence", "overall_confidence",
    }

    def test_csv_only_candidate_has_all_canonical_keys(self):
        from pipeline.merge.entity_resolution import EntityGroup
        from pipeline.merge.merger import merge_group
        from pipeline.confidence.scoring import score_profile
        from pipeline.export import profile_to_card_json

        csv = RawCsvRecord(
            source_id="csv_only",
            name="Vivek Choudhary",
            email="vivek@example.com",
            phone="+919876543210",
            current_company="TCS",
            title="Developer",
            years_experience="4",
        )
        normalize_csv_record(csv)
        group = EntityGroup(records=[csv_to_source_record(csv)], match_method="singleton")
        scored = score_profile(merge_group(group))
        card = profile_to_card_json(scored)

        assert self.REQUIRED_CANONICAL_KEYS <= set(card.keys())
        assert card["skills"] == []
        assert card["education"] == []
        assert card["headline"] == "Developer"  # CSV title fallback
        assert card["location"] is None
        assert card["skills_confidence"] is None

    def test_empty_resume_csv_fallback_explicit_empty_arrays(self):
        from pipeline.merge.entity_resolution import EntityGroup
        from pipeline.merge.merger import merge_group
        from pipeline.confidence.scoring import score_profile
        from pipeline.export import profile_to_card_json

        csv = RawCsvRecord(
            source_id="rashida",
            name="Rashida Ali",
            email="rashida.ali@gmail.com",
            phone="9876500002",
            current_company="Tech Mahindra",
            title="QA Lead",
            years_experience="5",
        )
        normalize_csv_record(csv)
        empty_resume = RawResumeRecord(
            source_id="r", file_path="empty.txt", raw_text=""
        )
        extracted = extract_fields(empty_resume)
        normalize_extracted_resume(extracted)
        group = EntityGroup(
            records=[csv_to_source_record(csv), resume_to_source_record(extracted)],
            match_method="exact_email",
        )
        scored = score_profile(merge_group(group))
        card = profile_to_card_json(scored)

        assert card["skills"] == []
        assert card["education"] == []
        assert "skills" in card and "education" in card
        assert card["years_experience"] == 5.0
        assert card["years_experience_confidence"] == 0.9

    def test_projected_empty_skills_is_array_not_null(self):
        from pipeline.merge.entity_resolution import EntityGroup
        from pipeline.merge.merger import merge_group
        from pipeline.confidence.scoring import score_profile
        from pipeline.project.projector import project, load_config

        csv = RawCsvRecord(
            source_id="x", name="Test", email="t@x.com", years_experience="3"
        )
        normalize_csv_record(csv)
        group = EntityGroup(records=[csv_to_source_record(csv)], match_method="singleton")
        scored = score_profile(merge_group(group))
        out = project(scored, load_config())

        assert out["skills"] == []
        assert out["experience"] == [] or isinstance(out["experience"], list)
        assert out["education"] == []
        assert out["skills_confidence"] is None

    def test_batch_profiles_share_identical_top_level_keys(self):
        from pipeline.pipeline import run_pipeline
        from pathlib import Path

        batch = Path("test_data_v2/recruiter.csv")
        if not batch.exists():
            pytest.skip("test_data_v2 not found")

        results = run_pipeline(batch, Path("test_data_v2/resumes"))
        real = [r for r in results if r.get("full_name")]
        assert len(real) >= 2
        key_sets = [set(r.keys()) for r in real]
        assert all(ks == key_sets[0] for ks in key_sets[1:]), (
            "Profiles in same batch have different top-level keys"
        )
