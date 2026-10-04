#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
bash "$TOOLS_ROOT/scripts/platform.sh" open > "$STATE/browser-forward.log" 2>&1 &
forward_pid=$!
cleanup() { kill "$forward_pid" 2>/dev/null || true; wait "$forward_pid" 2>/dev/null || true; }
trap cleanup EXIT
ready=false
for attempt in {1..30}; do
  kill -0 "$forward_pid" 2>/dev/null || break
  ready=true
  for app in $APPS; do
    curl -fsS --max-time 2 "http://127.0.0.1:$(app_localPort "$app")/$(python3 -c 'import json,sys; c=json.load(open("platform.json")); print(next(x["path"].lstrip("/") for x in c["checks"] if x["service"]==sys.argv[1]))' "$app")" >/dev/null 2>&1 || ready=false
  done
  [ "$ready" != true ] || break
  sleep 1
done
if [ "$ready" != true ]; then cat "$STATE/browser-forward.log" >&2; exit 1; fi
make browser-test
