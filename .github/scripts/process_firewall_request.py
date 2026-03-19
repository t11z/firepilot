"""FirePilot — GitHub Actions script for processing firewall change requests.

Reads a GitHub Issue body, downloads any PDF attachments, calls the Claude API
with the issue content and PDF documents, and posts Claude's response as an
issue comment.

When MCP_STRATA_URL and MCP_ITSM_URL are set, the Claude API call includes
an mcp_servers parameter so that Claude can call live validation tools
(list_security_zones, list_security_rules, etc.) against the running MCP
servers during analysis.

Required environment variables:
    GITHUB_TOKEN       — GitHub Actions token for issue operations and attachment downloads
    ANTHROPIC_API_KEY  — Claude API authentication key
    ISSUE_NUMBER       — GitHub issue number (integer as string)
    ISSUE_BODY         — Full body text of the GitHub issue
    REPO               — Repository in "owner/repo" format

Optional environment variables:
    MCP_STRATA_URL     — SSE endpoint URL for mcp-strata-cloud-manager
                         (e.g. http://localhost:8080/sse)
    MCP_ITSM_URL       — SSE endpoint URL for mcp-itsm
                         (e.g. http://localhost:8081/sse)
"""

from __future__ import annotations

import base64
import os
import re
import sys
import tempfile
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 4096
CLAUDE_ANTHROPIC_VERSION = "2023-06-01"
# Beta header required for the mcp_servers parameter in the Messages API.
CLAUDE_MCP_BETA = "mcp-client-2025-11-20"

# GitHub attachment URL pattern: [filename.pdf](https://github.com/user-attachments/assets/...)
PDF_ATTACHMENT_RE = re.compile(
    r'\[([^\]]+\.pdf)\]\((https://github\.com/user-attachments/assets/[^\)]+)\)',
    re.IGNORECASE,
)

MAX_PDF_BYTES = 32 * 1024 * 1024  # 32 MB — Claude API document size limit

GITHUB_API_BASE = "https://api.github.com"
SYSTEM_PROMPT_PATH = Path("prompts/system-prompt.md")


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

    GitHub renders uploaded files as Markdown links in the format:
        [filename.pdf](https://github.com/user-attachments/assets/...)
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


def encode_pdf(file_path: str) -> str | None:
    """Base64-encode a PDF file.

    Returns None and prints a warning if the file exceeds MAX_PDF_BYTES.
    """
    size = os.path.getsize(file_path)
    if size > MAX_PDF_BYTES:
        print(
            f"WARNING: Attachment '{os.path.basename(file_path)}' is {size} bytes "
            f"(limit {MAX_PDF_BYTES}). Skipping.",
            file=sys.stderr,
        )
        return None
    with open(file_path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


# ---------------------------------------------------------------------------
# Claude API
# ---------------------------------------------------------------------------

def build_user_content(issue_body: str, pdf_documents: list[dict]) -> list[dict]:
    """Construct the user message content blocks for the Claude API request."""
    content: list[dict] = []

    # Document blocks first (supporting PDFs), followed by the issue text
    for doc in pdf_documents:
        content.append(doc)

    content.append({"type": "text", "text": issue_body})
    return content


def call_claude_api(
    system_prompt: str,
    issue_body: str,
    pdf_documents: list[dict],
    anthropic_api_key: str,
    mcp_strata_url: str | None = None,
    mcp_itsm_url: str | None = None,
) -> str:
    """Call the Claude API and return the response text.

    When mcp_strata_url and mcp_itsm_url are provided, the request includes
    the mcp_servers parameter so Claude can call validation tools against the
    running MCP servers during analysis.

    Note: The Claude API mcp_servers parameter connects to the provided URLs
    from Anthropic's infrastructure. For GitHub Actions workflows, the MCP
    servers run on localhost and are referenced by their SSE endpoint URLs.

    Raises requests.RequestException on network or HTTP errors.
    """
    payload: dict = {
        "model": CLAUDE_MODEL,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "system": system_prompt,
        "messages": [
            {
                "role": "user",
                "content": build_user_content(issue_body, pdf_documents),
            }
        ],
    }

    headers: dict = {
        "x-api-key": anthropic_api_key,
        "anthropic-version": CLAUDE_ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    if mcp_strata_url and mcp_itsm_url:
        # Attach both MCP servers so Claude can call validation tools
        # (list_security_zones, list_security_rules, list_addresses, etc.)
        # during the analysis turn.  The mcp_servers parameter requires the
        # mcp-client beta header.
        payload["mcp_servers"] = [
            {
                "type": "url",
                "url": mcp_strata_url,
                "name": "mcp-strata-cloud-manager",
            },
            {
                "type": "url",
                "url": mcp_itsm_url,
                "name": "mcp-itsm",
            },
        ]
        # mcp_toolset entries in tools tell the API which server each toolset
        # belongs to and whether all tools are enabled by default.
        payload["tools"] = [
            {
                "type": "mcp_toolset",
                "mcp_server_name": "mcp-strata-cloud-manager",
                "default_config": {"enabled": True},
            },
            {
                "type": "mcp_toolset",
                "mcp_server_name": "mcp-itsm",
                "default_config": {"enabled": True},
            },
        ]
        headers["anthropic-beta"] = CLAUDE_MCP_BETA
        print(
            f"MCP servers attached: strata={mcp_strata_url}, itsm={mcp_itsm_url}",
            flush=True,
        )
    else:
        print("MCP servers not configured — running in analysis-only mode.", flush=True)

    response = requests.post(
        CLAUDE_API_URL,
        json=payload,
        headers=headers,
        timeout=180,  # Extended timeout to allow for MCP tool call round-trips
    )

    if not response.ok:
        # Do not log the response body — it may contain sensitive information
        raise requests.HTTPError(
            f"Claude API returned HTTP {response.status_code}",
            response=response,
        )

    data = response.json()
    texts = [
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ]
    return "\n".join(texts).strip()


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

    # MCP server URLs are optional — set by the workflow when servers are running
    mcp_strata_url = os.environ.get("MCP_STRATA_URL") or None
    mcp_itsm_url = os.environ.get("MCP_ITSM_URL") or None

    # Load system prompt from the versioned file in the repository
    if not SYSTEM_PROMPT_PATH.exists():
        print(
            f"ERROR: System prompt not found at '{SYSTEM_PROMPT_PATH}'.",
            file=sys.stderr,
        )
        sys.exit(1)
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    # --- Parse PDF attachments ---
    attachments = parse_pdf_attachments(issue_body)
    print(f"Found {len(attachments)} PDF attachment(s) in issue body.")

    pdf_documents: list[dict] = []
    download_warnings: list[str] = []
    size_warnings: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        for filename, url in attachments:
            local_path = download_pdf(filename, url, github_token, tmp_dir)
            if local_path is None:
                download_warnings.append(filename)
                continue

            encoded = encode_pdf(local_path)
            if encoded is None:
                size_warnings.append(filename)
                continue

            pdf_documents.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": encoded,
                },
            })

        print(
            f"Successfully encoded {len(pdf_documents)} PDF(s) for Claude API. "
            f"Download failures: {len(download_warnings)}, "
            f"Size exceeded: {len(size_warnings)}."
        )

        # --- Call Claude API ---
        claude_response: str | None = None
        claude_error: str | None = None

        try:
            claude_response = call_claude_api(
                system_prompt=system_prompt,
                issue_body=issue_body,
                pdf_documents=pdf_documents,
                anthropic_api_key=anthropic_api_key,
                mcp_strata_url=mcp_strata_url,
                mcp_itsm_url=mcp_itsm_url,
            )
        except requests.HTTPError as exc:
            # Extract only the status code — do not include response body
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            claude_error = f"Claude API call failed with HTTP status {status_code}."
        except requests.RequestException as exc:
            claude_error = f"Claude API call failed: {exc}"

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
            "The analysis could not be completed: the Claude API returned an empty response.\n\n"
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


if __name__ == "__main__":
    main()
