#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
revision() { h status "$1" -o json | node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).version'; }
db_revision=$(revision "$DB_RELEASE")
pvc=$(k get pvc "$DB_PVC" -o jsonpath='{.metadata.uid}')
secret=$(k get secret "$DB_SECRET" -o jsonpath='{.metadata.resourceVersion}')
for app in $APPS; do
  others_before=''
  for other in $APPS; do
    [ "$other" != "$app" ] || continue
    others_before+="$other:$(revision "$other"):$(k get deployment "$other" -o jsonpath='{.metadata.generation}');"
  done
  start=$(revision "$app")
  replicas=$(k get deployment "$app" -o jsonpath='{.spec.replicas}')
  image=$(k get deployment "$app" -o jsonpath='{.spec.template.spec.containers[0].image}')
  restore() { h rollback "$app" "$start" --wait --timeout 10m; }
  trap restore EXIT
  h upgrade "$app" "$CHART" --reuse-values --set "replicas=$((replicas+1))" --wait --timeout 10m --history-max 10
  [ "$(k get deployment "$app" -o jsonpath='{.spec.replicas}')" = "$((replicas+1))" ]
  SERVICE="$app" REVISION="$start" bash "$TOOLS_ROOT/scripts/platform.sh" rollback
  trap - EXIT
  [ "$(k get deployment "$app" -o jsonpath='{.spec.replicas}')" = "$replicas" ]
  [ "$(k get deployment "$app" -o jsonpath='{.spec.template.spec.containers[0].image}')" = "$image" ]
  others_after=''
  for other in $APPS; do
    [ "$other" != "$app" ] || continue
    others_after+="$other:$(revision "$other"):$(k get deployment "$other" -o jsonpath='{.metadata.generation}');"
  done
  [ "$others_before" = "$others_after" ]
  [ "$(revision "$DB_RELEASE")" = "$db_revision" ]
  [ "$(k get pvc "$DB_PVC" -o jsonpath='{.metadata.uid}')" = "$pvc" ]
  [ "$(k get secret "$DB_SECRET" -o jsonpath='{.metadata.resourceVersion}')" = "$secret" ]
  echo "PASS: $app upgrade/rollback leaves other applications and database unchanged."
done
