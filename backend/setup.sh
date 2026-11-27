#!/usr/bin/env bash
# Set up the backend and run it locally (macOS, Linux, or Git Bash / WSL on Windows).
#
#   ./backend/setup.sh                  set up, then start the page and API on http://127.0.0.1:8765/
#   ./backend/setup.sh --port 9000      any other option goes to `python -m server`
#   ./backend/setup.sh --setup-only     set up without starting the server
#   ./backend/setup.sh --api-only       start the API without serving the page (see frontend/run.sh)
#
# Creates backend/.venv and installs requirements-server.txt into it; nothing is installed
# system-wide. Safe to run again. Set PYTHON=/path/to/python to choose the interpreter.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

die() { echo "error: $*" >&2; exit 1; }
new_enough() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; }

setup_only=false
serve_page=true
server_args=()
for arg in "$@"; do
    case "$arg" in
        --setup-only) setup_only=true ;;
        --api-only) serve_page=false ;;
        -h|--help) sed -n '2,/^set /{/^#/s/^# \{0,1\}//p;}' setup.sh; exit 0 ;;
        *) server_args+=("$arg") ;;
    esac
done

# Windows virtual environments keep the interpreter in Scripts/, the others in bin/.
venv_python() {
    if [ -x .venv/Scripts/python.exe ]; then echo .venv/Scripts/python.exe; else echo .venv/bin/python; fi
}

# Reuse .venv only if it works: new enough, and with pip (a failed creation can leave it without).
py="$(venv_python)"
if ! { new_enough "$py" && "$py" -m pip --version >/dev/null 2>&1; }; then
    base=""
    if [ -n "${PYTHON:-}" ]; then
        new_enough "$PYTHON" || die "PYTHON=$PYTHON is not Python 3.11 or newer"
        base="$PYTHON"
    else
        for candidate in python3.14 python3.13 python3.12 python3.11 python3 python; do
            if new_enough "$candidate"; then base="$candidate"; break; fi
        done
    fi
    [ -n "$base" ] || die "Python 3.11 or newer not found; install it from https://www.python.org/downloads/"
    echo "Creating backend/.venv with $("$base" --version)"
    "$base" -m venv --clear .venv || die "could not create .venv (on Debian/Ubuntu, install the python3-venv package)"
    py="$(venv_python)"
fi

# Install only when the requirements changed since the last successful install.
stamp=.venv/requirements.installed
if ! cmp -s requirements-server.txt "$stamp"; then
    echo "Installing dependencies"
    "$py" -m pip install --quiet --disable-pip-version-check -r requirements-server.txt \
        || die "dependency install failed (see the output above)"
    cp requirements-server.txt "$stamp"
fi

echo "Setup complete"
if "$setup_only"; then exit 0; fi

# The ${array[@]+...} form keeps an empty array legal under `set -u` on macOS's bash 3.2.
if "$serve_page"; then server_args=(--static ../frontend ${server_args[@]+"${server_args[@]}"}); fi
exec "$py" -m server ${server_args[@]+"${server_args[@]}"}
