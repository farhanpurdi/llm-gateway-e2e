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

echo
echo "======================================"
echo "LLM Gateway E2E Validation"
echo "======================================"

echo
echo "[1/8] Bash syntax"

while IFS= read -r -d '' file; do
  echo "Checking: $file"
  bash -n "$file"
done < <(
  find scripts \
    -type f \
    -name "*.sh" \
    -print0
)

echo "Bash syntax: PASS"


echo
echo "[2/8] ShellCheck"

if ! command -v shellcheck >/dev/null; then
  echo "ERROR: shellcheck is not installed."
  exit 1
fi

find scripts \
  -type f \
  -name "*.sh" \
  -print0 \
  | xargs -0 shellcheck \
      --severity=warning

echo "ShellCheck: PASS"


echo
echo "[3/8] Python syntax"

python3 \
  -m compileall \
  -q \
  tests \
  scripts/ci

echo "Python syntax: PASS"


echo
echo "[4/8] Python dependency health"

python3 -m pip check

echo "Python dependencies: PASS"


echo
echo "[5/8] Regression suite structure"

python3 \
  scripts/ci/validate-suite.py


echo
echo "[6/8] Pytest collection"

python3 \
  -m pytest \
  --collect-only \
  -q

echo "Pytest collection: PASS"


echo
echo "[7/8] Offline regression tests"

"$REPO_ROOT/scripts/run-unit.sh"

echo "Offline regression tests: PASS"

echo
echo "[8/8] Git safety"

if git ls-files \
    | grep -qE '(^|/)\.env$'; then

    echo "ERROR: .env is tracked by Git."
    exit 1
fi

if git ls-files \
    | grep -qE '\.(pem|key|p12|pfx)$'; then

    echo "ERROR: credential file "
    echo "is tracked by Git."
    exit 1
fi

echo "Git safety: PASS"

echo
echo "======================================"
echo "E2E VALIDATION: PASSED"
echo "======================================"
