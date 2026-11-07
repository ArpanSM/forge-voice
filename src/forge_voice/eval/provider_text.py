"""Provider-backed text interpreter for the release profiles.

The model extracts intent and caller entities; the same #4 policy, eight tools,
confirmation and idempotency path still executes the call. This is the text-mode provider
seam used by the hybrid (Groq) and local (LFM3) release runs.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from pydantic import ConfigDict

from forge_voice.adapters.sqlite import SQLiteAdapter
from forge_voice.clock import FixedClock
from forge_voice.domain import Address
from forge_voice.eval.provider_check import ORCAROUTER_BASE_URL, ORCAROUTER_MODEL
from forge_voice.models import StrictModel
from forge_voice.policy.conversation import ConversationPolicy
from forge_voice.policy.state import CallIntent
from forge_voice.providers import (
    ChatMessage,
    ChatProvider,
    ProviderError,
    ProviderRequest,
    ProviderSettings,
    build_provider,
)
from forge_voice.runtime.hybrid import (
    MAX_RATE_LIMIT_RETRIES,
    RATE_LIMIT_BUDGET_SECONDS,
    is_rate_limit_error,
    retry_after_seconds,
)
from forge_voice.runtime.interpreter import CallerFacts, extract_facts
from forge_voice.tenants import TenantConfig, load_all_tenants
from forge_voice.validation import normalize_phone, normalize_zip

INTENTS = frozenset(intent.value for intent in CallIntent)
WINDOWS = frozenset({"morning", "afternoon", "evening"})
DEFAULT_LFM3_BASE = "http://127.0.0.1:8082"


class TextProviderError(RuntimeError):
    """The configured text provider was unavailable or returned unusable output."""


class TextProviderQuotaError(TextProviderError):
    """The provider's daily token budget is exhausted; retrying cannot help."""


class _RateLimitedProviderError(ProviderError):
    def __init__(self, retry_after: float | None, response: httpx.Response) -> None:
        self.retry_after = retry_after
        self.response = response
        self.status_code = 429
        super().__init__("text provider rate limited")


class HttpxTransport:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def post_json(
        self,
        url: str,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        request_headers = dict(headers)
        if self.api_key:
            request_headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = httpx.post(
                url,
                json=payload,
                headers=request_headers,
                timeout=timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"text provider transport failed: {type(exc).__name__}") from exc
        if response.status_code == 429:
            retry = retry_after_seconds(_RateLimitedProviderError(None, response))
            raise _RateLimitedProviderError(retry, response)
        if response.status_code >= 400:
            raise ProviderError(f"text provider returned HTTP {response.status_code}")
        return response.json()


class TextExtraction(StrictModel):
    model_config = ConfigDict(extra="ignore")

    intent: str | None = None
    service_id: str | None = None
    name: str | None = None
    phone: str | None = None
    address_line1: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    preferred_day: str | None = None
    preferred_window: str | None = None
    preferred_hour: str | None = None
    wants_human: bool | None = None


def _prompt(tenant: TenantConfig, turns: list[str], now: Any) -> str:
    services = ", ".join(item.id for item in tenant.services)
    return (
        "Extract the caller facts as one JSON object. Keys: intent, service_id, name, phone, "
        "address_line1, city, state, zip, preferred_day, preferred_window, preferred_hour, "
        f"wants_human. intent in {sorted(INTENTS)}; service_id in [{services}] or null; "
        f"preferred_day YYYY-MM-DD; window morning/afternoon/evening; today {now.date()}. "
        f"Caller: {' '.join(turns)}"
    )


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    return text


@dataclass
class ProviderTextInterpreter:
    provider: ChatProvider
    tenants: dict[str, TenantConfig]
    model: str
    min_interval_seconds: float = 0.0
    _last_call: float = 0.0
    _cache: dict[tuple[Any, ...], CallerFacts] = field(default_factory=dict)

    def extract(
        self,
        *,
        scenario_id: str,
        tenant: TenantConfig,
        turns: list[str],
        caller_phone: str | None,
        now: Any,
        trust_intent: bool = False,
    ) -> CallerFacts:
        cache_key = (
            scenario_id,
            tuple(turns),
            caller_phone,
            trust_intent,
            now.isoformat(),
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        base = extract_facts(
            tenant,
            turns,
            SQLiteAdapter(":memory:"),
            now,
            caller_phone=caller_phone,
        )
        request = ProviderRequest(
            messages=[
                ChatMessage(
                    role="system",
                    content="Return JSON only.",
                ),
                ChatMessage(role="user", content=_prompt(tenant, turns, now)),
            ],
            temperature=0.0,
            # Free reasoning models may emit hidden reasoning before the JSON. Keep
            # enough budget for both; 160 tokens is enough only for non-reasoning models.
            max_tokens=640,
            seed=abs(int(hashlib.sha256(scenario_id.encode()).hexdigest()[:8], 16)) % 2_147_483_647,
        )
        response = self._complete(request)
        try:
            start = response.text.index("{")
            end = response.text.rindex("}") + 1
            raw = json.loads(response.text[start:end])
            parsed = TextExtraction.model_validate(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            raise TextProviderError(
                f"text provider returned no usable JSON: {response.text[:160]!r}"
            ) from exc
        result = self._merge(base, parsed, tenant, now, turns, trust_intent=trust_intent)
        self._cache[cache_key] = result
        return result

    def prefetch(
        self,
        cases: list[dict[str, Any]],
        *,
        trust_intent: bool = False,
    ) -> None:
        """Batch the provider extraction to stay inside free-tier token limits."""
        if self.min_interval_seconds <= 0:
            return
        pending: list[dict[str, Any]] = []
        for case in cases:
            key = self._cache_key(case, trust_intent)
            if key not in self._cache:
                pending.append(case)
        for start in range(0, len(pending), 2):
            self._prefetch_batch(pending[start : start + 2], trust_intent)

    def _cache_key(self, case: dict[str, Any], trust_intent: bool) -> tuple[Any, ...]:
        return (
            case["scenario_id"],
            tuple(case["turns"]),
            case["caller_phone"],
            trust_intent,
            case["now"].isoformat(),
        )

    def _prefetch_batch(self, cases: list[dict[str, Any]], trust_intent: bool) -> None:
        blocks = []
        for index, case in enumerate(cases):
            tenant = case["tenant"]
            services = ", ".join(item.id for item in tenant.services)
            blocks.append(
                f"[{index}] tenant={tenant.tenant_id}; services={services}; today="
                f"{case['now'].date().isoformat()}; caller={' '.join(case['turns'])}"
            )
        prompt = (
            "Extract each numbered call. Return one JSON object only: "
            '{"results":[{"id":0,"intent":"book","service_id":null,"name":null,'
            '"phone":null,"address_line1":null,"city":null,"state":null,"zip":null,'
            '"preferred_day":null,"preferred_window":null,"preferred_hour":null,'
            '"wants_human":false}, ...]}. '
            f"intent values: {sorted(INTENTS)}; preferred_day YYYY-MM-DD.\n" + "\n".join(blocks)
        )
        request = ProviderRequest(
            messages=[
                ChatMessage(role="system", content="Return JSON only."),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=0.0,
            # DeepSeek/GLM free tiers reason before returning JSON; a 780-token batch
            # cap truncated the result and looked like a provider failure. Two cases
            # per request also keeps the reasoning budget bounded.
            max_tokens=max(2400, 900 * len(cases)),
            seed=7,
        )
        response = self._complete(request)
        try:
            start = response.text.index("{")
            end = response.text.rindex("}") + 1
            payload = json.loads(response.text[start:end])
            results = payload.get("results") or []
        except (ValueError, json.JSONDecodeError) as exc:
            raise TextProviderError(
                f"text provider batch returned no usable JSON: {response.text[:160]!r}"
            ) from exc
        by_index = {
            int(item.get("id")): item
            for item in results
            if isinstance(item, dict) and str(item.get("id", "")).isdigit()
        }
        for index, case in enumerate(cases):
            raw = by_index.get(index)
            if raw is None:
                raise TextProviderError(f"text provider batch omitted call {index}")
            parsed = TextExtraction.model_validate(raw)
            base = extract_facts(
                case["tenant"],
                case["turns"],
                SQLiteAdapter(":memory:"),
                case["now"],
                caller_phone=case["caller_phone"],
            )
            merged = self._merge(
                base,
                parsed,
                case["tenant"],
                case["now"],
                case["turns"],
                trust_intent=trust_intent,
            )
            self._cache[self._cache_key(case, trust_intent)] = merged

    def _merge(
        self,
        base: CallerFacts,
        parsed: TextExtraction,
        tenant: TenantConfig,
        now: Any,
        turns: list[str],
        trust_intent: bool = False,
    ) -> CallerFacts:
        policy_intent = (
            ConversationPolicy(tenant, FixedClock(now))
            .classify_intent(turns[0] if turns else "")
            .value
        )
        proposed = parsed.intent
        if proposed not in INTENTS:
            proposed = None
        if base.wants_human:
            proposed = "human"
        intent = proposed if trust_intent and proposed is not None else policy_intent
        service = _clean(parsed.service_id)
        configured = {item.id for item in tenant.services}
        if service is not None and service not in configured:
            by_name = {item.name.lower(): item.id for item in tenant.services}
            service = by_name.get(service.lower())
        phone = base.phone
        if _clean(parsed.phone):
            try:
                phone = normalize_phone(parsed.phone or "")
            except Exception:
                phone = base.phone
        address = base.address
        line1 = _clean(parsed.address_line1)
        zip_code = _clean(parsed.zip)
        if line1 and zip_code:
            try:
                address = Address(
                    line1=line1,
                    city=_clean(parsed.city)
                    or ("San Jose" if tenant.tenant_id == "summit" else "San Francisco"),
                    state=(
                        (_clean(parsed.state) or "CA").upper()
                        if len(_clean(parsed.state) or "CA") == 2
                        else "CA"
                    ),
                    zip=normalize_zip(zip_code),
                )
            except Exception:
                address = base.address
        preferred_day = base.preferred_day
        if _clean(parsed.preferred_day):
            try:
                candidate = date.fromisoformat(str(parsed.preferred_day))
                horizon = now.date() + __import__("datetime").timedelta(
                    days=tenant.policies.booking_horizon_days
                )
                preferred_day = (
                    candidate if now.date() <= candidate <= horizon else base.preferred_day
                )
            except ValueError:
                preferred_day = base.preferred_day
        window = _clean(parsed.preferred_window)
        if window not in WINDOWS:
            window = base.preferred_window
        hour = base.preferred_hour
        raw_hour = _clean(parsed.preferred_hour)
        if raw_hour:
            try:
                if ":" in raw_hour:
                    clock, minute = raw_hour.split(":", 1)
                    hour = int(clock) * 60 + int(minute)
                else:
                    hour = int(float(raw_hour) * 60)
            except ValueError:
                hour = base.preferred_hour
        name = _clean(parsed.name) or base.name
        wants_human = (
            bool(parsed.wants_human) if parsed.wants_human is not None else base.wants_human
        )
        return replace(
            base,
            intent=intent,
            service_id=service if service is not None else base.service_id,
            name=name,
            phone=phone,
            address=address,
            preferred_day=preferred_day,
            preferred_window=window,
            preferred_hour=hour,
            wants_human=wants_human,
            human_mode="live"
            if wants_human and "transfer" in base.text.lower()
            else base.human_mode,
        )

    def _complete(self, request: ProviderRequest) -> Any:
        spent = 0.0
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            if self.min_interval_seconds:
                wait = self._last_call + self.min_interval_seconds - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                return self.provider.complete(request)
            except ProviderError as exc:
                if not is_rate_limit_error(exc):
                    raise TextProviderError(f"text provider failed: {exc}") from exc
                body = _exception_body(exc)
                if "tokens per day" in body or "tpd" in body:
                    raise TextProviderQuotaError(
                        "the provider daily token budget is exhausted"
                    ) from exc
                delay = retry_after_seconds(exc) or 20.0
                if attempt >= MAX_RATE_LIMIT_RETRIES or spent + delay > RATE_LIMIT_BUDGET_SECONDS:
                    raise TextProviderError(
                        f"text provider rate limit exceeded; retry in {delay:g}s"
                    ) from exc
                spent += delay
                time.sleep(delay)
        raise TextProviderError("text provider did not return a response")


def _exception_body(exc: BaseException) -> str:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        text = getattr(response, "text", None)
        if isinstance(text, str):
            return text.lower()
        body = getattr(current, "body", None)
        if isinstance(body, dict):
            return str(body).lower()
        current = current.__cause__ or current.__context__
    return str(exc).lower()


def build_text_interpreter(
    root: Path,
    profile: str,
    env: dict[str, str] | None = None,
) -> ProviderTextInterpreter:
    values = dict(env or {})
    tenants = load_all_tenants(Path(root) / "tenants")
    requested = values.get("EVAL_LLM_PROVIDER", "").strip().lower()
    if profile == "hybrid":
        selected = requested or "groq"
        if selected == "groq":
            key = values.get("GROQ_API_KEY", "").strip()
            if not key:
                raise TextProviderError("the hybrid text interpreter requires GROQ_API_KEY")
            settings = ProviderSettings(
                provider="groq",
                model=values.get("GROQ_MODEL", "qwen/qwen3.8-27b"),
                base_url="https://api.groq.com/openai/v1",
                timeout_seconds=30.0,
            )
            min_interval = 20.0
        elif selected == "orcarouter":
            key = values.get("ORCAROUTER_API_KEY", "").strip()
            if not key:
                raise TextProviderError("EVAL_LLM_PROVIDER=orcarouter requires ORCAROUTER_API_KEY")
            settings = ProviderSettings(
                provider="orcarouter",
                model=values.get("ORCAROUTER_MODEL", ORCAROUTER_MODEL),
                base_url=values.get("ORCAROUTER_BASE_URL", ORCAROUTER_BASE_URL),
                timeout_seconds=60.0,
            )
            # OrcaRouter free is 10 RPM; leave a margin for the tiny provider check.
            min_interval = 6.5
        else:
            raise TextProviderError(
                f"unsupported EVAL_LLM_PROVIDER {selected!r} for the hybrid profile; "
                "expected groq or orcarouter"
            )
    else:
        if requested not in {"", "lfm3"}:
            raise TextProviderError(
                f"unsupported EVAL_LLM_PROVIDER {requested!r} for the local profile; "
                "the local safety report requires lfm3"
            )
        key = "local"
        base = values.get("LFM3_AUDIO_BASE_URL", DEFAULT_LFM3_BASE).rstrip("/")
        try:
            health = httpx.get(f"{base}/health", timeout=3.0)
            if health.status_code >= 400:
                raise TextProviderError(f"LFM3 health returned HTTP {health.status_code}")
        except httpx.HTTPError as exc:
            raise TextProviderError(
                f"the local text interpreter requires LFM3 at {base}/health"
            ) from exc
        settings = ProviderSettings(
            provider="lfm3",
            model=values.get("LFM3_AUDIO_MODEL", "lfm3-audio-2b"),
            base_url=f"{base}/v1",
            timeout_seconds=60.0,
        )
        min_interval = 0.0
    provider = build_provider(settings, transport=HttpxTransport(api_key=key))
    return ProviderTextInterpreter(
        provider=provider,
        tenants=tenants,
        model=settings.model,
        min_interval_seconds=min_interval,
    )


__all__ = [
    "HttpxTransport",
    "ProviderTextInterpreter",
    "TextExtraction",
    "TextProviderError",
    "TextProviderQuotaError",
    "build_text_interpreter",
]
