"""Deterministic, offline provider used by unit tests and fixtures."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from forge_voice.providers.base import (
    ProviderRequest,
    ProviderResponse,
)


class FakeProvider:
    """Return scripted responses in order, then a deterministic echo.

    No clock, randomness or network is used. Two instances given the same script and requests
    produce identical responses.
    """

    def __init__(
        self,
        responses: Sequence[ProviderResponse | Mapping[str, object]] | None = None,
        *,
        name: str = "fake",
        model: str = "fake-1",
    ) -> None:
        self._name = name
        self._model = model
        self._responses = [
            response
            if isinstance(response, ProviderResponse)
            else ProviderResponse.model_validate(response)
            for response in responses or ()
        ]
        self._calls: list[ProviderRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def calls(self) -> list[ProviderRequest]:
        return list(self._calls)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        index = len(self._calls)
        self._calls.append(request)
        if index < len(self._responses):
            response = self._responses[index]
            return response.model_copy(
                update={
                    "provider": self._name,
                    "model": response.model if response.model != "fake-1" else self._model,
                }
            )

        last_user = self._last_user_message(request)
        return ProviderResponse(
            text=f"FakeProvider turn {index + 1}: {last_user}",
            provider=self._name,
            model=self._model,
        )

    @staticmethod
    def _last_user_message(request: ProviderRequest) -> str:
        for message in reversed(request.messages):
            if message.role == "user":
                return message.content
        return request.messages[-1].content
