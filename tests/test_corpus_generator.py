from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, time
from pathlib import Path

import pytest
import yaml

from forge_voice.corpus import (
    SeedDataError,
    SeedSlot,
    TenantSeed,
    build_tenant_seed,
    generate_corpus,
    validate_tenant_seed,
)
from forge_voice.tenants import TenantConfigError, load_tenant

ROOT = Path(__file__).resolve().parents[1]


def _source_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "tenants", root / "tenants")
    (root / "scenarios").mkdir(parents=True)
    shutil.copyfile(ROOT / "scenarios" / "manifest.yaml", root / "scenarios" / "manifest.yaml")
    return root


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def generated_root(tmp_path: Path) -> Path:
    root = _source_root(tmp_path)
    generate_corpus(root)
    return root


def _output(root: Path) -> Path:
    return root / "fixtures" / "corpus"


def _seed(root: Path, tenant: str = "harborlight") -> dict:
    return json.loads((_output(root) / "seed" / f"{tenant}.json").read_text(encoding="utf-8"))


def _tenant(root: Path, tenant: str = "harborlight") -> dict:
    return yaml.safe_load((root / "tenants" / f"{tenant}.yaml").read_text(encoding="utf-8"))


def test_generate_corpus_copies_tenant_yaml_files(generated_root: Path) -> None:
    for tenant in ("harborlight", "summit"):
        assert (_output(generated_root) / "tenants" / f"{tenant}.yaml").read_bytes() == (
            generated_root / "tenants" / f"{tenant}.yaml"
        ).read_bytes()


def test_generate_corpus_copies_scenario_manifest(generated_root: Path) -> None:
    assert (_output(generated_root) / "scenarios" / "manifest.yaml").read_bytes() == (
        generated_root / "scenarios" / "manifest.yaml"
    ).read_bytes()


def test_generate_corpus_writes_40_text_caller_scripts(generated_root: Path) -> None:
    callers = list((_output(generated_root) / "scenarios" / "callers").glob("text_*.txt"))
    assert len(callers) == 40


def test_generate_corpus_writes_10_audio_metadata_placeholders(generated_root: Path) -> None:
    placeholders = list(
        (_output(generated_root) / "scenarios" / "audio").glob("audio_*.placeholder.yaml")
    )
    assert len(placeholders) == 10


def test_generate_corpus_writes_audio_placeholder_at_manifest_fixture_path(
    generated_root: Path,
) -> None:
    manifest = yaml.safe_load(
        (generated_root / "scenarios" / "manifest.yaml").read_text(encoding="utf-8")
    )
    audio = [scenario for scenario in manifest["scenarios"] if scenario["mode"] == "audio"]
    for scenario in audio:
        marker = (
            _output(generated_root) / "scenarios" / f"{scenario['audio']['fixture']}.placeholder"
        )
        assert marker.is_file(), marker


def test_generate_corpus_writes_seed_files(generated_root: Path) -> None:
    assert (_output(generated_root) / "seed" / "harborlight.json").is_file()
    assert (_output(generated_root) / "seed" / "summit.json").is_file()


def test_generate_corpus_writes_verifiable_hashes(generated_root: Path) -> None:
    hashes = json.loads((_output(generated_root) / "hashes.json").read_text(encoding="utf-8"))
    artifacts = {entry["path"]: entry["sha256"] for entry in hashes["artifacts"]}
    for relative_path, digest in artifacts.items():
        digest_now = hashlib.sha256(
            (_output(generated_root) / relative_path).read_bytes()
        ).hexdigest()
        assert digest_now == digest


def test_generate_corpus_hash_manifest_reports_locked_counts(generated_root: Path) -> None:
    hashes = json.loads((_output(generated_root) / "hashes.json").read_text(encoding="utf-8"))
    assert hashes["counts"] == {
        "text": 40,
        "text_dev": 32,
        "text_held_out": 8,
        "text_smoke": 8,
        "text_critical_repeat": 10,
        "audio": 10,
        "audio_dev": 8,
        "audio_held_out": 2,
        "audio_smoke": 2,
        "audio_local": 6,
    }
    assert len(hashes["artifacts"]) == 65


def test_generate_corpus_summary_reports_manifest_hash(generated_root: Path) -> None:
    hashes = json.loads((_output(generated_root) / "hashes.json").read_text(encoding="utf-8"))
    artifact_hashes = {entry["path"]: entry["sha256"] for entry in hashes["artifacts"]}
    summary = generate_corpus(generated_root)
    assert summary.manifest_sha256 == artifact_hashes["scenarios/manifest.yaml"]


def test_generate_corpus_is_deterministic_on_rerun(tmp_path: Path) -> None:
    root = _source_root(tmp_path)

    generate_corpus(root)
    first = _tree(_output(root))
    first_hashes = json.loads(first["hashes.json"])

    generate_corpus(root)
    second = _tree(_output(root))

    assert first == second
    assert first_hashes == json.loads(second["hashes.json"])
    assert first["scenarios/manifest.yaml"] == second["scenarios/manifest.yaml"]


def test_seed_contains_customers_with_served_zip_codes(generated_root: Path) -> None:
    seed = _seed(generated_root)
    tenant = _tenant(generated_root)
    served = set(tenant["service_area"]["zip_allowlist"]) - set(
        tenant["service_area"]["zip_exclusions"]
    )
    assert len(seed["customers"]) >= 4
    assert all(customer["address"]["zip"] in served for customer in seed["customers"])


def test_seed_bookings_reference_known_customer_service_technician_and_slot(
    generated_root: Path,
) -> None:
    seed = _seed(generated_root)
    tenant = _tenant(generated_root)
    customers = {customer["customer_id"] for customer in seed["customers"]}
    services = {service["id"] for service in tenant["services"]}
    technicians = {
        technician["id"]: set(technician["skills"])
        for technician in tenant["dispatch"]["technicians"]
    }
    slots = {slot["slot_id"]: slot for slot in seed["slots"]}

    for booking in seed["bookings"]:
        assert booking["customer_id"] in customers
        assert booking["service_id"] in services
        assert booking["service_id"] in technicians[booking["technician_id"]]
        slot = slots[booking["slot_id"]]
        assert slot["service_id"] == booking["service_id"]
        assert slot["technician_id"] == booking["technician_id"]
        assert slot["start"] == booking["start"]


def test_seed_bookings_mark_their_slots_booked(generated_root: Path) -> None:
    seed = _seed(generated_root)
    slots = {slot["slot_id"]: slot for slot in seed["slots"]}
    for booking in seed["bookings"]:
        assert slots[booking["slot_id"]]["status"] == "booked"


def test_seed_calls_reference_known_customers_and_bookings(generated_root: Path) -> None:
    seed = _seed(generated_root)
    phones = {customer["phone"] for customer in seed["customers"]}
    bookings = {booking["booking_id"] for booking in seed["bookings"]}
    for call in seed["calls"]:
        if call["caller_phone"] is not None:
            assert call["caller_phone"] in phones
        if call["booking_id"] is not None:
            assert call["booking_id"] in bookings


def test_seed_calls_reference_existing_emergency_tickets(generated_root: Path) -> None:
    seed = _seed(generated_root)
    tickets = {ticket["ticket_id"]: ticket for ticket in seed["tickets"]}
    for call in seed["calls"]:
        if call["ticket_id"] is None:
            continue
        assert call["ticket_id"] in tickets
        assert tickets[call["ticket_id"]]["call_id"] == call["call_id"]


def test_seed_calendar_indexes_open_and_booked_slots(generated_root: Path) -> None:
    seed = _seed(generated_root)
    booked = {booking["slot_id"] for booking in seed["bookings"]}
    open_slots = {slot["slot_id"] for slot in seed["slots"] if slot["status"] == "open"}
    assert set(seed["calendar"]["booked_slot_ids"]) == booked
    assert set(seed["calendar"]["open_slot_ids"]) == open_slots


def test_seed_booked_slots_are_not_open(generated_root: Path) -> None:
    seed = _seed(generated_root)
    booked = {booking["slot_id"] for booking in seed["bookings"]}
    open_slots = {slot["slot_id"] for slot in seed["slots"] if slot["status"] == "open"}
    assert booked.isdisjoint(open_slots)


@pytest.mark.parametrize("status", ["open", "booked"])
def test_seed_slots_do_not_overlap_per_technician(generated_root: Path, status: str) -> None:
    seed = _seed(generated_root)
    slots = [slot for slot in seed["slots"] if slot["status"] == status]
    for index, first in enumerate(slots):
        for second in slots[index + 1 :]:
            if first["technician_id"] != second["technician_id"]:
                continue
            first_start = datetime.fromisoformat(first["start"])
            first_end = datetime.fromisoformat(first["end"])
            second_start = datetime.fromisoformat(second["start"])
            second_end = datetime.fromisoformat(second["end"])
            assert not (first_start < second_end and second_start < first_end), (
                first["slot_id"],
                second["slot_id"],
            )


def test_seed_slots_stay_within_configured_business_hours(generated_root: Path) -> None:
    seed = _seed(generated_root)
    tenant = _tenant(generated_root)
    for slot in seed["slots"]:
        start = datetime.fromisoformat(slot["start"])
        end = datetime.fromisoformat(slot["end"])
        ranges = tenant["business_hours"][start.strftime("%A").lower()]
        windows = [
            (
                datetime.combine(start.date(), time.fromisoformat(start_text), tzinfo=start.tzinfo),
                datetime.combine(start.date(), time.fromisoformat(end_text), tzinfo=start.tzinfo),
            )
            for start_text, end_text in (value.split("-") for value in ranges)
        ]
        assert any(
            start >= window_start and end <= window_end for window_start, window_end in windows
        )


def test_seed_slots_exclude_tenant_holidays(generated_root: Path) -> None:
    seed = _seed(generated_root)
    tenant = _tenant(generated_root)
    holidays = set(tenant["holidays"])
    assert holidays
    for slot in seed["slots"]:
        assert datetime.fromisoformat(slot["start"]).date().isoformat() not in holidays


def test_seed_includes_configured_saturday_slots(generated_root: Path) -> None:
    seed = _seed(generated_root)
    assert any(
        datetime.fromisoformat(slot["start"]).strftime("%A") == "Saturday" for slot in seed["slots"]
    )


def test_seed_validation_rejects_customer_zip_outside_service_area(
    generated_root: Path,
) -> None:
    seed = TenantSeed.model_validate(_seed(generated_root))
    tenant = load_tenant(generated_root / "tenants" / "harborlight.yaml")
    seed.customers[0].address.zip = "10001"

    with pytest.raises(SeedDataError, match="not served"):
        validate_tenant_seed(seed, tenant)


def test_seed_validation_rejects_open_slot_overlapping_booking(
    generated_root: Path,
) -> None:
    seed = TenantSeed.model_validate(_seed(generated_root))
    tenant = load_tenant(generated_root / "tenants" / "harborlight.yaml")
    seed.slots.append(
        SeedSlot(
            slot_id="slot_hl_conflict",
            tenant_id="harborlight",
            service_id="drain_cleaning",
            technician_id="tech_alex",
            start=datetime.fromisoformat("2026-11-09T09:15:00-08:00"),
            end=datetime.fromisoformat("2026-11-09T09:45:00-08:00"),
            status="open",
        )
    )

    with pytest.raises(SeedDataError, match="overlaps booking"):
        validate_tenant_seed(seed, tenant)


def test_seed_validation_rejects_booking_status_mismatch(generated_root: Path) -> None:
    seed = TenantSeed.model_validate(_seed(generated_root))
    tenant = load_tenant(generated_root / "tenants" / "harborlight.yaml")
    seed.bookings[0].status = "cancelled"

    with pytest.raises(SeedDataError, match="status"):
        validate_tenant_seed(seed, tenant)


def test_seed_validation_rejects_crm_customer_mismatch(generated_root: Path) -> None:
    seed = TenantSeed.model_validate(_seed(generated_root))
    tenant = load_tenant(generated_root / "tenants" / "harborlight.yaml")
    seed.crm.customer_ids = seed.crm.customer_ids[:-1]

    with pytest.raises(SeedDataError, match=r"crm\.customer_ids"):
        validate_tenant_seed(seed, tenant)


def test_seed_validation_rejects_dangling_emergency_ticket(generated_root: Path) -> None:
    seed = TenantSeed.model_validate(_seed(generated_root))
    tenant = load_tenant(generated_root / "tenants" / "harborlight.yaml")
    seed.tickets.clear()

    with pytest.raises(SeedDataError, match="unknown ticket"):
        validate_tenant_seed(seed, tenant)


def test_seed_sms_messages_are_queued_for_bookings(generated_root: Path) -> None:
    seed = _seed(generated_root)
    bookings = {booking["booking_id"]: booking for booking in seed["bookings"]}
    assert seed["sms"]["messages"]
    for message in seed["sms"]["messages"]:
        assert message["status"] == "queued"
        assert message["booking_id"] in bookings
        assert message["to"] == bookings[message["booking_id"]]["contact_phone"]


def test_seed_data_is_tenant_scoped(generated_root: Path) -> None:
    harborlight = _seed(generated_root, "harborlight")
    summit = _seed(generated_root, "summit")

    assert {customer["customer_id"] for customer in harborlight["customers"]}.isdisjoint(
        {customer["customer_id"] for customer in summit["customers"]}
    )
    assert {booking["tenant_id"] for booking in harborlight["bookings"]} == {"harborlight"}
    assert {booking["tenant_id"] for booking in summit["bookings"]} == {"summit"}
    assert {call["tenant_id"] for call in summit["calls"]} == {"summit"}


def test_build_tenant_seed_rejects_unknown_tenant() -> None:
    tenant = load_tenant(ROOT / "tenants" / "harborlight.yaml").model_copy(
        update={"tenant_id": "unknown_tenant"}
    )

    with pytest.raises(SeedDataError, match="unknown_tenant"):
        build_tenant_seed(tenant)


def test_generate_corpus_fails_closed_on_invalid_tenant(tmp_path: Path) -> None:
    root = _source_root(tmp_path)
    path = root / "tenants" / "harborlight.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.pop("display_name")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(TenantConfigError, match="display_name"):
        generate_corpus(root)

    assert not _output(root).exists()


@pytest.mark.parametrize("fail_name", ["harborlight.json", "hashes.json"])
def test_generate_corpus_restores_previous_output_when_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_name: str
) -> None:
    root = _source_root(tmp_path)
    generate_corpus(root)
    output = _output(root)
    before = _tree(output)
    real_replace = os.replace
    failed = False

    def fail_once(source: str | Path, target: str | Path) -> None:
        nonlocal failed
        assert output.exists(), "the corpus directory disappeared during the swap"
        if not failed and Path(target).name == fail_name:
            failed = True
            raise OSError("simulated commit failure")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_once)

    with pytest.raises(OSError, match="simulated commit failure"):
        generate_corpus(root)

    assert _tree(output) == before
    assert not (root / "fixtures" / ".corpus.staging").exists()
    assert not (root / "fixtures" / ".corpus.backup").exists()


def test_committed_corpus_matches_the_generator(tmp_path: Path) -> None:
    root = _source_root(tmp_path)
    generate_corpus(root)

    committed = ROOT / "fixtures" / "corpus"
    generated = _output(root)
    assert (committed / "hashes.json").read_bytes() == (generated / "hashes.json").read_bytes()
    assert _tree(committed) == _tree(generated)
