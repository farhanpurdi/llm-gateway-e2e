#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(
  cd "$(dirname "${BASH_SOURCE[0]}")" &&
  pwd
)"

ROOT_DIR="$(
  cd "$SCRIPT_DIR/.." &&
  pwd
)"

ENV_FILE="${E2E_ENV_FILE:-$ROOT_DIR/../llm-gateway-infra/.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: environment file not found:"
  echo "$ENV_FILE"
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

export E2E_FAST_MODEL="${E2E_FAST_MODEL:-company-fast}"
export E2E_CODING_MODEL="${E2E_CODING_MODEL:-company-coding}"

cd "$ROOT_DIR"

python3 -m pytest \
    -v \
    -m "not live and not unit"
