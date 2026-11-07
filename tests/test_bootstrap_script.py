"""The bootstrap installer is pinned, not trust-on-first-use."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_livekit.sh"


def test_bootstrap_rejects_a_wrong_archive_checksum(tmp_path: Path) -> None:
    bad = tmp_path / "livekit_fake.tar.gz"
    bad.write_bytes(b"not the pinned release")

    result = subprocess.run(
        ["bash", str(SCRIPT), "--verify", "amd64", str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr


def test_bootstrap_rejects_a_wrong_existing_binary_checksum(tmp_path: Path) -> None:
    bad = tmp_path / "livekit-server"
    bad.write_bytes(b"not the pinned binary")

    result = subprocess.run(
        ["bash", str(SCRIPT), "--verify-binary", "amd64", str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr


def test_bootstrap_does_not_fetch_a_checksum_file_at_install_time() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "checksums.txt" not in text
    assert "1e9ee90ca301e1842b2887fc77cb122759756a9c8aeb4334ee91de3325ec43fb" in text
    assert "2af6ce091d6b3c79d1677f8ff1bbb91a8007f40b2325c059b52d38383c0830b6" in text
    assert "85a58024d9b36542712514e0e926c0adb74f6182bcb19a664b9d9eb98ad01b52" in text
    assert "ddaf42cc5aafb91e78b94427e52808f6f90840a15c02523333999abb02dd8682" in text
