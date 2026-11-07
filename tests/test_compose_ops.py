"""Compose operations are tested at the script level with a fake Docker CLI.

These tests verify command sequencing and file effects, not real image builds, container
health or a live rollback.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compose_ops.sh"


@pytest.fixture
def fake_docker(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    executable = bin_dir / "docker"
    executable.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'tag=%s args=%s\\n' "${FORGE_VOICE_IMAGE_TAG:-}" "$*" >> "$FAKE_DOCKER_LOG"
if [[ "${1:-}" == "compose" && "${2:-}" == "version" ]]; then exit 0; fi
exit 0
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_DOCKER_LOG"] = str(log)
    return bin_dir, log, env


def _run(
    fake: tuple[Path, Path, dict[str, str]],
    root: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    _, _, env = fake
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SCRIPT), "--root", str(root), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _log(fake: tuple[Path, Path, dict[str, str]]) -> str:
    _, log, _ = fake
    return log.read_text(encoding="utf-8") if log.exists() else ""


def test_down_stops_the_stack_and_keeps_data(
    tmp_path: Path, fake_docker: tuple[Path, Path, dict[str, str]]
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "calls.jsonl").write_text("keep\n", encoding="utf-8")

    result = _run(fake_docker, tmp_path, "down")

    assert result.returncode == 0, result.stderr
    assert "compose down --remove-orphans" in _log(fake_docker)
    assert (tmp_path / "data" / "calls.jsonl").read_text(encoding="utf-8") == "keep\n"


def test_logs_follows_the_three_long_running_services(
    tmp_path: Path, fake_docker: tuple[Path, Path, dict[str, str]]
) -> None:
    result = _run(
        fake_docker,
        tmp_path,
        "logs",
        extra_env={"FORGE_VOICE_LOGS_FOLLOW": "0"},
    )

    assert result.returncode == 0, result.stderr
    log = _log(fake_docker)
    assert "compose logs --tail=200 livekit web agent" in log
    assert "--follow" not in log


def test_reset_deletes_only_synthetic_state_and_reseeds(
    tmp_path: Path, fake_docker: tuple[Path, Path, dict[str, str]]
) -> None:
    for relative in (
        "data/monitoring/calls.jsonl",
        "data/calls/call_1.jsonl",
        "data/forge_voice.db",
        "data/outbox.jsonl",
        "data/backup/keep.txt",
        "data/notes.txt",
        "recordings/call_1.wav",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    (tmp_path / ".env.local").write_text("LIVEKIT_API_KEY=devkey\n", encoding="utf-8")

    result = _run(fake_docker, tmp_path, "reset")

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "data" / "monitoring").exists()
    assert not (tmp_path / "data" / "calls").exists()
    assert not (tmp_path / "data" / "forge_voice.db").exists()
    assert not (tmp_path / "data" / "outbox.jsonl").exists()
    assert (tmp_path / "data" / "backup" / "keep.txt").exists()
    assert (tmp_path / "data" / "notes.txt").exists()
    assert not (tmp_path / "recordings" / "call_1.wav").exists()
    assert (tmp_path / "recordings").is_dir()
    assert (tmp_path / ".env.local").exists()
    log = _log(fake_docker)
    assert "compose down --remove-orphans" in log
    assert (
        "compose run --rm --no-deps --entrypoint python web -m forge_voice.monitoring.seed" in log
    )


def test_rollback_uses_the_previous_tag_and_restores_backup_after_a_schema_change(
    tmp_path: Path, fake_docker: tuple[Path, Path, dict[str, str]]
) -> None:
    release = tmp_path / ".release"
    release.mkdir()
    (release / "previous").write_text("v1\n", encoding="utf-8")
    (release / "current").write_text("v2\n", encoding="utf-8")
    (release / "previous-schema").write_text("1\n", encoding="utf-8")
    (release / "current-schema").write_text("2\n", encoding="utf-8")
    backup = tmp_path / "data" / "backup"
    backup.mkdir(parents=True)
    (backup / "restored.txt").write_text("old\n", encoding="utf-8")
    (tmp_path / "data" / "new-schema.txt").write_text("new\n", encoding="utf-8")

    result = _run(fake_docker, tmp_path, "rollback")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "data" / "restored.txt").read_text(encoding="utf-8") == "old\n"
    assert not (tmp_path / "data" / "new-schema.txt").exists()
    assert (backup / "restored.txt").exists()
    assert (release / "current").read_text(encoding="utf-8").strip() == "v1"
    assert (release / "previous").read_text(encoding="utf-8").strip() == "v2"
    log = _log(fake_docker)
    assert "compose down --remove-orphans" in log
    assert "tag=v1 args=compose up -d --no-build --wait --wait-timeout 300" in log


def test_rollback_keeps_current_data_when_the_schema_is_unchanged(
    tmp_path: Path, fake_docker: tuple[Path, Path, dict[str, str]]
) -> None:
    release = tmp_path / ".release"
    release.mkdir()
    (release / "previous").write_text("v1\n", encoding="utf-8")
    (release / "current").write_text("v2\n", encoding="utf-8")
    (release / "previous-schema").write_text("1\n", encoding="utf-8")
    (release / "current-schema").write_text("1\n", encoding="utf-8")
    (tmp_path / "data" / "backup").mkdir(parents=True)
    (tmp_path / "data" / "backup" / "old.txt").write_text("old\n", encoding="utf-8")
    (tmp_path / "data" / "current.txt").write_text("current\n", encoding="utf-8")

    result = _run(fake_docker, tmp_path, "rollback")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "data" / "current.txt").read_text(encoding="utf-8") == "current\n"
    assert not (tmp_path / "data" / "old.txt").exists()


def test_rollback_fails_closed_without_a_previous_tag(
    tmp_path: Path, fake_docker: tuple[Path, Path, dict[str, str]]
) -> None:
    result = _run(fake_docker, tmp_path, "rollback")

    assert result.returncode != 0
    assert ".release/previous" in result.stderr


def test_rollback_requires_the_backup_when_the_schema_changed(
    tmp_path: Path, fake_docker: tuple[Path, Path, dict[str, str]]
) -> None:
    release = tmp_path / ".release"
    release.mkdir()
    (release / "previous").write_text("v1\n", encoding="utf-8")
    (release / "current-schema").write_text("2\n", encoding="utf-8")
    (release / "previous-schema").write_text("1\n", encoding="utf-8")

    result = _run(fake_docker, tmp_path, "rollback")

    assert result.returncode != 0
    assert "data/backup" in result.stderr
