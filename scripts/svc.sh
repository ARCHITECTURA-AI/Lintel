#!/usr/bin/env bash
# Tiny process manager for local development: start/stop/restart/status of api, lab, web, runner.
# Usage: scripts/svc.sh start api | stop lab | restart api | status
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDS="$ROOT/.data/pids"; LOGS="$ROOT/.data/logs"
mkdir -p "$PIDS" "$LOGS"
cmd_for() {
  case "$1" in
    api)    echo "$ROOT/.venv/bin/uvicorn lintel_api.app:app --host 127.0.0.1 --port ${LINTEL_API_PORT:-8000}" ;;
    lab)    echo "$ROOT/.venv/bin/lintel-lab" ;;
    web)    echo "pnpm --dir $ROOT/apps/web start --port ${LINTEL_WEB_PORT:-3000}" ;;
    webdev) echo "pnpm --dir $ROOT/apps/web dev --port ${LINTEL_WEB_PORT:-3000}" ;;
    runner) echo "$ROOT/.venv/bin/lintel start ${RUNNER_ARGS:-}" ;;
    *) echo "" ;;
  esac
}
running() { [ -f "$PIDS/$1.pid" ] && kill -0 "$(cat "$PIDS/$1.pid")" 2>/dev/null; }
start() {
  local c; c="$(cmd_for "$1")"; [ -z "$c" ] && { echo "unknown service $1"; return 1; }
  if running "$1"; then echo "$1 already running ($(cat "$PIDS/$1.pid"))"; return 0; fi
  # exec keeps the pid; setsid makes it a process-group leader so stop can kill the whole group
  (cd "$ROOT" && exec setsid $c > "$LOGS/$1.log" 2>&1 < /dev/null) &
  echo $! > "$PIDS/$1.pid"
  sleep 0.5; echo "$1 started ($(cat "$PIDS/$1.pid")), log: .data/logs/$1.log"
}
stop() {
  if running "$1"; then
    local pid; pid="$(cat "$PIDS/$1.pid")"
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
    kill -9 -- "-$pid" 2>/dev/null || true
    echo "$1 stopped"
  fi
  rm -f "$PIDS/$1.pid"
}
case "${1:-status}" in
  start) shift; for s in "$@"; do start "$s"; done ;;
  stop) shift; for s in "$@"; do stop "$s"; done ;;
  restart) shift; for s in "$@"; do stop "$s"; start "$s"; done ;;
  status) for s in api lab web webdev runner; do if running "$s"; then echo "$s: running ($(cat "$PIDS/$s.pid"))"; else echo "$s: stopped"; fi; done ;;
  *) echo "usage: $0 start|stop|restart|status [services]"; exit 1 ;;
esac
