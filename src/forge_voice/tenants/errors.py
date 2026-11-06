"""Tenant configuration errors."""

from __future__ import annotations


class TenantConfigError(ValueError):
    """A tenant configuration is missing, malformed or internally inconsistent."""


class UnknownTenantError(TenantConfigError):
    """No configured tenant matches the requested slug."""


class UnknownServiceError(TenantConfigError):
    """A tenant does not offer the requested service."""
