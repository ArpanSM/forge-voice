# Sourced helper: return a Python 3.12+ interpreter or fail with a clear message.
find_python_bin() {
  local candidate
  for candidate in "${FORGE_VOICE_PYTHON:-}" python3 python3.12; do
    [[ -n "$candidate" ]] || continue
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' \
        >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  echo "Python 3.12+ is required for the local preflight and health helpers." >&2
  echo "Install python3.12 (or set FORGE_VOICE_PYTHON=/path/to/python3.12); see docs/runbook.md." >&2
  return 1
}
