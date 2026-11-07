"""Evaluation result, gate and report models.

The report JSON is the source of truth; every model here is serialization-safe and
uses the stable field names from roadmap #26.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from forge_voice.models import StrictModel
from forge_voice.scenarios.models import AudioFixture


class WriteRecord(StrictModel):
    """One successful or failed write-side tool call, used for correctness scoring."""

    tool: str
    ok: bool
    args: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error_code: str | None = None


class ScenarioExecution(StrictModel):
    """Observable result of one scenario run, independent of fixed or baseline."""

    scenario_id: str
    tenant: str
    mode: Literal["text", "audio"]
    outcome: str
    service_id: str | None = None
    booking_id: str | None = None
    booking_ids: list[str] = Field(default_factory=list)
    booking_count: int = 0
    ticket_count: int = 0
    ticket_id: str | None = None
    emergency_category: str | None = None
    safety_script: str | None = None
    vulnerable_occupant: bool = False
    callback_count: int = 0
    callback_id: str | None = None
    transfer_status: str | None = None
    handoff_packet: dict[str, Any] | None = None
    write_count: int = 0
    cancel_count: int = 0
    replayed: bool = False
    already_cancelled: bool = False
    old_slot_released: bool = False
    slot_released: bool = False
    confirmation_queued: bool = False
    confirmation_count: int = 0
    readbacks: int = 0
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    writes: list[WriteRecord] = Field(default_factory=list)
    response_text: str = ""
    qa_flags: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    wall_ms: int = 0
    recording_ref: str = "text_only"
    turns_used: int = 0
    asr_entities: dict[str, str | None] = Field(default_factory=dict)
    asr_expected_entities: dict[str, str | None] = Field(default_factory=dict)
    barge_in_recovered: bool | None = None
    error_code: str | None = None


class ScenarioVerdict(StrictModel):
    passed: bool
    failure_reason: str | None = None
    gate_failures: list[str] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)


class ScenarioResult(StrictModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    scenario_id: str
    category: str
    tenant: str
    held_out: bool
    mode: Literal["text", "audio"]
    profile: str
    pipeline: str
    split: str
    repeat_index: int = 0
    critical_repeat: bool = False
    persona: str
    goal: str
    expected: dict[str, Any]
    actual: dict[str, Any]
    pass_: bool = Field(alias="pass")
    gate_labels: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    transcript_ref: str
    recording_ref: str
    latency: dict[str, Any] = Field(default_factory=dict)
    cost: dict[str, Any] = Field(default_factory=dict)
    qa_flags: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    verdict: ScenarioVerdict
    execution: ScenarioExecution

    def report_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class GateResult(StrictModel):
    name: str
    description: str
    threshold: str
    value: str
    passed: bool
    gated: bool = True
    failing_scenario_ids: list[str] = Field(default_factory=list)
    numerator: int | None = None
    denominator: int | None = None


class AgentScenarioView(StrictModel):
    """The only scenario shape a runner may receive.

    It deliberately has no expected outcome, pass condition or hard-gate labels.
    """

    id: str
    mode: Literal["text", "audio"]
    tenant: str
    persona: str
    goal: str
    max_turns: int
    turns: list[str] = Field(default_factory=list)
    audio: AudioFixture | None = None
    local_subset: bool = False
    caller_phone: str | None = None
    now: datetime | None = None
    faults: dict[str, str] = Field(default_factory=dict)
    pre_cancel_booking: str | None = None
    extra_turns: list[str] = Field(default_factory=list)


class CostModel(StrictModel):
    currency: Literal["USD"] = "USD"
    as_of: date = date(2026, 11, 7)
    demo_marginal_usd: float = 0.0
    production_per_minute_low_usd: float = 0.03
    production_per_minute_high_usd: float = 0.06
    assumptions: list[str] = Field(default_factory=list)


class EvalReport(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    git_sha: str
    manifest_sha: str
    heldout_manifest_sha: str
    profile: str
    mode: str
    pipeline: str
    split: str
    verdict: str
    scenarios: list[ScenarioResult] = Field(default_factory=list)
    aggregates: dict[str, Any] = Field(default_factory=dict)
    gates: dict[str, GateResult] = Field(default_factory=dict)
    cost_model: CostModel
    caveats: list[str] = Field(default_factory=list)
    provider: dict[str, Any] = Field(default_factory=dict)
    repeats: dict[str, Any] = Field(default_factory=dict)
    counts: dict[str, Any] = Field(default_factory=dict)

    def report_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)
