# -*- coding: utf-8 -*-
"""
src/pipeline/ingest.py
======================
Orchestrates the end-to-end job ingestion pipeline.

Pipeline stages
---------------
1. **Load parameters** — read ``config/params.json`` to obtain the
   current search criteria.
2. **Fetch** — call the Adzuna API client to retrieve matching jobs.
3. **Geocode** — resolve each job's ``location_display`` string to
   WGS-84 coordinates via the caching geocoder.
4. **Persist** — upsert all enriched jobs into the SQLite database via
   SQLAlchemy.

The :func:`run` entry point is called both by the CLI script
(``scripts/fetch_jobs.py``) and the HTTP server's ``/api/fetch``
endpoint, ensuring a single authoritative pipeline implementation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import func, select

from config import settings
from src.api.adzuna import AdzunaClient, RawJob
from src.db.models import Job
from src.db.session import SessionFactory, init_db
from src.geo.geocoder import CachingGeocoder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parameter loading
# ---------------------------------------------------------------------------

def load_params(path: Path = settings.PARAMS_PATH) -> Dict[str, Any]:
    """
    Load search parameters from the JSON file at *path*.

    The ``_comment`` key (used for documentation within the JSON file)
    is stripped before the parameters are returned.

    Parameters
    ----------
    path:
        Filesystem path to the ``params.json`` file.

    Returns
    -------
    dict[str, Any]
        Clean mapping of parameter names to values.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    json.JSONDecodeError
        If the file contains malformed JSON.
    """
    logger.info("Loading search parameters from %s.", path.resolve())
    raw = json.loads(path.read_text(encoding="utf-8"))
    params = {k: v for k, v in raw.items() if not k.startswith("_")}
    logger.info("Resolved parameters: %s", json.dumps(params))
    return params


# ---------------------------------------------------------------------------
# Geocoding stage
# ---------------------------------------------------------------------------

def _geocode_jobs(
    jobs: List[RawJob],
    geocoder: CachingGeocoder,
) -> Dict[str, tuple[float | None, float | None]]:
    """
    Resolve the geographic coordinates for every unique location in *jobs*.

    Parameters
    ----------
    jobs:
        Raw job records whose ``location_display`` fields require resolution.
    geocoder:
        Configured :class:`~src.geo.geocoder.CachingGeocoder` instance.

    Returns
    -------
    dict[str, (float | None, float | None)]
        Mapping from location string → ``(lat, lon)`` or ``(None, None)``.
    """
    unique_locations = list(
        {job.location_display for job in jobs if job.location_display}
    )
    logger.info("Geocoding %d unique location strings.", len(unique_locations))
    return geocoder.resolve_many(unique_locations)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Persistence stage
# ---------------------------------------------------------------------------

def _next_search_run() -> int:
    """
    Return the next monotonic search-run counter.

    Queries the maximum ``search_run`` value currently in the ``jobs``
    table and returns ``max + 1``.  Returns ``1`` on an empty table.

    Returns
    -------
    int
        Next run identifier, strictly greater than any existing value.
    """
    with SessionFactory() as session:
        result = session.execute(select(func.max(Job.search_run))).scalar()
        return (result or 0) + 1


def _upsert_jobs(
    raw_jobs: List[RawJob],
    coordinates: Dict[str, Any],
    search_run: int,
) -> int:
    """
    Upsert *raw_jobs* into the database, attaching resolved coordinates.

    Uses a merge (insert-or-update) strategy: if a job with the same
    primary key already exists, its fields are refreshed — including
    the ``search_run`` value, which advances to the current run so the
    GeoJSON export picks it up.

    Parameters
    ----------
    raw_jobs:
        Jobs to persist.
    coordinates:
        Pre-resolved coordinate map from :func:`_geocode_jobs`.
    search_run:
        Current pipeline run counter (stamped on every row).

    Returns
    -------
    int
        Number of rows written (inserted or updated).
    """
    with SessionFactory() as session:
        for raw in raw_jobs:
            coords = coordinates.get(raw.location_display or "")
            lat, lon = coords if coords else (None, None)

            job = Job(
                id=raw.id,
                title=raw.title,
                company=raw.company,
                location_raw=raw.location_display,
                latitude=lat,
                longitude=lon,
                description=raw.description,
                salary_min=raw.salary_min,
                salary_max=raw.salary_max,
                contract_type=raw.contract_type,
                category=raw.category_label,
                redirect_url=raw.redirect_url,
                created_at=raw.created,
                search_run=search_run,
            )
            session.merge(job)  # INSERT OR UPDATE (PK-based).

        session.commit()

    count = len(raw_jobs)
    logger.info("Upserted %d jobs into the database (run #%d).", count, search_run)
    return count


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def run(params_path: Path = settings.PARAMS_PATH) -> Dict[str, Any]:
    """
    Execute the full ingestion pipeline and return a summary report.

    This function is the **sole entry point** for all pipeline executions,
    whether triggered by the CLI or the HTTP server.

    Parameters
    ----------
    params_path:
        Path to the search-parameter JSON file.

    Returns
    -------
    dict[str, Any]
        Execution summary containing:
        - ``params`` — the parameters that were used.
        - ``fetched`` — number of jobs returned by Adzuna.
        - ``persisted`` — number of rows written to the database.
        - ``geocoded`` — number of unique locations resolved.
    """
    logger.info("=== Ingestion pipeline start ===")

    # Stage 0: Schema.
    init_db()

    # Stage 1: Parameters.
    params = load_params(params_path)
    logger.info("Parameters: %s", params)

    # Stage 2: Fetch from Adzuna.
    client = AdzunaClient()
    raw_jobs = client.search(
        what=params.get("what"),
        where=params.get("where"),
        country=params.get("country"),
        salary_min=params.get("salary_min"),
        salary_max=params.get("salary_max"),
        contract_type=params.get("contract_type"),
        category=params.get("category"),
        distance=params.get("distance"),
        sort_by=params.get("sort_by"),
        max_pages=params.get("max_pages", settings.ADZUNA_MAX_PAGES),
    )
    logger.info("Adzuna returned %d jobs.", len(raw_jobs))

    if not raw_jobs:
        logger.warning("No jobs returned — pipeline complete with empty result set.")
        return {"params": params, "fetched": 0, "persisted": 0, "geocoded": 0}

    # Stage 3: Geocode.
    geocoder = CachingGeocoder()
    coordinates = _geocode_jobs(raw_jobs, geocoder)
    resolved = sum(1 for v in coordinates.values() if v is not None)

    # Stage 4: Persist — advance the search_run counter so this batch
    # becomes the exclusive result set returned by /api/jobs.
    run_id = _next_search_run()
    persisted = _upsert_jobs(raw_jobs, coordinates, search_run=run_id)

    summary = {
        "params": params,
        "fetched": len(raw_jobs),
        "persisted": persisted,
        "geocoded": resolved,
        "search_run": run_id,
    }
    logger.info("=== Ingestion pipeline complete: %s ===", summary)
    return summary
