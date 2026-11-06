"""OpenAI-compatible chat adapter used by both LFM3 and Groq profiles.

Only request shaping and response parsing live here. Network I/O is delegated to an injected
`HttpTransport`, which keeps unit tests offline and makes the same adapter usable against the
local LFM3 server or Groq.
"""

from __future__ import annotations

import json
from typing import Any

from forge_voice.providers.base import (
    HttpTransport,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderRequest,
    ProviderResponse,
    ProviderSettings,
    ProviderUsage,
    ToolCall,
)

VALID_FINISH_REASONS = {"stop", "tool_calls", "length"}


class OpenAICompatibleProvider:
    def __init__(self, *, settings: ProviderSettings, transport: HttpTransport) -> None:
        self._settings = settings
        self._transport = transport

    @property
    def name(self) -> str:
        return self._settings.provider

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        if not self._settings.base_url:
            raise ProviderNotConfiguredError(
                f"{self._settings.provider} requires provider.base_url"
            )
        url = f"{self._settings.base_url.rstrip('/')}/chat/completions"
        payload = self._payload(request)
        try:
            raw = self._transport.post_json(
                url,
                payload=payload,
                headers={"Content-Type": "application/json"},
                timeout_seconds=self._settings.timeout_seconds,
            )
        except ProviderError:
            raise
        except Exception as exc:  # transport failures become one stable provider error
            raise ProviderError(
                f"{self._settings.provider} transport failed: {type(exc).__name__}"
            ) from exc
        return self._parse(raw)

    def _payload(self, request: ProviderRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._settings.model,
            "messages": [message.model_dump(exclude_none=True) for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "seed": request.seed,
            "stream": False,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
        return payload

    def _parse(self, raw: dict[str, Any]) -> ProviderResponse:
        try:
            choice = raw["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self._settings.provider} returned no usable choice") from exc

        tool_calls = [
            self._parse_tool_call(tool_call) for tool_call in message.get("tool_calls") or []
        ]
        finish_reason = choice.get("finish_reason")
        if finish_reason not in VALID_FINISH_REASONS:
            finish_reason = "tool_calls" if tool_calls else "stop"

        usage_raw = raw.get("usage") or {}
        usage = ProviderUsage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
            completion_tokens=int(usage_raw.get("completion_tokens", 0)),
            total_tokens=int(usage_raw.get("total_tokens", 0)),
        )
        return ProviderResponse(
            text=message.get("content") or "",
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            provider=self._settings.provider,
            model=self._settings.model,
            usage=usage,
        )

    def _parse_tool_call(self, raw: dict[str, Any]) -> ToolCall:
        try:
            function = raw["function"]
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                raise TypeError("tool arguments must decode to an object")
            return ToolCall(
                id=raw["id"],
                name=function["name"],
                arguments=arguments,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError(f"{self._settings.provider} returned an invalid tool call") from exc
