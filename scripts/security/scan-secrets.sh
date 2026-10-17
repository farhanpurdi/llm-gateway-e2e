#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"
GITLEAKS_IMAGE="${GITLEAKS_IMAGE:-ghcr.io/gitleaks/gitleaks:v8.28.0}"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
scanner() {
  if [ -n "${GITLEAKS_BIN:-}" ]; then
    "$GITLEAKS_BIN" "$@"
  else
    docker run --rm --interactive --network=none \
      --volume "$TEMP_DIR:$TEMP_DIR:ro" "$GITLEAKS_IMAGE" "$@"
  fi
}
scanner version
cat > "$TEMP_DIR/canary.toml" <<'CANARY'
title = "LLM Gateway Gitleaks Canary"
[[rules]]
id = "llm-gateway-canary"
regex = '''COMPANY_GITLEAKS_CANARY_[A-Z0-9]{24}'''
CANARY
set +e
printf '%s\n' 'COMPANY_GITLEAKS_CANARY_ABCDEF1234567890ABCDEFGH' \
  | scanner --config="$TEMP_DIR/canary.toml" --redact --exit-code=42 stdin >/dev/null 2>&1
CANARY_STATUS=$?
set -e
if [ "$CANARY_STATUS" -ne 42 ]; then
  echo "ERROR: scanner canary failed ($CANARY_STATUS, expected 42)" >&2
  exit 1
fi
echo "Scanner engine self-test: PASS"
echo "Repository history scan"
git log -p --all --full-history --no-renames | scanner --redact stdin
echo "Current tracked and non-ignored files scan"
# Include uncommitted and new source files, but never ignored .env/backups.
python3 - <<'PYCODE' | scanner --redact stdin
from pathlib import Path
import subprocess, sys
names = subprocess.check_output(['git', 'ls-files', '-c', '-o', '--exclude-standard', '-z']).split(b'\0')
for name in sorted(set(names)):
    if not name:
        continue
    path = Path(name.decode())
    if path.is_file() and not path.is_symlink():
        sys.stdout.buffer.write(b'\nFILE: ' + name + b'\n' + path.read_bytes() + b'\n')
PYCODE
echo "SECRET SCAN: PASSED"
