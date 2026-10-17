#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" &&
    pwd
)"

INCLUDE_OUTAGE=false
if [ "${1:-}" = "--include-outage" ] && [ "$#" -eq 1 ]; then
    INCLUDE_OUTAGE=true
elif [ "$#" -ne 0 ]; then
    echo "Usage: $0 [--include-outage]" >&2
    exit 1
fi

"$SCRIPT_DIR/run-unit.sh"
"$SCRIPT_DIR/run-smoke.sh"
"$SCRIPT_DIR/run-native.sh"
"$SCRIPT_DIR/run-live.sh"
if [ "$INCLUDE_OUTAGE" = true ]; then
    "$SCRIPT_DIR/run-outage.sh" --confirm-existing-maintenance
else
    echo "Maintenance outage tests not selected; full release verification requires --include-outage."
fi
