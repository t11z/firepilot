#!/usr/bin/env bash
# check-no-env-files.sh — pre-commit hook to block accidental .env commits.
#
# Implements ADR-0006: "A pre-commit hook must verify that no file matching
# *.env (excluding *.env.example) is staged for commit."
#
# Pattern blocked : any file whose basename matches *.env
# Pattern allowed : any file whose basename matches *.env.example
#
# Exit codes:
#   0 — no blocked files staged; commit may proceed
#   1 — one or more blocked files staged; commit is aborted

set -euo pipefail

BLOCKED=()

while IFS= read -r file; do
    basename="${file##*/}"
    # Match *.env but not *.env.example
    if [[ "$basename" == *.env && "$basename" != *.env.example ]]; then
        BLOCKED+=("$file")
    fi
done < <(git diff --cached --name-only)

if [[ ${#BLOCKED[@]} -eq 0 ]]; then
    exit 0
fi

echo ""
echo "ERROR: Credential leak prevention (ADR-0006)"
echo "The following .env file(s) are staged for commit and must not be committed:"
echo ""
for file in "${BLOCKED[@]}"; do
    echo "  - $file"
done
echo ""
echo "To fix: unstage the file(s) with 'git restore --staged <file>'"
echo "Make sure .env files are listed in .gitignore."
echo ""

exit 1
