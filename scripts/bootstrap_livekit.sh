#!/usr/bin/env bash
# Download and verify the pinned open-source livekit-server into .tools/.
# Docker is not required. The binary is gitignored and only the local demo uses it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="1.13.11"
PINNED_AMD64="1e9ee90ca301e1842b2887fc77cb122759756a9c8aeb4334ee91de3325ec43fb"
PINNED_ARM64="2af6ce091d6b3c79d1677f8ff1bbb91a8007f40b2325c059b52d38383c0830b6"
PINNED_BINARY_AMD64="85a58024d9b36542712514e0e926c0adb74f6182bcb19a664b9d9eb98ad01b52"
PINNED_BINARY_ARM64="ddaf42cc5aafb91e78b94427e52808f6f90840a15c02523333999abb02dd8682"

pick_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo amd64 ;;
    aarch64|arm64) echo arm64 ;;
    *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
  esac
}

expected_archive_for() {
  case "$1" in
    amd64) echo "$PINNED_AMD64" ;;
    arm64) echo "$PINNED_ARM64" ;;
    *) echo "Unsupported asset architecture: $1" >&2; exit 1 ;;
  esac
}

expected_binary_for() {
  case "$1" in
    amd64) echo "$PINNED_BINARY_AMD64" ;;
    arm64) echo "$PINNED_BINARY_ARM64" ;;
    *) echo "Unsupported binary architecture: $1" >&2; exit 1 ;;
  esac
}

verify_hash() {
  local label="$1" path="$2" expected="$3" actual
  if [[ ! -f "$path" ]]; then
    echo "$label not found: $path" >&2
    exit 1
  fi
  actual="$(sha256sum "$path" | awk '{ print $1 }')"
  if [[ "$actual" != "$expected" ]]; then
    echo "checksum mismatch for $label: $path" >&2
    echo "expected $expected" >&2
    echo "actual   $actual" >&2
    exit 1
  fi
  echo "checksum ok: $path"
}

verify_archive() {
  verify_hash "archive" "$2" "$(expected_archive_for "$1")"
}

verify_binary() {
  verify_hash "binary" "$2" "$(expected_binary_for "$1")"
}

if [[ "${1:-}" == "--verify" ]]; then
  [[ $# -eq 3 ]] || { echo "usage: $0 --verify <amd64|arm64> <archive>" >&2; exit 2; }
  verify_archive "$2" "$3"
  exit 0
fi
if [[ "${1:-}" == "--verify-binary" ]]; then
  [[ $# -eq 3 ]] || { echo "usage: $0 --verify-binary <amd64|arm64> <binary>" >&2; exit 2; }
  verify_binary "$2" "$3"
  exit 0
fi

asset_arch="$(pick_arch)"
TOOLS="$ROOT/.tools"
BIN="$TOOLS/livekit-server"

if [[ -e "$BIN" ]]; then
  if [[ ! -x "$BIN" ]]; then
    echo "existing $BIN is not executable" >&2
    exit 1
  fi
  verify_binary "$asset_arch" "$BIN"
  if ! "$BIN" --version >/dev/null 2>&1; then
    echo "existing $BIN failed its --version check" >&2
    exit 1
  fi
  echo "livekit-server already installed and checksum-verified: $("$BIN" --version)"
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
asset="livekit_${VERSION}_${platform}_${asset_arch}.tar.gz"
base="https://github.com/livekit/livekit/releases/download/v${VERSION}"
mkdir -p "$TOOLS"
tmp="$(mktemp -d "$TOOLS/.livekit.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

echo "Downloading $asset …"
curl -fsSL --retry 3 -o "$tmp/$asset" "$base/$asset"
verify_archive "$asset_arch" "$tmp/$asset"
tar -xzf "$tmp/$asset" -C "$tmp" livekit-server
verify_binary "$asset_arch" "$tmp/livekit-server"
install -m 0755 "$tmp/livekit-server" "$BIN"
echo "Installed $("$BIN" --version) at $BIN"
