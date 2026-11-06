"""Fail-closed tenant config loading."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from forge_voice.tenants.errors import TenantConfigError, UnknownTenantError
from forge_voice.tenants.models import TenantConfig

SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def load_tenant(path: Path) -> TenantConfig:
    """Load and validate one tenant YAML.

    The file stem must equal `tenant_id`. Any YAML, schema or cross-reference problem raises
    `TenantConfigError`; no partially validated tenant is returned.
    """
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TenantConfigError(f"cannot read tenant config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise TenantConfigError(f"invalid YAML in tenant config {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise TenantConfigError(f"tenant config {path} must be a YAML mapping")

    tenant_id = raw.get("tenant_id")
    if not isinstance(tenant_id, str) or not SLUG_RE.fullmatch(tenant_id):
        raise TenantConfigError(f"tenant config {path} has a missing or invalid tenant_id")
    if path.stem != tenant_id:
        raise TenantConfigError(
            f"tenant config filename {path.name!r} does not match tenant_id {tenant_id!r}"
        )

    try:
        return TenantConfig.model_validate(raw)
    except ValidationError as exc:
        raise TenantConfigError(f"invalid tenant config {path}: {exc}") from exc


def load_tenant_by_slug(tenants_dir: Path, slug: str) -> TenantConfig:
    """Resolve exactly `tenants/<slug>.yaml`; never guess or fall back."""
    if not SLUG_RE.fullmatch(slug):
        raise UnknownTenantError(f"unknown tenant {slug!r}")
    path = Path(tenants_dir) / f"{slug}.yaml"
    if not path.is_file():
        raise UnknownTenantError(f"unknown tenant {slug!r}: {path} does not exist")
    config = load_tenant(path)
    if config.tenant_id != slug:
        raise TenantConfigError(
            f"tenant {slug!r} resolved to config for tenant {config.tenant_id!r}"
        )
    return config


def load_all_tenants(tenants_dir: Path) -> dict[str, TenantConfig]:
    """Load every `*.yaml` tenant file, rejecting duplicates or invalid configs."""
    tenants_dir = Path(tenants_dir)
    if not tenants_dir.is_dir():
        raise TenantConfigError(f"tenant directory {tenants_dir} does not exist")

    registry: dict[str, TenantConfig] = {}
    paths = sorted(tenants_dir.glob("*.yaml"))
    if not paths:
        raise TenantConfigError(f"no tenant configs found in {tenants_dir}")

    for path in paths:
        config = load_tenant(path)
        if config.tenant_id in registry:
            raise TenantConfigError(f"duplicate tenant_id {config.tenant_id!r}")
        registry[config.tenant_id] = config
    return registry
