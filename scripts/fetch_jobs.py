# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
scripts/fetch_jobs.py
=====================
Command-line entry point for the job ingestion pipeline.

Reads search parameters from ``config/params.json``, calls the Adzuna
API, geocodes all results, and persists them to the local SQLite database.

Usage
-----
::

    python scripts/fetch_jobs.py [--params PATH] [--verbose]

Options
-------
``--params PATH``
    Override the default ``config/params.json`` path.
``--verbose``
    Enable DEBUG-level logging for detailed pipeline tracing.

Exit codes
----------
0   Pipeline completed successfully (even if 0 jobs were returned).
1   Fatal error (invalid params, API credentials missing, etc.).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so imports resolve correctly
# regardless of the working directory from which this script is invoked.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import settings  # noqa: E402 (import after sys.path mutation)
from src.pipeline.ingest import run as run_pipeline  # noqa: E402


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _configure_logging(verbose: bool) -> None:
    """
    Configure the root logger.

    Parameters
    ----------
    verbose:
        When ``True``, emit DEBUG-level messages; otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fetch_jobs",
        description="Fetch, geocode, and persist jobs from the Adzuna API.",
    )
    parser.add_argument(
        "--params",
        type=Path,
        default=settings.PARAMS_PATH,
        metavar="PATH",
        help="Path to the search-parameter JSON file (default: config/params.json).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level log output.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Execute the ingestion pipeline and print a JSON summary to stdout.

    Returns
    -------
    int
        Shell exit code (0 = success, 1 = failure).
    """
    args = _parse_args()
    _configure_logging(args.verbose)

    logger = logging.getLogger(__name__)

    if not args.params.exists():
        logger.error("Parameter file not found: %s", args.params)
        return 1

    try:
        summary = run_pipeline(params_path=args.params)
    except KeyError as exc:
        logger.error(
            "Missing environment variable %s. "
            "Did you create a .env file from .env.example?",
            exc,
        )
        return 1
    except Exception as exc:
        logger.exception("Pipeline failed with unexpected error: %s", exc)
        return 1

    print("\n── Pipeline summary ──────────────────────────────────")
    print(json.dumps(summary, indent=2, default=str))
    print("──────────────────────────────────────────────────────\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
