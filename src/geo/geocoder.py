# -*- coding: utf-8 -*-
"""
src/geo/geocoder.py
===================
Location-string → WGS-84 coordinate resolver with persistent caching.

Architecture
------------
The :class:`CachingGeocoder` wraps ``geopy``'s Nominatim geocoder with
a two-level lookup strategy:

1. **Database cache** (:class:`~src.db.models.GeoCache`) — consulted
   first.  A ``NULL`` coordinate pair in the cache signals a previously
   failed lookup; the geocoder will **not** re-attempt these.

2. **Nominatim HTTP call** — performed only on a cache miss.  Results
   (including failures) are immediately persisted to avoid redundant
   network calls across pipeline runs.

Rate limiting
~~~~~~~~~~~~~
Nominatim's usage policy mandates at most one request per second.
The :attr:`GEOCODER_DELAY` setting enforces this; all callers should
ensure they do not bypass the rate limit by constructing multiple
instances in parallel.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

from config import settings
from src.db.models import GeoCache
from src.db.session import SessionFactory

logger = logging.getLogger(__name__)

#: Type alias for a resolved coordinate pair.
Coordinates = Tuple[float, float]


# ---------------------------------------------------------------------------
# Public geocoder
# ---------------------------------------------------------------------------

class CachingGeocoder:
    """
    Nominatim geocoder with transparent SQLite-backed result caching.

    Parameters
    ----------
    user_agent:
        HTTP User-Agent string sent to Nominatim.  Must be unique and
        descriptive per Nominatim's terms of service.
    timeout:
        Per-request timeout in seconds.
    delay:
        Minimum sleep duration (seconds) enforced between HTTP requests
        to respect Nominatim's 1 req/s rate limit.
    """

    def __init__(
        self,
        user_agent: str = settings.GEOCODER_USER_AGENT,
        timeout: int = settings.GEOCODER_TIMEOUT,
        delay: float = settings.GEOCODER_DELAY,
    ) -> None:
        self._geolocator = Nominatim(user_agent=user_agent, timeout=timeout)
        self._delay = delay

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def resolve(self, location: str) -> Optional[Coordinates]:
        """
        Resolve a human-readable location string to WGS-84 coordinates.

        The lookup order is: cache hit → Nominatim HTTP → cache write.

        Parameters
        ----------
        location:
            Any location description accepted by Nominatim (city name,
            postcode, address, region, …).

        Returns
        -------
        tuple[float, float] or None
            ``(latitude, longitude)`` on success; ``None`` when the
            location cannot be resolved (including previously failed
            attempts stored in the cache).
        """
        normalised = _normalise(location)
        if not normalised:
            return None

        # 1. Cache look-up.
        cached = self._cache_get(normalised)
        if cached is not None:
            lat, lon = cached
            if lat is None:
                logger.debug("Cache miss-negative for %r — skipping.", normalised)
                return None
            logger.debug("Cache hit for %r → (%s, %s).", normalised, lat, lon)
            return lat, lon

        # 2. Nominatim HTTP call (rate-limited).
        coords = self._geocode_remote(normalised)
        self._cache_set(normalised, coords)
        return coords

    def resolve_many(
        self,
        locations: list[str],
    ) -> dict[str, Optional[Coordinates]]:
        """
        Resolve multiple location strings, respecting the rate limit.

        Parameters
        ----------
        locations:
            Sequence of location strings to resolve.

        Returns
        -------
        dict[str, Coordinates | None]
            Mapping from each input string to its resolved coordinates
            (or ``None`` on failure).
        """
        results: dict[str, Optional[Coordinates]] = {}
        unique = list(dict.fromkeys(loc for loc in locations if loc))

        for loc in unique:
            results[loc] = self.resolve(loc)

        return results

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_get(
        self, location: str
    ) -> Optional[Tuple[Optional[float], Optional[float]]]:
        """
        Return the cached entry for *location*, or ``None`` on a cache miss.

        A return value of ``(None, None)`` (distinct from a Python ``None``
        return) indicates a previously recorded failed lookup.
        """
        with SessionFactory() as session:
            row: Optional[GeoCache] = session.get(GeoCache, location)
            if row is None:
                return None  # Genuine cache miss.
            return row.latitude, row.longitude

    def _cache_set(
        self, location: str, coords: Optional[Coordinates]
    ) -> None:
        """
        Persist a geocoding result (successful or failed) to the cache.

        Parameters
        ----------
        location:
            Normalised location string (cache key).
        coords:
            ``(lat, lon)`` on success; ``None`` to record a failed lookup.
        """
        lat, lon = coords if coords else (None, None)
        with SessionFactory() as session:
            entry = session.get(GeoCache, location)
            if entry is None:
                entry = GeoCache(location=location, latitude=lat, longitude=lon)
                session.add(entry)
            else:
                entry.latitude = lat
                entry.longitude = lon
            session.commit()

    # ------------------------------------------------------------------
    # Remote geocoding
    # ------------------------------------------------------------------

    def _geocode_remote(self, location: str) -> Optional[Coordinates]:
        """
        Perform a live Nominatim HTTP lookup with rate-limit enforcement.

        Parameters
        ----------
        location:
            Normalised location string to resolve.

        Returns
        -------
        tuple[float, float] or None
            Resolved coordinates, or ``None`` on failure / no result.
        """
        time.sleep(self._delay)

        try:
            result = self._geolocator.geocode(location)
        except GeocoderTimedOut:
            logger.warning("Nominatim timed out for %r.", location)
            return None
        except GeocoderServiceError as exc:
            logger.error("Nominatim service error for %r: %s", location, exc)
            return None

        if result is None:
            logger.debug("Nominatim returned no result for %r.", location)
            return None

        logger.debug(
            "Resolved %r → (%.6f, %.6f).", location, result.latitude, result.longitude
        )
        return result.latitude, result.longitude


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise(location: str) -> str:
    """
    Strip and lower-case a location string for consistent cache keying.

    Parameters
    ----------
    location:
        Raw location string.

    Returns
    -------
    str
        Normalised key (may be empty if the input was blank).
    """
    return location.strip().lower()
