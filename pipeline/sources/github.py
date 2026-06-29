"""Future extension point: GitHub profile source (not implemented)."""

from __future__ import annotations

# When implemented, register in pipeline/sources/__init__.py:
# SOURCE_READERS["github"] = "pipeline.sources.github.read_github_profile"


def read_github_profile(url: str) -> dict:
    """
    Placeholder for future GitHub API integration.

    Would return a raw record with name, bio, repos, languages.
    Not part of current build scope.
    """
    raise NotImplementedError(
        "GitHub source is a future extension — not implemented in this build."
    )
