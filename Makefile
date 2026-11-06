PYTHON ?= python3

.PHONY: spike-test spike-check spike-bench spike-console

spike-test:
	$(PYTHON) -m pytest spike -q

spike-check:
	$(PYTHON) scripts/check_env.py

spike-bench:
	PYTHONPATH=. $(PYTHON) scripts/turn_bench.py

spike-console:
	$(PYTHON) -m spike.agent console
