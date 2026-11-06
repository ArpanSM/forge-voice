"""Shared Pydantic base and validation helpers for configuration and fixture models."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Reject unknown fields on configuration, manifest and seed models."""

    model_config = ConfigDict(extra="forbid")


def ensure_unique(
    values: Sequence[str],
    label: str,
    *,
    error_type: type[ValueError] = ValueError,
) -> None:
    """Raise when a sequence contains duplicate string values."""
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise error_type(f"duplicate {label}: {duplicates}")
