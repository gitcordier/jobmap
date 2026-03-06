# -*- coding: utf-8 -*-
"""
src/api/adzuna.py
=================
Typed, stateless client for the Adzuna Jobs Search API.

Responsibilities
----------------
- Construct authenticated API requests.
- Handle HTTP-level retry logic transparently.
- Paginate through result sets up to a configurable page ceiling.
- Deserialise raw JSON into typed :class:`RawJob` dataclasses.

This module contains **no persistence logic** — it is a pure I/O adapter.

Reference
---------
https://developer.adzuna.com/docs/search
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain value object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RawJob:
    """
    Immutable representation of a single Adzuna API job result.

    All fields map directly to Adzuna's JSON schema.  Downstream
    layers (geocoder, ORM) consume this type rather than raw dicts,
    making contracts explicit and changes localised.
    """

    id: str
    title: str
    company: Optional[str]
    location_display: Optional[str]
    description: str
    salary_min: Optional[float]
    salary_max: Optional[float]
    contract_type: Optional[str]
    category_label: Optional[str]
    redirect_url: str
    created: str


# ---------------------------------------------------------------------------
# HTTP session factory (internal)
# ---------------------------------------------------------------------------

def _build_session(
    *,
    retries: int = 3,
    backoff_factor: float = 0.6,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> requests.Session:
    """
    Construct a :class:`requests.Session` with automatic retry semantics.

    Parameters
    ----------
    retries:
        Total retry attempts per request before propagating the error.
    backoff_factor:
        Multiplier for exponential back-off between retries.
        Sleep duration formula: ``{backoff_factor} * (2 ** (retry_number - 1))``.
    status_forcelist:
        HTTP response status codes that trigger a retry.

    Returns
    -------
    requests.Session
        Session with a mounted :class:`HTTPAdapter` on both ``http://``
        and ``https://`` prefixes.
    """
    session = requests.Session()
    retry_policy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=list(status_forcelist),
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_policy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# ---------------------------------------------------------------------------
# Public API client
# ---------------------------------------------------------------------------

class AdzunaClient:
    """
    Stateless HTTP client for the Adzuna Jobs Search API.

    A single client instance can be reused across multiple :meth:`search`
    calls; the underlying ``requests.Session`` maintains a connection pool
    for efficiency.

    Parameters
    ----------
    app_id:
        Adzuna application identifier.
    app_key:
        Adzuna application secret.
    country:
        ISO 3166-1 alpha-2 country code used in API path segments.
    results_per_page:
        Number of results requested per API page (1–50).
    """

    def __init__(
        self,
        app_id: str = settings.ADZUNA_APP_ID,
        app_key: str = settings.ADZUNA_APP_KEY,
        country: str = settings.ADZUNA_COUNTRY,
        results_per_page: int = settings.ADZUNA_RESULTS_PER_PAGE,
    ) -> None:
        self._app_id = app_id
        self._app_key = app_key
        self._default_country = country
        self._results_per_page = min(results_per_page, 50)  # API hard cap
        self._session = _build_session()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(
        self,
        what: Optional[str] = None,
        where: Optional[str] = None,
        country: Optional[str] = None,
        salary_min: Optional[int] = None,
        salary_max: Optional[int] = None,
        contract_type: Optional[str] = None,
        category: Optional[str] = None,
        distance: Optional[int] = None,
        sort_by: Optional[str] = None,
        max_pages: int = settings.ADZUNA_MAX_PAGES,
        **extra: Any,
    ) -> List[RawJob]:
        """
        Search for jobs matching the supplied criteria.

        All parameters mirror the Adzuna API query-parameter names.
        ``None`` values are omitted from the outgoing request.

        Parameters
        ----------
        what:
            Free-text keywords (job title, skills, technologies, …).
        where:
            Geographic location string (city, postcode, region, …).
        country:
            ISO 3166-1 alpha-2 country code for the API path segment.
            Overrides the instance-level default when supplied.
        salary_min:
            Minimum annual salary in local currency.
        salary_max:
            Maximum annual salary in local currency.
        contract_type:
            Employment type: ``permanent`` | ``contract`` |
            ``part_time`` | ``full_time``.
        category:
            Adzuna category tag (e.g. ``"it-jobs"``).
        distance:
            Search radius in kilometres around *where*.
        sort_by:
            Result ordering: ``relevance`` | ``date`` | ``salary``.
        max_pages:
            Upper limit on pages consumed (each page = up to 50 results).
        **extra:
            Additional Adzuna query parameters forwarded verbatim.

        Returns
        -------
        list[RawJob]
            Flat list of all jobs across all consumed pages.
        """
        resolved_country = country or self._default_country
        accumulated: List[RawJob] = []

        for page_batch in self._paginate(
            country=resolved_country,
            what=what,
            where=where,
            salary_min=salary_min,
            salary_max=salary_max,
            contract_type=contract_type,
            category=category,
            distance=distance,
            sort_by=sort_by,
            max_pages=max_pages,
            **extra,
        ):
            accumulated.extend(page_batch)

        logger.info("search() → %d total jobs returned.", len(accumulated))
        return accumulated

    # ------------------------------------------------------------------
    # Pagination logic
    # ------------------------------------------------------------------

    def _paginate(
        self,
        max_pages: int,
        country: str,
        **search_params: Any,
    ) -> Iterator[List[RawJob]]:
        """
        Yield batches of :class:`RawJob` objects, one batch per API page.

        Iteration stops when the API returns an empty result set or when
        *max_pages* pages have been consumed, whichever comes first.

        Yields
        ------
        list[RawJob]
            Non-empty list of jobs for the current page.
        """
        for page_index in range(1, max_pages + 1):
            batch = self._fetch_page(page=page_index, country=country, **search_params)
            if not batch:
                logger.debug(
                    "Empty response on page %d — pagination complete.", page_index
                )
                return
            logger.info("Page %d/%d → %d jobs.", page_index, max_pages, len(batch))
            yield batch

    def _fetch_page(self, page: int, country: str, **params: Any) -> List[RawJob]:
        """
        Retrieve a single page of results from the Adzuna API.

        Parameters
        ----------
        page:
            1-based page index.
        country:
            ISO 3166-1 alpha-2 country code for the URL path segment.
        **params:
            Search parameters (``None`` values are stripped).

        Returns
        -------
        list[RawJob]
            Deserialised jobs on this page, or ``[]`` on any HTTP error.
        """
        url = f"{settings.ADZUNA_BASE_URL}/{country}/search/{page}"
        query: Dict[str, Any] = {
            "app_id": self._app_id,
            "app_key": self._app_key,
            "results_per_page": self._results_per_page,
            **{k: v for k, v in params.items() if v is not None},
        }

        try:
            response = self._session.get(url, params=query, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Adzuna API error (page %d): %s", page, exc)
            return []

        payload: Dict[str, Any] = response.json()
        return [self._deserialise(item) for item in payload.get("results", [])]

    # ------------------------------------------------------------------
    # Deserialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _deserialise(raw: Dict[str, Any]) -> RawJob:
        """
        Map a raw Adzuna JSON result object to a :class:`RawJob`.

        Nested objects (``company``, ``location``, ``category``) are
        flattened by extracting their ``display_name`` / ``label`` fields.

        Parameters
        ----------
        raw:
            Single item from the ``results`` array in an Adzuna response.

        Returns
        -------
        RawJob
            Typed, immutable job record.
        """
        return RawJob(
            id=str(raw["id"]),
            title=raw.get("title", "").strip(),
            company=raw.get("company", {}).get("display_name"),
            location_display=raw.get("location", {}).get("display_name"),
            description=raw.get("description", "").strip(),
            salary_min=raw.get("salary_min"),
            salary_max=raw.get("salary_max"),
            contract_type=raw.get("contract_type"),
            category_label=raw.get("category", {}).get("label"),
            redirect_url=raw.get("redirect_url", ""),
            created=raw.get("created", ""),
        )
