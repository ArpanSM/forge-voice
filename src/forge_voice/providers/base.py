"""Provider-neutral chat seam for LFM3 and Groq.

Transport is injected so unit tests never open a socket. The provider owns request shaping and
response parsing; a concrete HTTP transport owns the network.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ProviderError(RuntimeError):
    """A provider call failed or returned an unusable response."""


class ProviderNotConfiguredError(ProviderError):
    """A network profile was selected without an injected transport or base URL."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatMessage(StrictModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class ToolSpec(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolCall(StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class ProviderUsage(StrictModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ProviderRequest(StrictModel):
    messages: list[ChatMessage] = Field(min_length=1)
    tools: list[ToolSpec] = Field(default_factory=list)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, gt=0)
    seed: int = 0
    request_id: str = Field(default="req_local", min_length=1)


class ProviderResponse(StrictModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "length"] = "stop"
    provider: str = "fake"
    model: str = "fake-1"
    usage: ProviderUsage = Field(default_factory=ProviderUsage)


class ProviderSettings(StrictModel):
    provider: Literal["fake", "lfm3", "groq"]
    model: str = Field(min_length=1)
    base_url: str | None = None
    timeout_seconds: float = Field(default=3.0, gt=0.0)


class ChatProvider(Protocol):
    @property
    def name(self) -> str: ...

    def complete(self, request: ProviderRequest) -> ProviderResponse: ...


class HttpTransport(Protocol):
    def post_json(
        self,
        url: str,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]: ...
