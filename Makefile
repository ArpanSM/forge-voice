PYTHON ?= python3.12
export PYTHONPATH := src

.PHONY: help install bootstrap corpus corpus-check test lint format text-demo audio-fixtures \
	audio-check demo demo-hybrid demo-smoke demo-hybrid-smoke \
	eval eval-local eval-audio eval-audio-local eval-heldout eval-smoke eval-baseline

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
	  'make eval          Full 40 text hybrid release gate + 10 critical repeats' \
	  'make eval-local    Full 40 text local safety-fallback report' \
	  'make eval-audio    10 audio hybrid on the self-hosted LiveKit server' \
	  'make eval-audio-local  6 audio local on the self-hosted LiveKit server' \
	  'make eval-heldout  Sealed 8 text + 2 audio held-out release check' \
	  'make eval-smoke    8 text dev subset, hard gates, under two minutes' \
	  'make eval-baseline 40 text baseline vs fixed on both profiles; never gates' \
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

EVAL_PYTHON ?= $(PYTHON) -m forge_voice.eval
EVAL_AUDIO_TRANSPORT ?= livekit
EVAL_RUN_ID ?=
EVAL_RUN_ID_ARG = $(if $(EVAL_RUN_ID),--run-id $(EVAL_RUN_ID),)

eval:
	$(EVAL_PYTHON) --profile hybrid --mode text --split release --pipeline fixed --repeat-critical $(EVAL_RUN_ID_ARG)

eval-local:
	$(EVAL_PYTHON) --profile local --mode text --split release --pipeline fixed $(EVAL_RUN_ID_ARG)

eval-audio: bootstrap
	$(EVAL_PYTHON) --profile hybrid --mode audio --split audio --pipeline fixed --transport $(EVAL_AUDIO_TRANSPORT) $(EVAL_RUN_ID_ARG)

eval-audio-local: bootstrap
	$(EVAL_PYTHON) --profile local --mode audio --split audio-local --pipeline fixed --transport $(EVAL_AUDIO_TRANSPORT) $(EVAL_RUN_ID_ARG)

eval-heldout: bootstrap
	$(EVAL_PYTHON) --profile hybrid --mode all --split heldout --pipeline fixed --transport livekit $(EVAL_RUN_ID_ARG)

eval-smoke:
	$(EVAL_PYTHON) --profile hybrid --mode text --split smoke --pipeline fixed --provider-check off --max-seconds 120 $(EVAL_RUN_ID_ARG)

eval-baseline:
	$(EVAL_PYTHON) --profile local --mode text --split release --pipeline baseline --provider-check auto --compare-fixed --run-id release-baseline-local
	-$(EVAL_PYTHON) --profile hybrid --mode text --split release --pipeline baseline --provider-check auto --compare-fixed --run-id release-baseline-hybrid
