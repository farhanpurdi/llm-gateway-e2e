#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(
  cd "$(dirname "${BASH_SOURCE[0]}")" &&
  pwd
)"

REPO_ROOT="$(
  cd "$SCRIPT_DIR/.." &&
  pwd
)"

cd "$REPO_ROOT"

echo
echo "======================================"
echo "LLM Gateway Enforcement Tests"
echo "======================================"

python3 \
  -m pytest \
  -v \
  -m "limits"

echo
echo "======================================"
echo "ENFORCEMENT TESTS: PASSED"
echo "======================================"