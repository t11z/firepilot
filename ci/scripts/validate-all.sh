#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CI_DIR="$REPO_ROOT/ci"
CONFIG_DIR="$REPO_ROOT/firewall-configs"
FIREPILOT_CONFIG="$REPO_ROOT/firepilot.yaml"

ERRORS=0

# ─── Gate 1: Schema Validation ───────────────────────────────────────────────
echo "=== Gate 1: Schema Validation ==="

if [ -f "$FIREPILOT_CONFIG" ]; then
  echo "Validating firepilot.yaml..."
  check-jsonschema \
    --schemafile "$CI_DIR/schemas/firepilot-config.schema.json" \
    "$FIREPILOT_CONFIG" || ERRORS=$((ERRORS + 1))
fi

# Iterate over every {folder}/{position}/ directory
for position_dir in "$CONFIG_DIR"/*/pre "$CONFIG_DIR"/*/post; do
  [ -d "$position_dir" ] || continue

  manifest="$position_dir/_rulebase.yaml"
  if [ ! -f "$manifest" ]; then
    echo "ERROR: No _rulebase.yaml in $position_dir"
    ERRORS=$((ERRORS + 1))
    continue
  fi

  echo "Validating manifest: $manifest"
  check-jsonschema \
    --schemafile "$CI_DIR/schemas/rulebase-manifest.schema.json" \
    "$manifest" || ERRORS=$((ERRORS + 1))

  # Validate each rule file (everything except _rulebase.yaml)
  for rule_file in "$position_dir"/*.yaml; do
    [ "$(basename "$rule_file")" = "_rulebase.yaml" ] && continue
    echo "Validating rule: $rule_file"
    check-jsonschema \
      --schemafile "$CI_DIR/schemas/security-rule.schema.json" \
      "$rule_file" || ERRORS=$((ERRORS + 1))
  done
done

if [ "$ERRORS" -gt 0 ]; then
  echo "Gate 1 FAILED: $ERRORS schema validation error(s)"
  exit 1
fi
echo "Gate 1 PASSED"

# ─── Gate 2: OPA Policy Evaluation ───────────────────────────────────────────
echo ""
echo "=== Gate 2: OPA Policy Evaluation ==="

# Build zones flag if firepilot.yaml exists
ZONES_FLAG=""
if [ -f "$FIREPILOT_CONFIG" ]; then
  ZONES_FLAG="--zones $FIREPILOT_CONFIG"
fi

for position_dir in "$CONFIG_DIR"/*/pre "$CONFIG_DIR"/*/post; do
  [ -d "$position_dir" ] || continue
  [ -f "$position_dir/_rulebase.yaml" ] || continue

  echo "Evaluating policies for: $position_dir"

  # shellcheck disable=SC2086
  DENY_RESULT=$(python "$CI_DIR/scripts/build-opa-input.py" \
    "$position_dir" $ZONES_FLAG \
    | opa eval -i /dev/stdin \
      -d "$CI_DIR/policies/firepilot.rego" \
      -f raw \
      'data.firepilot.validate.deny')

  # Check if deny set is non-empty (OPA -f raw returns {} for empty set)
  if [ "$DENY_RESULT" != "{}" ] && [ -n "$DENY_RESULT" ]; then
    echo "DENIED: $DENY_RESULT"
    ERRORS=$((ERRORS + 1))
  fi
done

if [ "$ERRORS" -gt 0 ]; then
  echo "Gate 2 FAILED: OPA policy violations detected"
  exit 1
fi
echo "Gate 2 PASSED"

# ─── Gate 3: Dry-Run Validation ──────────────────────────────────────────────
echo ""
echo "=== Gate 3: Dry-Run Validation ==="
bash "$CI_DIR/scripts/gate3-dry-run.sh" || exit 1
echo "Gate 3 PASSED"

echo ""
echo "=== All validation gates passed ==="
