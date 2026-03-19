#!/usr/bin/env bash
set -euo pipefail

echo "Gate 4: Deployment"
echo "Mode: ${FIREPILOT_ENV:-demo}"

if [ "${FIREPILOT_ENV:-demo}" = "demo" ]; then
  echo "DEMO MODE: Skipping live deployment"
  echo "In live mode, this gate:"
  echo "  1. Calls mcp-strata-cloud-manager to push candidate config"
  echo "  2. Creates an ITSM change request via mcp-itsm"
  echo "  3. Records deployment outcome on the change request"
  echo ""
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

# Live mode placeholder
echo "ERROR: Live deployment not yet implemented"
echo "Set FIREPILOT_ENV=demo or implement MCP server integration"
exit 1
