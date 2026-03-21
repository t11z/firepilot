"""FirePilot — GitHub Actions script for processing firewall change requests.

Reads a GitHub Issue body, downloads any PDF attachments, invokes the
client-side MCP agentic orchestrator (`ci/scripts/process-issue.py`) as a
subprocess, and posts its output as an issue comment.

If Claude's response contains a valid YAML security rule block (per ADR-0007),
the rule is extracted to a file and metadata is written to GitHub Actions
outputs so downstream workflow steps can commit the file and open a PR.

The orchestrator connects to mcp-strata-cloud-manager and mcp-itsm as local
stdio subprocesses and runs the full Claude agentic tool-use loop in-process.

Required environment variables:
    GITHUB_TOKEN       — GitHub Actions token for issue operations and attachment downloads
    ANTHROPIC_API_KEY  — Claude API authentication key
    ISSUE_NUMBER       — GitHub issue number (integer as string)
    ISSUE_BODY         — Full body text of the GitHub issue
    REPO               — Repository in "owner/repo" format
    OUTPUT_DIR         — Directory path where extracted YAML files are written
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests
import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# GitHub attachment URL pattern — two URL shapes are in use:
#   Legacy (files uploaded before ~2024):
#     https://github.com/user-attachments/files/<id>/<filename>
#   Current (asset pipeline):
#     https://github.com/user-attachments/assets/<uuid>
PDF_ATTACHMENT_RE = re.compile(
    r'\[([^\]]+\.pdf)\]\((https://github\.com/user-attachments/(?:assets|files)/[^\)]+)\)',
    re.IGNORECASE,
)

MAX_PDF_BYTES = 32 * 1024 * 1024  # 32 MB — Claude API document size limit

GITHUB_API_BASE = "https://api.github.com"

# Path to the client-side orchestrator, relative to the repository root
PROCESS_ISSUE_SCRIPT = Path("ci/scripts/process-issue.py")

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
# Environment
# ---------------------------------------------------------------------------

def get_required_env(name: str) -> str:
    """Return environment variable value or exit with an error message."""
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: Required environment variable '{name}' is not set.", file=sys.stderr)
        sys.exit(1)
    return value


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def post_issue_comment(repo: str, issue_number: int, body: str, github_token: str) -> None:
    """Post a comment on the specified GitHub issue."""
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/comments"
    response = requests.post(
        url,
        json={"body": body},
        headers={
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    response.raise_for_status()


def add_label(repo: str, issue_number: int, label: str, github_token: str) -> None:
    """Add a label to the specified GitHub issue."""
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/labels"
    response = requests.post(
        url,
        json={"labels": [label]},
        headers={
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    response.raise_for_status()


# ---------------------------------------------------------------------------
# PDF handling
# ---------------------------------------------------------------------------

def parse_pdf_attachments(issue_body: str) -> list[tuple[str, str]]:
    """Extract (filename, url) pairs for PDF attachments from the issue body.

    GitHub renders uploaded files as Markdown links in one of two formats:
        [filename.pdf](https://github.com/user-attachments/assets/...)   # current
        [filename.pdf](https://github.com/user-attachments/files/...)    # legacy
    """
    return PDF_ATTACHMENT_RE.findall(issue_body)


def download_pdf(filename: str, url: str, github_token: str, tmp_dir: str) -> str | None:
    """Download a PDF attachment from GitHub and return the local file path.

    Returns None if the download fails, logging a descriptive error.
    """
    dest = os.path.join(tmp_dir, filename)
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {github_token}"},
            timeout=60,
            stream=True,
        )
        response.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in response.iter_content(chunk_size=8192):
                fh.write(chunk)
        return dest
    except requests.RequestException as exc:
        print(f"WARNING: Failed to download attachment '{filename}': {exc}", file=sys.stderr)
        return None


def is_pdf_within_size_limit(file_path: str) -> bool:
    """Return True if the file is within the PDF size limit."""
    size = os.path.getsize(file_path)
    if size > MAX_PDF_BYTES:
        print(
            f"WARNING: Attachment '{os.path.basename(file_path)}' is {size} bytes "
            f"(limit {MAX_PDF_BYTES}). Skipping.",
            file=sys.stderr,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# YAML extraction from orchestrator response
# ---------------------------------------------------------------------------

def extract_yaml_blocks(text: str) -> list[str]:
    """Extract all fenced YAML code block contents from a Markdown string.

    Args:
        text: Raw Markdown text (e.g. Claude's response).

    Returns:
        List of raw YAML strings, one per fenced block found.  May be empty.
    """
    return YAML_BLOCK_RE.findall(text)


def is_security_rule(data: Any) -> bool:  # noqa: ANN401 — YAML can be Any type
    """Return True if a parsed YAML value looks like a FirePilot security rule.

    Discriminator: per ADR-0007, every security rule file has a ``schema_version``
    key.  Additional heuristics (``name`` and ``action``) reduce false positives.

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


def extract_rule_from_response(response_text: str) -> dict[str, Any] | None:
    """Scan an orchestrator response for a valid FirePilot security rule YAML block.

    Iterates all fenced YAML blocks in the response.  Returns the first valid
    security rule dict found, or None if no valid rule block is present.

    Args:
        response_text: Full text output from the orchestrator.

    Returns:
        Parsed rule dict if a valid block was found, otherwise None.
    """
    for raw in extract_yaml_blocks(response_text):
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            print(f"WARNING: Skipping unparseable YAML block: {exc}", file=sys.stderr)
            continue

        if is_security_rule(data):
            return data

    return None


def extract_placement(rule: dict[str, Any]) -> tuple[str, str]:
    """Extract (folder, position) from a rule dict, falling back to defaults.

    ADR-0007 states that ``folder`` and ``position`` must NOT appear in
    committed rule YAML files — they are derived from the directory path.
    Claude's response may include them as placement hints.  They are stripped
    before the file is written (see ``strip_placement_fields``).

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
        # sort_keys=False preserves the field order from the original response,
        # which improves readability of the generated PR diff.
        yaml.dump(clean_rule, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return file_path


def format_list(values: Any) -> str:  # noqa: ANN401 — YAML list fields can be Any
    """Format a YAML list field as a comma-separated string.

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


# ---------------------------------------------------------------------------
# Orchestrator invocation
# ---------------------------------------------------------------------------

def invoke_orchestrator(
    issue_body: str,
    attachment_paths: list[str],
    anthropic_api_key: str,
) -> tuple[str | None, str | None]:
    """Run the client-side MCP agentic orchestrator and return (response, error).

    The orchestrator connects to both MCP servers as stdio subprocesses,
    calls Claude with the full agentic tool-use loop, and writes the final
    text response to stdout.

    Returns (response_text, None) on success or (None, error_message) on failure.
    """
    cmd = [sys.executable, str(PROCESS_ISSUE_SCRIPT), "--issue-body", issue_body]
    for path in attachment_paths:
        cmd.extend(["--attachment", path])

    env = {**os.environ, "ANTHROPIC_API_KEY": anthropic_api_key}

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,  # 5-minute timeout for the full agentic loop
        )
    except subprocess.TimeoutExpired:
        return None, "Analysis timed out after 300 seconds."
    except OSError as exc:
        return None, f"Failed to launch orchestrator: {exc}"

    if result.returncode != 0:
        # Log stderr for debugging; do not expose it in the issue comment
        print(
            f"Orchestrator exited with code {result.returncode}. stderr:\n{result.stderr}",
            file=sys.stderr,
        )
        return None, f"Analysis script exited with code {result.returncode}."

    text = result.stdout.strip()
    if not text:
        return None, "The orchestrator produced no output."

    return text, None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point — orchestrates the full request processing pipeline."""
    github_token = get_required_env("GITHUB_TOKEN")
    anthropic_api_key = get_required_env("ANTHROPIC_API_KEY")
    issue_number = int(get_required_env("ISSUE_NUMBER"))
    issue_body = os.environ.get("ISSUE_BODY", "")
    repo = get_required_env("REPO")
    output_dir = Path(os.environ.get("OUTPUT_DIR", tempfile.mkdtemp()))

    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Parse PDF attachments ---
    attachments = parse_pdf_attachments(issue_body)
    print(f"Found {len(attachments)} PDF attachment(s) in issue body.")

    download_warnings: list[str] = []
    size_warnings: list[str] = []
    attachment_paths: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        for filename, url in attachments:
            local_path = download_pdf(filename, url, github_token, tmp_dir)
            if local_path is None:
                download_warnings.append(filename)
                continue

            if not is_pdf_within_size_limit(local_path):
                size_warnings.append(filename)
                continue

            attachment_paths.append(local_path)

        print(
            f"Downloaded {len(attachment_paths)} PDF(s) for analysis. "
            f"Download failures: {len(download_warnings)}, "
            f"Size exceeded: {len(size_warnings)}."
        )

        # --- Invoke the client-side MCP orchestrator ---
        claude_response, claude_error = invoke_orchestrator(
            issue_body=issue_body,
            attachment_paths=attachment_paths,
            anthropic_api_key=anthropic_api_key,
        )

    # --- Compose and post issue comment ---
    comment_parts: list[str] = []

    if claude_error:
        comment_parts.append(
            "## FirePilot Analysis — Error\n\n"
            f"The automated analysis could not be completed.\n\n"
            f"**Error**: {claude_error}\n\n"
            "Please contact the FirePilot administrator. No configuration has been generated."
        )
        try:
            add_label(repo, issue_number, "firepilot:failed", github_token)
        except requests.RequestException as label_exc:
            print(f"WARNING: Failed to add 'firepilot:failed' label: {label_exc}", file=sys.stderr)

    elif not claude_response:
        comment_parts.append(
            "## FirePilot Analysis — Incomplete\n\n"
            "The analysis could not be completed: the orchestrator returned an empty response.\n\n"
            "Please contact the FirePilot administrator."
        )
    else:
        comment_parts.append(f"## FirePilot Analysis\n\n{claude_response}")

    # Append attachment warnings
    if download_warnings:
        filenames = ", ".join(f"`{f}`" for f in download_warnings)
        comment_parts.append(
            f"\n\n---\n"
            f"**Warning**: The following attachment(s) could not be downloaded and were "
            f"excluded from the analysis: {filenames}. "
            f"Please verify the files are accessible and re-open a new request if needed."
        )

    if size_warnings:
        filenames = ", ".join(f"`{f}`" for f in size_warnings)
        comment_parts.append(
            f"\n\n---\n"
            f"**Warning**: The following attachment(s) exceed the 32 MB size limit and were "
            f"excluded from the analysis: {filenames}."
        )

    comment_body = "".join(comment_parts)

    try:
        post_issue_comment(repo, issue_number, comment_body, github_token)
        print("Successfully posted analysis comment to issue.")
    except requests.RequestException as exc:
        print(f"ERROR: Failed to post issue comment: {exc}", file=sys.stderr)
        sys.exit(1)

    # --- If Claude produced a rejection or error, signal no proposal ---
    if not claude_response:
        write_github_output("proposal_valid", "false")
        return

    # --- Attempt to extract a valid YAML rule from Claude's response ---
    rule = extract_rule_from_response(claude_response)

    if rule is None:
        # Claude rejected the request or did not produce a YAML block.
        # The analysis comment has already been posted above.
        print("No valid YAML security rule block found in orchestrator response.")
        write_github_output("proposal_valid", "false")

        # Apply the rejected label so the issue is visibly closed out.
        try:
            add_label(repo, issue_number, "firepilot:rejected", github_token)
        except requests.RequestException as label_exc:
            print(f"WARNING: Failed to add 'firepilot:rejected' label: {label_exc}", file=sys.stderr)
        return

    rule_name: str = rule.get("name", "")
    if not rule_name:
        print(
            "WARNING: Extracted YAML block is missing required field 'name'. "
            "Treating as rejection.",
            file=sys.stderr,
        )
        write_github_output("proposal_valid", "false")
        return

    folder, position = extract_placement(rule)
    print(f"Extracted rule: name='{rule_name}', folder='{folder}', position='{position}'")

    try:
        yaml_file = write_rule_file(rule, output_dir)
    except (KeyError, OSError) as exc:
        print(f"ERROR: Failed to write rule YAML file: {exc}", file=sys.stderr)
        write_github_output("proposal_valid", "false")
        sys.exit(1)

    print(f"Rule file written to: {yaml_file}")

    # Write all metadata to GitHub Actions outputs for downstream steps.
    write_github_output("proposal_valid", "true")
    write_github_output("rule_name", rule_name)
    write_github_output("folder", folder)
    write_github_output("position", position)
    write_github_output("yaml_file_path", str(yaml_file))
    write_github_output("from_zones", format_list(rule.get("from", [])))
    write_github_output("to_zones", format_list(rule.get("to", [])))
    write_github_output("action", str(rule.get("action", "")))
    write_github_output("services", format_list(rule.get("service", [])))


if __name__ == "__main__":
    main()
