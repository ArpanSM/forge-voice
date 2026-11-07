"""Evaluation harness, baseline, hard gates and generated report (ticket #6)."""

from forge_voice.eval.loader import (
    EvalSelection,
    HeldoutIsolationError,
    agent_view,
    load_selection,
    sealed_manifest,
)
from forge_voice.eval.models import EvalReport, ScenarioExecution, ScenarioResult
from forge_voice.eval.runner import EvalHarnessError, RunConfig, run_eval
from forge_voice.eval.scoring import (
    build_aggregates,
    build_scenario_result,
    evaluate_gates,
    score_scenario,
)

__all__ = [
    "EvalHarnessError",
    "EvalReport",
    "EvalSelection",
    "HeldoutIsolationError",
    "RunConfig",
    "ScenarioExecution",
    "ScenarioResult",
    "agent_view",
    "build_aggregates",
    "build_scenario_result",
    "evaluate_gates",
    "load_selection",
    "run_eval",
    "score_scenario",
    "sealed_manifest",
]
