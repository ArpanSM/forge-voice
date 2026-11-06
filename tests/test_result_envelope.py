from __future__ import annotations

import pytest
from pydantic import ValidationError

from forge_voice.result import ErrorInfo, ResultEnvelope


def test_success_envelope_carries_data_and_request_id() -> None:
    envelope = ResultEnvelope.success({"booking_id": "bk_0001"}, request_id="req_01")

    assert envelope.ok is True
    assert envelope.data == {"booking_id": "bk_0001"}
    assert envelope.error is None
    assert envelope.request_id == "req_01"
    assert envelope.model_dump(mode="json") == {
        "ok": True,
        "data": {"booking_id": "bk_0001"},
        "error": None,
        "request_id": "req_01",
    }


def test_failure_envelope_carries_stable_error() -> None:
    envelope: ResultEnvelope[dict] = ResultEnvelope.failure(
        "slot_unavailable",
        "That slot was just taken.",
        request_id="req_02",
    )

    assert envelope.ok is False
    assert envelope.data is None
    assert isinstance(envelope.error, ErrorInfo)
    assert envelope.error.code == "slot_unavailable"
    assert envelope.error.retryable is False
    assert envelope.error.details == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": True, "request_id": "req_03"},
        {
            "ok": False,
            "data": {"x": 1},
            "error": {"code": "internal_error", "message": "boom"},
            "request_id": "req_03",
        },
        {
            "ok": True,
            "data": {"x": 1},
            "error": {"code": "internal_error", "message": "boom"},
            "request_id": "req_03",
        },
    ],
)
def test_envelope_rejects_ambiguous_or_empty_success(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ResultEnvelope.model_validate(payload)
