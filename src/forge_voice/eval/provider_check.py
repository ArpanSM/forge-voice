"""Fail-closed hybrid provider check with the #5 rate-limit retry budget."""

from __future__ import annotations

import time
from typing import Any

import httpx

from forge_voice.runtime.hybrid import (
    MAX_RATE_LIMIT_RETRIES,
    RATE_LIMIT_BUDGET_SECONDS,
    HybridRateLimitError,
    retry_after_seconds,
)
from forge_voice.runtime.session import GROQ_BASE_URL, GROQ_MODEL

CHECK_PROMPT = "Reply with the single word OK."


class _RateLimited(Exception):
    def __init__(self, retry_after: float | None, response: Any = None) -> None:
        self.retry_after = retry_after
        self.response = response
        super().__init__(f"rate limited; retry_after={retry_after}")


def check_groq(
    api_key: str,
    *,
    model: str = GROQ_MODEL,
    base_url: str = GROQ_BASE_URL,
    timeout_seconds: float = 30.0,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    """Make one tiny live call so the hybrid release claim is not made blind."""
    if not api_key.strip():
        return {
            "ok": False,
            "status": "missing_key",
            "error": "GROQ_API_KEY is required for the hybrid release gate",
        }
    started = time.perf_counter()
    spent = 0.0
    attempts = 0
    while True:
        attempts += 1
        try:
            response = httpx.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": CHECK_PROMPT}],
                    "temperature": 0.0,
                    "max_tokens": 8,
                },
                timeout=timeout_seconds,
            )
            if response.status_code == 429:
                retry_after = retry_after_seconds(_RateLimited(None, response))
                raise _RateLimited(retry_after, response)
            if response.status_code in {401, 403}:
                return {
                    "ok": False,
                    "status": "unauthorized",
                    "model": model,
                    "attempts": attempts,
                    "error": f"Groq rejected the API key ({response.status_code})",
                }
            if response.status_code >= 400:
                return {
                    "ok": False,
                    "status": "error",
                    "model": model,
                    "attempts": attempts,
                    "error": f"Groq returned HTTP {response.status_code}",
                }
            payload = response.json()
            choice = (payload.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            text = str(message.get("content") or "").strip()
            return {
                "ok": bool(text),
                "status": "ok" if text else "empty",
                "model": model,
                "attempts": attempts,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "reply": text[:40],
            }
        except _RateLimited as exc:
            delay = 20.0 if exc.retry_after is None else exc.retry_after
            if attempts > MAX_RATE_LIMIT_RETRIES or spent + delay > RATE_LIMIT_BUDGET_SECONDS:
                return {
                    "ok": False,
                    "status": "rate_limited",
                    "model": model,
                    "attempts": attempts,
                    "retry_after_seconds": exc.retry_after,
                    "error": str(HybridRateLimitError(exc.retry_after)),
                }
            spent += delay
            sleep(delay)
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "status": "transport_error",
                "model": model,
                "attempts": attempts,
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }


__all__ = ["check_groq"]
