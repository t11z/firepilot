"""Integration tests for operations tools in live mode.

Verifies that push_candidate_config and get_job_status delegate to SCMClient
in live mode and that demo mode continues to return fixture data (regression guard).

No network access is required. SCMClient is mocked at the module level in
mcp_strata_cloud_manager.tools.operations by patching get_scm_client and
get_settings.

The demo-mode regression tests reuse the session-scoped server from conftest.py,
which is initialised with FIREPILOT_ENV=demo. Live-mode tests use monkeypatch to
replace get_settings with a live-mode mock inside each tool invocation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.fastmcp import FastMCP

from mcp_strata_cloud_manager.scm_client import (
    SCM_API_ERROR_CODE,
    SCM_AUTH_FAILURE_CODE,
    SCMAPIError,
    SCMAuthError,
    SCMClient,
    SCMResult,
)
from tests.conftest import call_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_live_settings() -> MagicMock:
    """Return a mock Settings object configured for live mode."""
    s = MagicMock()
    s.firepilot_env = "live"
    return s


def _make_scm_result(body: dict[str, Any], http_status: int = 201) -> SCMResult:
    """Wrap a response body in an SCMResult as the client would return."""
    return SCMResult(data=body, http_status=http_status, scm_request_id="req-ops-789")


_PUSH_RESPONSE: dict[str, Any] = {
    "id": "job-live-001",
    "job_status": "FIN",
    "job_result": "OK",
    "percent": 100,
    "summary": "Push completed",
}

_JOB_STATUS_RESPONSE: dict[str, Any] = {
    "data": [
        {
            "id": "job-live-001",
            "device_name": "fw-01",
            "end_ts": "2026-01-01T12:00:00Z",
            "start_ts": "2026-01-01T11:59:00Z",
            "job_result": "OK",
            "job_status": "FIN",
            "job_type": "CommitAndPush",
            "parent_id": "0",
            "percent": 100,
            "result_str": "OK",
            "status_str": "FIN",
            "summary": "Commit and push succeeded",
            "type_str": "CommitAndPush",
            "uname": "admin",
        }
    ]
}


def _make_mock_client() -> MagicMock:
    """Return a MagicMock SCMClient with operations methods stubbed as AsyncMocks."""
    client = MagicMock(spec=SCMClient)
    client.push_candidate_config = AsyncMock(
        return_value=_make_scm_result(_PUSH_RESPONSE)
    )
    client.get_job_status = AsyncMock(
        return_value=_make_scm_result(_JOB_STATUS_RESPONSE, http_status=200)
    )
    return client


def _patch_live(monkeypatch: pytest.MonkeyPatch, mock_client: MagicMock) -> None:
    """Patch get_settings and get_scm_client in the operations tools module."""
    monkeypatch.setattr(
        "mcp_strata_cloud_manager.tools.operations.get_settings",
        lambda: _make_live_settings(),
    )
    monkeypatch.setattr(
        "mcp_strata_cloud_manager.tools.operations.get_scm_client",
        lambda: mock_client,
    )


# ---------------------------------------------------------------------------
# Live mode — push_candidate_config
# ---------------------------------------------------------------------------


class TestPushCandidateConfigLiveMode:
    """push_candidate_config delegates to SCMClient and returns its data in live mode."""

    async def test_calls_client_in_live_mode(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool calls client.push_candidate_config in live mode."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        await call_tool(
            server,
            "push_candidate_config",
            {"ticket_id": "CHG-001", "folders": ["Shared"]},
        )

        mock_client.push_candidate_config.assert_awaited_once()

    async def test_returns_client_response_data(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool response body is the data returned by the client, not fixtures."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(
            server,
            "push_candidate_config",
            {"ticket_id": "CHG-001", "folders": ["Shared"]},
        )

        assert data["id"] == "job-live-001"
        assert data["job_status"] == "FIN"

    async def test_folders_passed_to_client(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """folders parameter is forwarded to client.push_candidate_config."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        await call_tool(
            server,
            "push_candidate_config",
            {"ticket_id": "CHG-001", "folders": ["Shared", "MyFolder"]},
        )

        call_folders, _, _ = mock_client.push_candidate_config.call_args.args
        assert call_folders == ["Shared", "MyFolder"]

    async def test_admin_passed_when_provided(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """admin parameter is forwarded to client.push_candidate_config when given."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        await call_tool(
            server,
            "push_candidate_config",
            {"ticket_id": "CHG-001", "folders": ["Shared"], "admin": ["svc-account"]},
        )

        _, call_admin, _ = mock_client.push_candidate_config.call_args.args
        assert call_admin == ["svc-account"]

    async def test_admin_is_none_when_not_provided(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """admin is passed as None when not given (client omits it from body)."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        await call_tool(
            server,
            "push_candidate_config",
            {"ticket_id": "CHG-001", "folders": ["Shared"]},
        )

        _, call_admin, _ = mock_client.push_candidate_config.call_args.args
        assert call_admin is None

    async def test_scm_api_error_returns_structured_error(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCMAPIError from the client returns SCM_API_ERROR error dict."""
        mock_client = _make_mock_client()
        mock_client.push_candidate_config = AsyncMock(
            side_effect=SCMAPIError(
                "SCM API returned HTTP 500",
                http_status=500,
                request_id="req-500",
                error_codes=["E013"],
            )
        )
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(
            server,
            "push_candidate_config",
            {"ticket_id": "CHG-001", "folders": ["Shared"]},
        )

        assert "error" in data
        assert data["error"]["code"] == SCM_API_ERROR_CODE
        assert data["error"]["scm_request_id"] == "req-500"
        assert "E013" in data["error"]["scm_error_codes"]

    async def test_scm_auth_error_returns_auth_failure_code(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCMAuthError from the client returns SCM_AUTH_FAILURE error dict."""
        mock_client = _make_mock_client()
        mock_client.push_candidate_config = AsyncMock(
            side_effect=SCMAuthError("auth failed")
        )
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(
            server,
            "push_candidate_config",
            {"ticket_id": "CHG-001", "folders": ["Shared"]},
        )

        assert "error" in data
        assert data["error"]["code"] == SCM_AUTH_FAILURE_CODE

    async def test_ticket_id_enforced_in_live_mode(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty ticket_id is rejected before the client is called in live mode."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(
            server,
            "push_candidate_config",
            {"ticket_id": "", "folders": ["Shared"]},
        )

        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"
        mock_client.push_candidate_config.assert_not_awaited()


# ---------------------------------------------------------------------------
# Live mode — get_job_status
# ---------------------------------------------------------------------------


class TestGetJobStatusLiveMode:
    """get_job_status delegates to SCMClient and returns its data in live mode."""

    async def test_calls_client_in_live_mode(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool calls client.get_job_status in live mode."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        await call_tool(server, "get_job_status", {"job_id": "job-live-001"})

        mock_client.get_job_status.assert_awaited_once()

    async def test_job_id_passed_to_client(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """job_id is forwarded to client.get_job_status."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        await call_tool(server, "get_job_status", {"job_id": "job-xyz-999"})

        (call_job_id,) = mock_client.get_job_status.call_args.args
        assert call_job_id == "job-xyz-999"

    async def test_returns_client_response_data(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool response body is the data returned by the client, not fixtures."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(server, "get_job_status", {"job_id": "job-live-001"})

        assert "data" in data
        assert data["data"][0]["id"] == "job-live-001"
        assert data["data"][0]["status_str"] == "FIN"

    async def test_scm_api_error_404_returns_structured_error(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCMAPIError (E005, 404) returns SCM_API_ERROR error dict."""
        mock_client = _make_mock_client()
        mock_client.get_job_status = AsyncMock(
            side_effect=SCMAPIError(
                "SCM API returned HTTP 404",
                http_status=404,
                request_id="req-404",
                error_codes=["E005"],
            )
        )
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(server, "get_job_status", {"job_id": "nonexistent-job"})

        assert "error" in data
        assert data["error"]["code"] == SCM_API_ERROR_CODE
        assert data["error"]["scm_request_id"] == "req-404"
        assert "E005" in data["error"]["scm_error_codes"]

    async def test_scm_auth_error_returns_auth_failure_code(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCMAuthError from the client returns SCM_AUTH_FAILURE error dict."""
        mock_client = _make_mock_client()
        mock_client.get_job_status = AsyncMock(
            side_effect=SCMAuthError("auth failed")
        )
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(server, "get_job_status", {"job_id": "any-job"})

        assert "error" in data
        assert data["error"]["code"] == SCM_AUTH_FAILURE_CODE


# ---------------------------------------------------------------------------
# Demo mode regression — fixture data is returned unchanged
# ---------------------------------------------------------------------------


class TestDemoModeRegression:
    """Demo mode continues to return fixture data after the live-mode changes."""

    async def test_push_candidate_config_demo_returns_fin_status(
        self, server: FastMCP
    ) -> None:
        """Demo mode push returns a completed job with status_str 'FIN'."""
        data = await call_tool(
            server,
            "push_candidate_config",
            {"ticket_id": "CHG-demo", "folders": ["Shared"]},
        )
        assert data["status_str"] == "FIN"
        assert data["result_str"] == "OK"

    async def test_push_candidate_config_demo_rejects_empty_ticket(
        self, server: FastMCP
    ) -> None:
        """Demo mode still enforces ticket_id (regression guard)."""
        data = await call_tool(
            server,
            "push_candidate_config",
            {"ticket_id": "", "folders": ["Shared"]},
        )
        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"

    async def test_get_job_status_demo_returns_completed_job(
        self, server: FastMCP
    ) -> None:
        """Demo mode returns a completed job fixture with the provided job_id."""
        data = await call_tool(
            server, "get_job_status", {"job_id": "test-job-id-123"}
        )
        assert "data" in data
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "test-job-id-123"
        assert data["data"][0]["status_str"] == "FIN"
