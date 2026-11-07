"""Hybrid Groq rate-limit handling shared by the agent and smoke checks."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

MAX_RATE_LIMIT_RETRIES = 2
RATE_LIMIT_BUDGET_SECONDS = 90.0
DEFAULT_RATE_LIMIT_DELAY = 20.0


class HybridRateLimitError(RuntimeError):
    """The Groq free-tier rate limit persisted beyond the retry budget."""

    def __init__(self, retry_after: float | None, message: str | None = None) -> None:
        self.retry_after = retry_after
        delay = f"{retry_after:g}s" if retry_after is not None else "the next window"
        super().__init__(
            message or f"hybrid free-tier rate limit; retry in {delay} (Groq 429 ITPM)"
        )


def _status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _exception_chain(exc: BaseException) -> list[BaseException]:
    candidates: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        candidates.append(current)
        current = current.__cause__ or current.__context__
    return candidates


def is_rate_limit_error(exc: BaseException) -> bool:
    for item in _exception_chain(exc):
        if _status_code(item) == 429:
            return True
        name = type(item).__name__.lower()
        if "ratelimit" in name or "rate_limit" in name:
            return True
        body = getattr(item, "body", None)
        if isinstance(body, dict) and (
            body.get("code") == "rate_limit_exceeded" or body.get("type") == "tokens"
        ):
            return True
        text = str(item).lower()
        if "rate limit" in text and ("429" in text or "itpm" in text):
            return True
    return False


def retry_after_seconds(exc: BaseException) -> float | None:
    """Read Retry-After from headers or Groq's "try again in Ns" body."""
    candidates = _exception_chain(exc)
    for item in candidates:
        value = getattr(item, "retry_after", None)
        if value is not None:
            try:
                return max(0.0, float(value))
            except (TypeError, ValueError):
                pass
        headers = getattr(item, "headers", None)
        if headers is None:
            response = getattr(item, "response", None)
            headers = getattr(response, "headers", None)
        if headers is not None:
            try:
                raw = headers.get("retry-after") or headers.get("Retry-After")
            except AttributeError:
                raw = None
            if raw is not None:
                parsed = _parse_delay(raw)
                if parsed is not None:
                    return parsed
        body = getattr(item, "body", None)
        messages: list[str] = [str(item)]
        if isinstance(body, dict):
            messages.extend(str(value) for value in body.values())
        for message in messages:
            match = re.search(r"try again in\s*([0-9.]+)\s*(ms|s)?", message, re.I)
            if match:
                value = float(match.group(1))
                return value / 1000 if (match.group(2) or "s").lower() == "ms" else value
    return None


def _parse_delay(raw: object) -> float | None:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0.0, value)


async def retry_async_chunks[T](
    operation: Callable[[], AsyncIterator[T]],
    *,
    sleep: Callable[[float], Any] = asyncio.sleep,
    max_retries: int = MAX_RATE_LIMIT_RETRIES,
    budget_seconds: float = RATE_LIMIT_BUDGET_SECONDS,
    on_retry: Callable[[int, float], None] | None = None,
) -> AsyncIterator[T]:
    """Yield an async LLM stream, retrying 429s within a bounded time budget.

    A retry is only safe before the attempt has yielded any output; if a stream
    fails after partial output, the error is re-raised rather than duplicating
    speech. Rate-limit errors beyond the budget/retry count become a clear
    HybridRateLimitError instead of a generic timeout.
    """
    spent = 0.0
    attempt = 0
    while True:
        yielded = False
        try:
            async for chunk in operation():
                yielded = True
                yield chunk
            return
        except Exception as exc:
            if not is_rate_limit_error(exc):
                raise
            if yielded:
                raise
            retry_after = retry_after_seconds(exc)
            delay = DEFAULT_RATE_LIMIT_DELAY if retry_after is None else retry_after
            if attempt >= max_retries or spent + delay > budget_seconds:
                raise HybridRateLimitError(retry_after) from exc
            attempt += 1
            spent += delay
            if on_retry is not None:
                on_retry(attempt, delay)
            await sleep(delay)


__all__ = [
    "DEFAULT_RATE_LIMIT_DELAY",
    "MAX_RATE_LIMIT_RETRIES",
    "RATE_LIMIT_BUDGET_SECONDS",
    "HybridRateLimitError",
    "is_rate_limit_error",
    "retry_after_seconds",
    "retry_async_chunks",
]
