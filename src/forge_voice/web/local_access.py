"""Shared local-only access checks for the browser, dashboard and admin routes."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import HTTPException, Request

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "testserver"})


def require_safe_post(request: Request) -> None:
    """Reject cross-origin state changes unless the Host is the local app."""
    host = (request.url.hostname or "").lower()
    if host not in LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="local_only")
    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in LOCAL_HOSTS
            or parsed.hostname != host
        ):
            raise HTTPException(status_code=403, detail="cross_origin_post")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status_code=403, detail="cross_origin_post")
