#!/usr/bin/env bash
# check-deps.sh — Verify that required tools are available on $PATH.
# Hard requirements (exit 1 if missing): python3, check-jsonschema, opa
# Soft requirements (warn but exit 0): ruff, pytest

MISSING_HARD=0
CHECK="✓"
CROSS="✗"
WARN="⚠"

echo "Checking dependencies..."

# ── python3 (hard, version 3.11+) ────────────────────────────────────────────
if command -v python3 >/dev/null 2>&1; then
  PYTHON_VERSION=$(python3 --version 2>&1)
  PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
  PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
  if [ "$PYTHON_MAJOR" -gt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; }; then
    printf "  %s python3 (%s)\n" "$CHECK" "$PYTHON_VERSION"
  else
    printf "  %s python3 — version 3.11+ required, found %s\n" "$CROSS" "$PYTHON_VERSION"
    MISSING_HARD=$((MISSING_HARD + 1))
  fi
else
  printf "  %s python3 — install from https://www.python.org/downloads/\n" "$CROSS"
  MISSING_HARD=$((MISSING_HARD + 1))
fi

# ── check-jsonschema (hard) ───────────────────────────────────────────────────
if command -v check-jsonschema >/dev/null 2>&1; then
  CJS_VERSION=$(check-jsonschema --version 2>&1 | head -1)
  printf "  %s check-jsonschema (%s)\n" "$CHECK" "$CJS_VERSION"
else
  printf "  %s check-jsonschema — install with: pip install check-jsonschema\n" "$CROSS"
  MISSING_HARD=$((MISSING_HARD + 1))
fi

# ── opa (hard) ────────────────────────────────────────────────────────────────
if command -v opa >/dev/null 2>&1; then
  OPA_VERSION=$(opa version 2>&1 | head -1)
  printf "  %s opa (%s)\n" "$CHECK" "$OPA_VERSION"
else
  printf "  %s opa — install from https://www.openpolicyagent.org/docs/latest/#1-download-opa\n" "$CROSS"
  printf "         Linux:   curl -L -o /usr/local/bin/opa https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static && chmod +x /usr/local/bin/opa\n"
  printf "         macOS:   brew install opa\n"
  MISSING_HARD=$((MISSING_HARD + 1))
fi

# ── ruff (soft) ───────────────────────────────────────────────────────────────
if command -v ruff >/dev/null 2>&1; then
  RUFF_VERSION=$(ruff --version 2>&1 | head -1)
  printf "  %s ruff (%s)\n" "$CHECK" "$RUFF_VERSION"
else
  printf "  %s ruff — not found (needed for make lint) — install with: pip install ruff\n" "$WARN"
fi

# ── pytest (soft) ─────────────────────────────────────────────────────────────
if command -v pytest >/dev/null 2>&1; then
  PYTEST_VERSION=$(pytest --version 2>&1 | head -1)
  printf "  %s pytest (%s)\n" "$CHECK" "$PYTEST_VERSION"
else
  printf "  %s pytest — not found (needed for make test) — install with: pip install pytest\n" "$WARN"
fi

# ── Final verdict ─────────────────────────────────────────────────────────────
echo ""
if [ "$MISSING_HARD" -gt 0 ]; then
  echo "ERROR: Missing $MISSING_HARD required tool(s)"
  exit 1
fi
echo "All required tools are available."
