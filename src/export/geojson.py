# -*- coding: utf-8 -*-
"""
src/export/geojson.py
=====================
Serialises :class:`~src.db.models.Job` ORM records to RFC 7946 GeoJSON.

Only jobs with resolved coordinates (non-NULL ``latitude`` and
``longitude``) are included in the output.  Jobs without coordinates
are silently excluded — the caller may log the omission count if needed.

The exported ``FeatureCollection`` is consumed directly by the Leaflet
front-end via the ``/api/jobs`` endpoint.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy import func, select

from src.db.models import Job
from src.db.session import SessionFactory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GeoJSON construction
# ---------------------------------------------------------------------------

def _job_to_feature(job: Job) -> Dict[str, Any]:
    """
    Convert a single :class:`Job` ORM instance to a GeoJSON Feature dict.

    The ``properties`` object exposes every display-relevant field
    consumed by the Leaflet popup template in ``map.html``.

    Parameters
    ----------
    job:
        A :class:`Job` with non-NULL latitude and longitude.

    Returns
    -------
    dict
        A valid GeoJSON Feature with ``Point`` geometry.
    """
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            # GeoJSON coordinate order: [longitude, latitude].
            "coordinates": [job.longitude, job.latitude],
        },
        "properties": {
            "id": job.id,
            "title": job.title,
            "company": job.company or "Unknown",
            "location": job.location_raw or "",
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "contract_type": job.contract_type or "",
            "category": job.category or "",
            "redirect_url": job.redirect_url or "",
            "created_at": job.created_at or "",
            "description": (job.description or "")[:300],  # Truncated for popup.
        },
    }


def jobs_as_geojson() -> Dict[str, Any]:
    """
    Query all geocoded jobs from the **current** search run and return a
    GeoJSON ``FeatureCollection``.

    "Current" is defined as the maximum ``search_run`` value present in
    the ``jobs`` table.  This guarantees that every new search completely
    replaces the displayed result set, regardless of how many prior runs
    are stored in the database.

    Only jobs where both ``latitude`` and ``longitude`` are non-NULL are
    included.  The result is safe to ``json.dumps()`` and return directly
    to the HTTP client.

    Returns
    -------
    dict
        A valid GeoJSON ``FeatureCollection``.
    """
    with SessionFactory() as session:
        # Determine the latest run identifier.
        latest_run: int = session.execute(
            select(func.max(Job.search_run))
        ).scalar() or 0

        stmt = (
            select(Job)
            .where(Job.search_run == latest_run)
            .where(Job.latitude.is_not(None))
            .where(Job.longitude.is_not(None))
            .order_by(Job.fetched_at.desc())
        )
        jobs: List[Job] = list(session.scalars(stmt))

    features = [_job_to_feature(job) for job in jobs]
    logger.info(
        "Exporting %d geocoded jobs as GeoJSON (search_run=%d).",
        len(features),
        latest_run,
    )

    return {
        "type": "FeatureCollection",
        "features": features,
    }
