# =============================================================================
# FILE: pipeline/normalize/skills.py | STAGE: 3 — Normalize (skills)
# DOES: Canonicalizes skill names via alias dict + rapidfuzz (≥85% threshold).
# IN:   Raw skill strings from CSV or resume.
# NEXT → pipeline/normalize/__init__.py → merge/merger.py (_union_skills)
# =============================================================================
"""Skill canonicalization via alias dictionary + fuzzy matching (rapidfuzz)."""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

# Curated alias map: variant -> canonical name
SKILL_ALIASES: dict[str, str] = {
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "react js": "React",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "node js": "Node.js",
    "python": "Python",
    "py": "Python",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "java": "Java",
    "golang": "Go",
    "go": "Go",
    "aws": "AWS",
    "amazon web services": "AWS",
    "sql": "SQL",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "machine learning": "Machine Learning",
    "ml": "Machine Learning",
    "deep learning": "Deep Learning",
    "dl": "Deep Learning",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "html": "HTML",
    "css": "CSS",
    "c++": "C++",
    "c#": "C#",
    "ruby": "Ruby",
    "rails": "Ruby on Rails",
    "ruby on rails": "Ruby on Rails",
    "swift": "Swift",
    "kotlin": "Kotlin",
    "rust": "Rust",
    "scala": "Scala",
    "spark": "Apache Spark",
    "apache spark": "Apache Spark",
    "hadoop": "Hadoop",
    "git": "Git",
    "linux": "Linux",
    "agile": "Agile",
    "scrum": "Scrum",
}

CANONICAL_SKILLS: list[str] = sorted(set(SKILL_ALIASES.values()))

FUZZY_THRESHOLD = 85  # below this, keep original rather than force-map


@dataclass
class SkillResult:
    name: str
    confidence: float
    method: str
    source: str = "resume"
    best_match: str | None = None
    best_score: float | None = None  # 0–100 rapidfuzz ratio


def canonicalize_skill(raw: str) -> SkillResult:
    """
    Map skill to canonical name using exact alias, then fuzzy match.
    Below 85% similarity, keep as-is with lower confidence — do not
    aggressively force-match into wrong buckets.
    """
    key = raw.strip().lower()
    if not key:
        return SkillResult(name=raw, confidence=0.0, method="empty")

    if key in SKILL_ALIASES:
        return SkillResult(
            name=SKILL_ALIASES[key],
            confidence=0.95,
            method="alias_dictionary",
        )

    best_match = None
    best_score = 0.0
    for canonical in CANONICAL_SKILLS:
        score = fuzz.ratio(key, canonical.lower())
        if score > best_score:
            best_score = score
            best_match = canonical

    if best_match and best_score >= FUZZY_THRESHOLD:
        return SkillResult(
            name=best_match,
            confidence=round(best_score / 100.0, 2),
            method="fuzzy_match_normalization",
        )

    return SkillResult(
        name=raw.strip(),
        confidence=0.6,
        method="kept_original_below_threshold",
        best_match=best_match,
        best_score=round(best_score, 1) if best_match else None,
    )

# -----------------------------------------------------------------------------
# ROUTE OUT: SkillResult (name, confidence, method, best_match, best_score)
# NEXT FILE → pipeline/normalize/__init__.py → CanonicalProfile.skills[]
# -----------------------------------------------------------------------------
