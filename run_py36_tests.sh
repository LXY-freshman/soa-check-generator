#!/usr/bin/env bash
set -eu

PYTHON_BIN="${PYTHON_BIN:-python3.6}"
ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"

"$PYTHON_BIN" -m compileall -q soa_generator tests
"$PYTHON_BIN" -m unittest discover -s tests -v
