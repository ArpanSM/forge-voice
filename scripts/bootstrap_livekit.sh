#!/usr/bin/env bash
# Download a pinned, checksum-verified open-source livekit-server into .tools/.
# Docker is not required. The binary is gitignored and only the local demo uses it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${LIVEKIT_SERVER_VERSION:-1.13.11}"
TOOLS="$ROOT/.tools"
BIN="$TOOLS/livekit-server"

if [[ -x "$BIN" ]] && "$BIN" --version >/dev/null 2>&1; then
  echo "livekit-server already installed: $("$BIN" --version)"
  exit 0
fi

os="$(uname -s)"
arch="$(uname -m)"
case "$os" in
  Linux) platform="linux" ;;
  *)
    echo "This local demo bootstraps the Linux livekit-server binary." >&2
    echo "On $os, install livekit-server from https://github.com/livekit/livekit/releases" >&2
    echo "and place it at $BIN (or use Docker Compose for ticket #8)." >&2
    exit 1
    ;;
esac
case "$arch" in
  x86_64|amd64) asset_arch="amd64" ;;
  aarch64|arm64) asset_arch="arm64" ;;
  *)
    echo "Unsupported architecture: $arch" >&2
    exit 1
    ;;
esac

asset="livekit_${VERSION}_${platform}_${asset_arch}.tar.gz"
base="https://github.com/livekit/livekit/releases/download/v${VERSION}"
mkdir -p "$TOOLS"
tmp="$(mktemp -d "$TOOLS/.livekit.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

echo "Downloading $asset …"
curl -fsSL --retry 3 -o "$tmp/$asset" "$base/$asset"
curl -fsSL --retry 3 -o "$tmp/checksums.txt" "$base/checksums.txt"
expected="$(awk -v name="$asset" '$2 == name { print $1 }' "$tmp/checksums.txt")"
if [[ -z "$expected" ]]; then
  echo "checksum for $asset not found" >&2
  exit 1
fi
actual="$(sha256sum "$tmp/$asset" | awk '{ print $1 }')"
if [[ "$actual" != "$expected" ]]; then
  echo "checksum mismatch for $asset" >&2
  exit 1
fi
tar -xzf "$tmp/$asset" -C "$tmp" livekit-server
install -m 0755 "$tmp/livekit-server" "$BIN"
echo "Installed $("$BIN" --version) at $BIN"
