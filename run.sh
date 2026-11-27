#!/usr/bin/env bash
# Run the whole app with one command: the backend API and the web page, connected.
# macOS, Linux, or Git Bash / WSL on Windows. On macOS you can also double-click start.command.
#
#   ./run.sh                     set up if needed, start both, open the page in your browser
#   BACKEND_PORT=9000 FRONTEND_PORT=3000 ./run.sh      other ports
#   NO_BROWSER=1 ./run.sh        do not open a browser
#
# Needs Python 3.11 or newer and curl. The first run creates backend/.venv and installs the
# server packages into it. Ctrl-C stops both.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

die() { echo "error: $*" >&2; exit 1; }
case "${1:-}" in -h|--help) sed -n '2,/^set /{/^#/s/^# \{0,1\}//p;}' run.sh; exit 0 ;; esac
command -v curl >/dev/null || die "curl not found; install it, or run backend/setup.sh and frontend/run.sh yourself"

backend_port="${BACKEND_PORT:-8765}"
frontend_port="${FRONTEND_PORT:-5173}"
api="http://127.0.0.1:$backend_port"
page="http://127.0.0.1:$frontend_port/?api=$api"

up() { curl -s -o /dev/null --max-time 1 "$1"; }
up "$api/api/health" && die "port $backend_port is already in use (another copy running?); set BACKEND_PORT"
up "http://127.0.0.1:$frontend_port/" && die "port $frontend_port is already in use; set FRONTEND_PORT"

./backend/setup.sh --setup-only

pids=()
cleanup() {
    trap - EXIT INT TERM
    for pid in ${pids[@]+"${pids[@]}"}; do kill "$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
    echo "stopped"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

./backend/setup.sh --api-only --port "$backend_port" & pids+=($!)
for _ in $(seq 1 60); do
    up "$api/api/health" && break
    kill -0 "${pids[0]}" 2>/dev/null || die "the backend stopped while starting (see the output above)"
    sleep 0.5
done
up "$api/api/health" || die "the backend did not answer on $api within 30 seconds"

./frontend/run.sh --port "$frontend_port" --api "$api" >/dev/null 2>&1 & pids+=($!)
for _ in $(seq 1 20); do up "http://127.0.0.1:$frontend_port/" && break; sleep 0.25; done
up "http://127.0.0.1:$frontend_port/" || die "the page server did not start on port $frontend_port"

echo
echo "  App:      $page"
echo "  API docs: $api/docs"
echo "  Ctrl-C to stop both."
echo

if [ -z "${NO_BROWSER:-}" ]; then
    if command -v open >/dev/null; then open "$page"
    elif command -v xdg-open >/dev/null; then xdg-open "$page" >/dev/null 2>&1 || true
    elif command -v explorer.exe >/dev/null; then explorer.exe "$page" || true
    fi
fi

# Stop when either server stops.
while kill -0 "${pids[0]}" 2>/dev/null && kill -0 "${pids[1]}" 2>/dev/null; do sleep 1; done
die "a server stopped unexpectedly"
