#!/usr/bin/env bash
set -euo pipefail
echo "Gate 3: Dry-Run Validation"
echo "Mode: ${FIREPILOT_ENV:-demo}"

if [ "${FIREPILOT_ENV:-demo}" = "demo" ]; then
  echo "DEMO MODE: Skipping live dry-run validation"
  echo "Result: PASS (mock)"
  exit 0
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
python "$REPO_ROOT/ci/scripts/gate3-dry-run.py" \
  --config-dir "$REPO_ROOT/firewall-configs/"
