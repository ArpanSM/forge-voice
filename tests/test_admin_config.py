"""The local admin editor validates tenant YAML and reloads only valid writes."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from forge_voice.tenants import TenantConfig, TenantConfigError, load_all_tenants
from forge_voice.web.admin import TenantAdminService
from forge_voice.web.app import create_app
from forge_voice.web.claims import TenantClaimSigner

ROOT = Path(__file__).resolve().parents[1]
SECRET = "local-admin-test-secret-that-is-long-enough"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def tenants_dir(tmp_path: Path) -> Path:
    target = tmp_path / "tenants"
    target.mkdir()
    for name in ("harborlight", "summit"):
        shutil.copy(ROOT / "tenants" / f"{name}.yaml", target / f"{name}.yaml")
    return target


@pytest.fixture
def admin(tenants_dir: Path) -> TenantAdminService:
    return TenantAdminService(tenants_dir)


@pytest.fixture
def client(admin: TenantAdminService) -> TestClient:
    app = create_app(
        tenants=admin.configs(),
        minter=None,
        claim_signer=TenantClaimSigner(SECRET, ttl_seconds=120),
        livekit_url="ws://localhost:7880",
        now=lambda: NOW,
        admin=admin,
    )
    return TestClient(app)


def _raw(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _valid_edit(path: Path, *, display_name: str) -> str:
    data = _raw(path)
    data["display_name"] = display_name
    return yaml.safe_dump(data, sort_keys=False)


def test_admin_page_edits_both_tenant_yamls(client: TestClient) -> None:
    index = client.get("/admin")
    assert index.status_code == 200
    assert "Harborlight Home Services" in index.text
    assert "Summit Heating" in index.text
    assert "tenant_id: harborlight" in index.text

    summit = client.get("/admin/summit")
    assert summit.status_code == 200
    assert "tenant_id: summit" in summit.text
    assert "tenant_id: harborlight" not in summit.text
    assert 'name="yaml"' in summit.text


def test_admin_valid_edit_writes_the_yaml_and_reloads(
    client: TestClient, tenants_dir: Path
) -> None:
    path = tenants_dir / "harborlight.yaml"
    edited = _valid_edit(path, display_name="Harborlight Test Services")

    response = client.post("/admin/harborlight", data={"yaml": edited}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/harborlight?saved=1"
    assert _raw(path)["display_name"] == "Harborlight Test Services"
    assert load_all_tenants(tenants_dir)["harborlight"].display_name == (
        "Harborlight Test Services"
    )
    page = client.get("/admin/harborlight?saved=1")
    assert page.status_code == 200
    assert "Saved and reloaded" in page.text
    # The public page reads the same reloaded registry.
    home = client.get("/")
    assert "Harborlight Test Services" in home.text


def test_admin_valid_edit_updates_the_second_tenant_too(
    client: TestClient, tenants_dir: Path
) -> None:
    path = tenants_dir / "summit.yaml"
    edited = _valid_edit(path, display_name="Summit Test Air")

    response = client.post("/admin/summit", data={"yaml": edited}, follow_redirects=False)

    assert response.status_code == 303
    assert load_all_tenants(tenants_dir)["summit"].display_name == "Summit Test Air"


def test_admin_invalid_schema_edit_is_rejected_without_reload_or_write(
    client: TestClient, tenants_dir: Path
) -> None:
    path = tenants_dir / "harborlight.yaml"
    before = path.read_text(encoding="utf-8")
    data = _raw(path)
    data["services"][0]["price_range"]["max"] = 1
    data["services"][0]["price_range"]["min"] = 999

    response = client.post(
        "/admin/harborlight",
        data={"yaml": yaml.safe_dump(data, sort_keys=False)},
    )

    assert response.status_code == 400
    assert "schema validation failed" in response.text
    assert "price_range.max" in response.text
    assert path.read_text(encoding="utf-8") == before
    assert client.get("/admin/harborlight").text.count("Harborlight Home Services") >= 1
    assert not list(tenants_dir.glob(".harborlight.yaml.*"))


def test_admin_rejects_an_edit_that_changes_the_tenant_id(
    client: TestClient, tenants_dir: Path
) -> None:
    path = tenants_dir / "harborlight.yaml"
    before = path.read_text(encoding="utf-8")
    data = _raw(path)
    data["tenant_id"] = "summit"

    response = client.post(
        "/admin/harborlight",
        data={"yaml": yaml.safe_dump(data, sort_keys=False)},
    )

    assert response.status_code == 400
    assert "tenant_id" in response.text
    assert path.read_text(encoding="utf-8") == before


def test_admin_rejects_invalid_yaml_and_unknown_fields(
    client: TestClient, tenants_dir: Path
) -> None:
    path = tenants_dir / "harborlight.yaml"
    before = path.read_text(encoding="utf-8")

    broken = client.post("/admin/harborlight", data={"yaml": "tenant_id: [unclosed"})
    assert broken.status_code == 400
    assert "invalid YAML" in broken.text

    data = _raw(path)
    data["workflow_graph"] = {"nodes": []}
    unknown = client.post(
        "/admin/harborlight",
        data={"yaml": yaml.safe_dump(data, sort_keys=False)},
    )
    assert unknown.status_code == 400
    assert "workflow_graph" in unknown.text
    assert path.read_text(encoding="utf-8") == before


def test_admin_route_fails_closed_for_unknown_tenants(client: TestClient) -> None:
    assert client.get("/admin/not-a-tenant").status_code == 404
    response = client.post("/admin/not-a-tenant", data={"yaml": "tenant_id: not-a-tenant\n"})
    assert response.status_code == 404


def test_admin_rejects_non_local_hosts_and_cross_origin_posts(
    client: TestClient, tenants_dir: Path
) -> None:
    remote = TestClient(client.app, base_url="http://public.example")
    assert remote.get("/admin").status_code == 403

    before = (tenants_dir / "harborlight.yaml").read_text(encoding="utf-8")
    response = client.post(
        "/admin/harborlight",
        data={"yaml": before},
        headers={"origin": "http://public.example"},
    )
    assert response.status_code == 403
    assert (tenants_dir / "harborlight.yaml").read_text(encoding="utf-8") == before


def test_admin_edit_reloads_the_monitoring_tenant_names(tenants_dir: Path) -> None:
    from forge_voice.monitoring.service import MonitoringService

    monitoring = MonitoringService(
        data_dir=tenants_dir.parent / "data",
        root=tenants_dir.parent,
        profile="local",
        seed=False,
    )
    admin = TenantAdminService(tenants_dir, on_reload=monitoring.reload_tenants)
    app = create_app(
        tenants=admin.configs(),
        minter=None,
        claim_signer=TenantClaimSigner(SECRET, ttl_seconds=120),
        livekit_url="ws://localhost:7880",
        now=lambda: NOW,
        admin=admin,
        monitoring=monitoring,
    )
    client = TestClient(app)
    path = tenants_dir / "summit.yaml"
    edited = _valid_edit(path, display_name="Summit Reloaded")
    assert client.post("/admin/summit", data={"yaml": edited}).status_code in {200, 303}
    assert monitoring.tenant_name("summit") == "Summit Reloaded"


def test_admin_save_is_atomic_and_keeps_the_previous_file_on_reload_failure(
    tenants_dir: Path,
) -> None:
    admin = TenantAdminService(tenants_dir)
    path = tenants_dir / "harborlight.yaml"
    before = path.read_text(encoding="utf-8")

    # Break the other tenant so a valid write cannot reload the full registry.
    summit = tenants_dir / "summit.yaml"
    summit_before = summit.read_text(encoding="utf-8")
    summit.write_text("tenant_id: summit\n", encoding="utf-8")

    with pytest.raises(TenantConfigError):
        admin.save(
            "harborlight",
            _valid_edit(path, display_name="Should Not Persist"),
        )

    assert path.read_text(encoding="utf-8") == before
    summit.write_text(summit_before, encoding="utf-8")
    assert admin.configs()["harborlight"] == TenantConfig.model_validate(_raw(path))


def test_admin_edit_covers_hours_services_area_handoff_adapters_kb_and_emergency(
    client: TestClient, tenants_dir: Path
) -> None:
    path = tenants_dir / "harborlight.yaml"
    data = _raw(path)
    data["business_hours"]["monday"] = ["08:00-18:00"]
    data["services"][0]["price_range"]["max"] = data["services"][0]["price_range"]["max"] + 25
    data["service_area"]["dispatch_zones"]["94107"] = "south"
    data["handoff"]["targets"][0]["phone"] = "+14155550999"
    data["integrations"]["calendar"]["config"]["path"] = "data/harborlight/calendar-v2.db"
    data["knowledge_base"]["faq"][0]["answer"] += " Synthetic demo only."
    data["emergency"]["categories"][0]["threshold"] = "any gas smell, no threshold"

    response = client.post(
        "/admin/harborlight",
        data={"yaml": yaml.safe_dump(data, sort_keys=False)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    reloaded = load_all_tenants(tenants_dir)["harborlight"]
    assert reloaded.business_hours.monday == ["08:00-18:00"]
    assert reloaded.services[0].price_range.max == data["services"][0]["price_range"]["max"]
    assert reloaded.service_area.dispatch_zones["94107"] == "south"
    assert reloaded.handoff.targets[0].phone == "+14155550999"
    assert reloaded.integrations.calendar.config["path"] == "data/harborlight/calendar-v2.db"
    assert "Synthetic demo only." in reloaded.knowledge_base.faq[0].answer
    assert reloaded.emergency.categories[0].threshold == "any gas smell, no threshold"
