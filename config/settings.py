# -*- coding: utf-8 -*-
"""
config/settings.py
==================
Centralised, environment-driven application configuration.

All runtime knobs are sourced exclusively from environment variables
(or a local ``.env`` file).  No value is ever hard-coded here — this
module is a *typed facade* over ``os.environ``.

Usage
-----
    from config import settings

    print(settings.ADZUNA_COUNTRY)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap: resolve project root, then load .env (if present).
# ---------------------------------------------------------------------------

#: Absolute path to the repository root (parent of this file's directory).
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Adzuna REST API
# ---------------------------------------------------------------------------

#: Adzuna developer application identifier.
ADZUNA_APP_ID: str = os.environ["ADZUNA_APP_ID"]

#: Adzuna developer application secret key.
ADZUNA_APP_KEY: str = os.environ["ADZUNA_APP_KEY"]

#: Root URL of the Adzuna Jobs API (v1).
ADZUNA_BASE_URL: str = "https://api.adzuna.com/v1/api/jobs"

#: Two-letter ISO 3166-1 country code used in API path segments.
ADZUNA_COUNTRY: str = os.getenv("ADZUNA_COUNTRY", "gb")

#: Number of results to request per API page (Adzuna maximum: 50).
ADZUNA_RESULTS_PER_PAGE: int = int(os.getenv("ADZUNA_RESULTS_PER_PAGE", "50"))

#: Hard upper bound on pages fetched per search run.
ADZUNA_MAX_PAGES: int = int(os.getenv("ADZUNA_MAX_PAGES", "5"))

# ---------------------------------------------------------------------------
# Geocoding (Nominatim / OpenStreetMap)
# ---------------------------------------------------------------------------

#: User-Agent string sent to Nominatim (required by their ToS).
GEOCODER_USER_AGENT: str = os.getenv("GEOCODER_USER_AGENT", "jobmap/1.0")

#: Per-request timeout in seconds for geocoding calls.
GEOCODER_TIMEOUT: int = int(os.getenv("GEOCODER_TIMEOUT", "10"))

#: Mandatory inter-request delay (seconds) to respect Nominatim rate limits.
GEOCODER_DELAY: float = float(os.getenv("GEOCODER_DELAY", "1.1"))

# ---------------------------------------------------------------------------
# Persistence (SQLAlchemy)
# ---------------------------------------------------------------------------

#: SQLAlchemy database connection URL.
#: Defaults to a file-based SQLite database inside ``data/``.
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{PROJECT_ROOT / 'data' / 'jobmap.db'}",
)

# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

#: Hostname or IP address the development server binds to.
SERVER_HOST: str = os.getenv("SERVER_HOST", "127.0.0.1")

#: TCP port the development server listens on.
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8080"))

# ---------------------------------------------------------------------------
# Filesystem paths
# ---------------------------------------------------------------------------

#: Path to the live search-parameter JSON file (read/written at runtime).
PARAMS_PATH: Path = PROJECT_ROOT / "config" / "params.json"

#: Path to the Jinja-less HTML template served by the development server.
TEMPLATE_PATH: Path = PROJECT_ROOT / "templates" / "map.html"

#: Directory used for all runtime data (DB, logs, …).
DATA_DIR: Path = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
