from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from forge_voice.tenants import (
    TenantConfigError,
    UnknownServiceError,
    UnknownTenantError,
    load_all_tenants,
    load_tenant,
    load_tenant_by_slug,
)

ROOT = Path(__file__).resolve().parents[1]
TENANTS_DIR = ROOT / "tenants"


def _raw(name: str) -> dict:
    return yaml.safe_load((TENANTS_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def _variant(tmp_path: Path, name: str, mutate) -> Path:
    data = _raw(name)
    mutate(data)
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_loader_loads_both_tenant_ids() -> None:
    registry = load_all_tenants(TENANTS_DIR)

    assert set(registry) == {"harborlight", "summit"}


def test_harborlight_config_has_expected_identity_and_coverage() -> None:
    harborlight = load_tenant(TENANTS_DIR / "harborlight.yaml")

    assert harborlight.display_name == "Harborlight Home Services"
    assert len(harborlight.service_area.zip_allowlist) == 8
    assert harborlight.has_zip("94107") is True


def test_harborlight_config_has_expected_services() -> None:
    harborlight = load_tenant(TENANTS_DIR / "harborlight.yaml")

    assert len(harborlight.services) == 7
    assert harborlight.require_service("drain_cleaning").price_range.min == 149


def test_summit_config_has_expected_identity_and_coverage() -> None:
    summit = load_tenant(TENANTS_DIR / "summit.yaml")

    assert summit.display_name == "Summit Heating & Air"
    assert len(summit.service_area.zip_allowlist) == 7
    assert summit.has_zip("95125") is True


def test_summit_config_has_expected_services() -> None:
    summit = load_tenant(TENANTS_DIR / "summit.yaml")

    assert len(summit.services) == 5
    assert summit.require_service("ac_repair").duration_minutes == 90


def test_loader_loads_tenant_by_slug() -> None:
    harborlight = load_tenant_by_slug(TENANTS_DIR, "harborlight")

    assert harborlight.tenant_id == "harborlight"


def test_loader_rejects_unknown_tenant() -> None:
    with pytest.raises(UnknownTenantError):
        load_tenant_by_slug(TENANTS_DIR, "nope")
    with pytest.raises(UnknownTenantError):
        load_tenant_by_slug(TENANTS_DIR, "../harborlight")


def test_loader_rejects_missing_required_field(tmp_path: Path) -> None:
    path = _variant(tmp_path, "harborlight", lambda data: data.pop("display_name"))

    with pytest.raises(TenantConfigError, match="display_name"):
        load_tenant(path)


def test_tenant_rejects_unknown_service() -> None:
    harborlight = load_tenant(TENANTS_DIR / "harborlight.yaml")

    with pytest.raises(UnknownServiceError):
        harborlight.require_service("roofing")


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda data: data["service_area"]["zip_allowlist"].append("9410"),
            id="short-zip",
        ),
        pytest.param(
            lambda data: data["service_area"]["zip_exclusions"].append("10001"),
            id="exclusion-outside-allowlist",
        ),
        pytest.param(
            lambda data: data["service_area"]["dispatch_zones"].pop("94133"),
            id="dispatch-zone-missing-allowlisted-zip",
        ),
        pytest.param(
            lambda data: data["dispatch"]["technicians"][0]["zips"].append("10001"),
            id="technician-outside-allowlist",
        ),
    ],
)
def test_loader_rejects_bad_zip_rule(tmp_path: Path, mutate) -> None:
    path = _variant(tmp_path, "harborlight", mutate)

    with pytest.raises(TenantConfigError):
        load_tenant(path)


def test_loader_rejects_unknown_service_references(tmp_path: Path) -> None:
    def add_unknown_skill(data: dict) -> None:
        data["dispatch"]["technicians"][0]["skills"].append("roofing")

    with pytest.raises(TenantConfigError, match="roofing"):
        load_tenant(_variant(tmp_path, "harborlight", add_unknown_skill))

    def add_unknown_pricing_service(data: dict) -> None:
        data["knowledge_base"]["pricing"].append(
            {"service_id": "roofing", "range": {"min": 1, "max": 2, "currency": "USD"}}
        )

    with pytest.raises(TenantConfigError, match="roofing"):
        load_tenant(_variant(tmp_path, "harborlight", add_unknown_pricing_service))


def test_loader_rejects_unknown_handoff_target_reference(tmp_path: Path) -> None:
    path = _variant(
        tmp_path,
        "summit",
        lambda data: data["emergency"]["categories"][0].update(
            {"transfer_target": "missing_target"}
        ),
    )

    with pytest.raises(TenantConfigError, match="missing_target"):
        load_tenant(path)


def test_loader_rejects_filename_and_tenant_id_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "summit.yaml"
    path.write_text((TENANTS_DIR / "harborlight.yaml").read_text(encoding="utf-8"))

    with pytest.raises(TenantConfigError, match="tenant_id"):
        load_tenant(path)
