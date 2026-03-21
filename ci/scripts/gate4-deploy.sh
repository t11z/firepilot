#!/usr/bin/env bash
set -euo pipefail
echo "Gate 4: Deployment"
echo "Mode: ${FIREPILOT_ENV:-demo}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TICKET_ID="${TICKET_ID:-}"

if [ "${FIREPILOT_ENV:-demo}" = "live" ] && [ -z "$TICKET_ID" ]; then
  echo "ERROR: TICKET_ID environment variable is required in live mode"
  exit 1
fi

python "$REPO_ROOT/ci/scripts/gate4-deploy.py" \
  --config-dir "$REPO_ROOT/firewall-configs/" \
  --ticket-id "${TICKET_ID:-demo}"
