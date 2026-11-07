PYTHON ?= python3.12
export PYTHONPATH := src

.PHONY: help install bootstrap corpus corpus-check test lint format text-demo audio-fixtures \
	audio-check demo demo-hybrid demo-smoke demo-hybrid-smoke

help:
	@printf '%s\n' \
	  'make install       Install the package, dev tools and demo dependencies' \
	  'make bootstrap     Download the pinned open-source livekit-server into .tools/' \
	  'make corpus        Regenerate tenants, seed data, scenarios and hashes' \
	  'make corpus-check  Regenerate and fail if committed fixtures drift' \
	  'make test          Run the offline unit test suite' \
	  'make lint          Run ruff check and format check' \
	  'make text-demo     Run representative text-mode book/reschedule/emergency/handoff calls' \
	  'make audio-fixtures Regenerate the ten WAV fixtures with LFM3 TTS' \
	  'make audio-check   Verify committed WAV fixtures and hashes offline' \
	  'make demo          Fully local stack: LiveKit + browser + LFM3 (no external calls)' \
	  'make demo-hybrid   Same stack with Groq qwen/qwen3.8-27b as the only external LLM' \
	  'make demo-smoke    Start the local stack and run a scripted WebRTC booking call' \
	  'make demo-hybrid-smoke  Hybrid stack + scripted booking (needs GROQ_API_KEY)' \
	  'make format        Apply ruff formatting'

install:
	$(PYTHON) -m pip install -e ".[dev,demo]"

bootstrap:
	./scripts/bootstrap_livekit.sh

corpus:
	$(PYTHON) -m forge_voice.corpus

corpus-check: corpus
	@test -z "$$(git status --porcelain -- fixtures/corpus)" || \
	  { git status --short -- fixtures/corpus; echo "corpus drift detected"; exit 1; }

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check src tests scripts
	$(PYTHON) -m ruff format --check src tests scripts

format:
	$(PYTHON) -m ruff check --fix src tests scripts
	$(PYTHON) -m ruff format src tests scripts

text-demo:
	$(PYTHON) -m forge_voice.runtime.demo

audio-fixtures:
	$(PYTHON) -m forge_voice.audio

audio-check:
	$(PYTHON) -m forge_voice.audio --check

demo: bootstrap
	FORGE_VOICE_PROFILE=local ./scripts/demo.sh

demo-hybrid: bootstrap
	FORGE_VOICE_PROFILE=hybrid ./scripts/demo.sh

demo-hybrid-smoke: bootstrap
	FORGE_VOICE_PROFILE=hybrid ./scripts/demo.sh --smoke

demo-smoke: bootstrap
	FORGE_VOICE_PROFILE=local ./scripts/demo.sh --smoke
