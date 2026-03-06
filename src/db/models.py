# -*- coding: utf-8 -*-
"""
src/db/models.py
================
SQLAlchemy ORM model definitions.

Two entities are persisted:

``Job``
    A single job listing fetched from the Adzuna API, enriched with
    resolved geographic coordinates.

``GeoCache``
    A persistent look-up table mapping raw location strings to
    (latitude, longitude) pairs, avoiding redundant geocoding calls.
"""

from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------

class Job(Base):
    """
    A single job listing as stored in the local database.

    Coordinates (``latitude``, ``longitude``) are populated by the
    geocoding pipeline and may be ``NULL`` when resolution fails.
    """

    __tablename__ = "jobs"

    #: Adzuna-assigned job identifier — globally unique, used as PK.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    #: Raw job title as returned by Adzuna.
    title: Mapped[str] = mapped_column(String(512), nullable=False)

    #: Employer display name (nullable — not all listings include one).
    company: Mapped[Optional[str]] = mapped_column(String(256))

    #: Location string exactly as returned by Adzuna (pre-geocoding).
    location_raw: Mapped[Optional[str]] = mapped_column(String(512))

    #: WGS-84 latitude resolved from ``location_raw``.
    latitude: Mapped[Optional[float]] = mapped_column(Float)

    #: WGS-84 longitude resolved from ``location_raw``.
    longitude: Mapped[Optional[float]] = mapped_column(Float)

    #: Short plaintext job description.
    description: Mapped[Optional[str]] = mapped_column(Text)

    #: Lower bound of the advertised salary range (annual, local currency).
    salary_min: Mapped[Optional[float]] = mapped_column(Float)

    #: Upper bound of the advertised salary range.
    salary_max: Mapped[Optional[float]] = mapped_column(Float)

    #: Employment contract type (``permanent``, ``contract``, …).
    contract_type: Mapped[Optional[str]] = mapped_column(String(64))

    #: Adzuna category label (e.g. ``"IT Jobs"``).
    category: Mapped[Optional[str]] = mapped_column(String(128))

    #: Canonical Adzuna redirect URL for the full listing.
    redirect_url: Mapped[Optional[str]] = mapped_column(String(2048))

    #: ISO 8601 creation timestamp as reported by Adzuna.
    created_at: Mapped[Optional[str]] = mapped_column(String(64))

    #: UTC timestamp of the last local fetch (set by the ingest pipeline).
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    #: Monotonically increasing run counter.  Every pipeline execution
    #: increments this value; the GeoJSON export filters on the maximum
    #: run so only the *current* search result set is ever displayed.
    search_run: Mapped[int] = mapped_column(default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<Job id={self.id!r} title={self.title!r}>"


# ---------------------------------------------------------------------------
# GeoCache
# ---------------------------------------------------------------------------

class GeoCache(Base):
    """
    Persistent geocoding cache.

    Each row maps a canonical location string to resolved WGS-84
    coordinates.  ``NULL`` coordinates indicate a previously attempted
    but failed lookup — the pipeline will not retry these.
    """

    __tablename__ = "geo_cache"

    #: Normalised location string used as the cache key.
    location: Mapped[str] = mapped_column(String(512), primary_key=True)

    #: Resolved latitude (``NULL`` ↔ lookup failed).
    latitude: Mapped[Optional[float]] = mapped_column(Float)

    #: Resolved longitude (``NULL`` ↔ lookup failed).
    longitude: Mapped[Optional[float]] = mapped_column(Float)

    #: UTC timestamp of the original geocoding call.
    resolved_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=datetime.datetime.utcnow,
    )

    def __repr__(self) -> str:
        return (
            f"<GeoCache location={self.location!r} "
            f"lat={self.latitude} lon={self.longitude}>"
        )
