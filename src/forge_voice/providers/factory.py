"""Provider configuration and the one place a concrete provider is chosen."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from forge_voice.providers.base import (
    ChatProvider,
    HttpTransport,
    ProviderNotConfiguredError,
    ProviderResponse,
    ProviderSettings,
)
from forge_voice.providers.fake import FakeProvider
from forge_voice.providers.openai_compatible import OpenAICompatibleProvider


def build_provider(
    settings: ProviderSettings,
    *,
    transport: HttpTransport | None = None,
    fake_responses: Sequence[ProviderResponse | Mapping[str, Any]] | None = None,
) -> ChatProvider:
    """Build the configured provider.

    `fake` is fully offline. `lfm3` and `groq` require an injected HTTP transport and base URL;
    without them the build fails closed instead of attempting a hidden network call.
    """
    if settings.provider == "fake":
        return FakeProvider(fake_responses)

    if transport is None:
        raise ProviderNotConfiguredError(
            f"{settings.provider} requires an injected HTTP transport; "
            "unit tests must use FakeProvider"
        )
    if not settings.base_url:
        raise ProviderNotConfiguredError(f"{settings.provider} requires provider base_url")
    return OpenAICompatibleProvider(settings=settings, transport=transport)
