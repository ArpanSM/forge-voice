from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from forge_voice.corpus import generate_corpus
from forge_voice.tenants import TenantConfigError

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


def test_generate_corpus_produces_tenants_manifest_seeds_callers_and_hashes(
    tmp_path: Path,
) -> None:
    root = _source_root(tmp_path)

    summary = generate_corpus(root)

    output = root / "fixtures" / "corpus"
    assert summary.output_dir == output
    assert (output / "tenants" / "harborlight.yaml").read_bytes() == (
        root / "tenants" / "harborlight.yaml"
    ).read_bytes()
    assert (output / "tenants" / "summit.yaml").read_bytes() == (
        root / "tenants" / "summit.yaml"
    ).read_bytes()
    assert (output / "scenarios" / "manifest.yaml").read_bytes() == (
        root / "scenarios" / "manifest.yaml"
    ).read_bytes()
    assert len(list((output / "scenarios" / "callers").glob("text_*.txt"))) == 40
    assert len(list((output / "scenarios" / "audio").glob("audio_*.placeholder.yaml"))) == 10
    assert len(list((output / "scenarios" / "fixtures" / "audio").glob("*.wav.placeholder"))) == 10
    assert (output / "seed" / "harborlight.json").is_file()
    assert (output / "seed" / "summit.json").is_file()

    hashes = json.loads((output / "hashes.json").read_text(encoding="utf-8"))
    assert hashes["counts"]["text"] == 40
    assert hashes["counts"]["audio"] == 10
    artifacts = {entry["path"]: entry["sha256"] for entry in hashes["artifacts"]}
    for relative_path, digest in artifacts.items():
        assert hashlib.sha256((output / relative_path).read_bytes()).hexdigest() == digest
    assert "seed/harborlight.json" in artifacts
    assert "scenarios/callers/text_book_01.txt" in artifacts
    assert "scenarios/audio/audio_bargein_01.placeholder.yaml" in artifacts
    assert "scenarios/fixtures/audio/bargein_01.wav.placeholder" in artifacts
    assert "hashes.json" not in artifacts
    assert summary.manifest_sha256 == artifacts["scenarios/manifest.yaml"]


def test_generate_corpus_is_deterministic_on_rerun(tmp_path: Path) -> None:
    root = _source_root(tmp_path)

    generate_corpus(root)
    first = _tree(root / "fixtures" / "corpus")
    first_hashes = json.loads(first["hashes.json"])
    first_manifest = first["scenarios/manifest.yaml"]

    generate_corpus(root)
    second = _tree(root / "fixtures" / "corpus")
    second_hashes = json.loads(second["hashes.json"])
    second_manifest = second["scenarios/manifest.yaml"]

    assert first == second
    assert first_hashes == second_hashes
    assert first_manifest == second_manifest


def test_seed_data_covers_customers_bookings_slots_calls_and_side_effects(
    tmp_path: Path,
) -> None:
    root = _source_root(tmp_path)
    generate_corpus(root)

    seed = json.loads((root / "fixtures" / "corpus" / "seed" / "harborlight.json").read_text())
    tenant = yaml.safe_load((root / "tenants" / "harborlight.yaml").read_text())
    allowed_zips = set(tenant["service_area"]["zip_allowlist"])
    service_ids = {service["id"] for service in tenant["services"]}
    tech_ids = {tech["id"] for tech in tenant["dispatch"]["technicians"]}

    assert seed["tenant_id"] == "harborlight"
    assert len(seed["customers"]) >= 4
    assert {booking["booking_id"] for booking in seed["bookings"]} >= {
        "bk_0001",
        "bk_0002",
        "bk_0003",
        "bk_0004",
    }
    assert len(seed["slots"]) > 100
    assert len(seed["calls"]) >= 3
    assert seed["sms"]["messages"]

    slots = {slot["slot_id"]: slot for slot in seed["slots"]}
    booked_slot_ids = []
    for booking in seed["bookings"]:
        assert booking["tenant_id"] == "harborlight"
        assert booking["service_id"] in service_ids
        assert booking["technician_id"] in tech_ids
        assert booking["customer_id"] in {c["customer_id"] for c in seed["customers"]}
        slot = slots[booking["slot_id"]]
        assert slot["status"] == "booked"
        assert slot["start"] == booking["start"]
        booked_slot_ids.append(booking["slot_id"])
    assert len(booked_slot_ids) == len(set(booked_slot_ids))
    assert set(seed["calendar"]["booked_slot_ids"]) == set(booked_slot_ids)
    assert set(seed["calendar"]["open_slot_ids"]) == {
        slot_id for slot_id, slot in slots.items() if slot["status"] == "open"
    }
    assert all(customer["address"]["zip"] in allowed_zips for customer in seed["customers"])
    assert seed["crm"]["customer_ids"] == [c["customer_id"] for c in seed["customers"]]
    assert all(message["status"] == "queued" for message in seed["sms"]["messages"])
    assert all(message["booking_id"] for message in seed["sms"]["messages"])


def test_seed_data_is_tenant_scoped(tmp_path: Path) -> None:
    root = _source_root(tmp_path)
    generate_corpus(root)

    harborlight = json.loads(
        (root / "fixtures" / "corpus" / "seed" / "harborlight.json").read_text()
    )
    summit = json.loads((root / "fixtures" / "corpus" / "seed" / "summit.json").read_text())

    assert {customer["customer_id"] for customer in harborlight["customers"]}.isdisjoint(
        {customer["customer_id"] for customer in summit["customers"]}
    )
    assert {booking["tenant_id"] for booking in harborlight["bookings"]} == {"harborlight"}
    assert {booking["tenant_id"] for booking in summit["bookings"]} == {"summit"}
    assert {call["tenant_id"] for call in summit["calls"]} == {"summit"}


def test_generate_corpus_fails_closed_on_invalid_tenant(tmp_path: Path) -> None:
    root = _source_root(tmp_path)
    path = root / "tenants" / "harborlight.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.pop("display_name")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(TenantConfigError, match="display_name"):
        generate_corpus(root)

    assert not (root / "fixtures" / "corpus").exists()


def test_committed_corpus_matches_the_generator(tmp_path: Path) -> None:
    root = _source_root(tmp_path)
    generate_corpus(root)

    committed = ROOT / "fixtures" / "corpus"
    generated = root / "fixtures" / "corpus"
    assert (committed / "hashes.json").read_bytes() == (generated / "hashes.json").read_bytes()
    assert _tree(committed) == _tree(generated)
