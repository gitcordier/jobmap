# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
scripts/serve.py
================
Launch the JobMap local HTTP development server.

The server exposes the map SPA (``/``) and a minimal REST API:

====================  =======  ================================================
Path                  Method   Description
====================  =======  ================================================
``/``                 GET      Single-page Leaflet application
``/api/params``       GET      Read current search parameters
``/api/params``       POST     Write new search parameters
``/api/jobs``         GET      All geocoded jobs as GeoJSON
``/api/fetch``        POST     Run the Adzuna → geocode → persist pipeline
====================  =======  ================================================

Usage
-----
::

    python scripts/serve.py [--host HOST] [--port PORT] [--verbose]

Options
-------
``--host HOST``
    Binding address (default: ``127.0.0.1``).
``--port PORT``
    TCP port (default: ``8080``).
``--verbose``
    Enable DEBUG-level logging.

Note
----
This server is intended for **local development only**.  It uses Python's
:class:`~http.server.ThreadingHTTPServer` and has no authentication,
rate-limiting, or production hardening.
"""

from __future__ import annotations

import argparse
import logging
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path bootstrap
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import settings  # noqa: E402
from src.db.session import init_db  # noqa: E402
from src.server.handler import JobMapHandler  # noqa: E402


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _configure_logging(verbose: bool) -> None:
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
        prog="serve",
        description="Start the JobMap local development server.",
    )
    parser.add_argument(
        "--host",
        default=settings.SERVER_HOST,
        help=f"Bind address (default: {settings.SERVER_HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.SERVER_PORT,
        help=f"TCP port (default: {settings.SERVER_PORT}).",
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
    Initialise the database schema and start the threading HTTP server.

    The server blocks until interrupted (Ctrl-C / SIGINT), at which
    point it performs a clean shutdown.

    Returns
    -------
    int
        Exit code (always 0 on clean shutdown).
    """
    args = _parse_args()
    _configure_logging(args.verbose)

    logger = logging.getLogger(__name__)

    # Ensure schema exists before accepting requests.
    try:
        init_db()
    except Exception as exc:
        logger.exception("Database initialisation failed: %s", exc)
        return 1

    address = (args.host, args.port)
    try:
        server = ThreadingHTTPServer(address, JobMapHandler)
    except OSError as exc:
        logger.error("Could not bind to %s:%d — %s", args.host, args.port, exc)
        return 1

    logger.info(
        "JobMap server running at  http://%s:%d/",
        args.host,
        args.port,
    )
    logger.info("Press Ctrl-C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutdown requested — stopping server.")
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
