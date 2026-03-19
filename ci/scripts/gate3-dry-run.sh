#!/usr/bin/env bash
set -euo pipefail

echo "Gate 3: Dry-run validation"
echo "Mode: ${FIREPILOT_ENV:-demo}"

if [ "${FIREPILOT_ENV:-demo}" = "demo" ]; then
  echo "DEMO MODE: Skipping SCM API dry-run validation"
  echo "In live mode, this gate calls mcp-strata-cloud-manager"
  echo "in validation mode to confirm the firewall API accepts"
  echo "the proposed configuration."
  echo "Result: PASS (mock)"
  exit 0
fi

# Live mode placeholder — will be replaced when MCP servers exist
echo "ERROR: Live dry-run validation not yet implemented"
echo "Set FIREPILOT_ENV=demo or implement MCP server integration"
exit 1
