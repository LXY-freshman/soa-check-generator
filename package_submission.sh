#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
OUTPUT_PATH="${1:-$ROOT_DIR/dist/SOA_Check_Generator-release.tar.gz}"
OUTPUT_DIR="$(dirname -- "$OUTPUT_PATH")"
STAGE_DIR="$(mktemp -d /tmp/soa-check-generator-release.XXXXXX)"
PACKAGE_ROOT="$STAGE_DIR/SOA_Check_Generator"
SOURCE_ROOT="$PACKAGE_ROOT/source"
LINUX_ROOT="$PACKAGE_ROOT/linux-package"

if [ ! -f "$ROOT_DIR/dist/SOA_Generator-linux-x86_64.tar.gz" ]; then
    echo "Missing dist/SOA_Generator-linux-x86_64.tar.gz; run ./build_linux.sh first." >&2
    exit 1
fi

mkdir -p "$SOURCE_ROOT" "$LINUX_ROOT" "$OUTPUT_DIR"

# Copy only deliverable project paths; local Git/configuration and screenshots stay out.
SOURCE_ITEMS=(
    .gitignore
    AGENTS.md
    LICENSE
    CHANGELOG.md
    GLOSSARY.md
    README.md
    adapters
    build_linux.sh
    docs
    launcher.py
    package_submission.sh
    RELEASE_README.md
    schemas
    soa_generator
    start_soa_generator.bat
    start_soa_generator.sh
    tests
    web
)
tar -C "$ROOT_DIR" \
    --exclude='*/__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.log' \
    --exclude='docs/research' \
    -cf - "${SOURCE_ITEMS[@]}" | tar -C "$SOURCE_ROOT" -xf -

cp "$ROOT_DIR/RELEASE_README.md" "$PACKAGE_ROOT/README.md"
cp "$ROOT_DIR/dist/SOA_Generator-linux-x86_64.tar.gz" "$LINUX_ROOT/"
(cd "$LINUX_ROOT" && sha256sum SOA_Generator-linux-x86_64.tar.gz > SHA256SUMS)

tar -C "$STAGE_DIR" -czf "$OUTPUT_PATH" SOA_Check_Generator
echo "Created $OUTPUT_PATH"
echo "Temporary staging directory: $STAGE_DIR"
