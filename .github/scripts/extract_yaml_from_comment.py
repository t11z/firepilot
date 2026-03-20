#!/usr/bin/env python3
"""FirePilot — Extract YAML security rule configuration from GitHub issue comments.

Fetches all comments on a GitHub issue, searches for fenced YAML code blocks
containing a ``schema_version`` key (the FirePilot security rule discriminator
defined in ADR-0007), and writes the extracted rule file to an output directory.

Metadata about the extracted rule (name, folder, position, zone summary) is
written to the GitHub Actions output file (``$GITHUB_OUTPUT``) for use in
subsequent workflow steps.

If no valid YAML rule block is found the script posts an error comment on the
issue and exits with status 1, causing the calling workflow to abort.

Required environment variables:
    GITHUB_TOKEN    — GitHub token for API authentication.
    ISSUE_NUMBER    — GitHub issue number (integer as string).
    REPO            — Repository in "owner/repo" format (e.g. ``org/repo``).
    OUTPUT_DIR      — Directory path where extracted YAML files are written.

Optional environment variables:
    GITHUB_OUTPUT   — Path to the GitHub Actions output file.  Set automatically
                      by the Actions runner.  If absent, outputs are printed to
                      stderr (useful for local testing).

Usage (called by ``.github/workflows/approve-and-commit.yml``):
    python extract_yaml_from_comment.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests
import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_API_BASE = "https://api.github.com"

# Default placement used when the YAML comment does not include folder/position.
# Matches the existing fixture structure in firewall-configs/shared/pre/.
# Per ADR-0007, folder and position are derived from directory structure at
# deploy time — they are NOT stored inside committed rule files.
DEFAULT_FOLDER = "shared"
DEFAULT_POSITION = "pre"

# Regex to extract fenced YAML code blocks from Markdown.
# Matches ```yaml … ``` (case-insensitive language tag, dotall body).
YAML_BLOCK_RE = re.compile(
    r"```yaml[ \t]*\r?\n(.*?)\r?\n```",
    re.DOTALL | re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _github_headers(token: str) -> dict[str, str]:
    """Return standard GitHub REST API request headers."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_issue_comments(
    repo: str,
    issue_number: int,
    token: str,
) -> list[dict[str, Any]]:
    """Fetch all comments on a GitHub issue, handling pagination.

    Args:
        repo: Repository in "owner/repo" format.
        issue_number: GitHub issue number.
        token: GitHub API authentication token.

    Returns:
        List of comment objects from the GitHub API (oldest first).

    Raises:
        requests.HTTPError: If the GitHub API request fails.
    """
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/comments"
    params: dict[str, int] = {"per_page": 100, "page": 1}
    all_comments: list[dict[str, Any]] = []

    while True:
        response = requests.get(
            url,
            headers=_github_headers(token),
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        page: list[dict[str, Any]] = response.json()
        if not page:
            break
        all_comments.extend(page)
        if len(page) < 100:
            break
        params["page"] += 1

    return all_comments


def post_issue_comment(
    repo: str,
    issue_number: int,
    body: str,
    token: str,
) -> None:
    """Post a comment on a GitHub issue.

    Args:
        repo: Repository in "owner/repo" format.
        issue_number: GitHub issue number.
        body: Markdown body of the comment.
        token: GitHub API authentication token.

    Raises:
        requests.HTTPError: If the API request fails.
    """
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/comments"
    response = requests.post(
        url,
        json={"body": body},
        headers=_github_headers(token),
        timeout=30,
    )
    response.raise_for_status()


# ---------------------------------------------------------------------------
# YAML extraction
# ---------------------------------------------------------------------------


def extract_yaml_blocks(comment_body: str) -> list[str]:
    """Extract all fenced YAML code block contents from a Markdown comment.

    Args:
        comment_body: Raw Markdown text of a single issue comment.

    Returns:
        List of raw YAML strings, one per fenced block found.  May be empty.
    """
    return YAML_BLOCK_RE.findall(comment_body)


def is_security_rule(data: Any) -> bool:  # noqa: ANN401 — YAML can be Any type
    """Return True if a parsed YAML value looks like a FirePilot security rule.

    Discriminator: per ADR-0007, every security rule file has a ``schema_version``
    key.  Additional heuristics (``name`` and ``action``) reduce false positives
    on other YAML blocks that might be present in comments.

    Args:
        data: Value returned by ``yaml.safe_load()``.

    Returns:
        True if ``data`` is a dict containing ``schema_version``, ``name``,
        and ``action``.
    """
    return (
        isinstance(data, dict)
        and "schema_version" in data
        and "name" in data
        and "action" in data
    )


def find_candidate_rules(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Scan issue comments for valid FirePilot security rule YAML blocks.

    Iterates comments from newest to oldest.  For each comment, extracts all
    fenced YAML blocks and attempts to parse them.  Returns the valid security
    rule dicts found in the most recent comment that contains at least one.

    Strategy (newest-first): Claude posts its proposal as the last comment, so
    the most recent comment containing a ``schema_version`` block is the one to
    use.

    Args:
        comments: List of GitHub comment objects in creation order (oldest first).

    Returns:
        List of parsed rule dicts from the most recent matching comment.
        Returns an empty list if no valid rule block is found anywhere.
    """
    for comment in reversed(comments):
        body: str = comment.get("body", "") or ""
        if not body:
            continue

        raw_blocks = extract_yaml_blocks(body)
        valid_rules: list[dict[str, Any]] = []

        for raw in raw_blocks:
            try:
                data = yaml.safe_load(raw)
            except yaml.YAMLError as exc:
                print(
                    f"WARNING: Skipping unparseable YAML block: {exc}",
                    file=sys.stderr,
                )
                continue

            if is_security_rule(data):
                valid_rules.append(data)

        if valid_rules:
            return valid_rules

    return []


# ---------------------------------------------------------------------------
# Rule file writing
# ---------------------------------------------------------------------------


def extract_placement(rule: dict[str, Any]) -> tuple[str, str]:
    """Extract (folder, position) from a rule dict, falling back to defaults.

    ADR-0007 states that ``folder`` and ``position`` must NOT appear in
    committed rule YAML files — they are derived from the directory path.
    However, Claude's analysis comment may include them as placement hints
    so the workflow knows where to write the file.  They are stripped before
    the file is committed (see ``strip_placement_fields``).

    Args:
        rule: Parsed rule YAML dictionary (may contain placement hints).

    Returns:
        Tuple of (folder, position).  Defaults: ("shared", "pre").
    """
    folder = str(rule.get("folder", DEFAULT_FOLDER)).strip() or DEFAULT_FOLDER
    position = str(rule.get("position", DEFAULT_POSITION)).strip() or DEFAULT_POSITION
    return folder, position


def strip_placement_fields(rule: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``rule`` with ``folder`` and ``position`` removed.

    Per ADR-0007 these fields are derived from directory structure and must
    not appear in committed security rule YAML files.

    Args:
        rule: Parsed rule YAML dictionary (may contain placement hints).

    Returns:
        New dict with ``folder`` and ``position`` keys omitted.
    """
    return {k: v for k, v in rule.items() if k not in ("folder", "position")}


def write_rule_file(rule: dict[str, Any], output_dir: Path) -> Path:
    """Serialise a security rule dict to a YAML file in ``output_dir``.

    The file is named ``{rule['name']}.yaml``.  The ``folder`` and
    ``position`` keys are stripped before writing (ADR-0007).

    Args:
        rule: Parsed rule YAML dictionary.
        output_dir: Directory to write the file into.

    Returns:
        Absolute path to the written file.

    Raises:
        KeyError: If ``name`` is missing from ``rule``.
        OSError: If the file cannot be written.
    """
    rule_name: str = rule["name"]
    clean_rule = strip_placement_fields(rule)
    file_path = output_dir / f"{rule_name}.yaml"

    with open(file_path, "w", encoding="utf-8") as fh:
        # sort_keys=False preserves the field order from the original comment,
        # which improves readability of the generated PR diff.
        yaml.dump(clean_rule, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return file_path


# ---------------------------------------------------------------------------
# GitHub Actions output helpers
# ---------------------------------------------------------------------------


def write_github_output(key: str, value: str) -> None:
    """Append a ``key=value`` pair to the GitHub Actions output file.

    Outputs written here are accessible in subsequent workflow steps via
    ``${{ steps.<step-id>.outputs.<key> }}``.

    Args:
        key: Output variable name (must be a valid shell identifier).
        value: Output value.  Newlines are collapsed to a single space because
               GitHub Actions step outputs must be single-line.
    """
    output_file = os.environ.get("GITHUB_OUTPUT")
    # Collapse newlines — multi-line values break GitHub output parsing.
    safe_value = value.replace("\r\n", " ").replace("\n", " ").replace("\r", "")

    if not output_file:
        # Graceful fallback for local testing without a runner environment.
        print(f"[GITHUB_OUTPUT not set] {key}={safe_value}", file=sys.stderr)
        return

    with open(output_file, "a", encoding="utf-8") as fh:
        fh.write(f"{key}={safe_value}\n")


def format_list(values: Any) -> str:  # noqa: ANN401 — YAML list fields can be Any
    """Format a YAML list field as a comma-separated string.

    Handles the common case where YAML fields like ``from``, ``to``, and
    ``service`` may be lists or a single string.

    Args:
        values: A list, string, or None from a parsed YAML field.

    Returns:
        Comma-separated string, or empty string for None/empty.
    """
    if isinstance(values, list):
        return ", ".join(str(v) for v in values)
    if values is None:
        return ""
    return str(values)


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def get_required_env(name: str) -> str:
    """Return an environment variable value or abort with a descriptive error.

    Args:
        name: Name of the environment variable.

    Returns:
        The variable's value (guaranteed non-empty string).
    """
    value = os.environ.get(name)
    if not value:
        print(
            f"ERROR: Required environment variable '{name}' is not set.",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point — extract YAML from issue comments and emit workflow outputs.

    Flow:
        1. Fetch all comments on the issue.
        2. Scan for valid security rule YAML blocks (newest comment first).
        3. If none found: post an error comment on the issue and exit 1.
        4. Write the extracted rule YAML to ``OUTPUT_DIR``.
        5. Write metadata to ``$GITHUB_OUTPUT`` for use in subsequent steps.
    """
    token = get_required_env("GITHUB_TOKEN")
    issue_number = int(get_required_env("ISSUE_NUMBER"))
    repo = get_required_env("REPO")
    output_dir = Path(get_required_env("OUTPUT_DIR"))

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching comments for issue #{issue_number} in {repo} …")
    try:
        comments = fetch_issue_comments(repo, issue_number, token)
    except requests.HTTPError as exc:
        print(f"ERROR: Failed to fetch issue comments: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(comments)} comment(s). Scanning for YAML security rules …")
    rules = find_candidate_rules(comments)

    if not rules:
        # Post a clear error comment before aborting so the issue author knows
        # what went wrong (acceptance criterion 4).
        error_body = (
            "## FirePilot — Approval Error\n\n"
            "The approval workflow could not find a valid YAML security rule "
            "configuration in the issue comments.\n\n"
            "**Required**: at least one issue comment must contain a fenced "
            "` ```yaml ` code block whose content includes a `schema_version` key "
            "(indicating a FirePilot security rule proposal).\n\n"
            "**Resolution**: ensure the FirePilot analysis workflow has run and "
            "posted its configuration proposal before applying the "
            "`firepilot:approved` label.\n\n"
            "_No branch or pull request was created._"
        )
        try:
            post_issue_comment(repo, issue_number, error_body, token)
            print("Posted error comment on issue.", file=sys.stderr)
        except requests.HTTPError as exc:
            print(f"WARNING: Failed to post error comment: {exc}", file=sys.stderr)

        print(
            "ERROR: No valid YAML security rule block found in issue comments.",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(rules) > 1:
        print(
            f"WARNING: Found {len(rules)} rule blocks in the most recent matching "
            "comment. Processing only the first one.",
            file=sys.stderr,
        )

    rule = rules[0]
    rule_name: str = rule.get("name", "")

    if not rule_name:
        print(
            "ERROR: Extracted YAML block is missing required field 'name'.",
            file=sys.stderr,
        )
        sys.exit(1)

    folder, position = extract_placement(rule)
    print(f"Extracted rule: name='{rule_name}', folder='{folder}', position='{position}'")

    try:
        yaml_file = write_rule_file(rule, output_dir)
    except (KeyError, OSError) as exc:
        print(f"ERROR: Failed to write rule YAML file: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Rule file written to: {yaml_file}")

    # Write all metadata to GitHub Actions outputs for downstream steps.
    write_github_output("rule_name", rule_name)
    write_github_output("folder", folder)
    write_github_output("position", position)
    write_github_output("yaml_file_path", str(yaml_file))
    write_github_output("from_zones", format_list(rule.get("from", [])))
    write_github_output("to_zones", format_list(rule.get("to", [])))
    write_github_output("action", str(rule.get("action", "")))
    write_github_output("services", format_list(rule.get("service", [])))

    # Print a JSON summary for workflow logs / debugging.
    summary = {
        "rule_name": rule_name,
        "folder": folder,
        "position": position,
        "yaml_file": str(yaml_file),
        "from_zones": format_list(rule.get("from", [])),
        "to_zones": format_list(rule.get("to", [])),
        "action": str(rule.get("action", "")),
        "services": format_list(rule.get("service", [])),
    }
    print("Extraction summary:")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
