#!/usr/bin/env bash
# Resolve Python 3.12+ and run the local health probes.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/python_bin.sh
source "$SCRIPT_DIR/python_bin.sh"
PYTHON_BIN="$(find_python_bin)" || exit 1
exec env PYTHONPATH="$SCRIPT_DIR/../src" "$PYTHON_BIN" "$SCRIPT_DIR/healthcheck.py" "$@"
