"""Tests for gate3-dry-run.py — dry-run validation logic.

All tests mock the MCP ClientSession.call_tool to avoid real subprocess/network calls.
Tests exercise the validation helpers and the top-level run_validation function.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

# The module under test
import sys

sys.path.insert(0, str(Path(__file__).parent))

import gate3_dry_run as g3  # noqa: E402  (imported after sys.path patch)
from gate3_dry_run import (  # noqa: E402
    _is_cidr_or_any,
    validate_addresses,
    validate_name_conflicts,
    validate_zones,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(tool_responses: dict[str, Any]) -> AsyncMock:
    """Build a mock ClientSession whose call_tool returns predefined responses.

    Args:
        tool_responses: Maps tool name to the dict the tool should return.

    Returns:
        AsyncMock ClientSession with call_tool wired up.
    """
    session = AsyncMock()

    async def call_tool(tool_name: str, arguments: dict) -> MagicMock:
        response_data = tool_responses.get(tool_name, {})
        result = MagicMock()
        from mcp.types import TextContent

        result.content = [TextContent(type="text", text=json.dumps(response_data))]
        return result

    session.call_tool = call_tool
    return session


def _zones_response(*names: str) -> dict:
    return {"data": [{"name": n} for n in names], "total": len(names)}


def _addresses_response(*names: str) -> dict:
    return {"data": [{"name": n} for n in names], "total": len(names)}


def _rules_response(*names: str) -> dict:
    return {"data": [{"name": n} for n in names], "total": len(names)}


# ---------------------------------------------------------------------------
# Unit tests — _is_cidr_or_any
# ---------------------------------------------------------------------------


def test_is_cidr_or_any_any() -> None:
    assert _is_cidr_or_any("any") is True


def test_is_cidr_or_any_cidr_v4() -> None:
    assert _is_cidr_or_any("10.1.0.0/24") is True


def test_is_cidr_or_any_host_v4() -> None:
    assert _is_cidr_or_any("192.168.1.1") is True


def test_is_cidr_or_any_cidr_v6() -> None:
    assert _is_cidr_or_any("2001:db8::/32") is True


def test_is_cidr_or_any_object_name() -> None:
    assert _is_cidr_or_any("web-subnet-10.1.0.0-24") is False


def test_is_cidr_or_any_named_address() -> None:
    assert _is_cidr_or_any("app-servers") is False


# ---------------------------------------------------------------------------
# Unit tests — validate_zones
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_zones_all_exist() -> None:
    rule = {"name": "test-rule", "from": ["web-zone"], "to": ["app-zone"]}
    session = _make_session(
        {"list_security_zones": _zones_response("web-zone", "app-zone", "db-zone")}
    )
    violations: list[str] = []
    await validate_zones(session, "shared", rule, violations)
    assert violations == []


@pytest.mark.asyncio
async def test_validate_zones_unknown_from_zone() -> None:
    rule = {"name": "bad-rule", "from": ["unknown-zone"], "to": ["app-zone"]}
    session = _make_session(
        {"list_security_zones": _zones_response("web-zone", "app-zone")}
    )
    violations: list[str] = []
    await validate_zones(session, "shared", rule, violations)
    assert any("unknown-zone" in v and "FAIL" in v for v in violations)


@pytest.mark.asyncio
async def test_validate_zones_unknown_to_zone() -> None:
    rule = {"name": "bad-rule", "from": ["web-zone"], "to": ["nonexistent"]}
    session = _make_session(
        {"list_security_zones": _zones_response("web-zone", "app-zone")}
    )
    violations: list[str] = []
    await validate_zones(session, "shared", rule, violations)
    assert any("nonexistent" in v and "FAIL" in v for v in violations)


@pytest.mark.asyncio
async def test_validate_zones_api_error() -> None:
    rule = {"name": "err-rule", "from": ["web-zone"], "to": ["app-zone"]}
    session = _make_session(
        {"list_security_zones": {"error": {"code": "SCM_AUTH_FAILURE", "message": "auth failed"}}}
    )
    violations: list[str] = []
    await validate_zones(session, "shared", rule, violations)
    assert any("FAIL" in v and "auth failed" in v for v in violations)


# ---------------------------------------------------------------------------
# Unit tests — validate_addresses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_addresses_all_exist() -> None:
    rule = {
        "name": "rule1",
        "source": ["web-subnet-10.1.0.0-24"],
        "destination": ["app-subnet-10.2.0.0-24"],
    }
    session = _make_session(
        {
            "list_addresses": _addresses_response(
                "web-subnet-10.1.0.0-24", "app-subnet-10.2.0.0-24"
            )
        }
    )
    violations: list[str] = []
    await validate_addresses(session, "shared", rule, violations)
    assert violations == []


@pytest.mark.asyncio
async def test_validate_addresses_cidr_skipped() -> None:
    rule = {"name": "rule1", "source": ["10.0.0.0/8"], "destination": ["any"]}
    session = _make_session({"list_addresses": _addresses_response()})
    violations: list[str] = []
    await validate_addresses(session, "shared", rule, violations)
    assert violations == []


@pytest.mark.asyncio
async def test_validate_addresses_unknown_object() -> None:
    rule = {"name": "rule1", "source": ["missing-obj"], "destination": ["any"]}
    session = _make_session({"list_addresses": _addresses_response("other-obj")})
    violations: list[str] = []
    await validate_addresses(session, "shared", rule, violations)
    assert any("missing-obj" in v and "FAIL" in v for v in violations)


@pytest.mark.asyncio
async def test_validate_addresses_api_error() -> None:
    rule = {"name": "rule1", "source": ["some-obj"], "destination": []}
    session = _make_session(
        {"list_addresses": {"error": {"code": "SCM_API_ERROR", "message": "server error"}}}
    )
    violations: list[str] = []
    await validate_addresses(session, "shared", rule, violations)
    assert any("FAIL" in v and "server error" in v for v in violations)


# ---------------------------------------------------------------------------
# Unit tests — validate_name_conflicts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_name_conflicts_no_conflict() -> None:
    rules = [{"name": "new-rule-1"}, {"name": "new-rule-2"}]
    session = _make_session(
        {"list_security_rules": _rules_response("existing-rule")}
    )
    violations: list[str] = []
    await validate_name_conflicts(session, "shared", "pre", rules, violations)
    assert violations == []


@pytest.mark.asyncio
async def test_validate_name_conflicts_conflict_detected() -> None:
    rules = [{"name": "existing-rule"}, {"name": "brand-new-rule"}]
    session = _make_session(
        {"list_security_rules": _rules_response("existing-rule", "other-rule")}
    )
    violations: list[str] = []
    await validate_name_conflicts(session, "shared", "pre", rules, violations)
    assert any("existing-rule" in v and "FAIL" in v for v in violations)
    # brand-new-rule should NOT produce a violation
    assert not any("brand-new-rule" in v and "FAIL" in v for v in violations)


@pytest.mark.asyncio
async def test_validate_name_conflicts_api_error() -> None:
    rules = [{"name": "some-rule"}]
    session = _make_session(
        {"list_security_rules": {"error": {"code": "SCM_API_ERROR", "message": "timeout"}}}
    )
    violations: list[str] = []
    await validate_name_conflicts(session, "shared", "pre", rules, violations)
    assert any("FAIL" in v and "timeout" in v for v in violations)


# ---------------------------------------------------------------------------
# Integration-style tests — run_validation with a temp config dir
# ---------------------------------------------------------------------------


@pytest.fixture()
def simple_config(tmp_path: Path) -> Path:
    """Create a minimal firewall-configs/ tree with one rule."""
    position_dir = tmp_path / "shared" / "pre"
    position_dir.mkdir(parents=True)

    manifest = {"schema_version": 1, "folder": "shared", "position": "pre", "rule_order": ["allow-web"]}
    (position_dir / "_rulebase.yaml").write_text(yaml.dump(manifest))

    rule = {
        "schema_version": 1,
        "name": "allow-web",
        "from": ["web-zone"],
        "to": ["app-zone"],
        "source": ["web-subnet"],
        "destination": ["app-subnet"],
        "source_user": ["any"],
        "application": ["ssl"],
        "category": ["any"],
        "service": ["application-default"],
        "action": "allow",
        "tag": ["firepilot-managed"],
    }
    (position_dir / "allow-web.yaml").write_text(yaml.dump(rule))
    return tmp_path


@pytest.mark.asyncio
async def test_run_validation_all_pass(simple_config: Path) -> None:
    """All checks pass — exit code 0."""
    good_responses = {
        "list_security_zones": _zones_response("web-zone", "app-zone"),
        "list_addresses": _addresses_response("web-subnet", "app-subnet"),
        "list_security_rules": _rules_response("other-existing-rule"),
    }
    mock_session = _make_session(good_responses)

    with patch("gate3_dry_run.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await g3.run_validation(simple_config)

    assert exit_code == 0


@pytest.mark.asyncio
async def test_run_validation_unknown_zone(simple_config: Path) -> None:
    """Unknown zone → exit 1 with violation."""
    bad_responses = {
        "list_security_zones": _zones_response("only-zone"),  # missing web-zone/app-zone
        "list_addresses": _addresses_response("web-subnet", "app-subnet"),
        "list_security_rules": _rules_response(),
    }
    mock_session = _make_session(bad_responses)

    with patch("gate3_dry_run.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await g3.run_validation(simple_config)

    assert exit_code == 1


@pytest.mark.asyncio
async def test_run_validation_unknown_address(simple_config: Path) -> None:
    """Unknown address object → exit 1."""
    bad_responses = {
        "list_security_zones": _zones_response("web-zone", "app-zone"),
        "list_addresses": _addresses_response(),  # no address objects
        "list_security_rules": _rules_response(),
    }
    mock_session = _make_session(bad_responses)

    with patch("gate3_dry_run.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await g3.run_validation(simple_config)

    assert exit_code == 1


@pytest.mark.asyncio
async def test_run_validation_name_conflict(simple_config: Path) -> None:
    """Name conflict with existing SCM rule → exit 1."""
    conflict_responses = {
        "list_security_zones": _zones_response("web-zone", "app-zone"),
        "list_addresses": _addresses_response("web-subnet", "app-subnet"),
        "list_security_rules": _rules_response("allow-web"),  # same name!
    }
    mock_session = _make_session(conflict_responses)

    with patch("gate3_dry_run.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await g3.run_validation(simple_config)

    assert exit_code == 1


@pytest.mark.asyncio
async def test_run_validation_multiple_violations_collected(simple_config: Path) -> None:
    """Multiple violations are all reported before exit — not short-circuited."""
    # Both zones and addresses are missing → should get violations for both
    bad_responses = {
        "list_security_zones": _zones_response(),  # no zones known
        "list_addresses": _addresses_response(),   # no addresses known
        "list_security_rules": _rules_response("allow-web"),  # name conflict too
    }
    mock_session = _make_session(bad_responses)

    with patch("gate3_dry_run.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await g3.run_validation(simple_config)

    assert exit_code == 1


@pytest.mark.asyncio
async def test_run_validation_mcp_server_unavailable(simple_config: Path) -> None:
    """MCP server fails to connect → exit 1."""
    with patch("gate3_dry_run.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = None
        exit_code = await g3.run_validation(simple_config)

    assert exit_code == 1
