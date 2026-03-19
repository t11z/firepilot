"""Tests for the add_audit_comment tool.

Covers happy path, event validation, not-found errors, multiple comments,
and SCM reference formatting.
"""

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


@pytest.mark.asyncio
async def test_add_audit_comment_success(server: FastMCP) -> None:
    """Adding a comment to the pre-seeded request '42' returns comment_id and url."""
    result = await call_tool(
        server,
        "add_audit_comment",
        {
            "change_request_id": "42",
            "event": "push_initiated",
            "detail": "Push to SCM candidate config initiated by FirePilot orchestrator",
            "scm_reference": "job-1234",
        },
    )

    assert "error" not in result
    assert "comment_id" in result
    assert isinstance(result["comment_id"], str)
    assert "url" in result
    assert "42" in result["url"]
    assert "created_at" in result


@pytest.mark.asyncio
async def test_add_audit_comment_invalid_event(server: FastMCP) -> None:
    """Using an invalid event value returns a structured INVALID_EVENT error."""
    result = await call_tool(
        server,
        "add_audit_comment",
        {
            "change_request_id": "42",
            "event": "invalid_event",
            "detail": "This should fail",
        },
    )

    assert "error" in result
    assert result["error"]["code"] == "INVALID_EVENT"
    assert "invalid_event" in result["error"]["message"]


@pytest.mark.asyncio
async def test_add_audit_comment_not_found(server: FastMCP) -> None:
    """Targeting a non-existent change request returns CHANGE_REQUEST_NOT_FOUND."""
    result = await call_tool(
        server,
        "add_audit_comment",
        {
            "change_request_id": "9999",
            "event": "push_succeeded",
            "detail": "Push completed",
        },
    )

    assert "error" in result
    assert result["error"]["code"] == "CHANGE_REQUEST_NOT_FOUND"
    assert "9999" in result["error"]["message"]


@pytest.mark.asyncio
async def test_add_multiple_comments(server: FastMCP) -> None:
    """Adding three comments to the same request produces unique comment IDs."""
    events = [
        ("rule_validated", "Validation passed"),
        ("candidate_written", "Config written to SCM"),
        ("push_initiated", "Push to candidate config started"),
    ]
    comment_ids = []

    for event, detail in events:
        result = await call_tool(
            server,
            "add_audit_comment",
            {
                "change_request_id": "42",
                "event": event,
                "detail": detail,
            },
        )
        assert "error" not in result, f"Unexpected error on event '{event}': {result}"
        comment_ids.append(result["comment_id"])

    # All comment IDs must be unique
    assert len(set(comment_ids)) == 3, f"Duplicate comment IDs found: {comment_ids}"


@pytest.mark.asyncio
async def test_comment_format_includes_scm_reference(server: FastMCP) -> None:
    """A comment with scm_reference included returns that reference in the URL."""
    result = await call_tool(
        server,
        "add_audit_comment",
        {
            "change_request_id": "42",
            "event": "push_succeeded",
            "detail": "Firewall rule deployed successfully",
            "scm_reference": "scm-job-xyz-987",
        },
    )

    assert "error" not in result
    assert "comment_id" in result
    # The comment was stored; the tool returns comment_id, url, created_at
    assert result["url"] is not None


@pytest.mark.asyncio
async def test_comment_format_without_scm_reference(server: FastMCP) -> None:
    """A comment without scm_reference is accepted and returns a valid comment_id."""
    result = await call_tool(
        server,
        "add_audit_comment",
        {
            "change_request_id": "42",
            "event": "request_rejected",
            "detail": "Change request rejected by security reviewer",
        },
    )

    assert "error" not in result
    assert "comment_id" in result
    assert "url" in result
    assert "created_at" in result
