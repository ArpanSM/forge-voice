"""Raw traces and recordings are pruned at the 30-day retention boundary."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

from forge_voice.monitoring.retention import main, prune_raw_data

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _touch(path: Path, *, days_old: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("synthetic\n", encoding="utf-8")
    timestamp = time.time() - days_old * 86400
    os.utime(path, (timestamp, timestamp))
    return path


def test_prunes_old_raw_calls_and_recordings_but_keeps_fresh_and_non_trace_files(
    tmp_path: Path,
) -> None:
    old_call = _touch(tmp_path / "data" / "calls" / "old.jsonl", days_old=31)
    fresh_call = _touch(tmp_path / "data" / "calls" / "fresh.jsonl", days_old=2)
    notes = _touch(tmp_path / "data" / "calls" / "notes.txt", days_old=31)
    old_recording = _touch(tmp_path / "recordings" / "old.wav", days_old=31)
    fresh_recording = _touch(tmp_path / "recordings" / "fresh.wav", days_old=2)

    removed = prune_raw_data(
        tmp_path / "data",
        tmp_path / "recordings",
        retention_days=30,
        now=NOW,
    )

    assert removed == {"calls": 1, "recordings": 1}
    assert not old_call.exists()
    assert fresh_call.exists()
    assert notes.exists()
    assert not old_recording.exists()
    assert fresh_recording.exists()


def test_missing_directories_are_a_no_op(tmp_path: Path) -> None:
    removed = prune_raw_data(tmp_path / "data", tmp_path / "recordings", now=NOW)

    assert removed == {"calls": 0, "recordings": 0}


def test_cli_reports_what_it_removed(tmp_path: Path, capsys) -> None:
    _touch(tmp_path / "data" / "calls" / "old.jsonl", days_old=40)

    code = main(
        [
            "--data-dir",
            str(tmp_path / "data"),
            "--recordings-dir",
            str(tmp_path / "recordings"),
            "--retention-days",
            "30",
            "--now",
            "2026-11-07T12:00:00+00:00",
        ]
    )

    assert code == 0
    assert "removed 1 raw call traces" in capsys.readouterr().out


def test_retention_window_must_be_positive(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError):
        prune_raw_data(tmp_path, tmp_path, retention_days=0)


def test_dashboard_startup_runs_the_raw_retention_job(tmp_path: Path, monkeypatch) -> None:
    from forge_voice.monitoring.service import MonitoringService

    called: dict[str, object] = {}

    def fake_prune(data_dir, recordings_dir, *, retention_days, now):
        called["data_dir"] = Path(data_dir)
        called["recordings_dir"] = Path(recordings_dir)
        called["retention_days"] = retention_days
        return {"calls": 0, "recordings": 0}

    monkeypatch.setattr("forge_voice.monitoring.service.prune_raw_data", fake_prune)
    monkeypatch.setattr(
        "forge_voice.monitoring.service.seed_dashboard_calls",
        lambda *args, **kwargs: [],
    )

    MonitoringService(
        data_dir=tmp_path / "data",
        root=tmp_path,
        profile="local",
        seed=True,
        now=lambda: NOW,
    )

    assert called["data_dir"] == tmp_path / "data"
    assert called["recordings_dir"] == tmp_path / "recordings"
    assert called["retention_days"] == 30
