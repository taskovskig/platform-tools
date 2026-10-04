#!/usr/bin/env bash
# Fault injection targets only the configured local namespace or app-dev; never production.
set -euo pipefail
source "$(dirname "$0")/common.sh"
psql_query() { k exec "$DB_STATEFULSET-0" -- sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"' sh "$1"; }
restore() { k scale "statefulset/$DB_STATEFULSET" --replicas=1 >/dev/null; }
trap restore EXIT

marker="$(openssl rand -hex 12)"
psql_query 'CREATE TABLE IF NOT EXISTS platform_mvp_probe (id text PRIMARY KEY)' >/dev/null
psql_query "INSERT INTO platform_mvp_probe VALUES ('$marker')" >/dev/null
old_uid=$(k get pod "$DB_STATEFULSET-0" -o jsonpath='{.metadata.uid}')
k delete pod "$DB_STATEFULSET-0" --wait=true >/dev/null
for _ in {1..60}; do
  new_uid=$(k get pod "$DB_STATEFULSET-0" -o jsonpath='{.metadata.uid}' 2>/dev/null || true)
  if [ -n "$new_uid" ] && [ "$new_uid" != "$old_uid" ]; then break; fi
  sleep 1
done
[ -n "$new_uid" ] && [ "$new_uid" != "$old_uid" ]
k wait pod/"$DB_STATEFULSET-0" --for=condition=Ready --timeout=180s >/dev/null
[ "$(psql_query "SELECT id FROM platform_mvp_probe WHERE id='$marker'")" = "$marker" ]
echo 'PASS: SQL row survived PostgreSQL pod replacement.'

api_pod=$(k get pods -l "app.kubernetes.io/instance=$DB_CLIENT" -o jsonpath='{.items[0].metadata.name}')
api_uid=$(k get pod "$api_pod" -o jsonpath='{.metadata.uid}')
restarts=$(k get pod "$api_pod" -o jsonpath='{.status.containerStatuses[0].restartCount}')
k scale "statefulset/$DB_STATEFULSET" --replicas=0 >/dev/null
k wait pod/"$DB_STATEFULSET-0" --for=delete --timeout=90s >/dev/null
# The application owns its expected behavior during dependency failure.
bash "$DB_OUTAGE_CHECK" "$api_pod"
[ "$(k get pod "$api_pod" -o jsonpath='{.metadata.uid}')" = "$api_uid" ]
[ "$(k get pod "$api_pod" -o jsonpath='{.status.containerStatuses[0].restartCount}')" = "$restarts" ]
echo 'PASS: application outage contract; client pod did not restart.'
restore
k rollout status "statefulset/$DB_STATEFULSET" --timeout=180s
k wait "pod/$api_pod" --for=condition=Ready --timeout=90s >/dev/null
bash "$TOOLS_ROOT/scripts/platform.sh" check
echo 'PASS: service recovered after database restoration.'
