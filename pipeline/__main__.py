# =============================================================================
# FILE: pipeline/__main__.py
# DOES: Allows `python -m pipeline` to launch the CLI.
# IN:   Command-line arguments from the shell.
# NEXT → pipeline/cli.py (main)
# =============================================================================
from pipeline.cli import main

if __name__ == "__main__":
    main()

# -----------------------------------------------------------------------------
# ROUTE OUT: delegates to cli.main()
# NEXT FILE → pipeline/cli.py
# -----------------------------------------------------------------------------
