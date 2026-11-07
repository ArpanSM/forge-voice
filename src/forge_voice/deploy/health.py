"""Local stack health probes used by `make health` and the compose preflight."""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

Opener = Callable[..., object]

DEFAULT_LFM3_URL = "http://127.0.0.1:8082/health"
DEFAULT_LIVEKIT_URL = "http://127.0.0.1:7880/"
DEFAULT_WEB_URL = "http://127.0.0.1:8000/health"
DEFAULT_AGENT_LOG = Path("data/demo/agent.log")


@dataclass(frozen=True)
class HealthCheck:
    name: str
    target: str
    ok: bool
    detail: str = ""


def check_http(
    name: str,
    url: str,
    *,
    timeout: float = 2.0,
    opener: Opener = urlopen,
) -> HealthCheck:
    """Probe one local HTTP endpoint; any non-200 or socket error fails closed."""
    try:
        response = opener(url, timeout=timeout)
        try:
            status = getattr(response, "status", 200)
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()
    except HTTPError as exc:
        return HealthCheck(name, url, False, f"HTTP {exc.code}")
    except (URLError, OSError, TimeoutError) as exc:
        return HealthCheck(name, url, False, str(exc))
    if status != 200:
        return HealthCheck(name, url, False, f"HTTP {status}")
    return HealthCheck(name, url, True)


def check_agent_log(
    path: Path | str,
    *,
    marker: str = "registered worker",
    max_age_seconds: float = 900.0,
    now: float | None = None,
) -> HealthCheck:
    """The host-binary demo has no fixed agent HTTP port; its readiness is a fresh log line."""
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
        age = (now if now is not None else time.time()) - target.stat().st_mtime
    except OSError as exc:
        return HealthCheck("agent", str(target), False, str(exc))
    if marker not in text:
        return HealthCheck("agent", str(target), False, f"missing {marker!r} in the log")
    if age > max_age_seconds:
        return HealthCheck(
            "agent",
            str(target),
            False,
            f"stale log: last changed {int(age)}s ago (limit {int(max_age_seconds)}s)",
        )
    return HealthCheck("agent", str(target), True)


def run_checks(
    endpoints: Iterable[tuple[str, str]],
    *,
    opener: Opener = urlopen,
    agent_log: Path | str | None = None,
    agent_log_max_age: float = 900.0,
) -> list[HealthCheck]:
    checks = [check_http(name, url, opener=opener) for name, url in endpoints]
    if agent_log is not None:
        checks.append(check_agent_log(agent_log, max_age_seconds=agent_log_max_age))
    return checks


def format_results(checks: Iterable[HealthCheck]) -> str:
    lines = []
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        detail = f" ({check.detail})" if check.detail else ""
        lines.append(f"{status:4} {check.name:8} {check.target}{detail}")
    return "\n".join(lines)


def main(
    argv: list[str] | None = None,
    *,
    opener: Opener = urlopen,
) -> int:
    parser = argparse.ArgumentParser(description="Check the local forge-voice stack")
    parser.add_argument("--lfm3-url", default=DEFAULT_LFM3_URL)
    parser.add_argument("--livekit-url", default=DEFAULT_LIVEKIT_URL)
    parser.add_argument("--web-url", default=DEFAULT_WEB_URL)
    parser.add_argument("--agent-url")
    parser.add_argument("--agent-log", type=Path)
    parser.add_argument("--agent-log-max-age", type=float, default=900.0)
    args = parser.parse_args(argv)

    endpoints = [
        ("lfm3", args.lfm3_url),
        ("livekit", args.livekit_url),
        ("web", args.web_url),
    ]
    if args.agent_url:
        endpoints.append(("agent", args.agent_url))
    checks = run_checks(
        endpoints,
        opener=opener,
        agent_log=args.agent_log,
        agent_log_max_age=args.agent_log_max_age,
    )
    print(format_results(checks))
    if all(check.ok for check in checks):
        return 0
    print(
        "Local stack is not healthy. Start LFM3 with `lfm3 audio`, check ports "
        "7880/8000/8081/8082, and see docs/runbook.md.",
        flush=True,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
