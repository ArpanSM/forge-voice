from __future__ import annotations

import socket
from typing import Any

import pytest

from forge_voice.providers import (
    ChatMessage,
    FakeProvider,
    ProviderNotConfiguredError,
    ProviderRequest,
    ProviderSettings,
    ToolSpec,
    build_provider,
)
from forge_voice.providers.openai_compatible import OpenAICompatibleProvider

TOOLS = [
    ToolSpec(
        name="get_availability",
        description="Return synthetic appointment slots.",
        parameters={"type": "object", "properties": {"zip": {"type": "string"}}},
    )
]


def _request(text: str = "I need a drain cleaning.", *, seed: int = 7) -> ProviderRequest:
    return ProviderRequest(
        messages=[
            ChatMessage(role="system", content="You are a booking agent."),
            ChatMessage(role="user", content=text),
        ],
        tools=TOOLS,
        seed=seed,
        request_id="req_test_0001",
    )


def test_fake_provider_returns_scripted_responses_in_order() -> None:
    provider = FakeProvider(
        [
            {"text": "Which ZIP is the service at?"},
            {"text": "I can offer Monday at 9.", "finish_reason": "stop"},
        ]
    )

    first = provider.complete(_request("Need a plumber."))
    second = provider.complete(_request("94107."))

    assert first.text == "Which ZIP is the service at?"
    assert second.text == "I can offer Monday at 9."
    assert first.provider == "fake"
    assert len(provider.calls) == 2
    assert provider.calls[1].messages[-1].content == "94107."


def test_fake_provider_default_reply_is_deterministic() -> None:
    def run() -> tuple[dict[str, Any], dict[str, Any]]:
        provider = FakeProvider()
        first = provider.complete(_request("First caller turn."))
        second = provider.complete(_request("Second caller turn."))
        return first.model_dump(), second.model_dump()

    first_run = run()
    second_run = run()

    assert first_run == second_run
    assert first_run[0]["text"].endswith("First caller turn.")
    assert first_run[1]["text"].endswith("Second caller turn.")


def test_fake_provider_works_with_network_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*args: object, **kwargs: object) -> None:
        raise AssertionError("FakeProvider attempted network access")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    provider = FakeProvider([{"text": "Offline response."}])

    response = provider.complete(_request())

    assert response.text == "Offline response."


def test_build_provider_returns_fake_for_fake_profile() -> None:
    provider = build_provider(ProviderSettings(provider="fake", model="fake-1"))

    assert isinstance(provider, FakeProvider)
    assert provider.complete(_request()).provider == "fake"


@pytest.mark.parametrize("profile", ["lfm3", "groq"])
def test_build_provider_requires_injected_transport_for_network_profiles(profile: str) -> None:
    with pytest.raises(ProviderNotConfiguredError, match=profile):
        build_provider(
            ProviderSettings(
                provider=profile,
                model="model-name",
                base_url="http://127.0.0.1:8082/v1",
            )
        )


class RecordingTransport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        url: str,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "url": url,
                "payload": payload,
                "headers": headers,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


def test_openai_compatible_provider_shapes_request_and_parses_tool_call() -> None:
    transport = RecordingTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_01",
                                "type": "function",
                                "function": {
                                    "name": "get_availability",
                                    "arguments": '{"zip": "94107"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        }
    )
    settings = ProviderSettings(
        provider="lfm3",
        model="lfm3-audio-2b",
        base_url="http://127.0.0.1:8082/v1",
        timeout_seconds=3.0,
    )
    provider = OpenAICompatibleProvider(settings=settings, transport=transport)

    response = provider.complete(_request())

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == "http://127.0.0.1:8082/v1/chat/completions"
    assert call["payload"]["model"] == "lfm3-audio-2b"
    assert call["payload"]["messages"][1]["content"] == "I need a drain cleaning."
    assert call["payload"]["tools"][0]["function"]["name"] == "get_availability"
    assert call["timeout_seconds"] == 3.0
    assert response.provider == "lfm3"
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].name == "get_availability"
    assert response.tool_calls[0].arguments == {"zip": "94107"}
    assert response.usage.total_tokens == 14
