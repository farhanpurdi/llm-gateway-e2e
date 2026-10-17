#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(
  cd "$(dirname "${BASH_SOURCE[0]}")" &&
  pwd
)"

REPO_ROOT="$(
  cd "$SCRIPT_DIR/../.." &&
  pwd
)"

cd "$REPO_ROOT"

if [ "$#" -ne 1 ]; then
  echo "Usage:"
  echo "  $0 <requirements-file>"
  exit 1
fi

REQUIREMENTS_FILE="$1"

if [ ! -f "$REQUIREMENTS_FILE" ]; then
  echo "ERROR: requirements file not found:"
  echo "$REQUIREMENTS_FILE"
  exit 1
fi

# Reuse an installed auditor when available; CI retains isolated-tool fallback.
if [ -n "${PIP_AUDIT_BIN:-}" ]; then
  "$PIP_AUDIT_BIN" -r "$REQUIREMENTS_FILE"
  exit 0
fi

PIP_AUDIT_VERSION="${PIP_AUDIT_VERSION:-2.10.1}"

TEMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TEMP_DIR"
}

trap cleanup EXIT

echo
echo "======================================"
echo "Python Dependency Audit"
echo "======================================"

echo
echo "Requirements:"
echo "  $REQUIREMENTS_FILE"

echo
echo "pip-audit:"
echo "  $PIP_AUDIT_VERSION"

python3 \
  -m venv \
  "$TEMP_DIR/venv"

"$TEMP_DIR/venv/bin/python" \
  -m pip \
  install \
  --quiet \
  --upgrade pip

"$TEMP_DIR/venv/bin/python" \
  -m pip \
  install \
  --quiet \
  "pip-audit==$PIP_AUDIT_VERSION"

"$TEMP_DIR/venv/bin/pip-audit" \
  -r "$REQUIREMENTS_FILE"

echo
echo "======================================"
echo "PYTHON DEPENDENCY AUDIT: PASSED"
echo "======================================"