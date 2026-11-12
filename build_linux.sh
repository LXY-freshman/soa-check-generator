#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BUILD_VENV="$ROOT_DIR/.build-venv"
BUILD_DEPS="$ROOT_DIR/.build-deps"
PYTHON="python3"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is required on the build machine." >&2
    exit 2
fi

if python3 -m venv "$BUILD_VENV" >/dev/null 2>&1 && [ -x "$BUILD_VENV/bin/python" ]; then
    PYTHON="$BUILD_VENV/bin/python"
else
    # Some minimal Linux images omit python3-venv; keep build dependencies local.
    rm -rf "$BUILD_VENV"
    mkdir -p "$BUILD_DEPS"
    export PYTHONPATH="$BUILD_DEPS${PYTHONPATH:+:$PYTHONPATH}"
fi

echo "Installing packaging tools in the project build environment"
if [ "$PYTHON" = "python3" ]; then
    python3 -m pip install --upgrade --target "$BUILD_DEPS" pyinstaller pypdf
else
    "$PYTHON" -m pip install --upgrade pyinstaller pypdf
fi

cd "$ROOT_DIR"
rm -rf build dist
"$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --specpath "$ROOT_DIR/build" \
    --onedir \
    --name SOA_Generator \
    --paths "$ROOT_DIR" \
    --add-data "$ROOT_DIR/web:web" \
    --hidden-import soa_generator.service \
    --hidden-import pypdf \
    launcher.py

cp README.md dist/SOA_Generator/README.md
cat > dist/SOA_Generator/start.sh <<'EOF'
#!/usr/bin/env bash
set -u
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$SCRIPT_DIR/SOA_Generator" "$@"
EOF
chmod +x dist/SOA_Generator/start.sh
tar -C dist -czf dist/SOA_Generator-linux-x86_64.tar.gz SOA_Generator
echo "Created dist/SOA_Generator-linux-x86_64.tar.gz"
