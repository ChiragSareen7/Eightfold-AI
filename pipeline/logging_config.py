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
