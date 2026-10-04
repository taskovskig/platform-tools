#!/usr/bin/env bash
# Administrative provisioning only; application deployment uses a separate credential.
set -euo pipefail
TOOLS_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
: "${KUBECONFIG:?Set KUBECONFIG to an administrative credential file}"
[ -f "$KUBECONFIG" ] || { echo 'KUBECONFIG must name an existing file.' >&2; exit 1; }
args=(--kubeconfig "$KUBECONFIG" --context kind-testkube-samples)
kubectl "${args[@]}" apply -f "$TOOLS_ROOT/defaults/namespaces.yaml"
kubectl "${args[@]}" -n app-ci apply -f "$TOOLS_ROOT/defaults/ci-access.yaml"
kubectl "${args[@]}" -n app-dev apply -f "$TOOLS_ROOT/defaults/development-access.yaml"
kubectl "${args[@]}" -n app-prod apply -f "$TOOLS_ROOT/defaults/production-access.yaml"
kubectl "${args[@]}" get namespaces app-ci app-dev app-prod
