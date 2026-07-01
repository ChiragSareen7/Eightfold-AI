# =============================================================================
# FILE: pipeline/cli.py | STAGE: 8 — CLI entry
# DOES: Command-line interface — reads --csv, --resumes, --config; writes projected JSON.
# IN:   Disk paths from argparse.
# NEXT → pipeline/pipeline.py (run_pipeline)
# =============================================================================
"""Stage 8: CLI surface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.logging_config import setup_logging, warn
from pipeline.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Candidate profile transformer — messy sources to canonical profiles",
    )
    parser.add_argument(
        "--csv",
        required=True,
        help="Path to recruiter CSV export",
    )
    parser.add_argument(
        "--resumes",
        required=True,
        help="Path to resumes folder (PDF/DOCX)",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Write JSON output to this file path",
    )
    parser.add_argument(
        "--config",
        help="Optional projection config JSON (default: built-in full schema)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Also print JSON to stdout",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show warning logs",
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    csv_path = Path(args.csv)
    resumes_path = Path(args.resumes)

    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)
    if not resumes_path.exists():
        print(f"Error: Resumes path not found: {resumes_path}", file=sys.stderr)
        sys.exit(1)

    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"Error: Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
    else:
        config_path = None

    try:
        results = run_pipeline(csv_path, resumes_path, config_path)
    except Exception as exc:
        print(f"Error: pipeline failed: {exc}", file=sys.stderr)
        sys.exit(1)

    output_json = json.dumps(results, indent=2, ensure_ascii=False)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_json, encoding="utf-8")
        if not args.stdout:
            print(f"Wrote {len(results)} profile(s) to {out_path}")

    if args.stdout or not args.output:
        print(output_json)

    if not results:
        warn("Pipeline produced zero profiles — check inputs and warnings")


if __name__ == "__main__":
    main()

# -----------------------------------------------------------------------------
# ROUTE OUT: projected profile JSON → stdout and/or --output file
# NEXT FILE → pipeline/pipeline.py (full pipeline run)
# -----------------------------------------------------------------------------
