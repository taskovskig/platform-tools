#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
KIND_IMAGE='kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5'
need() { command -v "$1" >/dev/null || { echo "Missing $1. See DEVELOPER-GUIDE.md." >&2; exit 1; }; }
doctor() {
  for tool in docker kubectl helm curl tar git base64 openssl shasum; do need "$tool"; done
  [ "$PLATFORM_ENVIRONMENT" != local ] || need kind
  docker info >/dev/null || { echo 'Start Docker Desktop and retry.' >&2; exit 1; }
  echo 'Required tools and Docker are available.'
}
cluster() {
  [ "$PLATFORM_ENVIRONMENT" = local ] || { echo 'Cluster lifecycle operations are disabled for shared environments.' >&2; exit 1; }
  doctor
  if ! kind get clusters | grep -qx "$CLUSTER"; then
    kind create cluster --name "$CLUSTER" --image "$KIND_IMAGE" --config "$KIND_CONFIG" --kubeconfig "$KUBECONFIG_FILE" --wait 120s
  else
    kind export kubeconfig --name "$CLUSTER" --kubeconfig "$KUBECONFIG_FILE"
  fi
  chmod 600 "$KUBECONFIG_FILE"
}
build() {
  TAG="${TAG:-$(git rev-parse --short HEAD)-$(date -u +%Y%m%d%H%M%S)-$$}"
  # Use the developer's Dockerfiles verbatim. Only application inputs enter the
  # context: platform credentials, kubeconfig and test tooling cannot be copied.
  tar --exclude=node_modules --exclude=dist --exclude=.git -cf "$STATE/build-context.tar" \
    "${BUILD_CONTEXT[@]}"
  for app in $(applications); do
    local build_args=(-f "$(app_dockerfile "$app")" -t "$(app_image "$app"):$TAG")
    if [ "$PLATFORM_ENVIRONMENT" != local ]; then
      build_args+=(--platform "$IMAGE_PLATFORM"
        --label "org.opencontainers.image.revision=$(git rev-parse HEAD)"
        --label "io.platform.source-tree=$(git rev-parse HEAD^{tree})"
        --label "io.platform.ci-build=$TAG")
      if [ -n "${GITHUB_REPOSITORY:-}" ]; then
        build_args+=(--label "org.opencontainers.image.source=https://github.com/$GITHUB_REPOSITORY")
      fi
    fi
    docker build "${build_args[@]}" - < "$STATE/build-context.tar"
  done
  printf '%s\n' "$TAG" > "$STATE/built-tag"
}
credentials() {
  if [ "$PLATFORM_ENVIRONMENT" = local ]; then
    k apply -f "$NAMESPACE_MANIFEST"
  else
    # Namespace and RBAC are provisioned by an administrator, never by PR code.
    k get serviceaccount default >/dev/null
  fi
  # Reuse the existing Secret: PostgreSQL only uses initialization credentials once.
  if k get secret "$DB_SECRET" >/dev/null 2>&1; then
    local username password database
    username=$(k get secret "$DB_SECRET" -o jsonpath='{.data.POSTGRES_USER}' | base64 --decode)
    password=$(k get secret "$DB_SECRET" -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 --decode)
    database=$(k get secret "$DB_SECRET" -o jsonpath='{.data.POSTGRES_DB}' | base64 --decode)
    if [ "$username" != "$DB_USER" ] || [ "$password" != "$DB_PASSWORD" ] || [ "$database" != "$DB_NAME" ]; then
      echo 'Existing database Secret does not match the requested credentials/database. See the migration runbook; credentials will not be overwritten.' >&2
      exit 1
    fi
    return
  fi
  if k get pvc "$DB_PVC" >/dev/null 2>&1; then
    echo 'Database Secret missing but data exists. Restore its original credentials; see the runbook.' >&2
    exit 1
  fi
  export DB_USER DB_PASSWORD DB_NAME DB_SECRET NAMESPACE
  python3 -c 'import json,os; print(json.dumps({"apiVersion":"v1","kind":"Secret","metadata":{"name":os.environ["DB_SECRET"],"namespace":os.environ["NAMESPACE"]},"type":"Opaque","stringData":{"POSTGRES_USER":os.environ["DB_USER"],"POSTGRES_PASSWORD":os.environ["DB_PASSWORD"],"POSTGRES_DB":os.environ["DB_NAME"]}}))' | k create -f - >/dev/null
}
legacy_guard() {
  if { [ -n "$LEGACY_RELEASE" ] && h status "$LEGACY_RELEASE" >/dev/null 2>&1; } || { [ -n "$LEGACY_STATEFULSET" ] && k get statefulset "$LEGACY_STATEFULSET" >/dev/null 2>&1; } || { [ -n "$LEGACY_PVC" ] && k get pvc "$LEGACY_PVC" >/dev/null 2>&1; }; then
    echo 'Legacy combined deployment detected. Back up data and follow DEVELOPER-GUIDE.md; no resources will be adopted or deleted.' >&2
    exit 1
  fi
}
db_up() {
  legacy_guard
  python3 "$TOOLS_ROOT/scripts/render-infrastructure.py" "$STATE/infrastructure" "$NAMESPACE" "$DB_RELEASE" "$DB_SECRET"
  NAMESPACE_MANIFEST="${NAMESPACE_MANIFEST:-$STATE/infrastructure/namespace.json}"
  DB_ACCOUNT="${DB_ACCOUNT:-$STATE/infrastructure/db-serviceaccount.json}"
  credentials
  k apply -f "$DB_ACCOUNT"
  local chart
  chart=$(bash "$TOOLS_ROOT/scripts/db-chart.sh")
  h upgrade --install "$DB_RELEASE" "$chart" -f "$TOOLS_ROOT/defaults/db.values.yaml" -f "$DB_VALUES" -f "$STATE/infrastructure/db.values.json" --wait --timeout 10m --history-max 10
}
render() {
  : > "$STATE/rendered.yaml"
  for app in $(applications); do
    helm template "$app" "$CHART" --namespace "$NAMESPACE" -f "$(app_values "$app")" >> "$STATE/rendered.yaml"
    printf '\n---\n' >> "$STATE/rendered.yaml"
  done
}
publish_images() {
  mkdir -p "$STATE/images" "$STATE/anonymous-docker"
  for app in $(applications); do
    docker push "$(app_image "$app"):$TAG"
    local reference
    reference=$(docker image inspect "$(app_image "$app"):$TAG" --format '{{index .RepoDigests 0}}')
    [[ "$reference" = "$(app_image "$app")@sha256:"* ]] && [[ "${reference##*@sha256:}" =~ ^[a-f0-9]{64}$ ]] || { echo 'Registry did not return the expected image digest.' >&2; exit 1; }
    printf '%s\n' "$reference" > "$STATE/images/$app"
  done
  # Publish both images before checking visibility so first-time setup can expose both packages.
  for app in $(applications); do
    if ! DOCKER_CONFIG="$STATE/anonymous-docker" docker manifest inspect "$(cat "$STATE/images/$app")" >/dev/null 2>&1; then
      echo "Make the GHCR package $(app_image "$app") public, then rerun this job. No deployment has started." >&2
      exit 1
    fi
  done
}
require_ci() {
  [ "$PLATFORM_ENVIRONMENT" = app-ci ] && [ "$NAMESPACE" = app-ci ] || { echo 'CI reset/build is restricted to app-ci.' >&2; exit 1; }
  [ "$SERVICE" = all ] || { echo 'CI must process every application.' >&2; exit 1; }
}
ci_reset() {
  require_ci
  for app in $APPS; do h uninstall "$app" --ignore-not-found --wait --timeout 5m; done
  h uninstall "$DB_RELEASE" --ignore-not-found --wait --timeout 5m
  k delete pvc "$DB_PVC" --ignore-not-found=true --wait=true --timeout=120s
  k delete secret "$DB_SECRET" --ignore-not-found=true
}
ci_up() {
  require_ci
  [[ "${GH_BUILD_NUMBER:-}" =~ ^[1-9][0-9]*$ ]] || { echo 'Set GH_BUILD_NUMBER to the GitHub run number.' >&2; exit 1; }
  TAG="ci-$GH_BUILD_NUMBER"
  doctor
  build
  publish_images
  for app in $APPS; do
    docker tag "$(app_image "$app"):$TAG" "$(app_image "$app"):ci-latest"
    docker push "$(app_image "$app"):ci-latest"
    printf '%s:%s@%s\n' "$(app_image "$app")" "$TAG" "$(cat "$STATE/images/$app" | cut -d @ -f 2)" > "$STATE/images/$app.tagged"
    mv "$STATE/images/$app.tagged" "$STATE/images/$app"
  done
  db_up
  deploy
  check
}
ci_passed() {
  require_ci
  # Called only after the complete acceptance suite has passed.
  TAG=$(cat "$STATE/built-tag")
  [[ "$TAG" =~ ^ci-[1-9][0-9]*$ ]] || { echo 'Missing CI build tag.' >&2; exit 1; }
  for app in $APPS; do
    docker tag "$(app_image "$app"):$TAG" "$(app_image "$app"):ci-passed"
    docker push "$(app_image "$app"):ci-passed"
  done
}
promote() {
  [ "$PLATFORM_ENVIRONMENT" = app-dev ] && [ "$NAMESPACE" = app-dev ] || { echo 'Promotion is restricted to app-dev.' >&2; exit 1; }
  [ "$SERVICE" = all ] || { echo 'Promotion must process every application.' >&2; exit 1; }
  mkdir -p "$STATE/images"
  local tree revision build candidate passed first_build=''
  tree=$(git rev-parse HEAD^{tree})
  # Validate every image before moving any development tags or Helm releases.
  for app in $APPS; do
    docker pull "$(app_image "$app"):ci-latest"
    docker pull "$(app_image "$app"):ci-passed"
    candidate=$(docker image inspect "$(app_image "$app"):ci-latest" --format '{{.Id}}')
    passed=$(docker image inspect "$(app_image "$app"):ci-passed" --format '{{.Id}}')
    [ "$candidate" = "$passed" ] || { echo "$app: ci-latest has not passed acceptance." >&2; exit 1; }
    revision=$(docker image inspect "$candidate" --format '{{index .Config.Labels "io.platform.source-tree"}}')
    [ "$revision" = "$tree" ] || { echo "$app: ci-latest does not match merged source. Rerun CI for the intended branch before promotion." >&2; exit 1; }
    build=$(docker image inspect "$candidate" --format '{{index .Config.Labels "io.platform.ci-build"}}')
    [[ "$build" =~ ^ci-[1-9][0-9]*$ ]] || { echo 'Missing CI build identity.' >&2; exit 1; }
    [ -z "$first_build" ] || [ "$first_build" = "$build" ] || { echo 'Application images are from different CI builds.' >&2; exit 1; }
    first_build="$build"
    printf '%s\n' "$candidate" > "$STATE/images/$app.id"
  done
  TAG=dev-latest
  for app in $APPS; do
    docker tag "$(cat "$STATE/images/$app.id")" "$(app_image "$app"):$TAG"
    docker push "$(app_image "$app"):$TAG"
    local reference
    reference=$(docker image inspect "$(app_image "$app"):$TAG" --format '{{index .RepoDigests 0}}')
    [[ "$reference" = "$(app_image "$app")@sha256:"* ]] && [[ "${reference##*@sha256:}" =~ ^[a-f0-9]{64}$ ]] || { echo 'Invalid promoted image digest.' >&2; exit 1; }
    printf '%s:%s@%s\n' "$(app_image "$app")" "$TAG" "${reference##*@}" > "$STATE/images/$app"
  done
  db_up
  deploy
  check
  # Mark only a deployment that completed rollout and HTTP verification.
  for app in $APPS; do
    docker tag "$(cat "$STATE/images/$app.id")" "$(app_image "$app"):dev-passed"
    docker push "$(app_image "$app"):dev-passed"
  done
}
production_deploy() {
  [ "$PLATFORM_ENVIRONMENT" = app-prod ] && [ "$NAMESPACE" = app-prod ] || { echo 'Production deployment requires app-prod.' >&2; exit 1; }
  [ "$SERVICE" = all ] || { echo 'Production must deploy every application.' >&2; exit 1; }
  # Revalidate the release and its age immediately before cluster mutations.
  python3 "$TOOLS_ROOT/scripts/production-release.py" prepare
  TAG=$(cat "$STATE/production-tag")
  [[ "$TAG" =~ ^prod-[0-9]{8}T[0-9]{6}Z$ ]] || { echo 'Invalid production release tag.' >&2; exit 1; }
  for app in $APPS; do
    local reference
    reference=$(cat "$STATE/images/$app")
    local digest_reference="$(app_image "$app")@${reference##*@}"
    docker pull "$digest_reference"
    docker tag "$digest_reference" "$(app_image "$app"):$TAG"
  done
  db_up
  deploy
  check
}

deploy() {
  legacy_guard
  [[ "$TAG" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$ ]] || { echo 'Invalid image tag.' >&2; exit 1; }
  for app in $(applications); do
    docker image inspect "$(app_image "$app"):$TAG" >/dev/null
    local reference="$(app_image "$app"):$TAG"
    if [ "$PLATFORM_ENVIRONMENT" != local ]; then
      reference=$(cat "$STATE/images/$app")
    else
      kind load docker-image --name "$CLUSTER" "$(app_image "$app"):$TAG"
    fi
    helm lint "$CHART" --strict -f "$(app_values "$app")"
    local release_args=(--install "$app" "$CHART" --reset-values -f "$(app_values "$app")"
      --set-string "image=$reference")
    h upgrade "${release_args[@]}" --dry-run=server --hide-secret >/dev/null
    h upgrade "${release_args[@]}" --wait --timeout 10m --history-max 10
  done
}
FORWARD_PIDS=()
stop_forwards() {
  for pid in "${FORWARD_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  done
}
forward() {
  local service="$1" remote="$2" requested="$3" label="$4"
  local logfile="$STATE/$label.log"
  : > "$logfile"
  kubectl --kubeconfig "$KUBECONFIG_FILE" --context "$KUBE_CONTEXT" -n "$NAMESPACE" \
    port-forward --address 127.0.0.1 "service/$service" "$requested:$remote" > "$logfile" 2>&1 &
  local pid=$!
  FORWARD_PIDS+=("$pid")
  trap stop_forwards EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  FORWARD_PORT=''
  for _ in {1..40}; do
    kill -0 "$pid" 2>/dev/null || { cat "$logfile" >&2; return 1; }
    FORWARD_PORT=$(sed -n 's/.*127.0.0.1:\([0-9]*\) ->.*/\1/p' "$logfile" | head -1)
    if [ -n "$FORWARD_PORT" ]; then return; fi
    sleep 0.25
  done
  echo "Port-forward to $service timed out." >&2
  return 1
}
check() {
  local origins=()
  for app in $APPS; do
    forward "$app" "$(app_port "$app")" 0 "check-$app"
    origins+=("$app=http://127.0.0.1:$FORWARD_PORT")
  done
  python3 "$TOOLS_ROOT/scripts/check-http.py" "${origins[@]}"
}
open() {
  for app in $APPS; do
    forward "$app" "$(app_port "$app")" "$(app_localPort "$app")" "open-$app"
    echo "$app: http://localhost:$FORWARD_PORT"
  done
  echo 'Ctrl-C stops the tunnels.'
  while true; do
    for pid in "${FORWARD_PIDS[@]}"; do
      kill -0 "$pid" 2>/dev/null || { echo 'Tunnel closed; restart make open.' >&2; return 1; }
    done
    sleep 1
  done
}
case "${1:-help}" in
  doctor) doctor ;;
  up) applications >/dev/null; cluster; legacy_guard; db_up; build; deploy; check; echo 'Run make open to access the configured services.' ;;
  ci-reset) ci_reset ;;
  ci-up) ci_up ;;
  ci-passed) ci_passed ;;
  promote) promote ;;
  production-deploy) production_deploy ;;
  deploy)
    [ "$PLATFORM_ENVIRONMENT" = local ] || { echo 'Use ci-up or promote for shared environments.' >&2; exit 1; }
    applications >/dev/null
    doctor; legacy_guard; build; deploy; check ;;
  db-up) doctor; db_up ;;
  rollback)
    REVISION="${REVISION:?Set REVISION to a Helm revision listed by make releases}"
    [[ "$REVISION" =~ ^[1-9][0-9]*$ ]] || { echo 'REVISION must be a positive integer.' >&2; exit 1; }
    need helm
    [ "$SERVICE" != all ] || { echo "Set SERVICE to one application." >&2; exit 1; }
    applications >/dev/null
    h rollback "$SERVICE" "$REVISION" --wait --timeout 10m --history-max 10
    check ;;
  render) applications >/dev/null; render; cat "$STATE/rendered.yaml" ;;
  check) check ;;
  open) open ;;
  status) h list; k get deployments,statefulsets,pods,services,pvc ;;
  logs)
    if [ "$SERVICE" = "$DB_RELEASE" ]; then k logs "statefulset/$DB_STATEFULSET" --all-containers --tail=100 -f
    else
      [ "$SERVICE" != all ] || SERVICE=$(echo "$APPS" | cut -d ' ' -f 1)
      applications >/dev/null
      k logs "deployment/$SERVICE" --all-containers --tail=100 -f
    fi ;;
  diagnose)
    for release in $APPS "$DB_RELEASE"; do h history "$release" || true; done
    k get pods,pvc -o wide
    k get endpointslices
    k get events --sort-by=.lastTimestamp
    for app in $APPS; do k logs "deployment/$app" --tail=50 || true; done
    k logs "statefulset/$DB_STATEFULSET" --tail=50 || true ;;
  releases) for release in $APPS "$DB_RELEASE"; do echo "Release: $release"; h history "$release"; done ;;
  down)
    [ "$PLATFORM_ENVIRONMENT" = local ] || { echo 'Deleting the shared cluster is forbidden.' >&2; exit 1; }
    [ "${CONFIRM:-}" = "$CLUSTER" ] || { echo "Deletes local cluster AND database. Run make down CONFIRM=$CLUSTER" >&2; exit 1; }
    kind delete cluster --name "$CLUSTER" --kubeconfig "$KUBECONFIG_FILE" ;;
  *) echo 'Commands: doctor up ci-reset ci-up ci-passed promote db-up deploy rollback render check open status logs diagnose releases down' ;;
esac
