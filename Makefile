PYTHON ?= python3

.PHONY: spike-test spike-check

spike-test:
	$(PYTHON) -m pytest spike -q

spike-check:
	$(PYTHON) scripts/check_env.py
