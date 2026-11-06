from __future__ import annotations

from datetime import timedelta

import pytest

from forge_voice.policy import (
    CallIntent,
    CallOutcome,
    CallPhase,
    ConfirmationRequiredError,
    ConversationPolicy,
    TokenStatus,
)


def test_all_seven_intents_and_nine_outcomes_are_explicit() -> None:
    assert {intent.value for intent in CallIntent} == {
        "book",
        "reschedule",
        "cancel",
        "status",
        "emergency",
        "pricing_faq",
        "human",
    }
    assert {outcome.value for outcome in CallOutcome} == {
        "booked",
        "rescheduled",
        "cancelled",
        "emergency_ticket",
        "transferred",
        "callback",
        "info_only",
        "abandoned",
        "failed",
    }


def test_new_call_starts_in_greet_with_no_outcome(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)

    state = policy.start_call("call_1", "+14155550101")

    assert state.phase is CallPhase.greet
    assert state.intent is None
    assert state.outcome is None
    assert state.tenant_id == "harborlight"
    assert state.call_id == "call_1"
    assert state.caller_phone == "+14155550101"


@pytest.mark.parametrize(
    ("utterance", "intent"),
    [
        ("I need a drain cleaning", CallIntent.book),
        ("I need to move my appointment", CallIntent.reschedule),
        ("Please cancel my booking", CallIntent.cancel),
        ("When is my appointment?", CallIntent.status),
        ("I smell gas near the furnace", CallIntent.emergency),
        ("How much is a drain cleaning?", CallIntent.pricing_faq),
        ("I want to talk to a person", CallIntent.human),
    ],
)
def test_policy_routes_each_intent(harborlight, clock, utterance, intent) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")

    assert policy.identify_intent(state, utterance) is intent
    assert state.intent is intent


def test_confirmation_token_requires_readback_and_explicit_yes(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1", "+14155550101")
    policy.identify_intent(state, "I need a drain cleaning")
    payload = {"service_id": "drain_cleaning", "slot_id": "slot_hl_00001"}

    with pytest.raises(ConfirmationRequiredError):
        policy.issue_confirmation(state, target="slot_hl_00001", payload=payload)

    policy.record_readback(state, payload)
    assert policy.confirm(state, "yes, book it") is True
    token = policy.issue_confirmation(state, target="slot_hl_00001", payload=payload)

    assert token.token.startswith("ct_")
    assert token.expires_at - token.issued_at == timedelta(seconds=120)
    assert (
        policy.tokens.validate(token.token, token.binding, at=clock.now).status is TokenStatus.valid
    )


def test_refusal_never_issues_a_token(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")
    policy.record_readback(state, {"slot_id": "slot_hl_00001"})

    assert policy.confirm(state, "no, don't book it yet") is False
    with pytest.raises(ConfirmationRequiredError):
        policy.issue_confirmation(state, target="slot_hl_00001", payload={"slot_id": "x"})


def test_token_payload_must_match_the_readback_payload(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")
    policy.record_readback(state, {"service_id": "drain_cleaning", "slot_id": "slot_hl_00001"})
    policy.confirm(state, "yes")

    with pytest.raises(ConfirmationRequiredError):
        policy.issue_confirmation(
            state,
            target="slot_hl_00002",
            payload={"service_id": "drain_cleaning", "slot_id": "slot_hl_00002"},
        )


def test_token_is_one_use_and_expires_after_120_seconds(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")
    payload = {"service_id": "drain_cleaning", "slot_id": "slot_hl_00001"}
    policy.record_readback(state, payload)
    policy.confirm(state, "yes")
    token = policy.issue_confirmation(state, target="slot_hl_00001", payload=payload)

    assert policy.tokens.consume(token.token, token.binding).status is TokenStatus.valid
    assert policy.tokens.validate(token.token, token.binding).status is TokenStatus.used

    second_payload = {"service_id": "drain_cleaning", "slot_id": "slot_hl_00002"}
    policy.record_readback(state, second_payload)
    policy.confirm(state, "yes, that one")
    second = policy.issue_confirmation(state, target="slot_hl_00002", payload=second_payload)
    later = clock.now + timedelta(seconds=121)
    assert (
        policy.tokens.validate(second.token, second.binding, at=later).status is TokenStatus.expired
    )


def test_token_is_bound_to_tenant_call_intent_target_and_payload(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")
    payload = {"service_id": "drain_cleaning", "slot_id": "slot_hl_00001"}
    policy.record_readback(state, payload)
    policy.confirm(state, "yes")
    token = policy.issue_confirmation(state, target="slot_hl_00001", payload=payload)

    tampered = token.binding.model_copy(update={"call_id": "call_2"})
    assert policy.tokens.validate(token.token, tampered).status is TokenStatus.binding_mismatch

    forged = policy.tokens.validate("ct_made_up_by_the_model", token.binding)
    assert forged.status is TokenStatus.unknown


def test_policy_classifies_after_hours_and_cutoff(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)

    assert policy.is_after_hours(clock.now) is False
    late = clock.now.replace(hour=21)
    assert policy.is_after_hours(late) is True
    assert policy.within_change_cutoff(clock.now + timedelta(minutes=119), clock.now) is True
    assert policy.within_change_cutoff(clock.now + timedelta(minutes=121), clock.now) is False

    state = policy.start_call("call_1")
    assert policy.can_change(state) is True
    policy.record_change(state)
    assert policy.can_change(state) is False
    assert state.change_count == 1
