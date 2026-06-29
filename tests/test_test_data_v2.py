"""
Test fixture batch v2 + export full card-view JSON for manual review.

Run tests:
    pytest tests/test_test_data_v2.py -v

Generate output JSON files (full card view + all configs):
    python tests/test_test_data_v2.py

Output written to: out/test_data_v2/
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.export import profile_to_card_json
from pipeline.pipeline import build_canonical_profiles, run_pipeline
from pipeline.project.projector import ProjectionError, load_config, project

ROOT = Path(__file__).resolve().parent.parent
TEST_DATA = ROOT / "test_data_v2"
CSV = TEST_DATA / "recruiter.csv"
RESUMES = TEST_DATA / "resumes"
OUT_DIR = ROOT / "out" / "test_data_v2"
DEFAULT_CONFIG = ROOT / "pipeline" / "project" / "default_config.json"
STRICT_CONFIG = TEST_DATA / "config_strict_v2.json"
LENIENT_CONFIG = TEST_DATA / "config_lenient_v2.json"


def _project_all(profiles, config_path: Path) -> tuple[list[dict], list[dict]]:
    """Project each profile; return (successes, errors)."""
    config = load_config(config_path)
    ok: list[dict] = []
    errors: list[dict] = []
    for p in profiles:
        try:
            ok.append(project(p, config))
        except ProjectionError as exc:
            errors.append({
                "candidate_id": p.candidate_id,
                "full_name": p.full_name,
                "error": str(exc),
                "card_view": profile_to_card_json(p),
            })
    return ok, errors


def export_test_data_v2() -> Path:
    """Run v2 batch and write all outputs to out/test_data_v2/."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    profiles = build_canonical_profiles(CSV, RESUMES)

    card_profiles = [profile_to_card_json(p) for p in profiles]
    card_profiles.sort(key=lambda x: (x.get("full_name") or "").lower())

    default_projected = run_pipeline(CSV, RESUMES, DEFAULT_CONFIG)
    default_projected.sort(key=lambda x: (x.get("full_name") or "").lower())

    strict_ok, strict_errors = _project_all(profiles, STRICT_CONFIG)
    strict_ok.sort(key=lambda x: (x.get("full_name") or "").lower())

    lenient_ok, lenient_errors = _project_all(profiles, LENIENT_CONFIG)
    lenient_ok.sort(key=lambda x: (x.get("full_name") or "").lower())

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "csv": str(CSV.relative_to(ROOT)),
        "resumes_dir": str(RESUMES.relative_to(ROOT)),
        "canonical_profile_count": len(profiles),
    }

    combined = {
        "meta": meta,
        "full_card_view": {
            "description": "All fields, confidence, provenance — matches web UI cards",
            "profile_count": len(card_profiles),
            "profiles": card_profiles,
        },
        "default_schema_projection": {
            "config": str(DEFAULT_CONFIG.relative_to(ROOT)),
            "profile_count": len(default_projected),
            "profiles": default_projected,
        },
        "strict_v2_projection": {
            "config": str(STRICT_CONFIG.relative_to(ROOT)),
            "on_missing": "error",
            "profile_count": len(strict_ok),
            "projection_error_count": len(strict_errors),
            "profiles": strict_ok,
            "projection_errors": strict_errors,
        },
        "lenient_v2_projection": {
            "config": str(LENIENT_CONFIG.relative_to(ROOT)),
            "on_missing": "omit",
            "profile_count": len(lenient_ok),
            "profiles": lenient_ok,
        },
    }

    combined_path = OUT_DIR / "combined_results.json"
    combined_path.write_text(
        json.dumps(combined, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    (OUT_DIR / "full_card_view.json").write_text(
        json.dumps({"meta": meta, "profiles": card_profiles}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUT_DIR / "projected_default_schema.json").write_text(
        json.dumps({"meta": meta, "profiles": default_projected}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUT_DIR / "projected_strict_v2.json").write_text(
        json.dumps({
            "meta": meta,
            "profiles": strict_ok,
            "projection_errors": strict_errors,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUT_DIR / "projected_lenient_v2.json").write_text(
        json.dumps({"meta": meta, "profiles": lenient_ok}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Wrote {len(card_profiles)} profiles to {OUT_DIR}/")
    print(f"  combined_results.json       (all configs in one file)")
    print(f"  full_card_view.json         (full card view — check this first)")
    print(f"  projected_default_schema.json")
    print(f"  projected_strict_v2.json    ({len(strict_errors)} projection errors)")
    print(f"  projected_lenient_v2.json")
    return combined_path


@pytest.fixture(scope="module")
def v2_profiles():
    if not CSV.exists():
        pytest.skip("test_data_v2 not found")
    return build_canonical_profiles(CSV, RESUMES)


@pytest.fixture(scope="module", autouse=True)
def v2_export_once():
    """Generate JSON output files once when this module is loaded by pytest."""
    if CSV.exists():
        export_test_data_v2()


class TestV2BatchCompletes:
    def test_batch_produces_profiles(self, v2_profiles):
        assert len(v2_profiles) >= 15

    def test_unreadable_resumes_do_not_crash_batch(self, v2_profiles):
        names = {p.full_name for p in v2_profiles if p.full_name}
        assert "Rashida Ali" in names
        assert "Suresh Pillai" in names


class TestV2MohammedMohammadSeparate:
    def test_two_iqbals_stay_separate(self, v2_profiles):
        iqbal = [p for p in v2_profiles if p.full_name and "iqbal" in p.full_name.lower()]
        assert len(iqbal) == 2
        ids = {p.candidate_id for p in iqbal}
        assert len(ids) == 2


class TestV2NoSkillsHeaderLeak:
    HEADER_WORDS = {"skills", "experience", "education"}

    def test_no_section_headers_in_skills(self, v2_profiles):
        for p in v2_profiles:
            names = {s.name.lower() for s in p.skills}
            leaked = names & self.HEADER_WORDS
            assert not leaked, f"{p.full_name}: header in skills {leaked}"


class TestV2AnjaliUS:
    def test_us_country_not_india(self, v2_profiles):
        anjali = next(p for p in v2_profiles if p.full_name == "Anjali Bhatt")
        assert anjali.location
        assert anjali.location.get("country") == "US"


class TestV2ExportFilesExist:
    def test_output_files_written(self):
        if not CSV.exists():
            pytest.skip("test_data_v2 not found")
        assert (OUT_DIR / "full_card_view.json").exists()
        assert (OUT_DIR / "combined_results.json").exists()
        data = json.loads((OUT_DIR / "full_card_view.json").read_text())
        assert "profiles" in data
        assert len(data["profiles"]) >= 15
        first = data["profiles"][0]
        assert "overall_confidence" in first
        assert "provenance" in first
        assert "field_confidence" in first


if __name__ == "__main__":
    export_test_data_v2()
