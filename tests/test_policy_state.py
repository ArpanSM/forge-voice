from __future__ import annotations

from datetime import timedelta

import pytest

from forge_voice.domain import Address
from forge_voice.policy import (
    CallIntent,
    CallOutcome,
    CallPhase,
    ConfirmationRequiredError,
    ConfirmationTokenStore,
    ConversationPolicy,
    ReadbackPayload,
    TokenStatus,
    payload_digest,
)


def _readback(tenant, *, slot_id="slot_hl_00001", service_id="drain_cleaning"):
    service = tenant.require_service(service_id)
    return ReadbackPayload(
        tenant_id=tenant.tenant_id,
        intent=CallIntent.book,
        target=slot_id,
        service_id=service.id,
        service_name=service.name,
        start="2026-11-09T09:00:00-08:00",
        end="2026-11-09T10:00:00-08:00",
        technician_id="tech_alex",
        technician_name="Alex",
        address=Address(
            line1="12 Alder St",
            city="San Francisco",
            state="CA",
            zip="94107",
        ),
        contact_phone="+14155550101",
        customer_name="Sam Rivera",
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


def test_policy_phase_progression_is_explicit(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")

    assert state.phase is CallPhase.greet
    policy.identify_intent(state, "I need a drain cleaning")
    assert state.phase is CallPhase.collect
    policy.begin_offer(state)
    assert state.phase is CallPhase.offer
    policy.read_back(state, _readback(harborlight))
    assert state.phase is CallPhase.awaiting_confirmation
    assert policy.confirm(state, "yes").accepted is True
    assert state.phase is CallPhase.write
    token = policy.issue_confirmation(state)
    policy.mark_written(state, target=token.binding.target, booking_id="bk_new")
    assert state.phase is CallPhase.done


def test_confirmation_token_requires_readback_and_explicit_yes(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1", "+14155550101")
    policy.identify_intent(state, "I need a drain cleaning")

    with pytest.raises(ConfirmationRequiredError):
        policy.issue_confirmation(state)

    policy.begin_offer(state)
    policy.read_back(state, _readback(harborlight))
    decision = policy.confirm(state, "yes, book it")
    assert decision.accepted is True
    token = policy.issue_confirmation(state)

    assert token.token.startswith("ct_")
    assert token.expires_at - token.issued_at == timedelta(seconds=120)
    assert state.phase is CallPhase.write
    assert (
        policy.tokens.validate(token.token, token.binding, at=clock.now).status is TokenStatus.valid
    )


def test_yes_before_readback_returns_explicit_confirmation_required(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")

    decision = policy.confirm(state, "yes, book it")

    assert decision.accepted is False
    assert decision.error == "explicit_confirmation_required"
    assert state.explicit_yes is False


def test_ambiguous_yes_wait_is_refused_without_raising(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")
    policy.begin_offer(state)
    policy.read_back(state, _readback(harborlight))

    decision = policy.confirm(state, "yes, wait")

    assert decision.accepted is False
    assert decision.error == "explicit_confirmation_required"
    assert state.explicit_yes is False
    with pytest.raises(ConfirmationRequiredError):
        policy.issue_confirmation(state)


def test_refusal_never_issues_a_token(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")
    policy.begin_offer(state)
    policy.read_back(state, _readback(harborlight))

    decision = policy.confirm(state, "no, don't book it yet")

    assert decision.accepted is False
    assert state.explicit_yes is False
    with pytest.raises(ConfirmationRequiredError):
        policy.issue_confirmation(state)


def test_confirm_after_readback_authorizes_one_decision(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")
    policy.begin_offer(state)
    policy.read_back(state, _readback(harborlight))

    first = policy.confirm(state, "yes, book it")
    assert first.accepted is True
    assert state.explicit_yes is True
    second = policy.confirm(state, "no")
    assert second.accepted is False
    assert state.explicit_yes is False


def test_refresh_clears_confirmation_and_requires_a_new_readback(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")
    policy.begin_offer(state)
    policy.read_back(state, _readback(harborlight))
    assert policy.confirm(state, "yes").accepted is True

    policy.clear_confirmation(state)
    policy.begin_offer(state)

    assert state.awaiting_confirmation is False
    assert state.explicit_yes is False
    assert state.confirmation_token is None
    assert policy.confirm(state, "yes").accepted is False

    policy.read_back(state, _readback(harborlight, slot_id="slot_hl_00002"))
    assert state.awaiting_confirmation is True
    assert policy.confirm(state, "yes, that one").accepted is True


def test_readback_binds_the_exact_target_and_payload(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")
    payload = _readback(harborlight, slot_id="slot_hl_00002")
    policy.begin_offer(state)
    policy.read_back(state, payload)
    policy.confirm(state, "yes")
    token = policy.issue_confirmation(state)

    assert token.binding.target == "slot_hl_00002"
    assert token.binding.payload_hash == payload_digest(payload.token_payload())


def test_token_is_one_use(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")
    policy.begin_offer(state)
    policy.read_back(state, _readback(harborlight))
    policy.confirm(state, "yes")
    token = policy.issue_confirmation(state)

    assert policy.tokens.consume(token.token, token.binding).status is TokenStatus.valid
    assert policy.tokens.validate(token.token, token.binding).status is TokenStatus.used


def test_token_expires_after_120_seconds(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")
    policy.begin_offer(state)
    policy.read_back(state, _readback(harborlight))
    policy.confirm(state, "yes")
    token = policy.issue_confirmation(state)
    later = clock.now + timedelta(seconds=121)

    assert (
        policy.tokens.validate(token.token, token.binding, at=later).status is TokenStatus.expired
    )


def test_token_is_bound_to_tenant_call_intent_target_and_payload(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")
    policy.identify_intent(state, "I need a drain cleaning")
    policy.begin_offer(state)
    policy.read_back(state, _readback(harborlight))
    policy.confirm(state, "yes")
    token = policy.issue_confirmation(state)

    tampered = token.binding.model_copy(update={"call_id": "call_2"})
    assert policy.tokens.validate(token.token, tampered).status is TokenStatus.binding_mismatch

    forged = policy.tokens.validate("ct_made_up_by_the_model", token.binding)
    assert forged.status is TokenStatus.unknown


def test_token_factory_is_injectable_for_determinism(harborlight, clock) -> None:
    def issue(factory):
        tokens = ConfirmationTokenStore(clock, token_factory=lambda: factory)
        policy = ConversationPolicy(harborlight, clock, tokens)
        state = policy.start_call("call_1", "+14155550101")
        policy.identify_intent(state, "I need a drain cleaning")
        policy.begin_offer(state)
        policy.read_back(state, _readback(harborlight))
        policy.confirm(state, "yes")
        return policy.issue_confirmation(state)

    assert issue("fixed").token == issue("fixed").token


def test_policy_classifies_after_hours(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)

    assert policy.is_after_hours(clock.now) is False
    assert policy.is_after_hours(clock.now.replace(hour=21)) is True


def test_policy_classifies_the_change_cutoff(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)

    assert policy.within_change_cutoff(clock.now + timedelta(minutes=119), clock.now) is True
    assert policy.within_change_cutoff(clock.now + timedelta(minutes=121), clock.now) is False


def test_policy_allows_one_self_serve_change(harborlight, clock) -> None:
    policy = ConversationPolicy(harborlight, clock)
    state = policy.start_call("call_1")

    assert policy.can_change(state) is True
    policy.record_change(state)
    assert policy.can_change(state) is False
    assert state.change_count == 1
