#!/bin/bash --norc
# Download a toolshed release, verify it, and extract it.
#
# Nothing here is specific to this repository's releases: --repo and --asset make
# it reusable by anyone publishing their own toolshed-rendered bin/ directory.
set -euo pipefail

repo="chpatton013/toolshed"
version="latest"
asset="toolshed-bin.tar.gz"
dest="${XDG_DATA_HOME:-$HOME/.local/share}/toolshed"
install_dotslash=1

usage() {
  cat <<'USAGE'
Usage: install.sh [options]

Downloads a release asset, verifies it against the release's SHA256SUMS,
extracts it, and prints the resulting bin directory on stdout.

Options:
  --repo OWNER/NAME   GitHub repository to install from
                      (default: chpatton013/toolshed)
  --version TAG       Release tag, or `latest` (default: latest)
  --asset NAME        Release asset to extract (default: toolshed-bin.tar.gz)
  --dest DIR          Parent install directory; the release lands in DIR/TAG
                      (default: $XDG_DATA_HOME/toolshed, else
                      ~/.local/share/toolshed)
  --no-dotslash       Do not install the dotslash runtime
  -h, --help          Show this message

The dotslash runtime is installed first unless --no-dotslash is passed, because
the pinned manifests in bin/ are not executable without it.

Add the printed directory to PATH:

  eval "export PATH=\"$(bash install.sh):\$PATH\""
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
  --repo)
    repo="$2"
    shift 2
    ;;
  --version)
    version="$2"
    shift 2
    ;;
  --asset)
    asset="$2"
    shift 2
    ;;
  --dest)
    dest="$2"
    shift 2
    ;;
  --no-dotslash)
    install_dotslash=0
    shift
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    echo "Unknown option: $1" >&2
    usage >&2
    exit 1
    ;;
  esac
done

# Resolve `latest` to a concrete tag by following GitHub's redirect, so the
# install directory is named after a real version rather than a moving target.
if [ "$version" = "latest" ]; then
  effective="$(
    curl -fsSLI -o /dev/null -w '%{url_effective}' \
      "https://github.com/$repo/releases/latest"
  )"
  version="${effective##*/}"
  if [ -z "$version" ] || [ "$version" = "latest" ]; then
    echo "Could not resolve the latest release of $repo" >&2
    exit 1
  fi
  echo "Resolved latest to $version" >&2
fi

base="https://github.com/$repo/releases/download/$version"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

curl -fsSL "$base/$asset" -o "$tmp/$asset"
curl -fsSL "$base/SHA256SUMS" -o "$tmp/SHA256SUMS"

# Prefer the GNU tool, fall back to the BSD/macOS one.
if command -v sha256sum >/dev/null 2>&1; then
  (cd "$tmp" && sha256sum --check --ignore-missing SHA256SUMS)
elif command -v shasum >/dev/null 2>&1; then
  (cd "$tmp" && shasum -a 256 --check --ignore-missing SHA256SUMS)
else
  echo "Need sha256sum or shasum to verify the download" >&2
  exit 1
fi

target="$dest/$version"
mkdir -p "$target"
tar xzf "$tmp/$asset" -C "$target"

if [ "$install_dotslash" -eq 1 ]; then
  curl -fsSL \
    "https://raw.githubusercontent.com/$repo/$version/scripts/bootstrap/dotslash.sh" \
    -o "$tmp/dotslash.sh"
  bash "$tmp/dotslash.sh"
fi

echo "$target/bin"
