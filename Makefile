PYTHON ?= python3

.PHONY: spike-test spike-check spike-bench spike-console spike-token spike-webrtc

spike-test:
	$(PYTHON) -m pytest spike -q

spike-check:
	$(PYTHON) scripts/check_env.py

spike-bench:
	PYTHONPATH=. $(PYTHON) scripts/turn_bench.py

spike-console:
	$(PYTHON) -m spike.agent console

spike-token:
	$(PYTHON) -m spike.token_server

spike-webrtc:
	PYTHONPATH=. $(PYTHON) scripts/webrtc_bench.py
