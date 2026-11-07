"""Deterministic corpus generation for tenants, seeds, scenarios and hashes."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge_voice.audio.fixtures import (
    AudioScript,
    load_audio_scripts,
    verify_fixtures,
)
from forge_voice.corpus.seed import ANCHOR_DATE, build_tenant_seed
from forge_voice.scenarios import AudioScenario, ScenarioManifest, TextScenario, load_manifest
from forge_voice.tenants import load_all_tenants


@dataclass(frozen=True)
class CorpusSummary:
    output_dir: Path
    artifact_hashes: dict[str, str]
    manifest_sha256: str
    text_scenarios: int
    audio_scenarios: int


@dataclass(frozen=True)
class _ArtifactSet:
    contents: dict[str, bytes]
    manifest_sha256: str


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def _caller_script(scenario: TextScenario) -> bytes:
    lines = [
        f"# scenario: {scenario.id}",
        f"# persona: {scenario.persona}",
        f"# goal: {scenario.goal}",
        f"# max_turns: {scenario.max_turns}",
        "",
        *scenario.turns,
        "",
    ]
    return "\n".join(lines).encode()


def _audio_caller_script(scenario: AudioScenario, script: AudioScript) -> bytes:
    lines = [
        f"# scenario: {scenario.id}",
        f"# tenant: {scenario.tenant}",
        f"# persona: {scenario.persona}",
        f"# goal: {scenario.goal}",
        f"# degradation: {script.degradation or 'none'}",
        "",
    ]
    for turn in script.turns:
        lines.append(f"[pause {turn.pause_before_ms} ms]")
        lines.append(turn.text)
        lines.append(f"[pause {turn.pause_after_ms} ms]")
    lines.append("")
    return "\n".join(lines).encode()


def _build_artifacts(root: Path, manifest: ScenarioManifest) -> _ArtifactSet:
    contents: dict[str, bytes] = {}
    for slug in sorted(manifest.tenants):
        contents[f"tenants/{slug}.yaml"] = (root / "tenants" / f"{slug}.yaml").read_bytes()

    manifest_bytes = (root / "scenarios" / "manifest.yaml").read_bytes()
    contents["scenarios/manifest.yaml"] = manifest_bytes

    for scenario in manifest.text_scenarios:
        contents[f"scenarios/callers/{scenario.id}.txt"] = _caller_script(scenario)

    audio_scripts = load_audio_scripts(root / "scenarios" / "audio_scripts.yaml", manifest)
    for scenario in manifest.audio_scenarios:
        contents[f"scenarios/audio/{scenario.id}.txt"] = _audio_caller_script(
            scenario, audio_scripts[scenario.id]
        )
        fixture_path = root / "scenarios" / scenario.audio.fixture
        if not fixture_path.is_file():
            raise FileNotFoundError(
                f"missing audio fixture {fixture_path}; run `make audio-fixtures` first"
            )
        contents[f"scenarios/{scenario.audio.fixture}"] = fixture_path.read_bytes()
    contents["scenarios/fixtures/audio/hashes.json"] = (
        root / "scenarios" / "fixtures" / "audio" / "hashes.json"
    ).read_bytes()

    for slug, tenant in sorted(load_all_tenants(root / "tenants").items()):
        seed = build_tenant_seed(tenant)
        contents[f"seed/{slug}.json"] = _json_bytes(seed.model_dump(mode="json"))

    return _ArtifactSet(
        contents=contents,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )


def _relative_files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _remove_empty_dirs(root: Path) -> None:
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        with suppress(OSError):
            directory.rmdir()


def _restore_previous(output: Path, backup: Path) -> None:
    previous_paths = _relative_files(backup)
    for path in sorted(backup.rglob("*")):
        if not path.is_file():
            continue
        target = output / path.relative_to(backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, target)
    for relative_path in _relative_files(output) - previous_paths:
        (output / relative_path).unlink()
    _remove_empty_dirs(output)
    shutil.rmtree(backup, ignore_errors=True)


def _commit_corpus(staging: Path, output: Path, staged_paths: set[str]) -> None:
    """Publish staged files with per-file atomic replaces and a hashes-last marker.

    The output directory is never removed. A backup copy keeps the previous corpus valid if
    any replace before the `hashes.json` commit marker fails.
    """
    backup = output.parent / ".corpus.backup"
    shutil.rmtree(backup, ignore_errors=True)
    had_output = output.exists()
    output.mkdir(parents=True, exist_ok=True)
    if had_output:
        shutil.copytree(output, backup)
    try:
        for relative_path in sorted(staged_paths - {"hashes.json"}):
            target = output / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / relative_path, target)
        os.replace(staging / "hashes.json", output / "hashes.json")
    except Exception:
        if had_output:
            _restore_previous(output, backup)
        else:
            shutil.rmtree(output, ignore_errors=True)
        raise
    shutil.rmtree(backup, ignore_errors=True)

    for relative_path in sorted(_relative_files(output) - staged_paths):
        (output / relative_path).unlink()
    _remove_empty_dirs(output)


def generate_corpus(root: Path | str) -> CorpusSummary:
    """Regenerate `fixtures/corpus/` from the tenant and scenario sources.

    Inputs are validated before any output path is touched. Output uses sorted JSON/YAML and
    a fixed anchor date, so two runs produce identical bytes and hashes.
    """
    root = Path(root).resolve()
    tenants = load_all_tenants(root / "tenants")
    manifest = load_manifest(
        root / "scenarios" / "manifest.yaml",
        known_tenants=tenants.keys(),
    )
    fixture_errors = verify_fixtures(root)
    if fixture_errors:
        from forge_voice.audio.fixtures import FixtureError

        raise FixtureError("audio fixtures are not stable: " + "; ".join(fixture_errors))
    artifacts = _build_artifacts(root, manifest)

    hashes = {
        "schema_version": 1,
        "generator": "forge_voice.corpus",
        "anchor_date": ANCHOR_DATE.isoformat(),
        "manifest_id": manifest.manifest_id,
        "counts": manifest.counts.model_dump(),
        "artifacts": [
            {
                "path": relative_path,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for relative_path, content in sorted(artifacts.contents.items())
        ],
    }

    fixtures_dir = root / "fixtures"
    staging = fixtures_dir / ".corpus.staging"
    output = fixtures_dir / "corpus"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    staged = dict(artifacts.contents)
    staged["hashes.json"] = _json_bytes(hashes)
    try:
        for relative_path, content in sorted(staged.items()):
            target = staging / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        _commit_corpus(staging, output, set(staged))
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    digest_by_path = {entry["path"]: entry["sha256"] for entry in hashes["artifacts"]}
    return CorpusSummary(
        output_dir=output,
        artifact_hashes=digest_by_path,
        manifest_sha256=artifacts.manifest_sha256,
        text_scenarios=manifest.counts.text,
        audio_scenarios=manifest.counts.audio,
    )
