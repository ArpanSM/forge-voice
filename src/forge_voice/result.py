"""Common result envelope shared by tools and scenario runs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1)
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ResultEnvelope[T](BaseModel):
    """One success/failure shape for every typed tool result.

    A success always carries `data`; a failure always carries `error`. The two are never both
    present, so callers cannot mistake a rejected write for a committed one.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: T | None = None
    error: ErrorInfo | None = None
    request_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def exactly_one_outcome(self) -> ResultEnvelope[T]:
        if self.ok:
            if self.data is None:
                raise ValueError("a successful envelope requires data")
            if self.error is not None:
                raise ValueError("a successful envelope must not carry an error")
        else:
            if self.error is None:
                raise ValueError("a failed envelope requires an error")
            if self.data is not None:
                raise ValueError("a failed envelope must not carry data")
        return self

    @classmethod
    def success(cls, data: T, *, request_id: str) -> ResultEnvelope[T]:
        return cls(ok=True, data=data, request_id=request_id)

    @classmethod
    def failure(
        cls,
        code: str,
        message: str,
        *,
        request_id: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> ResultEnvelope[T]:
        return cls(
            ok=False,
            error=ErrorInfo(
                code=code,
                message=message,
                retryable=retryable,
                details=details or {},
            ),
            request_id=request_id,
        )
