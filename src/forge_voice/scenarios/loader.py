"""Fail-closed scenario manifest loading."""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

import yaml
from pydantic import ValidationError

from forge_voice.scenarios.models import ScenarioManifest


class ScenarioConfigError(ValueError):
    """The scenario manifest is missing, malformed or violates the locked split."""


def load_manifest(
    path: Path,
    *,
    known_tenants: Collection[str],
) -> ScenarioManifest:
    """Load a manifest and verify every tenant reference against the registry."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ScenarioConfigError(f"cannot read scenario manifest {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ScenarioConfigError(f"invalid YAML in scenario manifest {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ScenarioConfigError(f"scenario manifest {path} must be a YAML mapping")

    try:
        manifest = ScenarioManifest.model_validate(raw)
    except ValidationError as exc:
        raise ScenarioConfigError(f"invalid scenario manifest {path}: {exc}") from exc

    known = set(known_tenants)
    referenced = set(manifest.tenants) | {scenario.tenant for scenario in manifest.scenarios}
    unknown = referenced - known
    if unknown:
        raise ScenarioConfigError(
            f"scenario manifest references unknown tenant(s): {sorted(unknown)}"
        )
    return manifest
