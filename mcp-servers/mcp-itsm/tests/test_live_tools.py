"""Integration tests for all four change request tools in live mode.

Verifies that each tool delegates to GitHubClient in live mode and that
demo mode continues to return fixture data (regression guard).

No network access is required. GitHubClient is mocked at the module level
in mcp_itsm.tools.change_requests by patching get_github_client and
get_settings.

The demo-mode regression tests reuse the session-scoped server from
conftest.py, which is initialised with FIREPILOT_ENV=demo.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.fastmcp import FastMCP

from mcp_itsm.github_client import GITHUB_API_ERROR_CODE, GitHubAPIError, GitHubClient
from tests.conftest import call_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_live_settings() -> MagicMock:
    """Return a mock Settings object configured for live mode."""
    s = MagicMock()
    s.firepilot_env = "live"
    s.itsm_github_token = "ghp_test"
    s.itsm_github_repo = "test-org/test-repo"
    return s


def _make_mock_client() -> MagicMock:
    """Return a MagicMock GitHubClient with all methods stubbed as AsyncMocks."""
    client = MagicMock(spec=GitHubClient)

    client.create_issue = AsyncMock(
        return_value={
            "number": 101,
            "html_url": "https://github.com/test-org/test-repo/issues/101",
            "created_at": "2026-03-20T10:00:00Z",
            "title": "Test change",
            "state": "open",
            "labels": [{"name": "firepilot:pending", "color": "ededed"}],
            "body": "## Change Request\n\n**Requestor**: Test User\n**Config Reference**: abc123\n\n---\n\nTest description",
            "updated_at": "2026-03-20T10:00:00Z",
            "closed_at": None,
        }
    )

    client.get_issue = AsyncMock(
        return_value={
            "number": 101,
            "title": "Test change",
            "html_url": "https://github.com/test-org/test-repo/issues/101",
            "state": "open",
            "labels": [{"name": "firepilot:pending", "color": "ededed"}],
            "body": "## Change Request\n\n**Requestor**: Test User\n**Config Reference**: abc123\n\n---\n\nTest description",
            "created_at": "2026-03-20T10:00:00Z",
            "updated_at": "2026-03-20T10:00:00Z",
            "closed_at": None,
        }
    )

    client.add_comment = AsyncMock(
        return_value={
            "id": 5001,
            "html_url": "https://github.com/test-org/test-repo/issues/101#issuecomment-5001",
            "created_at": "2026-03-20T11:00:00Z",
            "body": "**FirePilot Event**: `rule_validated`",
        }
    )

    client.set_labels = AsyncMock(
        return_value=[{"name": "firepilot:deployed", "color": "0e8a16"}]
    )

    client.close_issue = AsyncMock(
        return_value={
            "number": 101,
            "state": "closed",
            "html_url": "https://github.com/test-org/test-repo/issues/101",
            "closed_at": "2026-03-20T12:00:00Z",
        }
    )

    return client


# ---------------------------------------------------------------------------
# create_change_request — live mode
# ---------------------------------------------------------------------------


class TestCreateChangeRequestLive:
    """create_change_request delegates to client.create_issue in live mode."""

    async def test_calls_client_create_issue(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool calls client.create_issue in live mode."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        await call_tool(
            server,
            "create_change_request",
            {
                "title": "Test change",
                "description": "Test description",
                "config_reference": "abc123",
                "requestor": "Test User",
            },
        )

        mock_client.create_issue.assert_awaited_once()

    async def test_passes_firepilot_pending_label(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """create_issue is called with firepilot:pending in labels."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        await call_tool(
            server,
            "create_change_request",
            {
                "title": "Test",
                "description": "Desc",
                "config_reference": "sha:abc",
                "requestor": "Ops",
            },
        )

        call_kwargs = mock_client.create_issue.call_args
        assert "firepilot:pending" in call_kwargs.kwargs["labels"]

    async def test_maps_response_to_output_contract(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool output maps GitHub response fields to ITSM contract fields."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(
            server,
            "create_change_request",
            {
                "title": "Test",
                "description": "Desc",
                "config_reference": "sha:abc",
                "requestor": "Ops",
            },
        )

        assert "error" not in result
        assert result["change_request_id"] == "101"
        assert result["url"] == "https://github.com/test-org/test-repo/issues/101"
        assert result["status"] == "pending"
        assert result["created_at"] == "2026-03-20T10:00:00Z"

    async def test_github_api_error_returns_error_dict(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GitHubAPIError from client is mapped to a structured error response."""
        mock_client = _make_mock_client()
        mock_client.create_issue = AsyncMock(
            side_effect=GitHubAPIError(
                "GitHub API returned HTTP 422",
                http_status=422,
                github_request_id="req-422",
            )
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(
            server,
            "create_change_request",
            {
                "title": "Test",
                "description": "Desc",
                "config_reference": "sha:abc",
                "requestor": "Ops",
            },
        )

        assert "error" in result
        assert result["error"]["code"] == GITHUB_API_ERROR_CODE


# ---------------------------------------------------------------------------
# get_change_request — live mode
# ---------------------------------------------------------------------------


class TestGetChangeRequestLive:
    """get_change_request delegates to client.get_issue in live mode."""

    async def test_calls_client_get_issue(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool calls client.get_issue with the correct issue number."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        await call_tool(server, "get_change_request", {"change_request_id": "101"})

        mock_client.get_issue.assert_awaited_once_with(101)

    async def test_derives_status_from_firepilot_label(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Status is derived from the firepilot:* label on the issue."""
        mock_client = _make_mock_client()
        mock_client.get_issue = AsyncMock(
            return_value={
                "number": 101,
                "title": "Test",
                "html_url": "https://github.com/test-org/test-repo/issues/101",
                "state": "closed",
                "labels": [{"name": "firepilot:deployed", "color": "0e8a16"}],
                "body": "## Change Request\n\n**Requestor**: Ops\n**Config Reference**: abc\n\n---\n\nDesc",
                "created_at": "2026-03-20T10:00:00Z",
                "updated_at": "2026-03-20T12:00:00Z",
                "closed_at": "2026-03-20T12:00:00Z",
            }
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(server, "get_change_request", {"change_request_id": "101"})

        assert result["status"] == "deployed"

    async def test_defaults_status_to_pending_when_no_firepilot_label(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Status defaults to 'pending' when no firepilot:* label is present."""
        mock_client = _make_mock_client()
        mock_client.get_issue = AsyncMock(
            return_value={
                "number": 101,
                "title": "Test",
                "html_url": "https://github.com/test-org/test-repo/issues/101",
                "state": "open",
                "labels": [{"name": "priority:high", "color": "ee0701"}],
                "body": None,
                "created_at": "2026-03-20T10:00:00Z",
                "updated_at": "2026-03-20T10:00:00Z",
                "closed_at": None,
            }
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(server, "get_change_request", {"change_request_id": "101"})

        assert result["status"] == "pending"

    async def test_404_returns_change_request_not_found_error(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """404 from GitHubClient maps to CHANGE_REQUEST_NOT_FOUND error code."""
        mock_client = _make_mock_client()
        mock_client.get_issue = AsyncMock(
            side_effect=GitHubAPIError(
                "GitHub API returned HTTP 404",
                http_status=404,
                github_request_id="req-404",
            )
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(server, "get_change_request", {"change_request_id": "9999"})

        assert "error" in result
        assert result["error"]["code"] == "CHANGE_REQUEST_NOT_FOUND"
        assert "9999" in result["error"]["message"]

    async def test_non_404_api_error_returns_github_api_error(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-404 GitHubAPIError returns GITHUB_API_ERROR code."""
        mock_client = _make_mock_client()
        mock_client.get_issue = AsyncMock(
            side_effect=GitHubAPIError(
                "GitHub API returned HTTP 500",
                http_status=500,
                github_request_id="req-500",
            )
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(server, "get_change_request", {"change_request_id": "101"})

        assert "error" in result
        assert result["error"]["code"] == GITHUB_API_ERROR_CODE


# ---------------------------------------------------------------------------
# add_audit_comment — live mode
# ---------------------------------------------------------------------------


class TestAddAuditCommentLive:
    """add_audit_comment delegates to client.add_comment in live mode."""

    async def test_calls_client_add_comment(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool calls client.add_comment with the correct issue number."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        await call_tool(
            server,
            "add_audit_comment",
            {
                "change_request_id": "101",
                "event": "rule_validated",
                "detail": "OPA policy validation passed",
            },
        )

        mock_client.add_comment.assert_awaited_once()
        call_args = mock_client.add_comment.call_args
        assert call_args.args[0] == 101

    async def test_comment_body_contains_event_and_detail(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Formatted comment body includes the event name and detail text."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        await call_tool(
            server,
            "add_audit_comment",
            {
                "change_request_id": "101",
                "event": "push_succeeded",
                "detail": "Deployed to prod successfully",
                "scm_reference": "job-uuid-xyz",
            },
        )

        call_args = mock_client.add_comment.call_args
        body = call_args.kwargs["body"]
        assert "push_succeeded" in body
        assert "Deployed to prod successfully" in body
        assert "job-uuid-xyz" in body

    async def test_maps_response_to_output_contract(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool output maps GitHub comment response to ITSM contract fields."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(
            server,
            "add_audit_comment",
            {
                "change_request_id": "101",
                "event": "rule_validated",
                "detail": "Passed",
            },
        )

        assert "error" not in result
        assert result["comment_id"] == "5001"
        assert "url" in result
        assert "created_at" in result

    async def test_invalid_event_rejected_before_client_call(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid event is rejected with INVALID_EVENT before any client call."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(
            server,
            "add_audit_comment",
            {
                "change_request_id": "101",
                "event": "invalid_event_xyz",
                "detail": "Should be rejected",
            },
        )

        assert "error" in result
        assert result["error"]["code"] == "INVALID_EVENT"
        mock_client.add_comment.assert_not_awaited()

    async def test_github_api_error_returns_error_dict(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GitHubAPIError from client maps to a structured error response."""
        mock_client = _make_mock_client()
        mock_client.add_comment = AsyncMock(
            side_effect=GitHubAPIError(
                "GitHub API returned HTTP 500",
                http_status=500,
                github_request_id="req-500",
            )
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(
            server,
            "add_audit_comment",
            {
                "change_request_id": "101",
                "event": "rule_validated",
                "detail": "Passed",
            },
        )

        assert "error" in result
        assert result["error"]["code"] == GITHUB_API_ERROR_CODE


# ---------------------------------------------------------------------------
# update_change_request_status — live mode
# ---------------------------------------------------------------------------


class TestUpdateChangeRequestStatusLive:
    """update_change_request_status delegates to client methods in live mode."""

    async def test_calls_get_issue_then_set_labels(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool fetches current labels before setting new ones."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        await call_tool(
            server,
            "update_change_request_status",
            {"change_request_id": "101", "status": "deployed"},
        )

        mock_client.get_issue.assert_awaited_once_with(101)
        mock_client.set_labels.assert_awaited_once()

    async def test_replaces_firepilot_labels_with_new_status(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Old firepilot:* label is removed; new firepilot:{status} is added."""
        mock_client = _make_mock_client()
        mock_client.get_issue = AsyncMock(
            return_value={
                "number": 101,
                "title": "Test",
                "html_url": "https://github.com/test-org/test-repo/issues/101",
                "state": "open",
                "labels": [
                    {"name": "firepilot:pending", "color": "ededed"},
                    {"name": "priority:high", "color": "ee0701"},
                ],
                "body": None,
                "created_at": "2026-03-20T10:00:00Z",
                "updated_at": "2026-03-20T10:00:00Z",
                "closed_at": None,
            }
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        await call_tool(
            server,
            "update_change_request_status",
            {"change_request_id": "101", "status": "deployed"},
        )

        labels_set = mock_client.set_labels.call_args.args[1]
        assert "firepilot:deployed" in labels_set
        assert "firepilot:pending" not in labels_set
        assert "priority:high" in labels_set

    async def test_close_issue_true_calls_close_issue(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """close_issue=True triggers client.close_issue call."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(
            server,
            "update_change_request_status",
            {"change_request_id": "101", "status": "deployed", "close_issue": True},
        )

        mock_client.close_issue.assert_awaited_once_with(101)
        assert result["closed"] is True

    async def test_close_issue_false_skips_close(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """close_issue=False skips the client.close_issue call."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(
            server,
            "update_change_request_status",
            {"change_request_id": "101", "status": "failed", "close_issue": False},
        )

        mock_client.close_issue.assert_not_awaited()
        assert result["closed"] is False

    async def test_invalid_status_rejected_before_client_call(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid status is rejected before any client interaction."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(
            server,
            "update_change_request_status",
            {"change_request_id": "101", "status": "approved"},
        )

        assert "error" in result
        assert result["error"]["code"] == "INVALID_STATUS_TRANSITION"
        mock_client.get_issue.assert_not_awaited()

    async def test_404_returns_change_request_not_found(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """404 from get_issue maps to CHANGE_REQUEST_NOT_FOUND error code."""
        mock_client = _make_mock_client()
        mock_client.get_issue = AsyncMock(
            side_effect=GitHubAPIError(
                "GitHub API returned HTTP 404",
                http_status=404,
                github_request_id="req-404",
            )
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_itsm.tools.change_requests.get_github_client",
            lambda: mock_client,
        )

        result = await call_tool(
            server,
            "update_change_request_status",
            {"change_request_id": "9999", "status": "deployed"},
        )

        assert "error" in result
        assert result["error"]["code"] == "CHANGE_REQUEST_NOT_FOUND"


# ---------------------------------------------------------------------------
# Demo mode regression — all existing behaviour is preserved
# ---------------------------------------------------------------------------


class TestDemoModeRegression:
    """Demo mode continues to return fixture data after live-mode additions."""

    async def test_create_returns_pending_status(self, server: FastMCP) -> None:
        """Demo mode create_change_request returns status 'pending'."""
        result = await call_tool(
            server,
            "create_change_request",
            {
                "title": "Regression check",
                "description": "Demo mode should still work",
                "config_reference": "sha:regression",
                "requestor": "Test Suite",
            },
        )
        assert "error" not in result
        assert result["status"] == "pending"
        assert isinstance(result["change_request_id"], str)

    async def test_get_pre_seeded_fixture(self, server: FastMCP) -> None:
        """Demo mode returns the pre-seeded change request '42'."""
        result = await call_tool(
            server, "get_change_request", {"change_request_id": "42"}
        )
        assert "error" not in result
        assert result["change_request_id"] == "42"
        assert result["status"] == "pending"

    async def test_get_not_found_returns_error(self, server: FastMCP) -> None:
        """Demo mode returns CHANGE_REQUEST_NOT_FOUND for unknown IDs."""
        result = await call_tool(
            server, "get_change_request", {"change_request_id": "9999"}
        )
        assert "error" in result
        assert result["error"]["code"] == "CHANGE_REQUEST_NOT_FOUND"

    async def test_add_comment_on_existing_request(self, server: FastMCP) -> None:
        """Demo mode add_audit_comment succeeds on the pre-seeded request."""
        result = await call_tool(
            server,
            "add_audit_comment",
            {
                "change_request_id": "42",
                "event": "rule_validated",
                "detail": "Validation passed",
            },
        )
        assert "error" not in result
        assert "comment_id" in result

    async def test_update_status_deployed(self, server: FastMCP) -> None:
        """Demo mode update_change_request_status to deployed returns closed=True."""
        result = await call_tool(
            server,
            "update_change_request_status",
            {"change_request_id": "42", "status": "deployed"},
        )
        assert "error" not in result
        assert result["status"] == "deployed"
        assert result["closed"] is True

    async def test_invalid_status_rejected_in_demo(self, server: FastMCP) -> None:
        """Demo mode rejects invalid status transitions."""
        result = await call_tool(
            server,
            "update_change_request_status",
            {"change_request_id": "42", "status": "approved"},
        )
        assert "error" in result
        assert result["error"]["code"] == "INVALID_STATUS_TRANSITION"
