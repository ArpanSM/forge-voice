"""Release markers and rollback backup restoration, exercised with a fake Docker CLI.

These are script-level tests: they verify the commands and file effects, not real image
builds or container health.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts" / "release.sh"
OPS = ROOT / "scripts" / "compose_ops.sh"


@pytest.fixture
def fake_docker(tmp_path: Path) -> tuple[dict[str, str], Path]:
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
    return env, log


def _run(
    script: Path,
    root: Path,
    env: dict[str, str],
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = dict(env)
    if extra_env:
        merged.update(extra_env)
    return subprocess.run(
        ["bash", str(script), "--root", str(root), *args],
        cwd=ROOT,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


def _log(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def test_schema_changing_release_stops_services_and_rollback_restores_the_backup(
    tmp_path: Path, fake_docker: tuple[dict[str, str], Path]
) -> None:
    env, log_path = fake_docker
    release = tmp_path / ".release"
    release.mkdir()
    (release / "current").write_text("v1\n", encoding="utf-8")
    (release / "current-schema").write_text("1\n", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / "booking.db").write_text("old-schema\n", encoding="utf-8")

    result = _run(
        RELEASE,
        tmp_path,
        env,
        "v2",
        extra_env={"FORGE_VOICE_SCHEMA_VERSION": "2"},
    )

    assert result.returncode == 0, result.stderr
    assert (release / "previous").read_text(encoding="utf-8").strip() == "v1"
    assert (release / "previous-schema").read_text(encoding="utf-8").strip() == "1"
    assert (release / "current").read_text(encoding="utf-8").strip() == "v2"
    assert (release / "current-schema").read_text(encoding="utf-8").strip() == "2"
    assert (data / "backup" / "booking.db").read_text(encoding="utf-8") == "old-schema\n"
    lines = _log(log_path)
    assert any("compose down --remove-orphans" in line for line in lines)
    assert any("compose build" in line for line in lines)
    assert next(i for i, line in enumerate(lines) if "compose down" in line) < next(
        i for i, line in enumerate(lines) if "compose build" in line
    )

    (data / "booking.db").write_text("new-schema\n", encoding="utf-8")
    (data / "new-schema-only.txt").write_text("new\n", encoding="utf-8")
    rollback = _run(OPS, tmp_path, env, "rollback")

    assert rollback.returncode == 0, rollback.stderr
    assert (data / "booking.db").read_text(encoding="utf-8") == "old-schema\n"
    assert not (data / "new-schema-only.txt").exists()
    assert (release / "current-schema").read_text(encoding="utf-8").strip() == "1"
    assert any("tag=v1 args=compose up -d --no-build" in line for line in _log(log_path))


def test_release_without_a_schema_bump_keeps_the_marker(
    tmp_path: Path, fake_docker: tuple[dict[str, str], Path]
) -> None:
    env, _ = fake_docker
    release = tmp_path / ".release"
    release.mkdir()
    (release / "current").write_text("v1\n", encoding="utf-8")
    (release / "current-schema").write_text("1\n", encoding="utf-8")
    (tmp_path / "data").mkdir()

    result = _run(RELEASE, tmp_path, env, "v2")

    assert result.returncode == 0, result.stderr
    assert (release / "previous-schema").read_text(encoding="utf-8").strip() == "1"
    assert (release / "current-schema").read_text(encoding="utf-8").strip() == "1"
