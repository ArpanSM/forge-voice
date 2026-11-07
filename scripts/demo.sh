#!/usr/bin/env bash
# Start the fully local voice demo: livekit-server, FastAPI page/token server and the agent.
# `make demo` sets FORGE_VOICE_PROFILE=local; `make demo-hybrid` sets hybrid (Groq LLM only).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${FORGE_VOICE_PROFILE:-local}"
SMOKE=0
for arg in "$@"; do
  case "$arg" in
    --smoke) SMOKE=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$PROFILE" != "local" && "$PROFILE" != "hybrid" ]]; then
  echo "FORGE_VOICE_PROFILE must be local or hybrid, not $PROFILE" >&2
  exit 2
fi

"$ROOT/scripts/prepare_local_env.sh" "$ROOT"

set -a
# shellcheck disable=SC1091
source "$ROOT/.env.local"
set +a
export FORGE_VOICE_PROFILE="$PROFILE"
export LIVEKIT_URL="${LIVEKIT_URL:-ws://localhost:7880}"
export LIVEKIT_API_KEY="${LIVEKIT_API_KEY:-devkey}"
# Pass local dev credentials through the server environment, never argv/ps.

if [[ "$PROFILE" == "hybrid" && -z "${GROQ_API_KEY:-}" ]]; then
  echo "make demo-hybrid needs GROQ_API_KEY (environment or .env.local)." >&2
  echo "Use make demo for the fully local profile; no external call is allowed there." >&2
  exit 2
fi

if ! curl -fsS --max-time 3 "http://127.0.0.1:8082/health" >/dev/null 2>&1; then
  echo "LFM3-Audio-2B is not healthy on 127.0.0.1:8082." >&2
  echo "Start it on the host GPU with: lfm3 audio" >&2
  exit 1
fi

SERVER="$ROOT/.tools/livekit-server"
if [[ ! -x "$SERVER" ]]; then
  echo "livekit-server is missing; run make bootstrap first." >&2
  exit 1
fi

LIVEKIT_HTTP="${LIVEKIT_URL/ws:/http:}"
LIVEKIT_HTTP="${LIVEKIT_HTTP/wss:/https:}"
if curl -fsS --max-time 1 "$LIVEKIT_HTTP" >/dev/null 2>&1; then
  echo "Something is already serving $LIVEKIT_URL; stop it before make demo." >&2
  exit 1
fi

LOG_DIR="$ROOT/data/demo"
mkdir -p "$LOG_DIR"
PIDS=()
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  exit "$status"
}
trap cleanup EXIT INT TERM

echo "Starting livekit-server on ws://localhost:7880 …"
LIVEKIT_KEYS="${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}" "$SERVER" \
  --dev \
  --bind 127.0.0.1 \
  --node-ip 127.0.0.1 \
  >"$LOG_DIR/livekit.log" 2>&1 &
PIDS+=("$!")
for _ in $(seq 1 40); do
  if curl -fsS --max-time 1 "http://127.0.0.1:7880/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
if ! curl -fsS --max-time 1 "http://127.0.0.1:7880/" >/dev/null 2>&1; then
  echo "livekit-server did not start; see $LOG_DIR/livekit.log" >&2
  exit 1
fi

echo "Starting the local browser/token page on http://localhost:8000 …"
(
  cd "$ROOT"
  PYTHONPATH=src exec python3.12 -m forge_voice.web.app
) >"$LOG_DIR/web.log" 2>&1 &
PIDS+=("$!")
for _ in $(seq 1 40); do
  if curl -fsS --max-time 1 "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
if ! curl -fsS --max-time 1 "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
  echo "web/token server did not start; see $LOG_DIR/web.log" >&2
  exit 1
fi

echo "Starting the LiveKit agent worker (profile: $PROFILE) …"
(
  cd "$ROOT"
  PYTHONPATH=src exec python3.12 -m forge_voice.runtime.livekit_agent dev
) >"$LOG_DIR/agent.log" 2>&1 &
PIDS+=("$!")
echo "Waiting for the agent worker to register …"
for _ in $(seq 1 240); do
  if grep -q "registered worker" "$LOG_DIR/agent.log" 2>/dev/null; then
    break
  fi
  if ! kill -0 "${PIDS[2]}" 2>/dev/null; then
    echo "agent worker exited during startup; see $LOG_DIR/agent.log" >&2
    tail -40 "$LOG_DIR/agent.log" >&2 || true
    exit 1
  fi
  sleep 0.25
done
if ! grep -q "registered worker" "$LOG_DIR/agent.log" 2>/dev/null; then
  echo "agent worker did not register within 60s; see $LOG_DIR/agent.log" >&2
  tail -40 "$LOG_DIR/agent.log" >&2 || true
  exit 1
fi

echo
echo "Open http://localhost:8000 and press Start call."
echo "The AI/recording disclosure is on the page; the tenant comes from the signed token claim."
echo "Logs: $LOG_DIR/{livekit,web,agent}.log"
echo "Press Ctrl-C to stop all three processes."
echo

if [[ "$SMOKE" == "1" ]]; then
  PYTHONPATH=src python3.12 "$ROOT/scripts/livekit_smoke.py" \
    --web-url http://127.0.0.1:8000 \
    --tenant "${SMOKE_TENANT:-harborlight}" \
    --mode "${SMOKE_MODE:-booking}" \
    --timeout 240
  status=$?
  echo "Smoke result: $status"
  exit "$status"
fi

wait
