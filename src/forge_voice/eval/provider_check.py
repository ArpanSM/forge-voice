"""Fail-closed live provider check with the #5 rate-limit retry budget."""

from __future__ import annotations

import time
from typing import Any

import httpx

from forge_voice.runtime.hybrid import (
    MAX_RATE_LIMIT_RETRIES,
    RATE_LIMIT_BUDGET_SECONDS,
    retry_after_seconds,
)
from forge_voice.runtime.session import GROQ_BASE_URL, GROQ_MODEL

CHECK_PROMPT = "Reply with the single word OK."
ORCAROUTER_BASE_URL = "https://api.orcarouter.ai/v1"
ORCAROUTER_MODEL = "deepseek/deepseek-v4.1-flash-free"


class _RateLimited(Exception):
    def __init__(self, retry_after: float | None, response: Any = None) -> None:
        self.retry_after = retry_after
        self.response = response
        super().__init__(f"rate limited; retry_after={retry_after}")


def _label(provider: str) -> str:
    return "Groq" if provider == "groq" else "OrcaRouter"


def _is_daily_quota(body: str) -> bool:
    return any(
        marker in body
        for marker in (
            "per day",
            "tpd",
            "daily",
            "free usage limit",
            "requests per day",
            "rpd",
        )
    )


def _check_provider(
    provider: str,
    api_key: str,
    *,
    model: str,
    base_url: str,
    timeout_seconds: float = 30.0,
    sleep: Any = time.sleep,
    long_prompt: bool = False,
) -> dict[str, Any]:
    """Make one tiny live call so a provider-backed release claim is not made blind."""
    label = _label(provider)
    if not api_key.strip():
        return {
            "ok": False,
            "provider": provider,
            "status": "missing_key",
            "error": f"an API key is required for the {provider} release gate",
        }
    prompt = ("The quick brown fox jumps over the lazy dog. " * 60) if long_prompt else CHECK_PROMPT
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
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    # Reasoning models spend the first tokens on hidden reasoning; a tiny
                    # budget can return an empty content field even when the model is healthy.
                    "max_tokens": 640,
                },
                timeout=timeout_seconds,
            )
            if response.status_code == 429:
                retry_after = retry_after_seconds(_RateLimited(None, response))
                raise _RateLimited(retry_after, response)
            if response.status_code in {401, 403}:
                return {
                    "ok": False,
                    "provider": provider,
                    "status": "unauthorized",
                    "model": model,
                    "attempts": attempts,
                    "error": f"{label} rejected the API key ({response.status_code})",
                }
            if response.status_code >= 400:
                return {
                    "ok": False,
                    "provider": provider,
                    "status": "error",
                    "model": model,
                    "attempts": attempts,
                    "error": f"{label} returned HTTP {response.status_code}",
                }
            payload = response.json()
            choice = (payload.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            text = str(message.get("content") or "").strip()
            remaining_raw = response.headers.get("x-ratelimit-remaining-tokens")
            remaining = int(remaining_raw) if remaining_raw and remaining_raw.isdigit() else None
            if remaining is not None and remaining < 4000:
                return {
                    "ok": False,
                    "provider": provider,
                    "status": "insufficient_quota",
                    "model": model,
                    "attempts": attempts,
                    "remaining_tokens": remaining,
                    "error": (
                        "the Groq free-tier token budget is nearly exhausted; "
                        f"{remaining} tokens remain"
                    ),
                }
            return {
                "ok": bool(text),
                "provider": provider,
                "status": "ok" if text else "empty",
                "model": model,
                "attempts": attempts,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "reply": text[:40],
            }
        except _RateLimited as exc:
            body = ""
            if exc.response is not None:
                try:
                    body = exc.response.text
                except Exception:
                    body = ""
            if _is_daily_quota(body.lower()) or _is_daily_quota(str(exc).lower()):
                return {
                    "ok": False,
                    "provider": provider,
                    "status": "insufficient_quota",
                    "model": model,
                    "attempts": attempts,
                    "retry_after_seconds": exc.retry_after,
                    "error": body[:300] or f"the {label} free-tier daily budget is exhausted",
                }
            delay = 20.0 if exc.retry_after is None else exc.retry_after
            if attempts > MAX_RATE_LIMIT_RETRIES or spent + delay > RATE_LIMIT_BUDGET_SECONDS:
                return {
                    "ok": False,
                    "provider": provider,
                    "status": "rate_limited",
                    "model": model,
                    "attempts": attempts,
                    "retry_after_seconds": exc.retry_after,
                    "error": (
                        f"{label} free-tier rate limit; retry in "
                        f"{exc.retry_after if exc.retry_after is not None else 'unknown'}s"
                    ),
                }
            spent += delay
            sleep(delay)
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "provider": provider,
                "status": "transport_error",
                "model": model,
                "attempts": attempts,
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }


def check_groq(
    api_key: str,
    *,
    model: str = GROQ_MODEL,
    base_url: str = GROQ_BASE_URL,
    timeout_seconds: float = 30.0,
    sleep: Any = time.sleep,
    long_prompt: bool = False,
) -> dict[str, Any]:
    """Make one tiny live Groq call so the hybrid release claim is not made blind."""
    return _check_provider(
        "groq",
        api_key,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        sleep=sleep,
        long_prompt=long_prompt,
    )


def check_orcarouter(
    api_key: str,
    *,
    model: str = ORCAROUTER_MODEL,
    base_url: str = ORCAROUTER_BASE_URL,
    timeout_seconds: float = 60.0,
    sleep: Any = time.sleep,
    long_prompt: bool = False,
) -> dict[str, Any]:
    """Check the free OrcaRouter fallback used when the Groq daily budget is gone."""
    return _check_provider(
        "orcarouter",
        api_key,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        sleep=sleep,
        long_prompt=long_prompt,
    )


__all__ = [
    "CHECK_PROMPT",
    "ORCAROUTER_BASE_URL",
    "ORCAROUTER_MODEL",
    "check_groq",
    "check_orcarouter",
]
