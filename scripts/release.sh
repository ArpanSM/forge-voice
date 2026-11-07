#!/usr/bin/env bash
# Tag a local release, keep the previous tags and back up ./data for rollback.
# Usage: scripts/release.sh <version>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-}"
[[ -n "$VERSION" ]] || { echo "usage: $0 <version>" >&2; exit 2; }
cd "$ROOT"

die() {
  echo "$*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || die "Docker is not installed; the host-binary demo has no image rollback."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required."
docker info >/dev/null 2>&1 || die "The Docker daemon is not reachable."

if [[ -f .env.local ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
fi

CURRENT_TAG=""
[[ -f .release/current ]] && CURRENT_TAG="$(tr -d '[:space:]' < .release/current)"
SCHEMA_VERSION="${FORGE_VOICE_SCHEMA_VERSION:-1}"
if [[ -f .release/current-schema ]]; then
  SCHEMA_VERSION="${FORGE_VOICE_SCHEMA_VERSION:-$(tr -d '[:space:]' < .release/current-schema)}"
fi

mkdir -p .release
echo "Building local release images …"
FORGE_VOICE_IMAGE_TAG=local docker compose build

docker tag forge-voice-web:local "forge-voice-web:$VERSION"
docker tag forge-voice-agent:local "forge-voice-agent:$VERSION"

# Keep exactly one previous data snapshot for a schema-changing rollback.
rm -rf data/.backup.new
mkdir -p data/.backup.new
if [[ -d data ]]; then
  find data -mindepth 1 -maxdepth 1 \
    ! -name backup ! -name '.backup.new' -exec cp -a {} data/.backup.new/ \;
fi
rm -rf data/backup
mv data/.backup.new data/backup

if [[ -n "$CURRENT_TAG" ]]; then
  printf '%s\n' "$CURRENT_TAG" > .release/previous
  printf '%s\n' "$SCHEMA_VERSION" > .release/previous-schema
fi
printf '%s\n' "$VERSION" > .release/current
printf '%s\n' "$SCHEMA_VERSION" > .release/current-schema

echo "Release $VERSION tagged (web/agent) and ./data/backup refreshed."
if [[ -n "$CURRENT_TAG" ]]; then
  echo "Previous release: $CURRENT_TAG (make rollback)"
fi
