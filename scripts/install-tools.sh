#!/usr/bin/env bash
# Pinned Linux AMD64 toolchain for GitHub-hosted runners.
[ "$(uname -s)-$(uname -m)" = Linux-x86_64 ] || { echo "install-tools supports Linux AMD64; install local tools using the runbook." >&2; exit 1; }
cd "${PROJECT_ROOT:?}"
set -euo pipefail
mkdir -p .platform/bin
cd .platform/bin
curl -fsSLo kind https://kind.sigs.k8s.io/dl/v0.33.0/kind-linux-amd64
curl -fsSLo kind.sha256sum https://kind.sigs.k8s.io/dl/v0.33.0/kind-linux-amd64.sha256sum
echo "$(cut -d ' ' -f 1 kind.sha256sum)  kind" | sha256sum --check
curl -fsSLo kubectl https://dl.k8s.io/release/v1.37.0/bin/linux/amd64/kubectl
curl -fsSLo kubectl.sha256 https://dl.k8s.io/release/v1.37.0/bin/linux/amd64/kubectl.sha256
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check
curl -fsSLo helm.tar.gz https://get.helm.sh/helm-v4.3.0-linux-amd64.tar.gz
curl -fsSLo helm.sha256 https://get.helm.sh/helm-v4.3.0-linux-amd64.tar.gz.sha256sum
echo "$(cut -d ' ' -f 1 helm.sha256)  helm.tar.gz" | sha256sum --check
tar -xzf helm.tar.gz linux-amd64/helm
mv linux-amd64/helm helm
chmod +x kind kubectl helm
if [ -n "${GITHUB_PATH:-}" ]; then echo "$PWD" >> "$GITHUB_PATH"; fi
