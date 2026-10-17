#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "${1:-}" != "--confirm-existing-maintenance" ]; then
    echo "Usage: $0 --confirm-existing-maintenance (brief local dependency outage)" >&2
    exit 1
fi
shift
for dependency in llm-gateway-postgres llm-gateway-redis; do
    if [ "$(docker inspect --format '{{.State.Running}}' "$dependency")" != true ]; then
        echo "ERROR: dependencies must already be running" >&2
        exit 1
    fi
done
# Outer recovery guard complements the Python context manager and fixture cleanup.
recover() {
    docker start llm-gateway-postgres llm-gateway-redis >/dev/null
}
trap recover EXIT
export E2E_ALLOW_EXISTING_OUTAGE=1
export E2E_LIVE_MARKERS="live and outage"
"$SCRIPT_DIR/run-live.sh" tests/test_dependency_outage.py --tb=short -x -s "$@"
