"""The demo env helper fills a copied .env.local and keeps the secret private."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_local_env.sh"
DEMO = Path(__file__).resolve().parents[1] / "scripts" / "demo.sh"


def run_prepare(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def read_env(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (root / ".env.local").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_prepare_creates_a_private_env_file_without_printing_the_secret(
    tmp_path: Path,
) -> None:
    result = run_prepare(tmp_path)

    assert result.returncode == 0
    path = tmp_path / ".env.local"
    values = read_env(tmp_path)
    assert values["LIVEKIT_URL"] == "ws://localhost:7880"
    assert values["LIVEKIT_API_KEY"] == "devkey"
    assert len(values["LIVEKIT_API_SECRET"]) == 64
    assert values["LIVEKIT_API_SECRET"] not in result.stdout
    assert values["LIVEKIT_API_SECRET"] not in result.stderr
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_prepare_fills_an_empty_secret_from_a_copied_env_file(tmp_path: Path) -> None:
    path = tmp_path / ".env.local"
    path.write_text(
        "LIVEKIT_URL=ws://localhost:7880\nLIVEKIT_API_KEY=devkey\n"
        "LIVEKIT_API_SECRET=\nFORGE_VOICE_PROFILE=local\n",
        encoding="utf-8",
    )
    path.chmod(0o644)

    result = run_prepare(tmp_path)

    values = read_env(tmp_path)
    assert result.returncode == 0
    assert len(values["LIVEKIT_API_SECRET"]) == 64
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_prepare_preserves_an_existing_non_empty_secret(tmp_path: Path) -> None:
    path = tmp_path / ".env.local"
    path.write_text(
        "LIVEKIT_URL=ws://localhost:7880\nLIVEKIT_API_KEY=devkey\n"
        "LIVEKIT_API_SECRET=keep-this-local-value\n",
        encoding="utf-8",
    )

    run_prepare(tmp_path)

    assert read_env(tmp_path)["LIVEKIT_API_SECRET"] == "keep-this-local-value"


def test_demo_passes_the_secret_through_the_environment_not_argv() -> None:
    text = DEMO.read_text(encoding="utf-8")

    assert "--keys" not in text
    assert "LIVEKIT_KEYS=" in text
    assert "scripts/prepare_local_env.sh" in text
