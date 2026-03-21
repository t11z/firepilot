"""Integration tests for write tools in live mode.

Verifies that create_security_rule, create_address, and create_address_group
delegate to SCMClient in live mode and that demo mode continues to return
fixture data (regression guard).

No network access is required. SCMClient is mocked at the module level in
mcp_strata_cloud_manager.tools.write by patching get_scm_client and get_settings.

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
    return SCMResult(data=body, http_status=http_status, scm_request_id="req-test-456")


_CREATED_RULE_RESPONSE: dict[str, Any] = {
    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "name": "allow-web-traffic",
    "folder": "Shared",
    "action": "allow",
    "from": ["untrust-zone"],
    "to": ["web-zone"],
    "source": ["any"],
    "source_user": ["any"],
    "destination": ["any"],
    "service": ["application-default"],
    "application": ["web-browsing"],
    "category": ["any"],
    "disabled": False,
    "negate_source": False,
    "negate_destination": False,
    "log_start": False,
    "log_end": True,
}


def _make_mock_client() -> MagicMock:
    """Return a MagicMock SCMClient with create_security_rule stubbed as AsyncMock."""
    client = MagicMock(spec=SCMClient)
    client.create_security_rule = AsyncMock(
        return_value=_make_scm_result(_CREATED_RULE_RESPONSE)
    )
    return client


def _base_args() -> dict[str, Any]:
    """Return a minimal valid set of arguments for create_security_rule."""
    return {
        "ticket_id": "CHG-001",
        "folder": "Shared",
        "name": "allow-web-traffic",
        "action": "allow",
        "from_zones": ["untrust-zone"],
        "to_zones": ["web-zone"],
        "source": ["any"],
        "source_user": ["any"],
        "destination": ["any"],
        "service": ["application-default"],
        "application": ["web-browsing"],
        "category": ["any"],
    }


def _patch_live(monkeypatch: pytest.MonkeyPatch, mock_client: MagicMock) -> None:
    """Patch get_settings and get_scm_client in the write tools module."""
    monkeypatch.setattr(
        "mcp_strata_cloud_manager.tools.write.get_settings",
        lambda: _make_live_settings(),
    )
    monkeypatch.setattr(
        "mcp_strata_cloud_manager.tools.write.get_scm_client",
        lambda: mock_client,
    )


# ---------------------------------------------------------------------------
# Live mode — create_security_rule
# ---------------------------------------------------------------------------


class TestCreateSecurityRuleLiveMode:
    """create_security_rule delegates to SCMClient and returns its data in live mode."""

    async def test_calls_client_in_live_mode(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool calls client.create_security_rule in live mode."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        await call_tool(server, "create_security_rule", _base_args())

        mock_client.create_security_rule.assert_awaited_once()

    async def test_returns_client_response_data(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool response body is the data returned by the client, not fixtures."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(server, "create_security_rule", _base_args())

        assert data["id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert data["name"] == "allow-web-traffic"

    async def test_from_zones_mapped_to_from_in_body(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """from_zones parameter is mapped to 'from' key in the SCM request body."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        await call_tool(server, "create_security_rule", _base_args())

        _, body, _ = mock_client.create_security_rule.call_args.args
        assert "from" in body
        assert body["from"] == ["untrust-zone"]
        assert "from_zones" not in body

    async def test_to_zones_mapped_to_to_in_body(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """to_zones parameter is mapped to 'to' key in the SCM request body."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        await call_tool(server, "create_security_rule", _base_args())

        _, body, _ = mock_client.create_security_rule.call_args.args
        assert "to" in body
        assert body["to"] == ["web-zone"]
        assert "to_zones" not in body

    async def test_none_optional_fields_excluded_from_body(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Optional fields with None values are not included in the request body."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        # Call with no optional fields (description, tag, schedule, etc. are None)
        await call_tool(server, "create_security_rule", _base_args())

        _, body, _ = mock_client.create_security_rule.call_args.args
        assert "description" not in body
        assert "tag" not in body
        assert "schedule" not in body
        assert "log_setting" not in body
        assert "profile_setting" not in body

    async def test_profile_setting_group_included_when_provided(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """profile_setting is included in body as {group: [...]} when provided."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        args = _base_args()
        args["profile_setting_group"] = ["strict-profile"]
        await call_tool(server, "create_security_rule", args)

        _, body, _ = mock_client.create_security_rule.call_args.args
        assert body["profile_setting"] == {"group": ["strict-profile"]}

    async def test_folder_and_position_passed_as_client_args(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """folder and position are passed as the first and third args to the client."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        args = _base_args()
        args["position"] = "post"
        await call_tool(server, "create_security_rule", args)

        call_folder, _, call_position = mock_client.create_security_rule.call_args.args
        assert call_folder == "Shared"
        assert call_position == "post"

    async def test_scm_api_error_returns_structured_error(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCMAPIError from the client returns SCM_API_ERROR error dict."""
        mock_client = _make_mock_client()
        mock_client.create_security_rule = AsyncMock(
            side_effect=SCMAPIError(
                "SCM API returned HTTP 409",
                http_status=409,
                request_id="req-409",
                error_codes=["E006"],
            )
        )
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(server, "create_security_rule", _base_args())

        assert "error" in data
        assert data["error"]["code"] == SCM_API_ERROR_CODE
        assert data["error"]["scm_request_id"] == "req-409"
        assert "E006" in data["error"]["scm_error_codes"]

    async def test_scm_auth_error_returns_auth_failure_code(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCMAuthError from the client returns SCM_AUTH_FAILURE error dict."""
        mock_client = _make_mock_client()
        mock_client.create_security_rule = AsyncMock(
            side_effect=SCMAuthError("auth failed")
        )
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(server, "create_security_rule", _base_args())

        assert "error" in data
        assert data["error"]["code"] == SCM_AUTH_FAILURE_CODE

    async def test_ticket_id_enforced_in_live_mode(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty ticket_id is rejected before the client is called in live mode."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        args = _base_args()
        args["ticket_id"] = ""

        data = await call_tool(server, "create_security_rule", args)

        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"
        mock_client.create_security_rule.assert_not_awaited()

    async def test_whitespace_only_ticket_id_rejected(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whitespace-only ticket_id is rejected before the client is called."""
        mock_client = _make_mock_client()
        _patch_live(monkeypatch, mock_client)

        args = _base_args()
        args["ticket_id"] = "   "

        data = await call_tool(server, "create_security_rule", args)

        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"
        mock_client.create_security_rule.assert_not_awaited()


# ---------------------------------------------------------------------------
# Demo mode regression — fixture data is returned unchanged
# ---------------------------------------------------------------------------


class TestDemoModeRegression:
    """Demo mode continues to return fixture data after the live-mode changes."""

    async def test_create_security_rule_demo_returns_fixture_id(
        self, server: FastMCP
    ) -> None:
        """Demo mode returns a rule with the FIXTURE_CREATED_RULE_ID."""
        from mcp_strata_cloud_manager.fixtures.strata import FIXTURE_CREATED_RULE_ID

        data = await call_tool(
            server,
            "create_security_rule",
            {
                "ticket_id": "CHG-demo",
                "folder": "Shared",
                "name": "test-rule",
            },
        )
        assert data["id"] == FIXTURE_CREATED_RULE_ID

    async def test_create_security_rule_demo_rejects_empty_ticket(
        self, server: FastMCP
    ) -> None:
        """Demo mode still enforces ticket_id (regression guard)."""
        data = await call_tool(
            server,
            "create_security_rule",
            {"ticket_id": "", "folder": "Shared", "name": "test-rule"},
        )
        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"


# ---------------------------------------------------------------------------
# Helpers for create_address and create_address_group live-mode tests
# ---------------------------------------------------------------------------


_CREATED_ADDRESS_RESPONSE: dict[str, Any] = {
    "id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
    "name": "new-server",
    "description": "A new server",
    "tag": [],
    "ip_netmask": "192.168.1.1/32",
    "ip_range": None,
    "ip_wildcard": None,
    "fqdn": None,
}

_CREATED_GROUP_RESPONSE: dict[str, Any] = {
    "id": "cccccccc-dddd-eeee-ffff-aaaaaaaaaaaa",
    "name": "new-group",
    "description": "A new group",
    "tag": [],
    "static": ["new-server"],
    "dynamic": None,
}


def _make_address_mock_client() -> MagicMock:
    """Return a MagicMock SCMClient with create_address stubbed as AsyncMock."""
    client = MagicMock(spec=SCMClient)
    client.create_address = AsyncMock(
        return_value=_make_scm_result(_CREATED_ADDRESS_RESPONSE)
    )
    return client


def _make_group_mock_client() -> MagicMock:
    """Return a MagicMock SCMClient with create_address_group stubbed as AsyncMock."""
    client = MagicMock(spec=SCMClient)
    client.create_address_group = AsyncMock(
        return_value=_make_scm_result(_CREATED_GROUP_RESPONSE)
    )
    return client


def _base_address_args() -> dict[str, Any]:
    """Return minimal valid arguments for create_address."""
    return {
        "ticket_id": "CHG-addr-001",
        "folder": "Shared",
        "name": "new-server",
        "ip_netmask": "192.168.1.1/32",
    }


def _base_group_args() -> dict[str, Any]:
    """Return minimal valid arguments for create_address_group."""
    return {
        "ticket_id": "CHG-grp-001",
        "folder": "Shared",
        "name": "new-group",
        "static": ["new-server"],
    }


# ---------------------------------------------------------------------------
# Live mode — create_address
# ---------------------------------------------------------------------------


class TestCreateAddressLiveMode:
    """create_address delegates to SCMClient and returns its data in live mode."""

    async def test_calls_client_in_live_mode(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool calls client.create_address in live mode."""
        mock_client = _make_address_mock_client()
        _patch_live(monkeypatch, mock_client)

        await call_tool(server, "create_address", _base_address_args())

        mock_client.create_address.assert_awaited_once()

    async def test_returns_client_response_data(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool response body is the data returned by the client, not fixtures."""
        mock_client = _make_address_mock_client()
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(server, "create_address", _base_address_args())

        assert data["id"] == "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        assert data["name"] == "new-server"

    async def test_ticket_id_enforced_in_live_mode(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty ticket_id is rejected before the client is called in live mode."""
        mock_client = _make_address_mock_client()
        _patch_live(monkeypatch, mock_client)

        args = {**_base_address_args(), "ticket_id": ""}
        data = await call_tool(server, "create_address", args)

        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"
        mock_client.create_address.assert_not_awaited()

    async def test_whitespace_only_ticket_id_rejected(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whitespace-only ticket_id is rejected before the client is called."""
        mock_client = _make_address_mock_client()
        _patch_live(monkeypatch, mock_client)

        args = {**_base_address_args(), "ticket_id": "   "}
        data = await call_tool(server, "create_address", args)

        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"
        mock_client.create_address.assert_not_awaited()

    async def test_scm_api_error_returns_structured_error(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCMAPIError from the client returns SCM_API_ERROR error dict."""
        mock_client = _make_address_mock_client()
        mock_client.create_address = AsyncMock(
            side_effect=SCMAPIError(
                "SCM API returned HTTP 409",
                http_status=409,
                request_id="req-addr-409",
                error_codes=["E006"],
            )
        )
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(server, "create_address", _base_address_args())

        assert "error" in data
        assert data["error"]["code"] == SCM_API_ERROR_CODE
        assert data["error"]["scm_request_id"] == "req-addr-409"
        assert "E006" in data["error"]["scm_error_codes"]

    async def test_scm_auth_error_returns_auth_failure_code(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCMAuthError from the client returns SCM_AUTH_FAILURE error dict."""
        mock_client = _make_address_mock_client()
        mock_client.create_address = AsyncMock(
            side_effect=SCMAuthError("auth failed")
        )
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(server, "create_address", _base_address_args())

        assert "error" in data
        assert data["error"]["code"] == SCM_AUTH_FAILURE_CODE


# ---------------------------------------------------------------------------
# Live mode — create_address_group
# ---------------------------------------------------------------------------


class TestCreateAddressGroupLiveMode:
    """create_address_group delegates to SCMClient and returns its data in live mode."""

    async def test_calls_client_in_live_mode(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool calls client.create_address_group in live mode."""
        mock_client = _make_group_mock_client()
        _patch_live(monkeypatch, mock_client)

        await call_tool(server, "create_address_group", _base_group_args())

        mock_client.create_address_group.assert_awaited_once()

    async def test_returns_client_response_data(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool response body is the data returned by the client, not fixtures."""
        mock_client = _make_group_mock_client()
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(server, "create_address_group", _base_group_args())

        assert data["id"] == "cccccccc-dddd-eeee-ffff-aaaaaaaaaaaa"
        assert data["name"] == "new-group"

    async def test_ticket_id_enforced_in_live_mode(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty ticket_id is rejected before the client is called in live mode."""
        mock_client = _make_group_mock_client()
        _patch_live(monkeypatch, mock_client)

        args = {**_base_group_args(), "ticket_id": ""}
        data = await call_tool(server, "create_address_group", args)

        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"
        mock_client.create_address_group.assert_not_awaited()

    async def test_whitespace_only_ticket_id_rejected(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whitespace-only ticket_id is rejected before the client is called."""
        mock_client = _make_group_mock_client()
        _patch_live(monkeypatch, mock_client)

        args = {**_base_group_args(), "ticket_id": "   "}
        data = await call_tool(server, "create_address_group", args)

        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"
        mock_client.create_address_group.assert_not_awaited()

    async def test_scm_api_error_returns_structured_error(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCMAPIError from the client returns SCM_API_ERROR error dict."""
        mock_client = _make_group_mock_client()
        mock_client.create_address_group = AsyncMock(
            side_effect=SCMAPIError(
                "SCM API returned HTTP 409",
                http_status=409,
                request_id="req-grp-409",
                error_codes=["E006"],
            )
        )
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(server, "create_address_group", _base_group_args())

        assert "error" in data
        assert data["error"]["code"] == SCM_API_ERROR_CODE
        assert data["error"]["scm_request_id"] == "req-grp-409"
        assert "E006" in data["error"]["scm_error_codes"]

    async def test_scm_auth_error_returns_auth_failure_code(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCMAuthError from the client returns SCM_AUTH_FAILURE error dict."""
        mock_client = _make_group_mock_client()
        mock_client.create_address_group = AsyncMock(
            side_effect=SCMAuthError("auth failed")
        )
        _patch_live(monkeypatch, mock_client)

        data = await call_tool(server, "create_address_group", _base_group_args())

        assert "error" in data
        assert data["error"]["code"] == SCM_AUTH_FAILURE_CODE
