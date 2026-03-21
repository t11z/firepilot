"""FirePilot — client-side MCP agentic loop for firewall change request analysis.

Connects to mcp-strata-cloud-manager and mcp-itsm as local stdio subprocesses,
fetches their tool definitions, and runs a full agentic Claude API tool-use loop
in-process. The final text response is written to stdout for the caller to post
as a GitHub issue comment.

Usage:
    python ci/scripts/process-issue.py \\
        --issue-body "$(cat issue.txt)" \\
        --attachment /tmp/network-diagram.pdf \\
        --attachment /tmp/policy.pdf

Required environment variables:
    ANTHROPIC_API_KEY  — Claude API authentication key

Optional environment variables:
    FIREPILOT_ENV      — "demo" (default) or "live"

Exit codes:
    0  — analysis completed, response written to stdout
    1  — unrecoverable error (details on stderr)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path

import anthropic
from mcp import ClientSession
from mcp.types import CallToolResult, TextContent

# Allow importing mcp_connect from the same directory
sys.path.insert(0, str(Path(__file__).parent))
from mcp_connect import connect_mcp_server  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 4096
MAX_AGENTIC_ITERATIONS = 20
MAX_PDF_BYTES = 32 * 1024 * 1024  # 32 MB — Claude API document size limit

# Retry configuration for transient API errors (rate limits, 5xx)
RATE_LIMIT_RETRY_DELAYS = (60, 120, 240)  # seconds — 1 min, 2 min, 4 min

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "system-prompt.md"


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def encode_pdf(file_path: str) -> str | None:
    """Base64-encode a PDF file for the Claude API.

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


def build_pdf_document_blocks(attachment_paths: list[str]) -> list[dict]:
    """Encode each attachment as a Claude API document content block.

    Files that exceed MAX_PDF_BYTES are silently skipped (warning on stderr).
    """
    blocks: list[dict] = []
    for path in attachment_paths:
        encoded = encode_pdf(path)
        if encoded is not None:
            blocks.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": encoded,
                    },
                }
            )
    return blocks


# ---------------------------------------------------------------------------
# MCP helpers
# ---------------------------------------------------------------------------

def mcp_tools_to_claude_format(tools: list) -> list[dict]:
    """Convert MCP tool definitions to the Claude API tool format."""
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema,
        }
        for tool in tools
    ]


def call_tool_result_to_text(result: CallToolResult) -> str:
    """Extract plain text from a CallToolResult content list."""
    parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        else:
            # Fallback for non-text content blocks
            parts.append(str(block))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------

async def run_agentic_loop(
    client: anthropic.Anthropic,
    system_prompt: str,
    issue_body: str,
    pdf_blocks: list[dict],
    tool_defs: list[dict],
    tool_session_map: dict[str, ClientSession],
) -> str:
    """Run the Claude API agentic tool-use loop.

    Calls Claude, handles tool_use stop_reason by dispatching to the correct
    MCP session, then sends tool results back to Claude. Repeats until
    stop_reason is end_turn or MAX_AGENTIC_ITERATIONS is reached.

    Returns Claude's final text response.
    """
    # Build the initial user message content
    user_content: list[dict] = [*pdf_blocks, {"type": "text", "text": issue_body}]

    # Conversation history — built with explicit dicts to avoid extra fields
    # produced by model_dump() on Anthropic SDK response objects
    messages: list[dict] = [{"role": "user", "content": user_content}]

    for iteration in range(MAX_AGENTIC_ITERATIONS):
        kwargs: dict = {
            "model": CLAUDE_MODEL,
            "max_tokens": CLAUDE_MAX_TOKENS,
            "system": system_prompt,
            "messages": messages,
        }
        if tool_defs:
            kwargs["tools"] = tool_defs

        response = None
        for attempt, delay in enumerate([0, *RATE_LIMIT_RETRY_DELAYS]):
            if delay:
                print(
                    f"  Rate limit hit — waiting {delay}s before retry "
                    f"(attempt {attempt + 1}/{len(RATE_LIMIT_RETRY_DELAYS) + 1}).",
                    file=sys.stderr,
                )
                time.sleep(delay)
            try:
                response = client.messages.create(**kwargs)
                break  # success — exit retry loop
            except anthropic.AuthenticationError as exc:
                print(
                    f"ERROR: Anthropic API authentication failed — check ANTHROPIC_API_KEY. "
                    f"Details: {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)
            except anthropic.BadRequestError as exc:
                print(
                    f"ERROR: Anthropic API rejected the request (400). "
                    f"Details: {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)
            except anthropic.RateLimitError as exc:
                if attempt < len(RATE_LIMIT_RETRY_DELAYS):
                    print(
                        f"WARNING: Anthropic API rate limit exceeded. "
                        f"Details: {exc}",
                        file=sys.stderr,
                    )
                    continue
                print(
                    f"ERROR: Anthropic API rate limit exceeded after all retries. "
                    f"Details: {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)
            except anthropic.APIStatusError as exc:
                print(
                    f"ERROR: Anthropic API returned status {exc.status_code}. "
                    f"Details: {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)
            except anthropic.APIConnectionError as exc:
                print(
                    f"ERROR: Failed to connect to Anthropic API. "
                    f"Details: {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)

        if response is None:
            print("ERROR: No response received from Anthropic API.", file=sys.stderr)
            sys.exit(1)

        print(
            f"[iteration {iteration + 1}] stop_reason={response.stop_reason} "
            f"content_blocks={len(response.content)}",
            file=sys.stderr,
        )

        if response.stop_reason == "end_turn":
            # Collect all text blocks from the final response
            texts = [
                block.text
                for block in response.content
                if block.type == "text"
            ]
            return "\n".join(texts).strip()

        if response.stop_reason != "tool_use":
            # Unexpected stop — return whatever text we have
            texts = [
                block.text
                for block in response.content
                if block.type == "text"
            ]
            return "\n".join(texts).strip()

        # Append assistant turn — build dicts explicitly to avoid SDK extra fields
        assistant_content: list[dict] = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
        messages.append({"role": "assistant", "content": assistant_content})

        # Execute each tool_use block and collect results
        tool_result_content: list[dict] = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            session = tool_session_map.get(tool_name)

            if session is None:
                print(
                    f"WARNING: Tool '{tool_name}' not found in any MCP session. "
                    "Returning error result.",
                    file=sys.stderr,
                )
                tool_result_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "is_error": True,
                        "content": f"Tool '{tool_name}' is not available.",
                    }
                )
                continue

            print(
                f"  → calling tool '{tool_name}' with input {block.input}",
                file=sys.stderr,
            )
            try:
                call_result: CallToolResult = await session.call_tool(
                    tool_name, arguments=block.input
                )
                result_text = call_tool_result_to_text(call_result)
                tool_result_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "is_error": call_result.isError or False,
                        "content": result_text,
                    }
                )
                print(f"    ← result: {result_text[:120]!r}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 — catch any MCP transport error
                print(f"  ERROR calling tool '{tool_name}': {exc}", file=sys.stderr)
                tool_result_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "is_error": True,
                        "content": f"Tool call failed: {exc}",
                    }
                )

        messages.append({"role": "user", "content": tool_result_content})

    # Exceeded iteration limit — return best effort text
    print(
        f"WARNING: Reached maximum agentic iterations ({MAX_AGENTIC_ITERATIONS}). "
        "Returning partial response.",
        file=sys.stderr,
    )
    # Extract any text from the last assistant turn in history
    for msg in reversed(messages):
        if msg["role"] == "assistant":
            texts = [
                block["text"]
                for block in msg["content"]
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if texts:
                return "\n".join(texts).strip()
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def async_main(issue_body: str, attachment_paths: list[str]) -> str:
    """Orchestrate MCP server connections and the Claude agentic loop.

    Returns the final text response from Claude.
    """
    firepilot_env = os.environ.get("FIREPILOT_ENV", "demo")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    # Load system prompt
    if not SYSTEM_PROMPT_PATH.exists():
        print(
            f"ERROR: System prompt not found at '{SYSTEM_PROMPT_PATH}'.",
            file=sys.stderr,
        )
        sys.exit(1)
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    # Encode PDF attachments
    pdf_blocks = build_pdf_document_blocks(attachment_paths)
    print(
        f"Encoded {len(pdf_blocks)} of {len(attachment_paths)} PDF attachment(s).",
        file=sys.stderr,
    )

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    env_overrides = {"FIREPILOT_ENV": firepilot_env}

    async with AsyncExitStack() as stack:
        # Connect to both MCP servers; failures degrade gracefully
        strata_session = await connect_mcp_server(
            stack, "mcp_strata_cloud_manager.server", env_overrides
        )
        itsm_session = await connect_mcp_server(
            stack, "mcp_itsm.server", env_overrides
        )

        # Gather tool definitions and build a name → session dispatch map
        tool_defs: list[dict] = []
        tool_session_map: dict[str, ClientSession] = {}

        for session, label in [
            (strata_session, "mcp-strata-cloud-manager"),
            (itsm_session, "mcp-itsm"),
        ]:
            if session is None:
                print(f"WARNING: {label} is unavailable — its tools will be skipped.", file=sys.stderr)
                continue
            list_result = await session.list_tools()
            claude_tools = mcp_tools_to_claude_format(list_result.tools)
            tool_defs.extend(claude_tools)
            for tool in list_result.tools:
                tool_session_map[tool.name] = session
            print(
                f"Loaded {len(claude_tools)} tool(s) from {label}: "
                + ", ".join(t["name"] for t in claude_tools),
                file=sys.stderr,
            )

        print(
            f"Total tools available: {len(tool_defs)}. "
            f"Starting agentic loop (max {MAX_AGENTIC_ITERATIONS} iterations).",
            file=sys.stderr,
        )

        return await run_agentic_loop(
            client=client,
            system_prompt=system_prompt,
            issue_body=issue_body,
            pdf_blocks=pdf_blocks,
            tool_defs=tool_defs,
            tool_session_map=tool_session_map,
        )


def main() -> None:
    """Parse arguments and run the async orchestrator."""
    parser = argparse.ArgumentParser(
        description="Run Claude agentic loop with MCP tools for a firewall change request."
    )
    parser.add_argument(
        "--issue-body",
        required=True,
        help="Full body text of the GitHub issue.",
    )
    parser.add_argument(
        "--attachment",
        dest="attachments",
        action="append",
        default=[],
        metavar="PATH",
        help="Path to a downloaded PDF attachment (repeatable).",
    )
    args = parser.parse_args()

    result = asyncio.run(async_main(args.issue_body, args.attachments))
    print(result)


if __name__ == "__main__":
    main()
