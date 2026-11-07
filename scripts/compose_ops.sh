#!/usr/bin/env bash
# Local Compose operations for ticket #8: down, reset, logs and rollback.
# All paths are local; data stays in ./data and ./recordings unless reset/rollback says so.
set -euo pipefail

ROOT="${FORGE_VOICE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
if [[ "${1:-}" == "--root" ]]; then
  [[ $# -ge 2 ]] || { echo "usage: $0 [--root DIR] <down|reset|logs|rollback>" >&2; exit 2; }
  ROOT="$2"
  shift 2
fi
cd "$ROOT"

COMMAND="${1:-}"
case "$COMMAND" in
  down|reset|logs|rollback) ;;
  *)
    echo "usage: $0 [--root DIR] <down|reset|logs|rollback>" >&2
    exit 2
    ;;
esac

die() {
  echo "$*" >&2
  exit 1
}

if [[ -f .env.local ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
fi

LOCAL_ONLY=0
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  COMPOSE=()
  LOCAL_ONLY=1
fi

compose() {
  "${COMPOSE[@]}" "$@"
}

remove_synthetic_state() {
  rm -rf data/monitoring data/calls
  rm -f data/forge_voice.db data/forge_voice.db-shm data/forge_voice.db-wal
  rm -f data/outbox.jsonl
  mkdir -p data
}

seed_dashboard() {
  if [[ "$LOCAL_ONLY" == "1" ]]; then
    PYTHONPATH=src python3.12 -m forge_voice.monitoring.seed --root "$ROOT" --data-dir data
  elif ! compose run --rm --no-deps --entrypoint python web -m forge_voice.monitoring.seed; then
    echo "Compose image unavailable; reseeding with the host Python instead." >&2
    PYTHONPATH=src python3.12 -m forge_voice.monitoring.seed --root "$ROOT" --data-dir data
  fi
}

schema_value() {
  local file="$1"
  [[ -f "$file" ]] && tr -d '[:space:]' < "$file" || true
}

restore_backup() {
  local backup="data/backup"
  [[ -d "$backup" ]] || die "schema changed but $backup does not exist; restore it manually before rollback."
  local staging="data/.rollback-restore.$$"
  cp -a "$backup" "$staging"
  find data -mindepth 1 -maxdepth 1 \
    ! -name backup ! -name '.rollback-restore.*' -exec rm -rf {} +
  cp -a "$staging/." data/
  rm -rf "$staging"
  echo "Restored $backup into ./data."
}

case "$COMMAND" in
  down)
    [[ "$LOCAL_ONLY" == "0" ]] || die \
      "The host-binary demo runs in the foreground; stop it with Ctrl-C. Docker Compose is not available."
    compose down --remove-orphans
    echo "Stack stopped. ./data and ./recordings are kept."
    ;;
  logs)
    if [[ "$LOCAL_ONLY" == "1" ]]; then
      [[ -f data/demo/agent.log ]] || die \
        "No host demo logs in data/demo. Start the demo with make demo-local first."
      tail -n 200 -F data/demo/livekit.log data/demo/web.log data/demo/agent.log
    elif [[ "${FORGE_VOICE_LOGS_FOLLOW:-1}" == "0" ]]; then
      compose logs --tail=200 livekit web agent
    else
      compose logs --tail=200 --follow livekit web agent
    fi
    ;;
  reset)
    if [[ "$LOCAL_ONLY" == "0" ]]; then
      compose down --remove-orphans || true
    fi
    remove_synthetic_state
    seed_dashboard
    echo "Synthetic call and booking data reset and reseeded. ./data/backup is kept."
    ;;
  rollback)
    [[ "$LOCAL_ONLY" == "0" ]] || die \
      "Rollback needs the Compose images. The host-binary demo has no image tags; see docs/runbook.md."
    PREVIOUS_TAG="${FORGE_VOICE_PREVIOUS_TAG:-}"
    if [[ -z "$PREVIOUS_TAG" && -f .release/previous ]]; then
      PREVIOUS_TAG="$(tr -d '[:space:]' < .release/previous)"
    fi
    [[ -n "$PREVIOUS_TAG" ]] || die \
      "No previous release tag. Keep one in .release/previous or set FORGE_VOICE_PREVIOUS_TAG."

    CURRENT_TAG=""
    [[ -f .release/current ]] && CURRENT_TAG="$(tr -d '[:space:]' < .release/current)"
    CURRENT_SCHEMA="$(schema_value .release/current-schema)"
    PREVIOUS_SCHEMA="$(schema_value .release/previous-schema)"

    compose down --remove-orphans || true

    if [[ "${FORGE_VOICE_RESTORE_BACKUP:-0}" == "1" ]]; then
      restore_backup
    elif [[ -n "$CURRENT_SCHEMA" && -n "$PREVIOUS_SCHEMA" && "$CURRENT_SCHEMA" != "$PREVIOUS_SCHEMA" ]]; then
      echo "Schema changed from $PREVIOUS_SCHEMA to $CURRENT_SCHEMA; restoring ./data/backup first."
      restore_backup
    else
      echo "No schema change detected; keeping ./data (30-day synthetic retention applies)."
    fi

    echo "Starting previous release $PREVIOUS_TAG …"
    FORGE_VOICE_IMAGE_TAG="$PREVIOUS_TAG" \
      compose up -d --no-build --wait --wait-timeout 300

    mkdir -p .release
    printf '%s\n' "$PREVIOUS_TAG" > .release/current
    if [[ -n "$CURRENT_TAG" ]]; then
      printf '%s\n' "$CURRENT_TAG" > .release/previous
    fi
    if [[ -n "$PREVIOUS_SCHEMA" ]]; then
      printf '%s\n' "$PREVIOUS_SCHEMA" > .release/current-schema
      printf '%s\n' "$CURRENT_SCHEMA" > .release/previous-schema
    fi
    echo "Rolled back to $PREVIOUS_TAG. Run make health and one clean booking."
    ;;
esac
