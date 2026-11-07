#!/usr/bin/env bash
# Tag a local release, keep the previous tags and snapshot ./data for rollback.
# Usage: scripts/release.sh [--root DIR] <version>
# A schema-changing release must set FORGE_VOICE_SCHEMA_VERSION to a new value; the
# services are stopped first so SQLite/WAL files are copied consistently.
set -euo pipefail

ROOT="${FORGE_VOICE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
if [[ "${1:-}" == "--root" ]]; then
  [[ $# -ge 2 ]] || { echo "usage: $0 [--root DIR] <version>" >&2; exit 2; }
  ROOT="$2"
  shift 2
fi
VERSION="${1:-}"
[[ -n "$VERSION" ]] || { echo "usage: $0 [--root DIR] <version>" >&2; exit 2; }
cd "$ROOT"

die() {
  echo "$*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || die "Docker is not installed; the host-binary demo has no image rollback."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required."
docker info >/dev/null 2>&1 || die "The Docker daemon is not reachable."

PRESERVED_SCHEMA_VERSION="${FORGE_VOICE_SCHEMA_VERSION:-}"
if [[ -f .env.local ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
fi
if [[ -n "$PRESERVED_SCHEMA_VERSION" ]]; then
  export FORGE_VOICE_SCHEMA_VERSION="$PRESERVED_SCHEMA_VERSION"
fi

CURRENT_TAG=""
[[ -f .release/current ]] && CURRENT_TAG="$(tr -d '[:space:]' < .release/current)"
PREVIOUS_SCHEMA="1"
if [[ -f .release/current-schema ]]; then
  PREVIOUS_SCHEMA="$(tr -d '[:space:]' < .release/current-schema)"
fi
NEW_SCHEMA="${FORGE_VOICE_SCHEMA_VERSION:-$PREVIOUS_SCHEMA}"

mkdir -p .release data recordings
echo "Stopping the stack so SQLite/WAL files are quiescent before the snapshot …"
docker compose down --remove-orphans || true

echo "Building local release images …"
FORGE_VOICE_IMAGE_TAG=local docker compose build

docker tag forge-voice-web:local "forge-voice-web:$VERSION"
docker tag forge-voice-agent:local "forge-voice-agent:$VERSION"

# Keep exactly one previous data snapshot for a schema-changing rollback.
rm -rf data/.backup.new
mkdir -p data/.backup.new
find data -mindepth 1 -maxdepth 1 \
  ! -name backup ! -name '.backup.new' -exec cp -a {} data/.backup.new/ \;
rm -rf data/backup
mv data/.backup.new data/backup

if [[ -n "$CURRENT_TAG" ]]; then
  printf '%s\n' "$CURRENT_TAG" > .release/previous
fi
printf '%s\n' "$PREVIOUS_SCHEMA" > .release/previous-schema
printf '%s\n' "$VERSION" > .release/current
printf '%s\n' "$NEW_SCHEMA" > .release/current-schema

echo "Release $VERSION tagged (web/agent) and ./data/backup refreshed."
if [[ "$NEW_SCHEMA" != "$PREVIOUS_SCHEMA" ]]; then
  echo "Schema changed from $PREVIOUS_SCHEMA to $NEW_SCHEMA; make rollback will restore ./data/backup."
fi
if [[ -n "$CURRENT_TAG" ]]; then
  echo "Previous release: $CURRENT_TAG (make rollback)"
fi
