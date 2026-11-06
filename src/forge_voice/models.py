"""Shared Pydantic base for strict configuration and fixture models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Reject unknown fields on configuration, manifest and seed models."""

    model_config = ConfigDict(extra="forbid")
