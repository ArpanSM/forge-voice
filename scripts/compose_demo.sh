#!/usr/bin/env bash
# Start the explicit local Docker Compose stack for ticket #8.
# Usage: compose_demo.sh [local|hybrid]
# LFM3-Audio-2B stays on the host GPU; the agent reaches host.docker.internal:8082.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${1:-local}"
case "$PROFILE" in
  local|hybrid) ;;
  *) echo "usage: $0 [local|hybrid]" >&2; exit 2 ;;
esac

die() {
  echo "$*" >&2
  exit 1
}

"$ROOT/scripts/prepare_local_env.sh" "$ROOT"

PRESERVED_GROQ_KEY="${GROQ_API_KEY:-}"
if [[ -f "$ROOT/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env.local"
  set +a
fi
# A copied .env.example may carry an empty GROQ_API_KEY; keep an explicit shell key.
if [[ -n "$PRESERVED_GROQ_KEY" ]]; then
  export GROQ_API_KEY="$PRESERVED_GROQ_KEY"
fi
export FORGE_VOICE_PROFILE="$PROFILE"

command -v docker >/dev/null 2>&1 || die \
  "Docker is not installed. Use 'make demo-local' for the host-binary demo, or install Docker Compose."
docker compose version >/dev/null 2>&1 || die \
  "Docker Compose v2 is not available. Use 'make demo-local', or install Docker Compose."
docker info >/dev/null 2>&1 || die \
  "The Docker daemon is not reachable. Start Docker, or use 'make demo-local' for the host-binary demo."

[[ -n "${LIVEKIT_API_SECRET:-}" ]] || die \
  "LIVEKIT_API_SECRET is empty. Run scripts/prepare_local_env.sh or set it in .env.local."

case "${LIVEKIT_URL:-ws://localhost:7880}" in
  ws://localhost:7880|ws://127.0.0.1:7880) ;;
  *) die "Local-only stack: LIVEKIT_URL must be ws://localhost:7880, not ${LIVEKIT_URL}." ;;
esac

if [[ "$PROFILE" == "hybrid" && -z "${GROQ_API_KEY:-}" ]]; then
  die "make demo-hybrid needs GROQ_API_KEY in the environment or .env.local. Use make demo for the fully local profile."
fi

# LFM3 is a host service. Map the container name back to loopback for this check.
LFM3_BASE="${LFM3_AUDIO_BASE_URL:-http://127.0.0.1:8082}"
LFM3_HOST_CHECK="${LFM3_BASE/host.docker.internal/127.0.0.1}"
LFM3_HOST_CHECK="${LFM3_HOST_CHECK%/}"
if ! curl -fsS --max-time 3 "$LFM3_HOST_CHECK/health" >/dev/null 2>&1; then
  die "LFM3-Audio-2B is not healthy at $LFM3_HOST_CHECK/health. Start it with 'lfm3 audio' and wait for /health."
fi

# Fail closed before Compose if a local port is already taken (often a stale stack).
python3.12 - <<'PY'
import socket
import sys

for port in (7880, 7881, 8000, 8081):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        print(
            f"Port {port} is already in use. Stop the old stack with 'make down' "
            "or free the port before `make demo`.",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        sock.close()
PY

cd "$ROOT"
mkdir -p data recordings
echo "Starting the local Compose stack (profile: $PROFILE) …"
if ! docker compose up -d --build --wait --wait-timeout 300; then
  echo
  echo "The stack did not become healthy. Diagnostics:" >&2
  docker compose ps >&2 || true
  docker compose logs --tail=80 livekit web agent >&2 || true
  echo "Check LFM3 with 'lfm3 audio' and curl http://127.0.0.1:8082/health; see docs/runbook.md." >&2
  exit 1
fi

cat <<EOF

Forge Voice is running on localhost:
  Browser demo  http://localhost:8000
  Dashboard     http://localhost:8000/dashboard
  Admin         http://localhost:8000/admin
  LiveKit       ws://localhost:7880

Profile: $PROFILE (LFM3 audio always local; LLM is $([[ "$PROFILE" == "hybrid" ]] && echo "Groq only" || echo "local LFM3"))
Logs:    make logs
Stop:    make down
Reset:   make reset   (synthetic data only; reseeds)
Health:  make health
EOF
