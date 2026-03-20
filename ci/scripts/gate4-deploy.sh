#!/usr/bin/env bash
set -euo pipefail
echo "Gate 4: Deployment"
echo "Mode: ${FIREPILOT_ENV:-demo}"

if [ "${FIREPILOT_ENV:-demo}" = "demo" ]; then
  echo "DEMO MODE: Skipping live deployment"
  echo "Simulated deployment log:"
  echo "  timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "  action: push_candidate_config"
  echo "  folders: [shared]"
  echo "  status: FIN"
  echo "  result: OK"
  echo "  job_id: mock-job-$(date +%s)"
  echo ""
  echo "Result: PASS (mock)"
  exit 0
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TICKET_ID="${TICKET_ID:-}"

if [ -z "$TICKET_ID" ]; then
  echo "ERROR: TICKET_ID environment variable is required in live mode"
  exit 1
fi

python "$REPO_ROOT/ci/scripts/gate4-deploy.py" \
  --config-dir "$REPO_ROOT/firewall-configs/" \
  --ticket-id "$TICKET_ID"
