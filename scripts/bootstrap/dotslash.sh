#!/bin/bash --norc
# Install the dotslash runtime, unless it is already resolvable.
#
# dotslash cannot be distributed as a dotslash file, so it is the one tool that
# has to be fetched conventionally before any of the pinned manifests in bin/
# will execute.
set -euo pipefail

if command -v dotslash >/dev/null 2>&1; then
  exit 0
fi

version="${DOTSLASH_VERSION:-latest}"
url="https://github.com/facebook/dotslash/releases/$version/download"

kernel="$(uname -s)"
case "$kernel" in
Linux*)
  arch="$(uname -m)"
  case "$arch" in
  aarch64 | arm64)
    url+="/dotslash-linux-musl.aarch64.tar.gz"
    ;;
  x86_64)
    url+="/dotslash-linux-musl.x86_64.tar.gz"
    ;;
  *)
    echo "Unsupported architecture: $arch" >&2
    exit 1
    ;;
  esac
  ;;
Darwin*)
  # One universal binary covers both macOS architectures.
  url+="/dotslash-macos.tar.gz"
  ;;
*)
  echo "Unsupported kernel: $kernel" >&2
  exit 1
  ;;
esac

user_bin_dir="${XDG_BIN_HOME:-$HOME/.local/bin}"
mkdir -p "$user_bin_dir"
curl -fSL "$url" | tar fzx - -C "$user_bin_dir"

echo "Installed dotslash to $user_bin_dir" >&2
if ! command -v dotslash >/dev/null 2>&1; then
  echo "Add $user_bin_dir to PATH to make dotslash resolvable." >&2
fi
