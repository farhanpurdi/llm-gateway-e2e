#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Actual operator onboarding, both aliases and verified agent tool execution.
# The standard live runner loads the existing infra environment privately.
exec "$SCRIPT_DIR/run-live.sh" tests/test_opencode.py "$@"
