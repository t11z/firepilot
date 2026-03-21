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


def _make_end_turn_response(text: str = "Analysis complete.") -> MagicMock:
    """Build a minimal mock Anthropic response with stop_reason=end_turn."""
    block = MagicMock()
    block.type = "text"
    block.text = text

    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
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
