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

GITLEAKS_IMAGE="${GITLEAKS_IMAGE:-ghcr.io/gitleaks/gitleaks:v8.28.0}"

TEMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TEMP_DIR"
}

trap cleanup EXIT


echo
echo "======================================"
echo "Secret Scan"
echo "======================================"

echo
echo "Scanner:"
echo "  $GITLEAKS_IMAGE"


#
# --------------------------------------------------
# 1. Verify scanner binary can run
# --------------------------------------------------
#

echo
echo "[1/3] Scanner availability"

docker run \
  --rm \
  --network=none \
  "$GITLEAKS_IMAGE" \
  version

echo "Scanner availability: PASS"


#
# --------------------------------------------------
# 2. Scanner engine self-test
#
# IMPORTANT:
# This uses our OWN detection rule.
# It does not depend on GitHub/OpenAI/etc rules.
# --------------------------------------------------
#

echo
echo "[2/3] Scanner engine self-test"

cat > "$TEMP_DIR/canary.toml" <<'EOF'
title = "LLM Gateway Gitleaks Canary"

[[rules]]
id = "llm-gateway-canary"
description = "Internal Gitleaks scanner self-test"
regex = '''COMPANY_GITLEAKS_CANARY_[A-Z0-9]{24}'''
keywords = [
  "COMPANY_GITLEAKS_CANARY_"
]
EOF


CANARY_SECRET="COMPANY_GITLEAKS_CANARY_ABCDEF1234567890ABCDEFGH"

set +e

printf '%s\n' "$CANARY_SECRET" \
  | docker run \
      --rm \
      --interactive \
      --network=none \
      --volume \
        "$TEMP_DIR/canary.toml:/canary.toml:ro" \
      "$GITLEAKS_IMAGE" \
      --config=/canary.toml \
      --redact \
      --exit-code=42 \
      stdin \
      >/dev/null 2>&1

CANARY_STATUS=$?

set -e


if [ "$CANARY_STATUS" -ne 42 ]; then
  echo "ERROR: scanner engine self-test failed."
  echo
  echo "Expected exit code:"
  echo "  42"
  echo
  echo "Actual exit code:"
  echo "  $CANARY_STATUS"
  echo
  echo "The scanner did not detect our controlled canary."
  exit 1
fi


echo "Scanner engine self-test: PASS"


#
# --------------------------------------------------
# 3. Scan repository Git history
# --------------------------------------------------
#

echo
echo "[3/3] Repository history scan"

git log \
  -p \
  --all \
  --full-history \
  --no-renames \
  | docker run \
      --rm \
      --interactive \
      --network=none \
      "$GITLEAKS_IMAGE" \
      --redact \
      --verbose \
      stdin


echo
echo "======================================"
echo "SECRET SCAN: PASSED"
echo "======================================"