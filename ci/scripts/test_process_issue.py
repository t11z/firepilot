"""Tests for process-issue.py — Anthropic API error handling in the agentic loop.

Exercises run_agentic_loop for happy-path and Anthropic API error cases
introduced to handle BadRequestError (insufficient credits) and other SDK errors.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import anthropic
import pytest

sys.path.insert(0, str(Path(__file__).parent))

import process_issue as pi  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOOL_DEFS: list[dict] = []
_TOOL_SESSION_MAP: dict = {}


def _make_end_turn_response(
    text: str = "Analysis complete.",
    cache_read: int = 0,
    cache_write: int = 0,
) -> MagicMock:
    """Build a minimal mock Anthropic response with stop_reason=end_turn."""
    block = MagicMock()
    block.type = "text"
    block.text = text

    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    usage.cache_read_input_tokens = cache_read
    usage.cache_creation_input_tokens = cache_write

    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    response.usage = usage
    return response


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_agentic_loop_happy_path() -> None:
    """run_agentic_loop returns Claude's text when API call succeeds."""
    client = MagicMock(spec=anthropic.Anthropic)
    client.messages = MagicMock()
    client.messages.create = MagicMock(return_value=_make_end_turn_response("All good."))

    result = await pi.run_agentic_loop(
        client=client,
        system_prompt="You are a firewall assistant.",
        issue_body="Please review this request.",
        pdf_blocks=[],
        tool_defs=_TOOL_DEFS,
        tool_session_map=_TOOL_SESSION_MAP,
    )

    assert result == "All good."
    client.messages.create.assert_called_once()

    call_kwargs = client.messages.create.call_args.kwargs
    # system must be a list of content blocks with cache_control
    system = call_kwargs["system"]
    assert isinstance(system, list)
    assert len(system) == 1
    block = system[0]
    assert block["type"] == "text"
    assert block["text"] == "You are a firewall assistant."
    assert block["cache_control"] == {"type": "ephemeral"}
    # top-level cache_control must be present
    assert call_kwargs["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# Anthropic API error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bad_request_error_exits_with_code_1() -> None:
    """run_agentic_loop calls sys.exit(1) on anthropic.BadRequestError."""
    client = MagicMock(spec=anthropic.Anthropic)
    client.messages = MagicMock()

    error_body = {"type": "error", "error": {"type": "invalid_request_error",
                  "message": "Your credit balance is too low to access the Anthropic API."}}
    client.messages.create = MagicMock(
        side_effect=anthropic.BadRequestError(
            message="Your credit balance is too low to access the Anthropic API.",
            response=MagicMock(status_code=400, headers={}),
            body=error_body,
        )
    )

    with pytest.raises(SystemExit) as exc_info:
        await pi.run_agentic_loop(
            client=client,
            system_prompt="sys",
            issue_body="body",
            pdf_blocks=[],
            tool_defs=_TOOL_DEFS,
            tool_session_map=_TOOL_SESSION_MAP,
        )

    assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_authentication_error_exits_with_code_1() -> None:
    """run_agentic_loop calls sys.exit(1) on anthropic.AuthenticationError."""
    client = MagicMock(spec=anthropic.Anthropic)
    client.messages = MagicMock()
    client.messages.create = MagicMock(
        side_effect=anthropic.AuthenticationError(
            message="Invalid API key.",
            response=MagicMock(status_code=401, headers={}),
            body={"type": "error", "error": {"type": "authentication_error",
                  "message": "Invalid API key."}},
        )
    )

    with pytest.raises(SystemExit) as exc_info:
        await pi.run_agentic_loop(
            client=client,
            system_prompt="sys",
            issue_body="body",
            pdf_blocks=[],
            tool_defs=_TOOL_DEFS,
            tool_session_map=_TOOL_SESSION_MAP,
        )

    assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_rate_limit_error_exits_with_code_1() -> None:
    """run_agentic_loop calls sys.exit(1) on anthropic.RateLimitError."""
    client = MagicMock(spec=anthropic.Anthropic)
    client.messages = MagicMock()
    client.messages.create = MagicMock(
        side_effect=anthropic.RateLimitError(
            message="Rate limit exceeded.",
            response=MagicMock(status_code=429, headers={}),
            body={"type": "error", "error": {"type": "rate_limit_error",
                  "message": "Rate limit exceeded."}},
        )
    )

    with pytest.raises(SystemExit) as exc_info:
        await pi.run_agentic_loop(
            client=client,
            system_prompt="sys",
            issue_body="body",
            pdf_blocks=[],
            tool_defs=_TOOL_DEFS,
            tool_session_map=_TOOL_SESSION_MAP,
        )

    assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_api_status_error_exits_with_code_1() -> None:
    """run_agentic_loop calls sys.exit(1) on generic anthropic.APIStatusError."""
    client = MagicMock(spec=anthropic.Anthropic)
    client.messages = MagicMock()
    client.messages.create = MagicMock(
        side_effect=anthropic.InternalServerError(
            message="Internal server error.",
            response=MagicMock(status_code=500, headers={}),
            body={"type": "error", "error": {"type": "api_error",
                  "message": "Internal server error."}},
        )
    )

    with pytest.raises(SystemExit) as exc_info:
        await pi.run_agentic_loop(
            client=client,
            system_prompt="sys",
            issue_body="body",
            pdf_blocks=[],
            tool_defs=_TOOL_DEFS,
            tool_session_map=_TOOL_SESSION_MAP,
        )

    assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_api_connection_error_exits_with_code_1() -> None:
    """run_agentic_loop calls sys.exit(1) on anthropic.APIConnectionError."""
    client = MagicMock(spec=anthropic.Anthropic)
    client.messages = MagicMock()
    client.messages.create = MagicMock(
        side_effect=anthropic.APIConnectionError(request=MagicMock())
    )

    with pytest.raises(SystemExit) as exc_info:
        await pi.run_agentic_loop(
            client=client,
            system_prompt="sys",
            issue_body="body",
            pdf_blocks=[],
            tool_defs=_TOOL_DEFS,
            tool_session_map=_TOOL_SESSION_MAP,
        )

    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Prompt caching — new tests (ADR-0013)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_metrics_logged_to_stderr(capsys: pytest.CaptureFixture) -> None:
    """run_agentic_loop logs cache_read= and cache_write= fields on each iteration."""
    client = MagicMock(spec=anthropic.Anthropic)
    client.messages = MagicMock()
    client.messages.create = MagicMock(
        return_value=_make_end_turn_response("Done.", cache_read=1500, cache_write=3000)
    )

    await pi.run_agentic_loop(
        client=client,
        system_prompt="sys",
        issue_body="body",
        pdf_blocks=[],
        tool_defs=_TOOL_DEFS,
        tool_session_map=_TOOL_SESSION_MAP,
    )

    captured = capsys.readouterr()
    assert "cache_read=1500" in captured.err
    assert "cache_write=3000" in captured.err


@pytest.mark.asyncio
async def test_tool_cache_control_on_last_tool_only() -> None:
    """When tool_defs is non-empty, only the last tool has cache_control in kwargs."""
    tool_defs = [
        {"name": "tool_a", "description": "First tool", "input_schema": {}},
        {"name": "tool_b", "description": "Second tool", "input_schema": {}},
        {"name": "tool_c", "description": "Third tool", "input_schema": {}},
    ]

    client = MagicMock(spec=anthropic.Anthropic)
    client.messages = MagicMock()
    client.messages.create = MagicMock(return_value=_make_end_turn_response())

    await pi.run_agentic_loop(
        client=client,
        system_prompt="sys",
        issue_body="body",
        pdf_blocks=[],
        tool_defs=tool_defs,
        tool_session_map=_TOOL_SESSION_MAP,
    )

    call_kwargs = client.messages.create.call_args.kwargs
    tools = call_kwargs["tools"]
    assert len(tools) == 3
    # First two tools must NOT have cache_control
    assert "cache_control" not in tools[0]
    assert "cache_control" not in tools[1]
    # Last tool must have cache_control: ephemeral
    assert tools[2]["cache_control"] == {"type": "ephemeral"}
    # Original tool data preserved
    assert tools[2]["name"] == "tool_c"
