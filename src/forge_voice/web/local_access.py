"""Shared local-only access checks for the browser, dashboard and admin routes."""

from __future__ import annotations

from urllib.parse import SplitResult, urlparse

from fastapi import HTTPException, Request

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "testserver"})
DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin_parts(parsed: SplitResult) -> tuple[str, str, int | None]:
    scheme = parsed.scheme.lower()
    return (
        scheme,
        (parsed.hostname or "").lower(),
        parsed.port or DEFAULT_PORTS.get(scheme),
    )


def require_safe_post(request: Request) -> None:
    """Reject cross-origin state changes unless the full origin matches the local app."""
    host = (request.url.hostname or "").lower()
    if host not in LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="local_only")
    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        try:
            same_origin = _origin_parts(parsed) == _origin_parts(request.url)
        except ValueError:
            same_origin = False
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in LOCAL_HOSTS
            or parsed.username
            or parsed.password
            or not same_origin
        ):
            raise HTTPException(status_code=403, detail="cross_origin_post")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status_code=403, detail="cross_origin_post")
