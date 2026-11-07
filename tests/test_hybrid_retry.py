"""Offline evidence for the hybrid Groq 429 retry/backoff policy."""

from __future__ import annotations

import asyncio

import pytest

from forge_voice.runtime.hybrid import (
    HybridRateLimitError,
    is_rate_limit_error,
    retry_after_seconds,
    retry_async_chunks,
)


class FakeResponse:
    def __init__(self, status_code: int, headers: dict[str, str]) -> None:
        self.status_code = status_code
        self.headers = headers


class FakeRateLimitError(Exception):
    def __init__(self, retry_after: str | None = "2") -> None:
        headers = {} if retry_after is None else {"retry-after": retry_after}
        self.response = FakeResponse(429, headers)


class FakeGroqTransport:
    """Injected provider stream: 429 once, then a successful booking continuation."""

    def __init__(self, failures: int = 1) -> None:
        self.failures = failures
        self.attempts = 0

    async def stream(self):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise FakeRateLimitError("3")
        yield "booked"


def test_retry_after_seconds_reads_the_server_header() -> None:
    error = FakeRateLimitError("7")

    assert is_rate_limit_error(error)
    assert retry_after_seconds(error) == 7.0


def test_nested_gateway_error_and_body_delay_are_detected() -> None:
    class GatewayError(Exception):
        pass

    cause = FakeRateLimitError(retry_after=None)
    cause.body = {"message": "Rate limit reached; try again in 1.75s"}
    wrapped = GatewayError("failed after 4 attempts")
    wrapped.__cause__ = cause

    assert is_rate_limit_error(wrapped)
    assert retry_after_seconds(wrapped) == 1.75


def test_rate_limit_retries_the_injected_stream_and_succeeds() -> None:
    transport = FakeGroqTransport(failures=1)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in retry_async_chunks(
                transport.stream, sleep=fake_sleep, max_retries=2, budget_seconds=30
            )
        ]

    assert asyncio.run(collect()) == ["booked"]
    assert transport.attempts == 2
    assert sleeps == [3.0]


def test_retry_budget_exhaustion_is_a_clear_rate_limit_error() -> None:
    transport = FakeGroqTransport(failures=3)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in retry_async_chunks(
                transport.stream, sleep=fake_sleep, max_retries=1, budget_seconds=5
            )
        ]

    with pytest.raises(HybridRateLimitError) as raised:
        asyncio.run(collect())

    assert "hybrid free-tier rate limit" in str(raised.value)
    assert raised.value.retry_after == 3.0
    assert sleeps == [3.0]


def test_non_rate_limit_errors_are_not_swallowed() -> None:
    async def broken():
        raise ValueError("bad tool schema")
        yield "never"

    async def collect() -> list[str]:
        return [chunk async for chunk in retry_async_chunks(broken)]

    with pytest.raises(ValueError, match="bad tool schema"):
        asyncio.run(collect())
