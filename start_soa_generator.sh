#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

if command -v python3 >/dev/null 2>&1; then
    exec python3 launcher.py "$@"
fi

if command -v python >/dev/null 2>&1; then
    exec python launcher.py "$@"
fi

echo "Python 3.10 or newer was not found." >&2
echo "Install Python and run this script again." >&2
exit 2
