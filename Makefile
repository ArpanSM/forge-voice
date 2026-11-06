PYTHON ?= python3.12
export PYTHONPATH := src

.PHONY: help install corpus corpus-check test lint format text-demo

help:
	@printf '%s\n' \
	  'make install       Install the package and dev dependencies' \
	  'make corpus        Regenerate tenants, seed data, scenarios and hashes' \
	  'make corpus-check  Regenerate and fail if committed fixtures drift' \
	  'make test          Run the offline unit test suite' \
	  'make lint          Run ruff check and format check' \
	  'make text-demo     Run representative text-mode book/reschedule/emergency/handoff calls' \
	  'make format        Apply ruff formatting'

install:
	$(PYTHON) -m pip install -e ".[dev]"

corpus:
	$(PYTHON) -m forge_voice.corpus

corpus-check: corpus
	@test -z "$$(git status --porcelain -- fixtures/corpus)" || \
	  { git status --short -- fixtures/corpus; echo "corpus drift detected"; exit 1; }

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests

format:
	$(PYTHON) -m ruff check --fix src tests
	$(PYTHON) -m ruff format src tests

text-demo:
	$(PYTHON) -m forge_voice.runtime.demo
