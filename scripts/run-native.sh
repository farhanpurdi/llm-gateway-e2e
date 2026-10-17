#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GATEWAY_CONTAINER="${E2E_GATEWAY_CONTAINER:-llm-gateway}"

echo "Native LiteLLM fault/retry probe on the existing gateway container."
echo "No provider requests or gateway configuration changes."

exec docker exec --interactive "$GATEWAY_CONTAINER" python - \
    < "$REPO_ROOT/tests/native_failure_probe.py"
