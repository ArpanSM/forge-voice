"""Local FastAPI browser page and signed tenant-token endpoint.

No tenant is accepted from an unsigned query parameter. The page posts a tenant
selection, the server signs a short-lived tenant claim into the LiveKit token
metadata, and the agent verifies that claim before any policy state exists.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import Field

from forge_voice.models import StrictModel
from forge_voice.monitoring.service import MonitoringService
from forge_voice.tenants import TenantConfig, load_all_tenants
from forge_voice.web.admin import TenantAdminService, register_admin_routes
from forge_voice.web.claims import DEFAULT_TTL_SECONDS, ClaimError, TenantClaimSigner
from forge_voice.web.local_access import LOCAL_HOSTS
from forge_voice.web.page import render_page

STATIC_DIR = Path(__file__).resolve().parent / "static"
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DEFAULT_LIVEKIT_URL = "ws://localhost:7880"


class TokenRequest(StrictModel):
    tenant: str = Field(min_length=1)
    identity: str | None = None


class MintedToken(StrictModel):
    url: str
    token: str


class TokenMinter(Protocol):
    def mint(
        self,
        *,
        room: str,
        identity: str,
        metadata: str,
        ttl_seconds: int,
    ) -> MintedToken: ...


class LiveKitTokenMinter:
    """Production minter; imports the LiveKit API only when the demo needs it."""

    def __init__(self, *, url: str, api_key: str, api_secret: str) -> None:
        self.url = url
        self._api_key = api_key
        self._api_secret = api_secret

    def mint(
        self,
        *,
        room: str,
        identity: str,
        metadata: str,
        ttl_seconds: int,
    ) -> MintedToken:
        from datetime import timedelta

        from livekit import api
        from livekit.protocol.agent_dispatch import RoomAgentDispatch
        from livekit.protocol.room import RoomConfiguration

        from forge_voice.config import AGENT_NAME

        grants = api.VideoGrants(
            room_join=True,
            room=room,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )
        token = (
            api.AccessToken(self._api_key, self._api_secret)
            .with_identity(identity)
            .with_name(identity)
            .with_metadata(metadata)
            .with_grants(grants)
            .with_room_config(RoomConfiguration(agents=[RoomAgentDispatch(agent_name=AGENT_NAME)]))
            .with_ttl(timedelta(seconds=ttl_seconds))
            .to_jwt()
        )
        return MintedToken(url=self.url, token=token)


def _safe_identity(value: str | None) -> str:
    if value and _IDENTITY_RE.fullmatch(value):
        return value
    return f"caller-{secrets.token_hex(4)}"


def create_app(
    *,
    tenants: Mapping[str, TenantConfig],
    minter: TokenMinter | None,
    claim_signer: TenantClaimSigner | None,
    livekit_url: str,
    now: Callable[[], datetime] | None = None,
    monitoring: MonitoringService | None = None,
    admin: TenantAdminService | None = None,
) -> FastAPI:
    app = FastAPI(title="forge-voice local browser")
    clock = now or (lambda: datetime.now(UTC))
    fallback = dict(sorted(tenants.items()))

    def current_tenants() -> dict[str, TenantConfig]:
        if admin is not None:
            return dict(sorted(admin.configs().items()))
        return fallback

    @app.middleware("http")
    async def local_only(request, call_next):
        host = (request.url.hostname or "").lower()
        if host not in LOCAL_HOSTS:
            return JSONResponse(status_code=403, content={"error": "local_only"})
        return await call_next(request)

    if monitoring is not None:
        from forge_voice.monitoring.routes import register_dashboard_routes

        register_dashboard_routes(app, monitoring)
    if admin is not None:
        register_admin_routes(app, admin)

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "ok": True,
            "tenants": sorted(current_tenants()),
            "livekit_url": livekit_url,
            "token_endpoint": "/token",
            "configured": bool(minter and claim_signer and livekit_url),
        }

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return render_page(
            [
                {"slug": slug, "name": tenant.display_name}
                for slug, tenant in current_tenants().items()
            ]
        )

    @app.get("/static/livekit-client.umd.min.js", response_class=FileResponse)
    async def livekit_client() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "livekit-client.umd.min.js",
            media_type="text/javascript",
        )

    @app.post("/token")
    async def token(body: TokenRequest) -> JSONResponse:
        tenant = current_tenants().get(body.tenant)
        if tenant is None:
            return JSONResponse(status_code=404, content={"error": "unknown_tenant"})
        if minter is None or claim_signer is None or not livekit_url:
            return JSONResponse(status_code=503, content={"error": "livekit_not_configured"})
        call_id = f"call_{secrets.token_hex(8)}"
        room = f"forge-voice-{tenant.tenant_id}-{call_id}"
        identity = _safe_identity(body.identity)
        signed = claim_signer.issue(
            tenant.tenant_id,
            call_id=call_id,
            room=room,
            now=clock(),
        )
        metadata = json.dumps(
            {"tenant": tenant.tenant_id, "tenant_claim": signed.token},
            sort_keys=True,
            separators=(",", ":"),
        )
        minted = minter.mint(
            room=room,
            identity=identity,
            metadata=metadata,
            ttl_seconds=claim_signer.ttl_seconds,
        )
        return JSONResponse(
            content={
                "tenant": tenant.tenant_id,
                "tenant_name": tenant.display_name,
                "call_id": call_id,
                "url": minted.url,
                "token": minted.token,
                "room": room,
                "identity": identity,
                "ttl_seconds": claim_signer.ttl_seconds,
                "expires_at": signed.claim.expires_at.isoformat(),
            }
        )

    return app


def create_app_from_env(
    root: Path | str | None = None,
    *,
    monitoring: MonitoringService | None = None,
) -> FastAPI:
    repository = Path(root).resolve() if root else Path(__file__).resolve().parents[3]
    from forge_voice.config import load_local_env

    load_local_env(repository)
    configured_host = os.environ.get("FORGE_VOICE_WEB_HOST", "127.0.0.1").strip()
    if configured_host not in LOCAL_HOSTS:
        raise SystemExit("forge-voice is local-only; bind to 127.0.0.1, localhost or ::1")
    tenants = load_all_tenants(repository / "tenants")
    url = os.environ.get("LIVEKIT_URL", DEFAULT_LIVEKIT_URL).strip()
    api_key = os.environ.get("LIVEKIT_API_KEY", "").strip()
    api_secret = os.environ.get("LIVEKIT_API_SECRET", "").strip()
    signer = None
    if api_secret:
        try:
            signer = TenantClaimSigner(api_secret, ttl_seconds=DEFAULT_TTL_SECONDS)
        except ClaimError:
            signer = None
    minter = None
    if url and api_key and api_secret:
        minter = LiveKitTokenMinter(url=url, api_key=api_key, api_secret=api_secret)
    if monitoring is None:
        profile = os.environ.get("FORGE_VOICE_PROFILE", "local").strip().lower()
        data_dir = Path(os.environ.get("FORGE_VOICE_DATA_DIR", repository / "data"))
        monitoring = MonitoringService(
            data_dir=data_dir,
            root=repository,
            profile="hybrid" if profile == "hybrid" else "local",
            seed=os.environ.get("FORGE_VOICE_DASHBOARD_SEED", "1") != "0",
        )
    admin = TenantAdminService(
        repository / "tenants",
        on_reload=monitoring.reload_tenants,
    )
    return create_app(
        tenants=tenants,
        minter=minter,
        claim_signer=signer,
        livekit_url=url,
        monitoring=monitoring,
        admin=admin,
    )


def main() -> None:
    import uvicorn

    host = os.environ.get("FORGE_VOICE_WEB_HOST", "127.0.0.1").strip()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("forge-voice is local-only; bind to 127.0.0.1, localhost or ::1")
    uvicorn.run(
        create_app_from_env(),
        host=host,
        port=int(os.environ.get("FORGE_VOICE_WEB_PORT", "8000")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
