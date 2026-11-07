"""The ten audio fixtures are committed, scripted and hash-checked offline."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from forge_voice.audio.fixtures import (
    AudioScript,
    AudioTurn,
    fixture_hash,
    load_audio_scripts,
    load_fixture_manifest,
    synthesize_fixture,
    verify_fixtures,
)
from forge_voice.runtime.audio_io import parse_pcm16_wav
from forge_voice.scenarios import load_manifest

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "scenarios"
FIXTURES = SCENARIOS / "fixtures" / "audio"


class FakeTts:
    """Deterministic, offline WAV producer used to prove assembly and hashing."""

    def __init__(self, samples_per_char: int = 4, rate: int = 24000) -> None:
        self.samples_per_char = samples_per_char
        self.rate = rate
        self.calls: list[dict[str, object]] = []

    def synthesize(self, text: str, *, voice: str, lang: str, seed: int) -> bytes:
        self.calls.append({"text": text, "voice": voice, "lang": lang, "seed": seed})
        count = max(1, len(text) * self.samples_per_char)
        value = (seed % 1000).to_bytes(2, "little", signed=False)
        samples = (value * count)[: count * 2]
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self.rate)
            handle.writeframes(samples)
        return buffer.getvalue()


def scripts():
    manifest = load_manifest(SCENARIOS / "manifest.yaml", known_tenants={"harborlight", "summit"})
    return manifest, load_audio_scripts(SCENARIOS / "audio_scripts.yaml", manifest)


def test_audio_scripts_cover_every_manifest_scenario_with_the_right_tenant() -> None:
    manifest, loaded = scripts()

    assert set(loaded) == {scenario.id for scenario in manifest.audio_scenarios}
    for scenario in manifest.audio_scenarios:
        assert loaded[scenario.id].tenant == scenario.tenant
        if scenario.audio.method == "livekit_simulation":
            assert loaded[scenario.id].degradation is None


def test_scripts_mark_the_expected_degradations() -> None:
    _, loaded = scripts()

    assert loaded["audio_noisy_01"].degradation == "noisy"
    assert loaded["audio_badline_01"].degradation == "badline"
    assert loaded["audio_lowmic_01"].degradation == "lowmic"
    assert loaded["audio_packetloss_01"].degradation == "packetloss"
    assert loaded["audio_bargein_01"].degradation is None


def test_silence_script_starts_with_three_seconds_of_silence() -> None:
    _, loaded = scripts()

    script = loaded["audio_silence_01"]

    assert script.turns[0].pause_before_ms >= 3000


def test_synthesize_fixture_is_deterministic_and_keeps_every_turn() -> None:
    script = AudioScript(
        tenant="harborlight",
        turns=[
            AudioTurn(text="one", pause_before_ms=0, pause_after_ms=100),
            AudioTurn(text="two", pause_before_ms=50, pause_after_ms=0),
        ],
    )
    tts = FakeTts(samples_per_char=10)

    first = synthesize_fixture(script, tts, seed=11)
    second = synthesize_fixture(
        AudioScript.model_validate(script.model_dump()), FakeTts(10), seed=11
    )

    assert first == second
    assert len(tts.calls) == 2
    parsed = parse_pcm16_wav(first)
    samples = len("one") * 10 + len("two") * 10
    gap_ms = 100 + 50
    assert parsed.frame_count == samples + gap_ms * 24
    assert parsed.sample_rate == 24000


def test_committed_fixtures_all_have_stable_hashes() -> None:
    manifest = load_fixture_manifest(FIXTURES / "hashes.json")

    assert len(manifest.fixtures) == 10
    assert [entry.scenario_id for entry in manifest.fixtures] == sorted(
        entry.scenario_id for entry in manifest.fixtures
    )


def test_committed_audio_fixtures_verify_against_the_manifest() -> None:
    assert verify_fixtures(ROOT) == []


def test_every_committed_fixture_is_pcm16_mono_24khz_audio() -> None:
    manifest = load_fixture_manifest(FIXTURES / "hashes.json")

    for entry in manifest.fixtures:
        parsed = parse_pcm16_wav((SCENARIOS / entry.fixture).read_bytes())
        assert parsed.sample_rate == 24000
        assert parsed.channels == 1
        assert parsed.sample_width == 2
        assert parsed.duration_ms > 1000
        assert len(parsed.frames) > 40_000


def test_silence_fixture_leads_with_silence() -> None:
    manifest = load_fixture_manifest(FIXTURES / "hashes.json")
    entry = next(item for item in manifest.fixtures if item.scenario_id == "audio_silence_01")

    parsed = parse_pcm16_wav((SCENARIOS / entry.fixture).read_bytes())
    lead = parsed.frames[: int(2.5 * 24000) * 2]

    assert set(lead) == {0}


def test_fixture_hash_is_the_sha256_of_exactly_the_committed_bytes() -> None:
    manifest = load_fixture_manifest(FIXTURES / "hashes.json")
    entry = manifest.fixtures[0]
    data = (SCENARIOS / entry.fixture).read_bytes()

    assert fixture_hash(data) == entry.sha256


def test_audio_scripts_reject_a_scenario_the_manifest_does_not_know() -> None:
    manifest, _ = scripts()
    bad = {
        "schema_version": 1,
        "scenarios": {
            "audio_unknown_01": {
                "tenant": "harborlight",
                "turns": [{"text": "hello"}],
            }
        },
    }
    from forge_voice.audio.fixtures import load_audio_scripts_data

    with pytest.raises(ValueError, match="audio_unknown_01"):
        load_audio_scripts_data(bad, manifest)
