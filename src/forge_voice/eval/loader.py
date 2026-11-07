"""Fail-closed eval selection, held-out sealing and runner isolation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from forge_voice.scenarios import ScenarioManifest, load_manifest
from forge_voice.scenarios.models import AudioScenario, Scenario, TextScenario

VALID_SPLITS = frozenset(
    {"smoke", "release", "dev", "heldout", "text-all", "audio", "audio-local", "critical"}
)


class HeldoutIsolationError(ValueError):
    """A held-out runner was started without the sealed manifest hash."""


@dataclass(frozen=True)
class EvalSelection:
    manifest: ScenarioManifest
    scenarios: list[Scenario]
    split: str
    manifest_sha: str
    heldout_manifest: dict[str, object]
    heldout_manifest_sha: str


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


HELDOUT_PIN = "scenarios/heldout.sha256"


def verify_heldout_pin(root: Path | str, computed: str) -> str:
    path = Path(root) / HELDOUT_PIN
    try:
        pinned = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HeldoutIsolationError(f"held-out pin is missing: {path}") from exc
    if not pinned:
        raise HeldoutIsolationError(f"held-out pin is empty: {path}")
    if pinned != computed:
        raise HeldoutIsolationError(
            "held-out manifest hash does not match the committed pin; "
            f"pinned={pinned} computed={computed}"
        )
    return pinned


def sealed_manifest(manifest: ScenarioManifest) -> dict[str, object]:
    """Return the scorer-only held-out labels and their stable hash."""
    held_out = sorted(
        (scenario for scenario in manifest.scenarios if scenario.held_out),
        key=lambda scenario: scenario.id,
    )
    scenarios = [scenario.model_dump(mode="json") for scenario in held_out]
    payload: dict[str, object] = {
        "schema_version": 1,
        "manifest_id": manifest.manifest_id,
        "scenario_ids": [scenario.id for scenario in held_out],
        "scenarios": scenarios,
    }
    payload["sha256"] = _canonical_sha256(payload)
    return payload


def _select(manifest: ScenarioManifest, split: str) -> list[Scenario]:
    if split not in VALID_SPLITS:
        raise ValueError(f"unknown eval split {split!r}; expected one of {sorted(VALID_SPLITS)}")
    if split == "smoke":
        return [
            scenario
            for scenario in manifest.text_scenarios
            if scenario.smoke and not scenario.held_out
        ]
    if split == "release":
        return [scenario for scenario in manifest.scenarios if scenario.mode == "text"]
    if split == "dev":
        return [scenario for scenario in manifest.scenarios if not scenario.held_out]
    if split == "heldout":
        return [scenario for scenario in manifest.scenarios if scenario.held_out]
    if split == "text-all":
        return list(manifest.text_scenarios)
    if split == "audio":
        return list(manifest.audio_scenarios)
    if split == "audio-local":
        return [scenario for scenario in manifest.audio_scenarios if scenario.local_subset]
    if split == "critical":
        return [scenario for scenario in manifest.text_scenarios if scenario.critical_repeat]
    raise AssertionError(f"unhandled split {split!r}")


def load_selection(root: Path | str, *, split: str) -> EvalSelection:
    root = Path(root).resolve()
    manifest_path = root / "scenarios" / "manifest.yaml"
    tenant_slugs = {path.stem for path in (root / "tenants").glob("*.yaml")}
    manifest = load_manifest(manifest_path, known_tenants=tenant_slugs)
    sealed = sealed_manifest(manifest)
    verify_heldout_pin(root, str(sealed["sha256"]))
    return EvalSelection(
        manifest=manifest,
        scenarios=_select(manifest, split),
        split=split,
        manifest_sha=file_sha256(manifest_path),
        heldout_manifest=sealed,
        heldout_manifest_sha=str(sealed["sha256"]),
    )


def agent_view(
    scenario: Scenario,
    *,
    heldout_manifest_sha: str | None,
    expected_heldout_sha: str | None = None,
    caller_phone: str | None = None,
    now: datetime | None = None,
    faults: dict[str, str] | None = None,
    pre_cancel_booking: str | None = None,
    extra_turns: list[str] | None = None,
) -> object:
    """Build the only view a runner may see; expected labels never cross this seam."""
    if scenario.held_out and not heldout_manifest_sha:
        raise HeldoutIsolationError(
            "held-out scenarios require the sealed held-out manifest hash before a runner starts"
        )
    if expected_heldout_sha is not None and heldout_manifest_sha != expected_heldout_sha:
        raise HeldoutIsolationError(
            "held-out manifest hash does not match the sealed pin; refusing to start"
        )
    from forge_voice.eval.models import AgentScenarioView

    text = scenario if isinstance(scenario, TextScenario) else None
    audio = scenario if isinstance(scenario, AudioScenario) else None
    return AgentScenarioView(
        id=scenario.id,
        mode=scenario.mode,
        tenant=scenario.tenant,
        persona=scenario.persona,
        goal=scenario.goal,
        max_turns=scenario.max_turns,
        turns=list(text.turns) if text else [],
        audio=audio.audio if audio else None,
        local_subset=audio.local_subset if audio else False,
        caller_phone=caller_phone,
        now=now,
        faults=dict(faults or {}),
        pre_cancel_booking=pre_cancel_booking,
        extra_turns=list(extra_turns or []),
    )


def assert_runner_view(view: object) -> None:
    payload = view.model_dump(mode="json") if hasattr(view, "model_dump") else dict(view)
    forbidden = {
        "expected",
        "expected_final_state",
        "expected_tool_calls",
        "pass_condition",
        "hard_gates",
    }
    leaked = forbidden & set(payload)
    if leaked:
        raise HeldoutIsolationError(f"runner view leaked expected outcome labels: {sorted(leaked)}")
