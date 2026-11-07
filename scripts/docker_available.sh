#!/usr/bin/env bash
# Exit 0 only when Docker, Compose v2 and a reachable local daemon are available.
set -euo pipefail
command -v docker >/dev/null 2>&1 || exit 1
docker compose version >/dev/null 2>&1 || exit 1
docker info >/dev/null 2>&1 || exit 1
