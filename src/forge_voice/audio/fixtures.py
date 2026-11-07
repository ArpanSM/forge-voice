"""Audio fixture scripts, deterministic synthesis, hashes and offline verification."""

from __future__ import annotations

import argparse
import array
import hashlib
import io
import json
import math
import os
import shutil
import sys
import wave
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml
from pydantic import Field, ValidationError

from forge_voice.models import StrictModel
from forge_voice.runtime.audio_io import WavFormatError, parse_pcm16_wav
from forge_voice.scenarios.models import AudioScenario, ScenarioManifest

SAMPLE_RATE = 24000
DEFAULT_VOICE = "female"
DEFAULT_LANGUAGE = "en"
GENERATOR = "forge_voice.audio.fixtures"


class FixtureError(ValueError):
    """A fixture script, manifest or generated WAV violates its contract."""


class AudioTurn(StrictModel):
    text: str = Field(min_length=1)
    pause_before_ms: int = Field(default=120, ge=0, le=10_000)
    pause_after_ms: int = Field(default=120, ge=0, le=10_000)


class AudioScript(StrictModel):
    tenant: str = Field(min_length=1)
    turns: list[AudioTurn] = Field(min_length=1)
    degradation: Literal["badline", "lowmic", "packetloss", "noisy"] | None = None


class AudioScriptSet(StrictModel):
    schema_version: Literal[1]
    scenarios: dict[str, AudioScript]


class FixtureTts(StrictModel):
    provider: Literal["lfm3"]
    model: Literal["lfm3-audio-2b"]
    voice: Literal["female"]
    language: Literal["en"]
    sample_rate: Literal[24000]
    temperature: Literal[0.0]


class FixtureEntry(StrictModel):
    scenario_id: str
    tenant: str
    fixture: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=1)
    duration_ms: int = Field(ge=1)
    sample_rate: Literal[24000] = SAMPLE_RATE
    channels: Literal[1] = 1
    turns_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    degradation: Literal["badline", "lowmic", "packetloss", "noisy"] | None = None
    seed: int


class FixtureManifest(StrictModel):
    schema_version: Literal[1]
    generator: str
    tts: FixtureTts
    fixtures: list[FixtureEntry]


class TtsClient(Protocol):
    def synthesize(self, text: str, *, voice: str, lang: str, seed: int) -> bytes: ...


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FixtureError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise FixtureError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise FixtureError(f"{path} must be a YAML mapping")
    return raw


def load_audio_scripts_data(
    raw: Mapping[str, Any], manifest: ScenarioManifest
) -> dict[str, AudioScript]:
    try:
        parsed = AudioScriptSet.model_validate(dict(raw))
    except ValidationError as exc:
        raise FixtureError(f"invalid audio script set: {exc}") from exc
    expected = {scenario.id: scenario for scenario in manifest.audio_scenarios}
    unknown = set(parsed.scenarios) - set(expected)
    missing = set(expected) - set(parsed.scenarios)
    if unknown:
        raise FixtureError(f"audio script set contains unknown scenario(s): {sorted(unknown)}")
    if missing:
        raise FixtureError(f"audio script set is missing scenario(s): {sorted(missing)}")
    for scenario_id, script in parsed.scenarios.items():
        scenario = expected[scenario_id]
        if script.tenant != scenario.tenant:
            raise FixtureError(
                f"audio script {scenario_id} tenant {script.tenant!r} "
                f"does not match manifest tenant {scenario.tenant!r}"
            )
        if scenario.audio.method == "degraded_clip" and script.degradation is None:
            raise FixtureError(f"audio script {scenario_id} needs a degradation")
        if scenario.audio.method == "livekit_simulation" and script.degradation is not None:
            raise FixtureError(
                f"audio script {scenario_id} is a clean simulation but sets a degradation"
            )
    return dict(sorted(parsed.scenarios.items()))


def load_audio_scripts(path: Path, manifest: ScenarioManifest) -> dict[str, AudioScript]:
    return load_audio_scripts_data(_read_yaml(path), manifest)


def load_fixture_manifest(path: Path) -> FixtureManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FixtureError(f"cannot read fixture hashes {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FixtureError(f"invalid fixture hashes {path}: {exc}") from exc
    try:
        manifest = FixtureManifest.model_validate(raw)
    except ValidationError as exc:
        raise FixtureError(f"invalid fixture hashes {path}: {exc}") from exc
    return manifest


def fixture_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def turns_hash(script: AudioScript) -> str:
    payload = json.dumps(script.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _silence(frame_count: int) -> bytes:
    return b"\x00\x00" * frame_count


def _degrade(frames: bytes, rate: int, kind: str, seed: int) -> bytes:
    samples = array.array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    import random

    rng = random.Random(seed)
    count = len(samples)
    rms = math.sqrt(sum(value * value for value in samples) / count) if count else 0.0
    if kind == "noisy":
        sigma = (rms or 300.0) / (10 ** (10 / 20))
        output = [value + rng.gauss(0, sigma) for value in samples]
        result = array.array("h", (max(-32768, min(32767, int(v))) for v in output))
    elif kind == "badline":
        result = array.array("h", [0]) * count
        previous = 0.0
        sigma = (rms or 300.0) / (10 ** (25 / 20))
        for index, value in enumerate(samples):
            previous = 0.65 * previous + 0.35 * value
            noisy = previous + rng.gauss(0, sigma)
            result[index] = max(-32768, min(32767, int(noisy)))
    elif kind == "lowmic":
        result = array.array("h", [0]) * count
        previous = 0.0
        for index, value in enumerate(samples):
            previous = 0.85 * previous + 0.15 * value
            boosted = previous * 1.4
            result[index] = max(-32768, min(32767, int(boosted)))
    elif kind == "packetloss":
        result = array.array("h", samples)
        chunk = max(1, int(rate * 0.02))
        for start in range(0, count, chunk):
            if rng.random() < 0.06:
                for index in range(start, min(start + chunk, count)):
                    result[index] = 0
    else:
        raise FixtureError(f"unknown degradation {kind!r}")
    if sys.byteorder != "little":
        result.byteswap()
    return result.tobytes()


def synthesize_fixture(
    script: AudioScript,
    tts: TtsClient,
    *,
    voice: str = DEFAULT_VOICE,
    lang: str = DEFAULT_LANGUAGE,
    seed: int = 0,
    sample_rate: int = SAMPLE_RATE,
) -> bytes:
    """Assemble one caller WAV from per-turn LFM3 TTS output.

    The seed is fixed per scenario and turn, and the server is called with
    temperature 0, so the same model build regenerates identical bytes.
    """
    chunks: list[bytes] = []
    for index, turn in enumerate(script.turns):
        chunks.append(_silence(round(turn.pause_before_ms * sample_rate / 1000)))
        audio = tts.synthesize(turn.text, voice=voice, lang=lang, seed=seed + index)
        parsed = parse_pcm16_wav(audio)
        if parsed.sample_rate != sample_rate:
            raise FixtureError(f"LFM3 returned {parsed.sample_rate} Hz; expected {sample_rate} Hz")
        if parsed.channels != 1:
            raise FixtureError("fixture synthesis requires mono TTS audio")
        chunks.append(parsed.frames)
        chunks.append(_silence(round(turn.pause_after_ms * sample_rate / 1000)))
    frames = b"".join(chunks)
    if script.degradation is not None:
        frames = _degrade(frames, sample_rate, script.degradation, seed)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)
    return buffer.getvalue()


def _seed_for(scenario_id: str) -> int:
    return int(hashlib.sha256(scenario_id.encode("utf-8")).hexdigest()[:8], 16)


def _entry(
    scenario: AudioScenario,
    script: AudioScript,
    data: bytes,
    *,
    seed: int,
) -> FixtureEntry:
    parsed = parse_pcm16_wav(data)
    return FixtureEntry(
        scenario_id=scenario.id,
        tenant=scenario.tenant,
        fixture=scenario.audio.fixture,
        sha256=fixture_hash(data),
        bytes=len(data),
        duration_ms=parsed.duration_ms,
        sample_rate=parsed.sample_rate,
        channels=parsed.channels,
        turns_sha256=turns_hash(script),
        degradation=script.degradation,
        seed=seed,
    )


def generate_fixtures(
    root: Path | str,
    tts: TtsClient,
    *,
    voice: str = DEFAULT_VOICE,
    lang: str = DEFAULT_LANGUAGE,
) -> FixtureManifest:
    """Synthesize all fixtures into staging, then publish WAVs and hashes last.

    Existing fixture bytes and the previous hash manifest stay intact if synthesis
    or a staging write fails. Publishing uses `os.replace`, and `hashes.json` is
    replaced only after every WAV has moved into place.
    """
    root = Path(root).resolve()
    from forge_voice.scenarios import load_manifest

    tenants = {path.stem for path in (root / "tenants").glob("*.yaml")}
    manifest = load_manifest(root / "scenarios" / "manifest.yaml", known_tenants=tenants)
    scripts = load_audio_scripts(root / "scenarios" / "audio_scripts.yaml", manifest)
    fixtures_dir = root / "scenarios" / "fixtures" / "audio"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    staging = root / "scenarios" / "fixtures" / ".audio.staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    entries: list[FixtureEntry] = []
    staged: dict[str, bytes] = {}
    try:
        for scenario in sorted(manifest.audio_scenarios, key=lambda item: item.id):
            seed = _seed_for(scenario.id)
            data = synthesize_fixture(scripts[scenario.id], tts, voice=voice, lang=lang, seed=seed)
            name = Path(scenario.audio.fixture).name
            staged[name] = data
            entries.append(_entry(scenario, scripts[scenario.id], data, seed=seed))
            (staging / name).write_bytes(data)

        manifest_out = FixtureManifest(
            schema_version=1,
            generator=GENERATOR,
            tts=FixtureTts(
                provider="lfm3",
                model="lfm3-audio-2b",
                voice=voice,
                language=lang,
                sample_rate=SAMPLE_RATE,
                temperature=0.0,
            ),
            fixtures=entries,
        )
        hashes_bytes = (
            json.dumps(manifest_out.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        (staging / "hashes.json").write_bytes(hashes_bytes)

        for name in sorted(staged):
            os.replace(staging / name, fixtures_dir / name)
        os.replace(staging / "hashes.json", fixtures_dir / "hashes.json")
        for path in fixtures_dir.glob("*.wav"):
            if path.name not in staged:
                path.unlink()
        return manifest_out
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def verify_fixtures(root: Path | str) -> list[str]:
    root = Path(root).resolve()
    errors: list[str] = []
    try:
        from forge_voice.scenarios import load_manifest

        tenants = {path.stem for path in (root / "tenants").glob("*.yaml")}
        manifest = load_manifest(root / "scenarios" / "manifest.yaml", known_tenants=tenants)
        scripts = load_audio_scripts(root / "scenarios" / "audio_scripts.yaml", manifest)
        fixture_manifest = load_fixture_manifest(
            root / "scenarios" / "fixtures" / "audio" / "hashes.json"
        )
    except (FixtureError, ValueError) as exc:
        return [str(exc)]

    expected = {scenario.id: scenario for scenario in manifest.audio_scenarios}
    seen: set[str] = set()
    for entry in fixture_manifest.fixtures:
        seen.add(entry.scenario_id)
        scenario = expected.get(entry.scenario_id)
        if scenario is None:
            errors.append(f"hashes.json lists unknown scenario {entry.scenario_id}")
            continue
        if entry.fixture != scenario.audio.fixture:
            errors.append(
                f"{entry.scenario_id}: hash path {entry.fixture!r} does not match "
                f"manifest path {scenario.audio.fixture!r}"
            )
        path = root / "scenarios" / entry.fixture
        if not path.is_file():
            errors.append(f"{entry.scenario_id}: missing fixture {path}")
            continue
        data = path.read_bytes()
        tts = fixture_manifest.tts
        if tts.provider != "lfm3" or tts.model != "lfm3-audio-2b":
            errors.append("fixture tts provider/model drift")
        if tts.voice != DEFAULT_VOICE or tts.language != DEFAULT_LANGUAGE:
            errors.append("fixture tts voice/language drift")
        if tts.sample_rate != SAMPLE_RATE or tts.temperature != 0.0:
            errors.append("fixture tts rate/temperature drift")
        if entry.tenant != scenario.tenant:
            errors.append(f"{entry.scenario_id}: tenant drift")
        if entry.channels != 1:
            errors.append(f"{entry.scenario_id}: channels drift")
        if entry.degradation != scripts[entry.scenario_id].degradation:
            errors.append(f"{entry.scenario_id}: degradation drift")
        if entry.seed != _seed_for(entry.scenario_id):
            errors.append(f"{entry.scenario_id}: seed drift")
        if len(data) != entry.bytes:
            errors.append(f"{entry.scenario_id}: byte-size drift")
        if fixture_hash(data) != entry.sha256:
            errors.append(f"{entry.scenario_id}: sha256 drift")
        try:
            parsed = parse_pcm16_wav(data)
        except WavFormatError as exc:
            errors.append(f"{entry.scenario_id}: {exc}")
            continue
        if parsed.sample_rate != entry.sample_rate:
            errors.append(f"{entry.scenario_id}: sample rate drift")
        if parsed.channels != 1:
            errors.append(f"{entry.scenario_id}: fixture is not mono")
        if parsed.duration_ms != entry.duration_ms:
            errors.append(f"{entry.scenario_id}: duration drift")
        if turns_hash(scripts[entry.scenario_id]) != entry.turns_sha256:
            errors.append(f"{entry.scenario_id}: caller script drift")
    missing = set(expected) - seen
    if missing:
        errors.append(f"hashes.json is missing scenario(s): {sorted(missing)}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed fixtures and hashes without calling LFM3",
    )
    parser.add_argument("--root", default=None, help="repository root")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[3]
    if args.check:
        errors = verify_fixtures(root)
        if errors:
            print("\n".join(errors))
            return 1
        print("audio fixtures and hashes are stable")
        return 0
    from forge_voice.audio.lfm3 import Lfm3TtsClient, Lfm3TtsError

    client = Lfm3TtsClient.from_env()
    try:
        manifest = generate_fixtures(root, client)
    except (FixtureError, Lfm3TtsError) as exc:
        print(f"audio fixture generation failed: {exc}", file=sys.stderr)
        return 1
    print(f"generated {len(manifest.fixtures)} audio fixtures under scenarios/fixtures/audio")
    for entry in manifest.fixtures:
        print(f"  {entry.scenario_id}: {entry.duration_ms} ms  sha256 {entry.sha256[:12]}…")
    return 0


__all__ = [
    "AudioScript",
    "AudioScriptSet",
    "AudioTurn",
    "FixtureEntry",
    "FixtureError",
    "FixtureManifest",
    "FixtureTts",
    "TtsClient",
    "fixture_hash",
    "generate_fixtures",
    "load_audio_scripts",
    "load_audio_scripts_data",
    "load_fixture_manifest",
    "main",
    "synthesize_fixture",
    "turns_hash",
    "verify_fixtures",
]
