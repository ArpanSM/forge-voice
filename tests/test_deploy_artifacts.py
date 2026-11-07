"""The Compose deployment, Make targets and handover docs stay inside ticket #8."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_compose_has_the_three_service_stack_and_lfm3_gate() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert {"livekit", "web", "agent", "lfm3-check"} <= set(services)
    assert "LFM3_AUDIO_BASE_URL" in services["agent"]["environment"]
    assert (
        services["agent"]["environment"]["LFM3_AUDIO_BASE_URL"]
        == "http://host.docker.internal:8082"
    )
    assert any(
        host.startswith("host.docker.internal:")
        for host in services["agent"].get("extra_hosts", [])
    )
    assert services["agent"]["depends_on"]["lfm3-check"]["condition"] == "service_healthy"


def test_compose_healthchecks_cover_livekit_web_agent_and_lfm3() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    for name in ("livekit", "web", "agent", "lfm3-check"):
        assert services[name]["healthcheck"]["test"], name
    assert "8000/health" in str(services["web"]["healthcheck"])
    assert "8081" in str(services["agent"]["healthcheck"])
    assert "host.docker.internal:8082/health" in str(services["lfm3-check"]["healthcheck"])


def test_compose_mounts_data_and_recordings_on_localhost_only() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    volumes = services["agent"]["volumes"] + services["web"]["volumes"]

    assert "./data:/app/data" in volumes
    assert "./recordings:/app/recordings" in volumes
    for service in ("livekit", "web", "agent"):
        for mapping in services[service].get("ports", []):
            assert str(mapping).startswith("127.0.0.1:"), (service, mapping)


def test_compose_uses_interpolated_image_tags_and_no_baked_secrets() -> None:
    text = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    compose = yaml.safe_load(text)
    services = compose["services"]

    assert "${FORGE_VOICE_IMAGE_TAG:-local}" in services["web"]["image"]
    assert "${FORGE_VOICE_IMAGE_TAG:-local}" in services["agent"]["image"]
    assert "LIVEKIT_API_SECRET:?" in text
    assert "GROQ_API_KEY=" not in text
    assert "livekit.cloud" not in text.lower()
    assert "sip://" not in text.lower()
    assert "sip" not in services


def test_dockerfile_has_web_and_agent_targets() -> None:
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim AS base" in dockerfile
    assert "FROM base AS web" in dockerfile
    assert "FROM base AS agent" in dockerfile
    assert "forge_voice.web.app" in dockerfile
    assert "forge_voice.runtime.livekit_agent" in dockerfile


def test_makefile_keeps_both_demo_paths_and_operations() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")

    for target in (
        "demo:",
        "demo-local:",
        "demo-compose:",
        "demo-hybrid:",
        "demo-hybrid-local:",
        "demo-hybrid-compose:",
        "down:",
        "reset:",
        "logs:",
        "rollback:",
        "health:",
    ):
        assert f"\n{target}" in text, target
    assert "DOCKER_AVAILABLE" in text
    assert "./scripts/demo.sh" in text
    assert "./scripts/compose_demo.sh" in text
    assert "./scripts/compose_ops.sh" in text


def test_runbook_is_one_page_and_covers_operations_and_failures() -> None:
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")

    required = [
        "lfm3 audio",
        ".env.local",
        "make demo",
        "make demo-hybrid",
        "make down",
        "make reset",
        "make logs",
        "make rollback",
        "http://localhost:8000",
        "/dashboard",
        "/admin",
        "LFM3",
        "Groq",
        "free",
        "rollback",
        "30-day",
        "No Cloud",
        "SIP",
    ]
    for needle in required:
        assert needle in runbook, needle
    assert len(runbook.splitlines()) <= 220


def test_training_outline_fits_five_minutes() -> None:
    training = (ROOT / "docs" / "training.md").read_text(encoding="utf-8")

    assert "5-minute" in training
    for minute in ("0:00", "1:00", "2:00", "3:00", "4:00"):
        assert minute in training
    assert "dashboard" in training.lower()
    assert "admin" in training.lower()
    assert "transfer" in training.lower()


def test_handover_checklist_and_support_boundary_are_written() -> None:
    handover = (ROOT / "docs" / "handover.md").read_text(encoding="utf-8")

    lowered = handover.lower()
    for needle in (
        "handover checklist",
        "- [ ]",
        "30 days",
        "bug fixes",
        "deployment help",
        "one config change",
        "change request",
        "new tenants",
        "new services",
        "new integrations",
        "secrets",
        "retention",
    ):
        assert needle in lowered, needle
    assert "No production SLA" in handover


def test_docs_do_not_claim_cloud_sip_or_paid_paths() -> None:
    combined = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("docs/runbook.md", "docs/training.md", "docs/handover.md")
    ).lower()

    assert "no cloud transport" in combined or "no cloud" in combined
    assert "sip" in combined
    assert "no paid" in combined or "no paid fallback" in combined
    assert "livekit cloud" not in combined or "no livekit cloud" in combined
