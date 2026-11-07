"""Validating tenant YAML editor served by the local FastAPI app.

The admin page edits exactly ``tenants/<slug>.yaml``. It validates the whole document
against the same tenant schema the agent loads, writes it atomically, then reloads the
in-process registry. An invalid edit is rejected before the file is touched, so a bad
paste can never leave the local demo unloadable. There is no workflow graph and no code
generation here.
"""

from __future__ import annotations

import contextlib
import html
import json
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from forge_voice.monitoring.atomic import atomic_write_text
from forge_voice.tenants import (
    TenantConfig,
    TenantConfigError,
    UnknownTenantError,
    load_all_tenants,
)
from forge_voice.tenants.loader import SLUG_RE
from forge_voice.web.local_access import require_safe_post

MAX_ADMIN_BODY_BYTES = 2_000_000


class TenantAdminService:
    """Own the mutable tenant registry and the validated YAML writes behind it."""

    def __init__(
        self,
        tenants_dir: Path | str,
        *,
        on_reload: Callable[[], None] | None = None,
    ) -> None:
        self.tenants_dir = Path(tenants_dir).resolve()
        self._on_reload = on_reload
        self._configs = load_all_tenants(self.tenants_dir)

    def configs(self) -> dict[str, TenantConfig]:
        return dict(self._configs)

    def slugs(self) -> list[str]:
        return sorted(self._configs)

    def default_slug(self) -> str:
        slugs = self.slugs()
        if not slugs:
            raise TenantConfigError(f"no tenant configs found in {self.tenants_dir}")
        return slugs[0]

    def read_yaml(self, slug: str) -> str:
        self._require_known(slug)
        try:
            return self._path(slug).read_text(encoding="utf-8")
        except OSError as exc:
            raise TenantConfigError(f"cannot read tenant config {slug!r}: {exc}") from exc

    def validate_yaml(self, slug: str, text: str) -> TenantConfig:
        self._require_known(slug)
        if not isinstance(text, str) or not text.strip():
            raise TenantConfigError("tenant config must not be empty")
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise TenantConfigError(f"invalid YAML: {exc}") from exc
        if not isinstance(raw, dict):
            raise TenantConfigError("tenant config must be a YAML mapping")
        tenant_id = raw.get("tenant_id")
        if tenant_id != slug:
            raise TenantConfigError(
                f"tenant_id must stay {slug!r}; this page cannot rename or create tenants"
            )
        try:
            return TenantConfig.model_validate(raw)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in error['loc']) or 'config'}: {error['msg']}"
                for error in exc.errors()
            )
            raise TenantConfigError(f"schema validation failed: {details}") from exc

    def save(self, slug: str, text: str) -> TenantConfig:
        """Validate, write atomically and reload; never leave a partial or invalid file."""
        config = self.validate_yaml(slug, text)
        path = self._path(slug)
        try:
            original = path.read_text(encoding="utf-8")
            mode = path.stat().st_mode & 0o777
        except OSError as exc:
            raise TenantConfigError(f"cannot read tenant config {slug!r}: {exc}") from exc
        payload = text if text.endswith("\n") else f"{text}\n"
        atomic_write_text(path, payload)
        try:
            path.chmod(mode)
            self.reload()
        except BaseException:
            atomic_write_text(path, original)
            path.chmod(mode)
            # Keep the original validation/reload error; the file is already restored.
            with contextlib.suppress(Exception):
                self.reload()
            raise
        return config

    def reload(self) -> dict[str, TenantConfig]:
        configs = load_all_tenants(self.tenants_dir)
        self._configs = configs
        if self._on_reload is not None:
            self._on_reload()
        return configs

    def _require_known(self, slug: str) -> None:
        if not SLUG_RE.fullmatch(slug) or slug not in self._configs:
            raise UnknownTenantError(f"unknown tenant {slug!r}")

    def _path(self, slug: str) -> Path:
        self._require_known(slug)
        return self.tenants_dir / f"{slug}.yaml"


def register_admin_routes(app: FastAPI, service: TenantAdminService) -> None:
    @app.get("/admin", response_class=HTMLResponse)
    async def admin_index(
        tenant: str | None = None,
        saved: str | None = None,
        error: str | None = None,
    ) -> HTMLResponse:
        slug = tenant or service.default_slug()
        return _page(service, slug, saved=bool(saved), error=error)

    @app.get("/admin/{slug}", response_class=HTMLResponse)
    async def admin_tenant(
        slug: str,
        saved: str | None = None,
        error: str | None = None,
    ) -> HTMLResponse:
        return _page(service, slug, saved=bool(saved), error=error)

    @app.post("/admin/{slug}", response_model=None)
    async def admin_save(slug: str, request: Request) -> HTMLResponse | RedirectResponse:
        require_safe_post(request)
        try:
            text = await _form_yaml(request)
        except ValueError as exc:
            return _page(service, slug, error=str(exc), status_code=400)
        try:
            service.save(slug, text)
        except UnknownTenantError as exc:
            raise HTTPException(status_code=404, detail="unknown_tenant") from exc
        except TenantConfigError as exc:
            return _page(service, slug, error=str(exc), status_code=400)
        return RedirectResponse(url=f"/admin/{slug}?saved=1", status_code=303)


async def _form_yaml(request: Request) -> str:
    body = await request.body()
    if len(body) > MAX_ADMIN_BODY_BYTES:
        raise ValueError("tenant config is too large for the local admin page")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    raw = body.decode("utf-8", errors="replace")
    if content_type == "application/json":
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("yaml"), str):
            raise ValueError("JSON body must contain a string 'yaml' field")
        return payload["yaml"]
    values = parse_qs(raw, keep_blank_values=True)
    text = values.get("yaml")
    if not text:
        raise ValueError("form body must contain a 'yaml' field")
    return text[0]


def _page(
    service: TenantAdminService,
    slug: str,
    *,
    saved: bool = False,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    try:
        text = service.read_yaml(slug)
    except UnknownTenantError as exc:
        raise HTTPException(status_code=404, detail="unknown_tenant") from exc
    body = render_admin_page(
        configs=service.configs(),
        slug=slug,
        yaml_text=text,
        saved=saved,
        error=error,
    )
    return HTMLResponse(body, status_code=status_code)


def render_admin_page(
    *,
    configs: dict[str, TenantConfig],
    slug: str,
    yaml_text: str,
    saved: bool,
    error: str | None,
) -> str:
    links = "".join(
        f'<a class="tenant{" active" if tenant_id == slug else ""}" '
        f'href="/admin/{html.escape(tenant_id, quote=True)}">'
        f"{html.escape(config.display_name)}</a>"
        for tenant_id, config in sorted(configs.items())
    )
    banner = ""
    if saved:
        banner = (
            '<div class="banner ok" role="status">Saved and reloaded. New calls use this '
            "config.</div>"
        )
    if error:
        banner += (
            '<div class="banner bad" role="alert"><strong>Not saved.</strong> '
            f"<pre>{html.escape(error)}</pre></div>"
        )
    current = configs[slug]
    return (
        _ADMIN_PAGE.replace("__TENANT_LINKS__", links)
        .replace("__CURRENT_TENANT__", html.escape(current.display_name))
        .replace("__CURRENT_SLUG__", html.escape(slug, quote=True))
        .replace("__YAML__", html.escape(yaml_text))
        .replace("__BANNER__", banner)
    )


_ADMIN_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Forge Voice — tenant admin</title>
  <link rel="icon" href="data:," />
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { max-width: 1080px; margin: 28px auto; padding: 0 20px; line-height: 1.5; }
    a { color: #2f7ed8; }
    .top { display: flex; flex-wrap: wrap; gap: 12px; align-items: baseline; }
    .top nav { display: flex; gap: 10px; margin-left: auto; }
    .tenant { padding: 6px 10px; border: 1px solid #8884; border-radius: 999px;
      text-decoration: none; }
    .tenant.active { background: #2f7ed822; border-color: #2f7ed8; }
    .banner { padding: 10px 12px; border-radius: 8px; margin: 14px 0; }
    .banner.ok { background: #2c9a5e22; border: 1px solid #2c9a5e; }
    .banner.bad { background: #d9534f22; border: 1px solid #d9534f; }
    .banner pre { white-space: pre-wrap; margin: 6px 0 0; }
    textarea { width: 100%; min-height: 62vh; box-sizing: border-box; padding: 12px;
      font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; border-radius: 8px;
      border: 1px solid #8884; background: #8881; color: inherit; }
    button { padding: 10px 16px; font: inherit; border-radius: 8px; cursor: pointer; }
    .hint { color: #777; }
    code { background: #8881; padding: 1px 5px; border-radius: 4px; }
  </style>
</head>
<body>
  <div class="top">
    <div>
      <h1 style="margin:0">Tenant admin</h1>
      <p class="hint" style="margin:4px 0 0">Editing <strong>__CURRENT_TENANT__</strong>
      · local only · validated before write</p>
    </div>
    <nav>__TENANT_LINKS__</nav>
  </div>

  __BANNER__

  <p>Edit identity, persona and voice, hours and holidays, services and price ranges,
  service area and ZIPs, transfer targets, calendar/CRM/SMS adapter endpoints, the
  knowledge base and emergency rules. Advanced fields stay editable as YAML. This page
  never changes code, the workflow graph or tenant ids; new tenants and services are
  change requests.</p>

  <form method="post" action="/admin/__CURRENT_SLUG__">
    <textarea id="yaml" name="yaml" spellcheck="false" aria-label="Tenant YAML">__YAML__</textarea>
    <p><button type="submit">Validate, save and reload</button>
    <span class="hint">Invalid YAML or schema is rejected without touching the live
    config.</span></p>
  </form>

  <p class="hint">Routes: <a href="/">browser demo</a> ·
  <a href="/dashboard">dashboard</a> · <a href="/health">health</a></p>
</body>
</html>
"""
