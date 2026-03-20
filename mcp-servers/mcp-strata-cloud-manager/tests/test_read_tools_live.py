"""Integration tests for read tools in live mode.

Verifies that each read tool delegates to SCMClient in live mode and that
demo mode continues to return fixture data (regression guard).

No network access is required. SCMClient is mocked at the module level in
mcp_strata_cloud_manager.tools.read by patching get_scm_client and get_settings.

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


def _make_scm_result(body: dict[str, Any]) -> SCMResult:
    """Wrap a response body in an SCMResult as the client would return."""
    return SCMResult(data=body, http_status=200, scm_request_id="req-test-123")


def _make_mock_client() -> MagicMock:
    """Return a MagicMock SCMClient with all four read methods stubbed as AsyncMocks."""
    client = MagicMock(spec=SCMClient)
    client.list_security_zones = AsyncMock(
        return_value=_make_scm_result(
            {
                "data": [
                    {
                        "id": "z-live-001",
                        "name": "live-trust-zone",
                        "folder": "Shared",
                        "enable_user_identification": False,
                        "enable_device_identification": False,
                        "user_acl": {"include_list": [], "exclude_list": []},
                    }
                ],
                "limit": 200,
                "offset": 0,
                "total": 1,
            }
        )
    )
    client.list_security_rules = AsyncMock(
        return_value=_make_scm_result(
            {"data": [], "limit": 200, "offset": 0, "total": 0}
        )
    )
    client.list_addresses = AsyncMock(
        return_value=_make_scm_result(
            {"data": [], "limit": 200, "offset": 0, "total": 0}
        )
    )
    client.list_address_groups = AsyncMock(
        return_value=_make_scm_result(
            {"data": [], "limit": 200, "offset": 0, "total": 0}
        )
    )
    return client


# ---------------------------------------------------------------------------
# Live mode — list_security_zones
# ---------------------------------------------------------------------------


class TestListSecurityZonesLiveMode:
    """list_security_zones delegates to SCMClient and returns its data in live mode."""

    async def test_calls_client_in_live_mode(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool calls client.list_security_zones in live mode."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_scm_client",
            lambda: mock_client,
        )

        await call_tool(server, "list_security_zones", {"folder": "Shared"})

        mock_client.list_security_zones.assert_awaited_once()

    async def test_returns_client_response_data(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool response body is the data returned by the client, not fixtures."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_scm_client",
            lambda: mock_client,
        )

        data = await call_tool(server, "list_security_zones", {"folder": "Shared"})

        assert data["total"] == 1
        assert data["data"][0]["name"] == "live-trust-zone"

    async def test_folder_and_params_passed_to_client(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """folder, name, limit, and offset are forwarded to the client method."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_scm_client",
            lambda: mock_client,
        )

        await call_tool(
            server,
            "list_security_zones",
            {"folder": "MyFolder", "name": "web-zone", "limit": 10, "offset": 5},
        )

        mock_client.list_security_zones.assert_awaited_once_with(
            "MyFolder", name="web-zone", limit=10, offset=5
        )

    async def test_scm_auth_error_returns_auth_failure_code(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCMAuthError from the client returns SCM_AUTH_FAILURE error dict."""
        mock_client = _make_mock_client()
        mock_client.list_security_zones = AsyncMock(
            side_effect=SCMAuthError("auth failed")
        )
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_scm_client",
            lambda: mock_client,
        )

        data = await call_tool(server, "list_security_zones", {"folder": "Shared"})

        assert "error" in data
        assert data["error"]["code"] == SCM_AUTH_FAILURE_CODE

    async def test_scm_auth_error_message_does_not_expose_credentials(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCM_AUTH_FAILURE error message must not contain credential values."""
        mock_client = _make_mock_client()
        mock_client.list_security_zones = AsyncMock(
            side_effect=SCMAuthError("auth failed")
        )
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_scm_client",
            lambda: mock_client,
        )

        data = await call_tool(server, "list_security_zones", {"folder": "Shared"})

        error_str = str(data["error"])
        assert "fake-client-secret" not in error_str
        assert "SCM_CLIENT_SECRET" not in error_str

    async def test_scm_api_error_returns_api_error_code(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCMAPIError from the client returns SCM_API_ERROR error dict."""
        mock_client = _make_mock_client()
        mock_client.list_security_zones = AsyncMock(
            side_effect=SCMAPIError(
                "SCM API returned HTTP 404",
                http_status=404,
                request_id="req-404",
                error_codes=["E006"],
            )
        )
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_scm_client",
            lambda: mock_client,
        )

        data = await call_tool(server, "list_security_zones", {"folder": "Shared"})

        assert "error" in data
        assert data["error"]["code"] == SCM_API_ERROR_CODE


# ---------------------------------------------------------------------------
# Live mode — other read tools
# ---------------------------------------------------------------------------


class TestOtherReadToolsLiveMode:
    """Verify that all four read tools delegate to the SCMClient in live mode."""

    async def test_list_security_rules_calls_client(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """list_security_rules calls client.list_security_rules in live mode."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_scm_client",
            lambda: mock_client,
        )

        await call_tool(
            server,
            "list_security_rules",
            {"folder": "Shared", "position": "pre"},
        )

        mock_client.list_security_rules.assert_awaited_once()

    async def test_list_addresses_calls_client(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """list_addresses calls client.list_addresses in live mode."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_scm_client",
            lambda: mock_client,
        )

        await call_tool(server, "list_addresses", {"folder": "Shared"})

        mock_client.list_addresses.assert_awaited_once()

    async def test_list_address_groups_calls_client(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """list_address_groups calls client.list_address_groups in live mode."""
        mock_client = _make_mock_client()
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_settings",
            lambda: _make_live_settings(),
        )
        monkeypatch.setattr(
            "mcp_strata_cloud_manager.tools.read.get_scm_client",
            lambda: mock_client,
        )

        await call_tool(server, "list_address_groups", {"folder": "Shared"})

        mock_client.list_address_groups.assert_awaited_once()


# ---------------------------------------------------------------------------
# Demo mode regression — fixture data is returned unchanged
# ---------------------------------------------------------------------------


class TestDemoModeRegression:
    """Demo mode continues to return fixture data after the live-mode changes."""

    async def test_list_security_zones_demo_returns_fixtures(
        self, server: FastMCP
    ) -> None:
        """Demo mode returns all 4 fixture zones (unchanged from before this PR)."""
        data = await call_tool(server, "list_security_zones", {"folder": "Shared"})
        assert data["total"] == 4
        assert len(data["data"]) == 4

    async def test_list_security_rules_demo_returns_fixtures(
        self, server: FastMCP
    ) -> None:
        """Demo mode returns all 3 pre-position fixture rules."""
        data = await call_tool(
            server,
            "list_security_rules",
            {"folder": "Shared", "position": "pre"},
        )
        assert data["total"] == 3

    async def test_list_addresses_demo_returns_fixtures(
        self, server: FastMCP
    ) -> None:
        """Demo mode returns all 4 fixture address objects."""
        data = await call_tool(server, "list_addresses", {"folder": "Shared"})
        assert data["total"] == 4

    async def test_list_address_groups_demo_returns_fixtures(
        self, server: FastMCP
    ) -> None:
        """Demo mode returns the 1 fixture address group."""
        data = await call_tool(server, "list_address_groups", {"folder": "Shared"})
        assert data["total"] == 1
