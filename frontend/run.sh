#!/usr/bin/env bash
# Serve the web page on its own port (macOS, Linux, or Git Bash / WSL on Windows).
#
#   ./frontend/run.sh                       page on http://127.0.0.1:5173/, API at http://127.0.0.1:8765
#   ./frontend/run.sh --port 3000           another port for the page
#   ./frontend/run.sh --api http://127.0.0.1:9000    where the backend API is
#
# The page is plain files with no build step, so any Python 3 serves it; nothing is installed.
# Start the backend first (./backend/setup.sh --api-only), or use ./run.sh at the root for both.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

die() { echo "error: $*" >&2; exit 1; }

port="${FRONTEND_PORT:-5173}"
api="${API_URL:-http://127.0.0.1:8765}"
while [ $# -gt 0 ]; do
    case "$1" in
        --port) [ $# -ge 2 ] || die "--port needs a value"; port="$2"; shift 2 ;;
        --api) [ $# -ge 2 ] || die "--api needs a value"; api="$2"; shift 2 ;;
        -h|--help) sed -n '2,/^set /{/^#/s/^# \{0,1\}//p;}' run.sh; exit 0 ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
done

py=""
for candidate in python3 python; do
    if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 7))' >/dev/null 2>&1; then
        py="$candidate"; break
    fi
done
[ -n "$py" ] || die "Python 3 not found; install it from https://www.python.org/downloads/"

# The page reads ?api= to find the backend; it accepts only addresses on this machine.
echo "page on http://127.0.0.1:$port/?api=$api   (Ctrl-C to stop)"
exec "$py" -m http.server "$port" --bind 127.0.0.1 --directory .
