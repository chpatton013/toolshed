#!/bin/bash --norc
# Publish a toolshed release from an explicit version string.
#
# Usage: bash scripts/release.sh <version>
#
# Updates the version in pyproject.toml and the toolshed self-pin to
# <version>, commits them on the current branch, tags the commit v<version>,
# and pushes both. The push of the tag triggers .github/workflows/release.yml,
# which builds and publishes the GitHub release. The tag, wheel filename, and
# self-pin therefore always agree, because all come from the same version.
#
# Prerequisites: a clean working tree (changes here are hard to untangle),
# git and gh available, and push access to the remote.
set -euo pipefail

usage() {
  echo "Usage: bash scripts/release.sh <version>" >&2
}

if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi

version="$1"

if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Version must be X.Y.Z (got: $version)" >&2
  usage
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
manifest="$repo_root/pyproject.toml"
tag="v$version"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Working tree is dirty; commit or stash first." >&2
  exit 1
fi

if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
  echo "Tag $tag already exists locally; tags are immutable here." >&2
  exit 1
fi

if gh release view "$tag" --repo chpatton013/toolshed --json tagName >/dev/null 2>&1; then
  echo "A GitHub release named $tag already exists; publish the next version instead." >&2
  exit 1
fi

current="$(grep -m1 '^version = ' "$manifest" | sed -E 's/^version = "([^"]+)".*$/\1/')"
if [ "$current" = "$version" ]; then
  echo "pyproject.toml is already at $version; pick a new version." >&2
  exit 1
fi

# Plain text rewrites preserve taplo formatting rather than round-tripping TOML.
sed -i.bak "s/^version = \"$current\"/version = \"$version\"/" "$manifest"
rm -f "$manifest.bak"

manifest_toml="$repo_root/toolshed.toml"
sed -i.bak -E "s#(toolshed @ git\\+https://github.com/chpatton013/toolshed@).*#\\1$tag\",#" "$manifest_toml"
rm -f "$manifest_toml.bak"

if ! grep -q "toolshed @ git+https://github.com/chpatton013/toolshed@$tag\"" "$manifest_toml"; then
  echo "Could not update the toolshed self-pin to $tag" >&2
  exit 1
fi

git add "$manifest" "$manifest_toml"
git commit -m "release: bump version to $version"
git tag -a "$tag" -m "$tag"

branch="$(git symbolic-ref --quiet --short HEAD)"
git push origin "$branch" "$tag"
echo "Tagged and pushed $tag; watch the release workflow with: gh run watch --workflow release.yml --exit-status"
