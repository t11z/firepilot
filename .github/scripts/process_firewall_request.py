"""FirePilot — GitHub Actions script for processing firewall change requests.

Reads a GitHub Issue body, downloads any PDF attachments, invokes the
client-side MCP agentic orchestrator (`ci/scripts/process-issue.py`) as a
subprocess, and posts its output as an issue comment.

Claude writes YAML configuration files directly via the write_config_file MCP
tool during its agentic loop (ADR-0015). This script detects those files by
scanning OUTPUT_DIR for .yaml files — presence indicates a valid proposal,
absence indicates rejection. No regex or Markdown parsing is used.

The orchestrator connects to mcp-strata-cloud-manager and mcp-itsm as local
stdio subprocesses and runs the full Claude agentic tool-use loop in-process.

Required environment variables:
    GITHUB_TOKEN       — GitHub Actions token for issue operations and attachment downloads
    ANTHROPIC_API_KEY  — Claude API authentication key
    ISSUE_NUMBER       — GitHub issue number (integer as string)
    ISSUE_BODY         — Full body text of the GitHub issue
    REPO               — Repository in "owner/repo" format
    OUTPUT_DIR         — Directory path where Claude writes YAML files via write_config_file
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

# Default placement used when no _rulebase.yaml provides folder/position.
# Matches the existing fixture structure in firewall-configs/shared/pre/.
# Per ADR-0007, folder and position are derived from directory structure at
# deploy time — they are NOT stored inside committed rule files.
DEFAULT_FOLDER = "shared"
DEFAULT_POSITION = "pre"


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
# Output directory scanning (ADR-0015)
# ---------------------------------------------------------------------------

def scan_output_directory(output_dir: Path) -> list[Path]:
    """Return all .yaml files in the output directory, sorted by name.

    Files are written by Claude via the write_config_file MCP tool during the
    agentic loop. Their presence indicates a valid proposal; their absence
    indicates rejection.

    Args:
        output_dir: Path to the directory written by the write_config_file tool.

    Returns:
        Sorted list of .yaml file paths. Empty list if none exist.
    """
    return sorted(output_dir.glob("*.yaml"))


def extract_metadata_from_files(
    config_files: list[Path],
) -> dict[str, Any]:
    """Parse metadata from generated config files for workflow outputs.

    Reads the _rulebase.yaml manifest (if present) for folder and position.
    Reads the first security rule file found to extract rule_name, from_zones,
    to_zones, action, and services. If multiple rule files exist, aggregates
    zone and service information.

    Returns a dict with keys matching the existing GitHub Actions output
    contract: rule_name, folder, position, from_zones, to_zones, action,
    services.

    Args:
        config_files: Non-empty list of .yaml paths from scan_output_directory.

    Returns:
        Dict of metadata values. Falls back to defaults for missing fields.
    """
    folder = DEFAULT_FOLDER
    position = DEFAULT_POSITION
    rule_name = ""
    from_zones: list[str] = []
    to_zones: list[str] = []
    action = ""
    services: list[str] = []

    manifest_file = next(
        (p for p in config_files if p.name == "_rulebase.yaml"),
        None,
    )
    if manifest_file is not None:
        try:
            manifest_data = yaml.safe_load(manifest_file.read_text(encoding="utf-8"))
            if isinstance(manifest_data, dict):
                folder = str(manifest_data.get("folder", DEFAULT_FOLDER)) or DEFAULT_FOLDER
                position = str(manifest_data.get("position", DEFAULT_POSITION)) or DEFAULT_POSITION
                rule_order = manifest_data.get("rule_order", [])
                if isinstance(rule_order, list) and rule_order:
                    rule_name = str(rule_order[0])
        except (yaml.YAMLError, OSError) as exc:
            print(f"WARNING: Could not parse _rulebase.yaml: {exc}", file=sys.stderr)

    # Parse rule files to extract zone/action/service metadata.
    rule_files = [p for p in config_files if p.name != "_rulebase.yaml"]
    for rule_file in rule_files:
        try:
            rule_data = yaml.safe_load(rule_file.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            print(f"WARNING: Could not parse '{rule_file.name}': {exc}", file=sys.stderr)
            continue

        if not isinstance(rule_data, dict):
            continue

        # Use the first rule file's name as rule_name if manifest didn't set one.
        if not rule_name:
            rule_name = str(rule_data.get("name", rule_file.stem))

        # Aggregate zone and service lists across all rule files.
        raw_from = rule_data.get("from", [])
        if isinstance(raw_from, list):
            from_zones.extend(str(z) for z in raw_from if str(z) not in from_zones)

        raw_to = rule_data.get("to", [])
        if isinstance(raw_to, list):
            to_zones.extend(str(z) for z in raw_to if str(z) not in to_zones)

        if not action:
            action = str(rule_data.get("action", ""))

        raw_service = rule_data.get("service", [])
        if isinstance(raw_service, list):
            services.extend(str(s) for s in raw_service if str(s) not in services)

    return {
        "rule_name": rule_name,
        "folder": folder,
        "position": position,
        "from_zones": ", ".join(from_zones),
        "to_zones": ", ".join(to_zones),
        "action": action,
        "services": ", ".join(services),
    }


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

    # --- If Claude produced an error, signal no proposal ---
    if not claude_response:
        write_github_output("proposal_valid", "false")
        return

    # --- Check for configuration files written by Claude ---
    config_files = scan_output_directory(output_dir)

    if not config_files:
        # Claude did not produce any configuration files.
        # This means rejection (unprocessable request per ADR-0014).
        print("No configuration files found in output directory.")
        write_github_output("proposal_valid", "false")

        try:
            add_label(repo, issue_number, "firepilot:rejected", github_token)
        except requests.RequestException as label_exc:
            print(
                f"WARNING: Failed to add 'firepilot:rejected' label: {label_exc}",
                file=sys.stderr,
            )
        return

    # Files exist — extract metadata for downstream workflow steps.
    metadata = extract_metadata_from_files(config_files)

    write_github_output("proposal_valid", "true")
    write_github_output("rule_name", metadata["rule_name"])
    write_github_output("folder", metadata["folder"])
    write_github_output("position", metadata["position"])
    write_github_output("from_zones", metadata.get("from_zones", ""))
    write_github_output("to_zones", metadata.get("to_zones", ""))
    write_github_output("action", metadata.get("action", ""))
    write_github_output("services", metadata.get("services", ""))


if __name__ == "__main__":
    main()
