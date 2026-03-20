"""Tests for the change request lifecycle tools.

Covers create_change_request, get_change_request, and
update_change_request_status across the full lifecycle.
"""

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


@pytest.mark.asyncio
async def test_create_change_request(server: FastMCP) -> None:
    """Creating a new change request returns status 'pending' with a string ID."""
    result = await call_tool(
        server,
        "create_change_request",
        {
            "title": "Test change",
            "description": "Test description for zone change",
            "config_reference": "abc123",
            "requestor": "Test User",
        },
    )

    assert "error" not in result
    assert result["status"] == "pending"
    assert isinstance(result["change_request_id"], str)
    assert result["change_request_id"].isdigit()
    assert "url" in result
    assert "created_at" in result


@pytest.mark.asyncio
async def test_get_change_request_exists(server: FastMCP) -> None:
    """Getting the pre-seeded change request '42' returns status 'pending'."""
    result = await call_tool(
        server,
        "get_change_request",
        {"change_request_id": "42"},
    )

    assert "error" not in result
    assert result["change_request_id"] == "42"
    assert result["status"] == "pending"
    assert "firepilot:pending" in result["labels"]
    assert result["title"] == "Allow HTTPS from web-zone to app-zone for customer portal"
    assert result["closed_at"] is None


@pytest.mark.asyncio
async def test_get_change_request_not_found(server: FastMCP) -> None:
    """Getting a non-existent change request returns CHANGE_REQUEST_NOT_FOUND."""
    result = await call_tool(
        server,
        "get_change_request",
        {"change_request_id": "9999"},
    )

    assert "error" in result
    assert result["error"]["code"] == "CHANGE_REQUEST_NOT_FOUND"
    assert "9999" in result["error"]["message"]


@pytest.mark.asyncio
async def test_create_then_get(server: FastMCP) -> None:
    """Creating a request and then getting it returns matching data."""
    create_result = await call_tool(
        server,
        "create_change_request",
        {
            "title": "Deny telnet from untrust",
            "description": "Block telnet traffic ingress from untrust zone.",
            "config_reference": "pr/456",
            "requestor": "Security Team",
        },
    )
    assert "error" not in create_result

    cr_id = create_result["change_request_id"]
    get_result = await call_tool(
        server,
        "get_change_request",
        {"change_request_id": cr_id},
    )

    assert "error" not in get_result
    assert get_result["change_request_id"] == cr_id
    assert get_result["status"] == "pending"
    assert get_result["title"] == "Deny telnet from untrust"
    assert get_result["created_at"] == create_result["created_at"]


@pytest.mark.asyncio
async def test_update_status_deployed(server: FastMCP) -> None:
    """Updating a change request to 'deployed' sets status and closed=True."""
    create_result = await call_tool(
        server,
        "create_change_request",
        {
            "title": "Deploy rule set A",
            "description": "Activating the approved rule set.",
            "config_reference": "sha:deadbeef",
            "requestor": "Ops Team",
        },
    )
    cr_id = create_result["change_request_id"]

    update_result = await call_tool(
        server,
        "update_change_request_status",
        {"change_request_id": cr_id, "status": "deployed"},
    )

    assert "error" not in update_result
    assert update_result["change_request_id"] == cr_id
    assert update_result["status"] == "deployed"
    assert update_result["closed"] is True


@pytest.mark.asyncio
async def test_update_status_failed(server: FastMCP) -> None:
    """Updating a change request to 'failed' sets status and closed=True."""
    create_result = await call_tool(
        server,
        "create_change_request",
        {
            "title": "Deploy rule set B",
            "description": "Activating the approved rule set.",
            "config_reference": "sha:cafebabe",
            "requestor": "Ops Team",
        },
    )
    cr_id = create_result["change_request_id"]

    update_result = await call_tool(
        server,
        "update_change_request_status",
        {"change_request_id": cr_id, "status": "failed"},
    )

    assert "error" not in update_result
    assert update_result["status"] == "failed"
    assert update_result["closed"] is True


@pytest.mark.asyncio
async def test_update_status_invalid_transition_approved(server: FastMCP) -> None:
    """Attempting to set status 'approved' is rejected with INVALID_STATUS_TRANSITION."""
    create_result = await call_tool(
        server,
        "create_change_request",
        {
            "title": "Self-approval attempt",
            "description": "Attempting to bypass human review.",
            "config_reference": "sha:evil123",
            "requestor": "Rogue Agent",
        },
    )
    cr_id = create_result["change_request_id"]

    result = await call_tool(
        server,
        "update_change_request_status",
        {"change_request_id": cr_id, "status": "approved"},
    )

    assert "error" in result
    assert result["error"]["code"] == "INVALID_STATUS_TRANSITION"


@pytest.mark.asyncio
async def test_update_status_pending_rejected(server: FastMCP) -> None:
    """Attempting to set status 'pending' is rejected with INVALID_STATUS_TRANSITION."""
    result = await call_tool(
        server,
        "update_change_request_status",
        {"change_request_id": "42", "status": "pending"},
    )

    assert "error" in result
    assert result["error"]["code"] == "INVALID_STATUS_TRANSITION"


@pytest.mark.asyncio
async def test_full_lifecycle(server: FastMCP) -> None:
    """Full happy path: create → get (pending) → add comment → update deployed → get (deployed)."""
    # 1. Create a new change request
    create_result = await call_tool(
        server,
        "create_change_request",
        {
            "title": "Allow DNS from app-zone to dmz",
            "description": "Enable DNS resolution for app-zone hosts via DMZ resolver.",
            "config_reference": "pr/789",
            "requestor": "Network Engineering",
        },
    )
    assert "error" not in create_result
    cr_id = create_result["change_request_id"]
    assert create_result["status"] == "pending"

    # 2. Get the change request — should be pending
    get_result = await call_tool(
        server,
        "get_change_request",
        {"change_request_id": cr_id},
    )
    assert "error" not in get_result
    assert get_result["status"] == "pending"

    # 3. Add an audit comment
    comment_result = await call_tool(
        server,
        "add_audit_comment",
        {
            "change_request_id": cr_id,
            "event": "rule_validated",
            "detail": "OPA policy validation passed — 0 violations",
            "scm_reference": "rule-uuid-abc",
        },
    )
    assert "error" not in comment_result
    assert "comment_id" in comment_result
    assert "url" in comment_result

    # 4. Update status to deployed
    update_result = await call_tool(
        server,
        "update_change_request_status",
        {"change_request_id": cr_id, "status": "deployed"},
    )
    assert "error" not in update_result
    assert update_result["status"] == "deployed"
    assert update_result["closed"] is True

    # 5. Get again — should be deployed and closed
    final_result = await call_tool(
        server,
        "get_change_request",
        {"change_request_id": cr_id},
    )
    assert "error" not in final_result
    assert final_result["status"] == "deployed"
    assert final_result["closed_at"] is not None
