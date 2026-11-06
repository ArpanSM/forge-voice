"""The common result envelope and stable tool errors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import Field, model_validator

from forge_voice.errors import ErrorCode
from forge_voice.models import StrictModel


def sanitize_args(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: ("[redacted]" if key == "confirmation_token" else sanitize_args(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_args(item) for item in value]
    return value


class ToolError(StrictModel):
    code: ErrorCode
    message: str = Field(min_length=1)
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ToolResult(StrictModel):
    ok: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    request_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def envelope_is_consistent(self) -> ToolResult:
        if self.ok and self.error is not None:
            raise ValueError("a successful result cannot carry an error")
        if not self.ok and self.error is None:
            raise ValueError("a failed result must carry an error")
        return self

    @classmethod
    def success(cls, data: dict[str, Any], request_id: str) -> ToolResult:
        return cls(ok=True, data=data, request_id=request_id)

    @classmethod
    def failure(
        cls,
        code: ErrorCode,
        message: str,
        request_id: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> ToolResult:
        return cls(
            ok=False,
            error=ToolError(
                code=code,
                message=message,
                retryable=retryable,
                details=details or {},
            ),
            request_id=request_id,
        )
