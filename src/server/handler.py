# -*- coding: utf-8 -*-
"""
src/server/handler.py
=====================
HTTP request handler and route definitions for the JobMap local server.

This module wires the :class:`Router` to concrete handler functions,
implementing the following API surface:

====================  ========  =============================================
Path                  Method    Description
====================  ========  =============================================
``/``                 GET       Serve the ``map.html`` single-page application
``/api/params``       GET       Return current ``params.json`` as JSON
``/api/params``       POST      Update ``params.json`` from a JSON body
``/api/jobs``         GET       Return all geocoded jobs as GeoJSON
``/api/fetch``        POST      Run the ingestion pipeline synchronously
====================  ========  =============================================

Threading note
~~~~~~~~~~~~~~
The server is started with :class:`~http.server.ThreadingHTTPServer`;
each request runs in its own thread.  SQLAlchemy sessions are scoped
per-call (context-manager pattern), so concurrent access is safe.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict

from config import settings
from src.export.geojson import jobs_as_geojson
from src.server.router import Router

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level router (routes registered at import time)
# ---------------------------------------------------------------------------

router = Router()

# Serialize pipeline executions to prevent concurrent ingest runs.
_pipeline_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _send_json(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    """
    Serialise *payload* to JSON and write a complete HTTP response.

    ``Cache-Control: no-store`` is set unconditionally so that browsers
    and proxies never serve a stale API response from cache.

    Parameters
    ----------
    handler:
        Active request handler.
    payload:
        JSON-serialisable Python object.
    status:
        HTTP status code (default: 200).
    """
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _send_html(handler: BaseHTTPRequestHandler, html: bytes) -> None:
    """Write a complete HTML response."""
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(html)))
    handler.end_headers()
    handler.wfile.write(html)


def _send_error(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
    """Write a JSON error response."""
    _send_json(handler, {"error": message}, status=status)


def _read_body_json(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    """
    Read and parse the request body as JSON.

    Returns
    -------
    dict
        Parsed JSON payload, or an empty dict on parse failure.
    """
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Received malformed JSON body.")
        return {}


# ---------------------------------------------------------------------------
# Route: GET /
# ---------------------------------------------------------------------------

@router.route("GET", "/")
def serve_index(handler: BaseHTTPRequestHandler) -> None:
    """
    Serve the ``map.html`` single-page application.

    The file is read from disk on every request, so changes to the
    template are reflected immediately without restarting the server.
    """
    template: Path = settings.TEMPLATE_PATH
    if not template.exists():
        _send_error(handler, 404, f"Template not found: {template}")
        return

    html = template.read_bytes()
    _send_html(handler, html)


# ---------------------------------------------------------------------------
# Route: GET /api/params
# ---------------------------------------------------------------------------

@router.route("GET", "/api/params")
def get_params(handler: BaseHTTPRequestHandler) -> None:
    """Return the current search parameters from ``params.json``."""
    try:
        content = json.loads(settings.PARAMS_PATH.read_text(encoding="utf-8"))
        _send_json(handler, content)
    except Exception as exc:
        logger.exception("Failed to read params.json: %s", exc)
        _send_error(handler, 500, "Could not read parameters file.")


# ---------------------------------------------------------------------------
# Route: POST /api/params
# ---------------------------------------------------------------------------

@router.route("POST", "/api/params")
def update_params(handler: BaseHTTPRequestHandler) -> None:
    """
    Overwrite ``params.json`` with the JSON body of the request.

    The ``_comment`` key is preserved if already present.  All other
    keys from the incoming body replace existing values entirely.
    """
    incoming = _read_body_json(handler)
    if not incoming:
        _send_error(handler, 400, "Empty or invalid JSON body.")
        return

    try:
        existing = json.loads(settings.PARAMS_PATH.read_text(encoding="utf-8"))
    except Exception:
        existing = {}

    # Preserve documentation comments already in the file.
    merged = {k: v for k, v in existing.items() if k.startswith("_")}
    merged.update(incoming)

    settings.PARAMS_PATH.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("params.json updated: %s", incoming)
    _send_json(handler, {"status": "ok", "params": merged})


# ---------------------------------------------------------------------------
# Route: GET /api/jobs
# ---------------------------------------------------------------------------

@router.route("GET", "/api/jobs")
def get_jobs(handler: BaseHTTPRequestHandler) -> None:
    """Return all geocoded jobs from the database as a GeoJSON FeatureCollection."""
    try:
        geojson = jobs_as_geojson()
        _send_json(handler, geojson)
    except Exception as exc:
        logger.exception("Failed to export jobs: %s", exc)
        _send_error(handler, 500, "Could not export jobs.")


# ---------------------------------------------------------------------------
# Route: POST /api/fetch
# ---------------------------------------------------------------------------

@router.route("POST", "/api/fetch")
def trigger_fetch(handler: BaseHTTPRequestHandler) -> None:
    """
    Synchronously run the full ingestion pipeline.

    Concurrent fetch requests are serialised via ``_pipeline_lock`` to
    prevent race conditions on the database.  A second request received
    while a pipeline run is in progress will receive a 409 Conflict.
    """
    if not _pipeline_lock.acquire(blocking=False):
        _send_error(handler, 409, "A fetch operation is already in progress.")
        return

    try:
        # Import here to avoid circular imports at module load time.
        from src.pipeline.ingest import run as run_pipeline  # noqa: PLC0415
        summary = run_pipeline()
        _send_json(handler, {"status": "ok", "summary": summary})
    except Exception as exc:
        logger.exception("Pipeline execution failed: %s", exc)
        _send_error(handler, 500, f"Pipeline error: {exc}")
    finally:
        _pipeline_lock.release()


# ---------------------------------------------------------------------------
# Handler class
# ---------------------------------------------------------------------------

class JobMapHandler(BaseHTTPRequestHandler):
    """
    ``http.server`` request handler for the JobMap application.

    All routing is delegated to the module-level :data:`router` instance.
    Unmatched routes receive a standard 404 JSON response.
    """

    # Suppress the default per-request stdout logging; we use our own.
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D102
        logger.debug(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        """Dispatch GET requests through the router."""
        if not router.dispatch(self):
            _send_error(self, 404, f"No route for GET {self.path}")

    def do_POST(self) -> None:  # noqa: N802
        """Dispatch POST requests through the router."""
        if not router.dispatch(self):
            _send_error(self, 404, f"No route for POST {self.path}")

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight requests permissively (localhost use only)."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
