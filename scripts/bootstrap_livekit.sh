#!/usr/bin/env bash
# Download a pinned, checksum-verified open-source livekit-server into .tools/.
# Docker is not required. The binary is gitignored and only the local demo uses it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="1.13.11"
PINNED_AMD64="1e9ee90ca301e1842b2887fc77cb122759756a9c8aeb4334ee91de3325ec43fb"
PINNED_ARM64="2af6ce091d6b3c79d1677f8ff1bbb91a8007f40b2325c059b52d38383c0830b6"

pick_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo amd64 ;;
    aarch64|arm64) echo arm64 ;;
    *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
  esac
}

expected_for() {
  case "$1" in
    amd64) echo "$PINNED_AMD64" ;;
    arm64) echo "$PINNED_ARM64" ;;
    *) echo "Unsupported asset architecture: $1" >&2; exit 1 ;;
  esac
}

verify_archive() {
  local arch="$1" path="$2" expected actual
  expected="$(expected_for "$arch")"
  if [[ ! -f "$path" ]]; then
    echo "archive not found: $path" >&2
    exit 1
  fi
  actual="$(sha256sum "$path" | awk '{ print $1 }')"
  if [[ "$actual" != "$expected" ]]; then
    echo "checksum mismatch for $path" >&2
    echo "expected $expected" >&2
    echo "actual   $actual" >&2
    exit 1
  fi
  echo "checksum ok: $path"
}

if [[ "${1:-}" == "--verify" ]]; then
  [[ $# -eq 3 ]] || { echo "usage: $0 --verify <amd64|arm64> <archive>" >&2; exit 2; }
  verify_archive "$2" "$3"
  exit 0
fi

TOOLS="$ROOT/.tools"
BIN="$TOOLS/livekit-server"

if [[ -x "$BIN" ]] && "$BIN" --version >/dev/null 2>&1; then
  echo "livekit-server already installed: $("$BIN" --version)"
  exit 0
fi

os="$(uname -s)"
case "$os" in
  Linux) platform="linux" ;;
  *)
    echo "This local demo bootstraps the Linux livekit-server binary." >&2
    echo "On $os, install livekit-server from https://github.com/livekit/livekit/releases" >&2
    echo "and place it at $BIN (or use Docker Compose for ticket #8)." >&2
    exit 1
    ;;
esac
asset_arch="$(pick_arch)"
asset="livekit_${VERSION}_${platform}_${asset_arch}.tar.gz"
base="https://github.com/livekit/livekit/releases/download/v${VERSION}"
mkdir -p "$TOOLS"
tmp="$(mktemp -d "$TOOLS/.livekit.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

echo "Downloading $asset …"
curl -fsSL --retry 3 -o "$tmp/$asset" "$base/$asset"
verify_archive "$asset_arch" "$tmp/$asset"
tar -xzf "$tmp/$asset" -C "$tmp" livekit-server
install -m 0755 "$tmp/livekit-server" "$BIN"
echo "Installed $("$BIN" --version) at $BIN"
