"""Health probes fail closed and name the missing local dependency."""

from __future__ import annotations

from pathlib import Path
from urllib.error import URLError

from forge_voice.deploy.health import (
    check_agent_log,
    check_http,
    format_results,
    main,
    run_checks,
)


class FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _ok_opener(url: str, *, timeout: float) -> FakeResponse:
    assert timeout > 0
    return FakeResponse(200)


def _missing_opener(url: str, *, timeout: float) -> FakeResponse:
    raise URLError(f"connection refused: {url}")


def test_healthy_endpoint_is_ok() -> None:
    check = check_http("web", "http://127.0.0.1:8000/health", opener=_ok_opener)

    assert check.ok is True
    assert check.name == "web"
    assert check.detail == ""


def test_missing_endpoint_fails_with_a_detail() -> None:
    check = check_http("lfm3", "http://127.0.0.1:8082/health", opener=_missing_opener)

    assert check.ok is False
    assert "connection refused" in check.detail


def test_non_200_status_fails() -> None:
    check = check_http(
        "livekit",
        "http://127.0.0.1:7880/",
        opener=lambda url, *, timeout: FakeResponse(503),
    )

    assert check.ok is False
    assert check.detail == "HTTP 503"


def test_agent_readiness_uses_the_registered_worker_log(tmp_path: Path) -> None:
    log = tmp_path / "agent.log"
    log.write_text("starting worker\nregistered worker\n", encoding="utf-8")

    assert check_agent_log(log).ok is True

    log.write_text("starting worker\n", encoding="utf-8")
    missing = check_agent_log(log)
    assert missing.ok is False
    assert "registered worker" in missing.detail


def test_run_checks_reports_every_endpoint_even_after_a_failure() -> None:
    def mixed(url: str, *, timeout: float) -> FakeResponse:
        if "8082" in url:
            raise URLError("down")
        return FakeResponse(200)

    checks = run_checks(
        [
            ("lfm3", "http://127.0.0.1:8082/health"),
            ("web", "http://127.0.0.1:8000/health"),
        ],
        opener=mixed,
    )

    assert [check.ok for check in checks] == [False, True]
    text = format_results(checks)
    assert "FAIL lfm3" in text
    assert "OK   web" in text


def test_cli_exits_nonzero_and_names_the_fix_when_lfm3_is_missing(capsys) -> None:
    code = main(["--lfm3-url", "http://127.0.0.1:8082/health"], opener=_missing_opener)

    output = capsys.readouterr().out
    assert code == 1
    assert "lfm3 audio" in output
    assert "docs/runbook.md" in output


def test_cli_exits_zero_when_all_requested_checks_pass(capsys) -> None:
    code = main(
        [
            "--lfm3-url",
            "http://127.0.0.1:8082/health",
            "--livekit-url",
            "http://127.0.0.1:7880/",
            "--web-url",
            "http://127.0.0.1:8000/health",
        ],
        opener=_ok_opener,
    )

    assert code == 0
    assert "OK   lfm3" in capsys.readouterr().out


def test_agent_log_is_stale_when_old_even_if_the_marker_is_present(tmp_path: Path) -> None:
    import os
    import time

    log = tmp_path / "agent.log"
    log.write_text("registered worker\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(log, (old, old))

    check = check_agent_log(log, max_age_seconds=900, now=time.time())

    assert check.ok is False
    assert "stale log" in check.detail


def test_fresh_agent_log_is_ok(tmp_path: Path) -> None:
    import time

    log = tmp_path / "agent.log"
    log.write_text("registered worker\n", encoding="utf-8")

    assert check_agent_log(log, max_age_seconds=900, now=time.time()).ok is True
