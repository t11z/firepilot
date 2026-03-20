#!/usr/bin/env bash
set -euo pipefail

# Check dependencies, then run Gates 1-4 in demo mode
bash ci/scripts/check-deps.sh
FIREPILOT_ENV=demo bash ci/scripts/validate-all.sh
FIREPILOT_ENV=demo bash ci/scripts/gate4-deploy.sh
