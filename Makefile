PYTHON ?= python3.12
export PYTHONPATH := src

.PHONY: help install bootstrap corpus corpus-check test lint format text-demo audio-fixtures \
	audio-check demo demo-local demo-compose demo-hybrid demo-hybrid-local demo-hybrid-compose \
	demo-smoke demo-hybrid-smoke down reset logs rollback health release retention \
	eval eval-local eval-audio eval-audio-local eval-heldout eval-smoke eval-baseline \
	dashboard dashboard-seed dashboard-export review-smoke

DOCKER_AVAILABLE := $(shell ./scripts/docker_available.sh >/dev/null 2>&1 && echo 1 || echo 0)

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
	  'make demo          Local stack: Docker Compose when available, host binaries otherwise' \
	  'make demo-local    Force the host-binary LiveKit demo (no Docker needed)' \
	  'make demo-compose  Force the local Docker Compose stack; fails clearly without Docker' \
	  'make demo-hybrid   Same stack with Groq qwen/qwen3.8-27b as the only external LLM' \
	  'make demo-hybrid-local / demo-hybrid-compose  Force one deployment path' \
	  'make down          Stop the Compose stack; ./data and ./recordings stay' \
	  'make reset         Delete synthetic call/booking state and reseed it' \
	  'make logs          Follow LiveKit, web and agent logs' \
	  'make rollback      Start the previous image tags; restore ./data/backup on schema change' \
	  'make health        Probe LFM3, LiveKit, web and agent readiness' \
	  'make release       Tag local images and snapshot ./data for rollback (TAG=v1)' \
	  'make retention     Prune raw call traces and recordings older than 30 days' \
	  'make demo-smoke    Start the local stack and run a scripted WebRTC booking call' \
	  'make demo-hybrid-smoke  Hybrid stack + scripted booking (needs GROQ_API_KEY)' \
	  'make eval          Full 40 text hybrid release gate + 10 critical repeats' \
	  'make eval-local    Full 40 text local safety-fallback report' \
	  'make eval-audio    10 audio hybrid on the self-hosted LiveKit server' \
	  'make eval-audio-local  6 audio local on the self-hosted LiveKit server' \
	  'make eval-heldout  Sealed 8 text + 2 audio held-out release check' \
	  'make eval-smoke    8 text dev subset, hard gates, under two minutes' \
	  'make eval-baseline 40 text baseline vs fixed on both profiles; never gates' \
	  'make dashboard     Start the local FastAPI + HTMX dashboard on 127.0.0.1:8000' \
	  'make dashboard-seed  Seed the synthetic 30-day dashboard call set' \
	  'make dashboard-export  Write the handover static HTML sample' \
	  'make review-smoke  Weekly review helper; runs make eval-smoke after marking a call' \
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

demo:
ifeq ($(DOCKER_AVAILABLE),1)
	@echo "Docker Compose detected. Starting the Compose stack."
	@echo "Explicit paths: make demo-compose (Docker) or make demo-local (host binaries)."
	@$(MAKE) --no-print-directory demo-compose
else
	@echo "Docker Compose is unavailable; using the host-binary demo."
	@echo "For the explicit Docker path use make demo-compose after installing Docker."
	@$(MAKE) --no-print-directory demo-local
endif

demo-local: bootstrap
	FORGE_VOICE_PROFILE=local ./scripts/demo.sh

demo-compose:
	FORGE_VOICE_PROFILE=local ./scripts/compose_demo.sh local

demo-hybrid:
ifeq ($(DOCKER_AVAILABLE),1)
	@echo "Docker Compose detected. Starting the hybrid Compose stack (Groq LLM only)."
	@$(MAKE) --no-print-directory demo-hybrid-compose
else
	@echo "Docker Compose is unavailable; using the host-binary hybrid demo."
	@$(MAKE) --no-print-directory demo-hybrid-local
endif

demo-hybrid-local: bootstrap
	FORGE_VOICE_PROFILE=hybrid ./scripts/demo.sh

demo-hybrid-compose:
	FORGE_VOICE_PROFILE=hybrid ./scripts/compose_demo.sh hybrid

demo-hybrid-smoke: bootstrap
	FORGE_VOICE_PROFILE=hybrid ./scripts/demo.sh --smoke

demo-smoke: bootstrap
	FORGE_VOICE_PROFILE=local ./scripts/demo.sh --smoke

down:
	./scripts/compose_ops.sh down

reset:
	./scripts/compose_ops.sh reset

logs:
	./scripts/compose_ops.sh logs

rollback:
	./scripts/compose_ops.sh rollback

health:
	@if docker compose ps -q agent 2>/dev/null | grep -q .; then \
	  echo "MODE: Docker Compose stack (agent readiness URL)"; \
	  ./scripts/healthcheck.sh --agent-url http://127.0.0.1:8081/; \
	else \
	  echo "MODE: host-binary demo (fresh agent log)"; \
	  ./scripts/healthcheck.sh --agent-log data/demo/agent.log; \
	fi

release:
	@test -n "$(TAG)" || { echo "usage: make release TAG=v1" >&2; exit 2; }
	./scripts/release.sh "$(TAG)"

retention:
	$(PYTHON) -m forge_voice.monitoring.retention --data-dir data --recordings-dir recordings

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

dashboard:
	$(PYTHON) -m forge_voice.monitoring

dashboard-seed:
	$(PYTHON) -m forge_voice.monitoring.seed

dashboard-export:
	$(PYTHON) -m forge_voice.monitoring.export --data-dir data/dashboard-sample --output docs/samples/dashboard-sample.html --now 2026-11-07T12:00:00-08:00

review-smoke:
	$(PYTHON) -m forge_voice.monitoring.review $(if $(CALL_ID),--call-id "$(CALL_ID)",) --run-smoke
