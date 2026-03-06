# -*- coding: utf-8 -*-
"""
src/server/router.py
====================
Minimal, decorator-based HTTP router for the stdlib ``http.server`` layer.

Design goals
------------
- Zero third-party dependencies (stdlib only).
- Explicit, readable route registration via the :meth:`Router.route`
  decorator — identical in spirit to Flask's ``@app.route``, but backed
  by a simple dictionary lookup.
- Clean separation between routing logic and handler logic; the
  :class:`~src.server.handler.JobMapHandler` delegates to this router
  rather than containing a monolithic ``do_GET``/``do_POST`` block.

Usage
-----
    router = Router()

    @router.route("GET", "/api/jobs")
    def get_jobs(handler):
        ...

    # In the HTTP handler:
    router.dispatch(handler)
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: Type alias for a route handler callable.
#: Receives the :class:`~http.server.BaseHTTPRequestHandler` instance.
RouteHandler = Callable[["http.server.BaseHTTPRequestHandler"], None]  # type: ignore[name-defined]


class Router:
    """
    Registry mapping ``(method, path)`` pairs to handler callables.

    Attributes
    ----------
    _routes:
        Internal mapping: ``(METHOD, /path)`` → handler function.
    """

    def __init__(self) -> None:
        self._routes: Dict[Tuple[str, str], RouteHandler] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def route(
        self, method: str, path: str
    ) -> Callable[[RouteHandler], RouteHandler]:
        """
        Decorator that registers a handler for a specific method + path.

        Parameters
        ----------
        method:
            HTTP method (e.g. ``"GET"``, ``"POST"``).
        path:
            Exact URL path (e.g. ``"/api/jobs"``).

        Returns
        -------
        Callable
            The original handler function (unmodified).

        Example
        -------
        ::

            @router.route("GET", "/api/params")
            def get_params(handler):
                ...
        """
        def decorator(fn: RouteHandler) -> RouteHandler:
            key = (method.upper(), path)
            self._routes[key] = fn
            logger.debug("Registered route: %s %s → %s", method, path, fn.__name__)
            return fn

        return decorator

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(self, handler: object) -> bool:
        """
        Dispatch an incoming request to the registered handler.

        Parameters
        ----------
        handler:
            The active :class:`~http.server.BaseHTTPRequestHandler` instance.
            Expected to expose ``command`` (HTTP method) and ``path``
            attributes.

        Returns
        -------
        bool
            ``True`` if a matching route was found and invoked;
            ``False`` if no route matched (caller should send 404).
        """
        # Strip query string from path before matching.
        raw_path: str = getattr(handler, "path", "/")
        path = raw_path.split("?")[0]
        method: str = getattr(handler, "command", "GET").upper()

        key = (method, path)
        route_fn: Optional[RouteHandler] = self._routes.get(key)

        if route_fn is None:
            logger.debug("No route for %s %s.", method, path)
            return False

        logger.debug("Dispatching %s %s → %s.", method, path, route_fn.__name__)
        route_fn(handler)  # type: ignore[arg-type]
        return True
