#!/bin/bash --norc
# Publish a toolshed release from an explicit version string.
#
# Usage: bash scripts/release.sh <version>
#
# Updates the version in pyproject.toml to <version>, commits it on the
# current branch, tags the commit <version>, and pushes both. The push of
# the tag triggers .github/workflows/release.yml, which builds and publishes
# the GitHub release. The tag name and the wheel filename therefore always
# agree, because both come from the same version string.
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

# Plain text rewrite, matching toolshed/upstream.py's version handling: a
# TOML round-trip would discard the file's taplo formatting.
sed -i.bak "s/^version = \"$current\"/version = \"$version\"/" "$manifest"
rm -f "$manifest.bak"

git add "$manifest"
git commit -m "release: bump version to $version"
git tag -a "$tag" -m "$tag"

branch="$(git symbolic-ref --quiet --short HEAD)"
git push origin "$branch" "$tag"
echo "Tagged and pushed $tag; watch the release workflow with: gh run watch --workflow release.yml --exit-status"
