#!/usr/bin/env bash
# Developer-only end-to-end checks. Leave the local cluster available for debugging.
set -euo pipefail
[ -z "${CI:-}" ] || { echo 'local-tests must not run in CI.' >&2; exit 1; }
[ "${PLATFORM_ENVIRONMENT:-local}" = local ] || { echo 'local-tests requires the local environment.' >&2; exit 1; }
cd "${PROJECT_ROOT:?}"
make doctor
npm ci
npx cypress install
make test
make chart-test
make up
make helm-test
make resilience
TERM="${TERM:-xterm}" make browser-ci
echo 'Local tests passed. The local cluster remains running; use make down to remove it.'
