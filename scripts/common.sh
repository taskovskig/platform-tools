#!/usr/bin/env bash
set -euo pipefail
TOOLS_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PROJECT_ROOT="${PROJECT_ROOT:?Run through the application platform bootstrap}"
cd "$PROJECT_ROOT"
STATE="$PROJECT_ROOT/.platform"
mkdir -p "$STATE"
# config.py emits only validated variables/functions with shlex-quoted values.
settings=$(python3 "$TOOLS_ROOT/scripts/config.py" "$PROJECT_ROOT")
eval "$settings"
export PATH="$STATE/bin:$PATH"
export KIND_EXPERIMENTAL_PROVIDER=docker
export HELM_CACHE_HOME="$STATE/helm/cache"
export HELM_CONFIG_HOME="$STATE/helm/config"
export HELM_DATA_HOME="$STATE/helm/data"
if [ "$PLATFORM_ENVIRONMENT" = development ]; then
  KUBECONFIG_FILE="${KUBECONFIG:?Set KUBECONFIG to a deployment credential file}"
  [ -f "$KUBECONFIG_FILE" ] || { echo 'KUBECONFIG must name an existing file.' >&2; exit 1; }
else
  KUBECONFIG_FILE="$STATE/kubeconfig"
fi
export CLUSTER NAMESPACE KUBECONFIG_FILE KUBE_CONTEXT PLATFORM_ENVIRONMENT
CHART="$TOOLS_ROOT/helm"
SERVICE="${SERVICE:-all}"
k() { kubectl --kubeconfig "$KUBECONFIG_FILE" --context "$KUBE_CONTEXT" -n "$NAMESPACE" "$@"; }
h() { helm --kubeconfig "$KUBECONFIG_FILE" --kube-context "$KUBE_CONTEXT" -n "$NAMESPACE" "$@"; }
applications() {
  if [ "$SERVICE" = all ]; then echo "$APPS"; return; fi
  for app in $APPS; do if [ "$SERVICE" = "$app" ]; then echo "$app"; return; fi; done
  echo "Unknown SERVICE=$SERVICE. Choose: $APPS" >&2; return 1
}
