# =============================================================================
# FILE: pipeline/logging_config.py
# DOES: Central warning logger — pipeline logs issues without crashing the batch.
# IN:   warn() calls from any stage.
# NEXT → Used across all pipeline modules (no data flow).
# =============================================================================
"""Centralized logging for pipeline warnings — never crash the batch."""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger("candidate_transformer")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )


def warn(message: str) -> None:
    logger.warning(message)

# -----------------------------------------------------------------------------
# ROUTE OUT: stderr log lines only
# NEXT FILE → (none — cross-cutting utility)
# -----------------------------------------------------------------------------
