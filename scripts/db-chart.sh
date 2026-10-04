#!/usr/bin/env bash
# Version and checksum pin the independent upstream database package.
set -euo pipefail
cd "${PROJECT_ROOT:?}"
export PATH="$PWD/.platform/bin:$PATH"
version=1.6.8
archive="$PWD/.platform/postgres-$version.tgz"
checksum=d986d971aa0ab9dea23d0a497581dbb71d45841b7b82d6b718fffce52fdf0e67
mkdir -p .platform
if [ ! -f "$archive" ]; then
  helm pull postgres --repo https://groundhog2k.github.io/helm-charts/ --version "$version" --destination .platform >&2
fi
printf '%s  %s\n' "$checksum" "$archive" | shasum -a 256 --check >&2
printf '%s\n' "$archive"
