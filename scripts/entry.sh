#!/usr/bin/env bash
set -euo pipefail
# Publication has no environment or cluster credentials; do not load common.sh.
case "${1:-}" in
  production-release) exec python3 "$(dirname "$0")/production-release.py" publish ;;
  production-prepare) exec python3 "$(dirname "$0")/production-release.py" prepare ;;
esac
source "$(dirname "$0")/common.sh"
case "${1:-help}" in
  local-tests) bash "$TOOLS_ROOT/scripts/local-tests.sh" ;;
  version) cat "$TOOLS_ROOT/VERSION" ;;
  chart-test)
    deps="$STATE/test-deps/$(shasum -a 256 "$TOOLS_ROOT/tests/package-lock.json" | cut -d ' ' -f 1)"
    if [ ! -f "$deps/node_modules/js-yaml/package.json" ]; then
      mkdir -p "$deps"
      cp "$TOOLS_ROOT/tests/package.json" "$TOOLS_ROOT/tests/package-lock.json" "$deps/"
      npm ci --ignore-scripts --no-fund --prefix "$deps" --cache "$STATE/npm-cache"
    fi
    NODE_PATH="$deps/node_modules" node "$TOOLS_ROOT/tests/chart.cjs" "$CHART" "$PROJECT_ROOT" ;;
  helm-test) bash "$TOOLS_ROOT/scripts/verify-helm.sh" ;;
  resilience) bash "$TOOLS_ROOT/scripts/verify-resilience.sh" ;;
  install-tools) bash "$TOOLS_ROOT/scripts/install-tools.sh" ;;
  browser-ci) bash "$TOOLS_ROOT/scripts/browser-ci.sh" ;;
  *) bash "$TOOLS_ROOT/scripts/platform.sh" "$@" ;;
esac
