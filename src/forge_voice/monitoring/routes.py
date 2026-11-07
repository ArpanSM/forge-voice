"""FastAPI routes for the read-only local dashboard."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from forge_voice.monitoring.filters import CallFilters
from forge_voice.monitoring.page import (
    render_call_detail_page,
    render_dashboard_page,
    render_review_page,
)
from forge_voice.monitoring.service import MonitoringService
from forge_voice.policy.state import CallOutcome

HTMX_PATH = Path(__file__).resolve().parents[1] / "web" / "static" / "htmx.min.js"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "testserver"})


def _require_safe_post(request: Request) -> None:
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


def register_dashboard_routes(app: FastAPI, service: MonitoringService) -> None:
    @app.get("/static/htmx.min.js", response_class=FileResponse)
    async def htmx_client() -> FileResponse:
        return FileResponse(HTMX_PATH, media_type="text/javascript")

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        filters = _parse_filters(request)
        alerts = service.alerts()
        metrics = service.metrics(filters)
        records = service.calls(filters)
        return HTMLResponse(
            render_dashboard_page(
                metrics=metrics,
                records=records,
                filters=filters,
                alerts=alerts,
                tenant_names=service.tenant_options(),
                profile=service.profile,
                htmx=True,
            )
        )

    @app.get("/calls/{call_id}", response_class=HTMLResponse)
    async def call_detail(call_id: str) -> HTMLResponse:
        record = service.call(call_id)
        if record is None:
            raise HTTPException(status_code=404, detail="call_not_found")
        return HTMLResponse(
            render_call_detail_page(
                record=record,
                tenant_name=service.tenant_name(record.tenant_id),
            )
        )

    @app.get("/metrics.json")
    async def metrics(request: Request) -> JSONResponse:
        return JSONResponse(service.metrics(_parse_filters(request)))

    @app.get("/review", response_class=HTMLResponse)
    async def review() -> HTMLResponse:
        return HTMLResponse(
            render_review_page(
                records=service.weekly_sample(),
                marked=service.review_state(),
                candidates=[path.name for path in service.candidates()],
                tenant_names=service.tenant_options(),
            )
        )

    @app.post("/alerts/refresh")
    async def refresh_alerts(request: Request) -> RedirectResponse:
        _require_safe_post(request)
        service.sync_traces()
        service.refresh_alerts(notify=True)
        return RedirectResponse(url="/dashboard", status_code=303)

    @app.post("/review/mark")
    async def mark_review(
        request: Request,
        call_id: str = Query(min_length=1),
    ) -> RedirectResponse:
        _require_safe_post(request)
        try:
            service.mark_review(call_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_call_id") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="call_not_found") from exc
        return RedirectResponse(url="/review", status_code=303)

    @app.post("/review/candidate")
    async def create_candidate(
        request: Request,
        call_id: str = Query(min_length=1),
    ) -> RedirectResponse:
        _require_safe_post(request)
        try:
            service.create_scenario_candidate(call_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_call_id") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="call_not_found") from exc
        return RedirectResponse(url="/review", status_code=303)


def _parse_filters(request: Request) -> CallFilters:
    params = request.query_params
    try:
        from_date = _date(params.get("from"))
        to_date = _date(params.get("to"))
        outcome = CallOutcome(params["outcome"]) if params.get("outcome") else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    tenant = params.get("tenant") or None
    return CallFilters(
        tenant=tenant,
        from_date=from_date,
        to_date=to_date,
        outcome=outcome,
    )


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
