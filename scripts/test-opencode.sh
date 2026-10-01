#!/usr/bin/env bash

set -euo pipefail

: "${COMPANY_LLM_API_KEY:?COMPANY_LLM_API_KEY is required}"
: "${COMPANY_LLM_BASE_URL:?COMPANY_LLM_BASE_URL is required}"

echo "Testing OpenCode + company-fast..."

OUTPUT="$(
    opencode run \
        --standalone \
        --model company-ai/company-fast \
        "Reply exactly with OPENCODE_E2E_OK"
)"

if [[ "$OUTPUT" != *"OPENCODE_E2E_OK"* ]]; then
    echo "ERROR: OpenCode E2E failed."
    echo "$OUTPUT"
    exit 1
fi

echo "OpenCode E2E PASSED."