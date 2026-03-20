"""Tests for gate4-deploy.py — deployment workflow logic.

All tests mock MCP ClientSession.call_tool to avoid real subprocess/network calls.
Tests exercise run_deployment for happy-path and all documented failure modes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

import sys

sys.path.insert(0, str(Path(__file__).parent))

import gate4_deploy as g4  # noqa: E402
from gate4_deploy import run_deployment  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text_content(data: dict) -> MagicMock:
    """Build a mock CallToolResult with JSON-encoded text content."""
    from mcp.types import TextContent

    result = MagicMock()
    result.content = [TextContent(type="text", text=json.dumps(data))]
    return result


class _FakeSession:
    """Fake MCP session with per-call-tool configurable responses.

    Supports sequenced responses for a tool: provide a list and each call
    pops the next item. Provide a single dict for a constant response.
    """

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses: dict[str, Any] = responses
        self.calls: dict[str, list[dict]] = {}

    async def call_tool(self, tool_name: str, arguments: dict) -> MagicMock:
        self.calls.setdefault(tool_name, []).append(arguments)
        raw = self._responses.get(tool_name, {})
        if isinstance(raw, list):
            # Pop sequenced response; use last item if exhausted
            item = raw.pop(0) if raw else {}
        else:
            item = raw
        return _text_content(item)


def _make_config(tmp_path: Path, rules: list[dict] | None = None) -> Path:
    """Create a minimal firewall-configs/ tree.

    Args:
        tmp_path: Pytest tmp_path fixture.
        rules: List of rule dicts. Defaults to a single allow-web rule.

    Returns:
        Path to the config root directory.
    """
    if rules is None:
        rules = [
            {
                "schema_version": 1,
                "name": "allow-web",
                "from": ["web-zone"],
                "to": ["app-zone"],
                "source": ["any"],
                "destination": ["any"],
                "source_user": ["any"],
                "application": ["ssl"],
                "category": ["any"],
                "service": ["application-default"],
                "action": "allow",
                "tag": ["firepilot-managed"],
            }
        ]

    position_dir = tmp_path / "shared" / "pre"
    position_dir.mkdir(parents=True)

    rule_order = [r["name"] for r in rules]
    manifest = {
        "schema_version": 1,
        "folder": "shared",
        "position": "pre",
        "rule_order": rule_order,
    }
    (position_dir / "_rulebase.yaml").write_text(yaml.dump(manifest))

    for rule in rules:
        (position_dir / f"{rule['name']}.yaml").write_text(yaml.dump(rule))

    return tmp_path


# Standard success responses for the full happy path
_RULE_CREATED = {"id": "rule-uuid-abc123", "name": "allow-web"}
_AUDIT_COMMENT = {"comment_id": "c1", "url": "https://example.com/c1", "created_at": "2026-01-01T00:00:00Z"}
_PUSH_PENDING = {"job_id": "job-001", "status_str": "PEND", "result_str": ""}
_PUSH_RESPONSE = {"job_id": "job-001", "status_str": "FIN", "result_str": "OK"}
_JOB_FIN_OK = {"data": [{"id": "job-001", "status_str": "FIN", "result_str": "OK"}]}
_STATUS_DEPLOYED = {"change_request_id": "42", "status": "deployed", "url": "https://example.com", "closed": True}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_exit_0(tmp_path: Path) -> None:
    """Full happy path: rules created, push succeeds, ITSM updated → exit 0."""
    config_dir = _make_config(tmp_path)

    scm = _FakeSession(
        {
            "create_security_rule": _RULE_CREATED,
            "push_candidate_config": _PUSH_RESPONSE,
            "get_job_status": _JOB_FIN_OK,
        }
    )
    itsm = _FakeSession(
        {
            "add_audit_comment": _AUDIT_COMMENT,
            "update_change_request_status": _STATUS_DEPLOYED,
        }
    )

    exit_code = await run_deployment(scm, itsm, config_dir, "42", push_timeout=30)
    assert exit_code == 0

    # Verify ITSM recorded candidate_written and push_succeeded
    audit_calls = itsm.calls.get("add_audit_comment", [])
    events = [c["event"] for c in audit_calls]
    assert "candidate_written" in events
    assert "push_initiated" in events
    assert "push_succeeded" in events

    # Verify status set to deployed
    status_calls = itsm.calls.get("update_change_request_status", [])
    assert any(c["status"] == "deployed" for c in status_calls)


# ---------------------------------------------------------------------------
# Rule creation failure mid-batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rule_creation_failure_records_itsm_and_exits_1(tmp_path: Path) -> None:
    """create_security_rule returns error → ITSM records push_failed → exit 1."""
    rules = [
        {
            "schema_version": 1,
            "name": "rule-a",
            "from": ["web-zone"],
            "to": ["app-zone"],
            "source": ["any"],
            "destination": ["any"],
            "source_user": ["any"],
            "application": ["ssl"],
            "category": ["any"],
            "service": ["application-default"],
            "action": "allow",
            "tag": ["firepilot-managed"],
        },
        {
            "schema_version": 1,
            "name": "rule-b",
            "from": ["app-zone"],
            "to": ["db-zone"],
            "source": ["any"],
            "destination": ["any"],
            "source_user": ["any"],
            "application": ["mysql"],
            "category": ["any"],
            "service": ["application-default"],
            "action": "allow",
            "tag": ["firepilot-managed"],
        },
    ]
    config_dir = _make_config(tmp_path, rules)

    # First rule creation succeeds; second fails
    scm = _FakeSession(
        {
            "create_security_rule": [
                _RULE_CREATED,
                {"error": {"code": "SCM_API_ERROR", "message": "duplicate name"}},
            ],
        }
    )
    itsm = _FakeSession({"add_audit_comment": _AUDIT_COMMENT, "update_change_request_status": {}})

    exit_code = await run_deployment(scm, itsm, config_dir, "42", push_timeout=30)
    assert exit_code == 1

    audit_calls = itsm.calls.get("add_audit_comment", [])
    events = [c["event"] for c in audit_calls]
    assert "push_failed" in events

    status_calls = itsm.calls.get("update_change_request_status", [])
    assert any(c["status"] == "failed" for c in status_calls)


# ---------------------------------------------------------------------------
# Push returns PUSHFAIL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_failure_records_itsm_and_exits_1(tmp_path: Path) -> None:
    """push_candidate_config returns PUSHFAIL result → ITSM records failure → exit 1."""
    config_dir = _make_config(tmp_path)

    scm = _FakeSession(
        {
            "create_security_rule": _RULE_CREATED,
            "push_candidate_config": {
                "job_id": "job-002",
                "status_str": "PUSHFAIL",
                "result_str": "FAIL",
            },
        }
    )
    itsm = _FakeSession({"add_audit_comment": _AUDIT_COMMENT, "update_change_request_status": {}})

    exit_code = await run_deployment(scm, itsm, config_dir, "42", push_timeout=30)
    assert exit_code == 1

    status_calls = itsm.calls.get("update_change_request_status", [])
    assert any(c["status"] == "failed" for c in status_calls)


# ---------------------------------------------------------------------------
# Poll timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_timeout_records_itsm_and_exits_1(tmp_path: Path) -> None:
    """Job never reaches terminal state within timeout → ITSM records failure → exit 1."""
    config_dir = _make_config(tmp_path)

    # push returns non-terminal status; get_job_status also returns non-terminal
    scm = _FakeSession(
        {
            "create_security_rule": _RULE_CREATED,
            "push_candidate_config": {"job_id": "job-003", "status_str": "ACT", "result_str": ""},
            "get_job_status": {"data": [{"id": "job-003", "status_str": "ACT", "result_str": ""}]},
        }
    )
    itsm = _FakeSession({"add_audit_comment": _AUDIT_COMMENT, "update_change_request_status": {}})

    # Patch asyncio.sleep to be a no-op so the test doesn't actually wait
    with patch("gate4_deploy.asyncio.sleep", new_callable=AsyncMock):
        exit_code = await run_deployment(
            scm, itsm, config_dir, "42", push_timeout=0  # immediate timeout
        )

    assert exit_code == 1

    status_calls = itsm.calls.get("update_change_request_status", [])
    assert any(c["status"] == "failed" for c in status_calls)


# ---------------------------------------------------------------------------
# push_candidate_config returns an error dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_api_error_records_itsm_and_exits_1(tmp_path: Path) -> None:
    """push_candidate_config returns an error dict → ITSM records failure → exit 1."""
    config_dir = _make_config(tmp_path)

    scm = _FakeSession(
        {
            "create_security_rule": _RULE_CREATED,
            "push_candidate_config": {
                "error": {"code": "SCM_AUTH_FAILURE", "message": "token expired"}
            },
        }
    )
    itsm = _FakeSession({"add_audit_comment": _AUDIT_COMMENT, "update_change_request_status": {}})

    exit_code = await run_deployment(scm, itsm, config_dir, "42", push_timeout=30)
    assert exit_code == 1

    status_calls = itsm.calls.get("update_change_request_status", [])
    assert any(c["status"] == "failed" for c in status_calls)


# ---------------------------------------------------------------------------
# MCP server unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scm_server_unavailable_exits_1(tmp_path: Path) -> None:
    """async_main with connect_mcp_server returning None for SCM → exit 1."""
    config_dir = _make_config(tmp_path)

    with patch("gate4_deploy.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        # First call (SCM) returns None; second (ITSM) returns a session
        mock_connect.side_effect = [None, AsyncMock()]
        exit_code = await g4.async_main(config_dir, "42")

    assert exit_code == 1


@pytest.mark.asyncio
async def test_itsm_server_unavailable_exits_1(tmp_path: Path) -> None:
    """async_main with connect_mcp_server returning None for ITSM → exit 1."""
    config_dir = _make_config(tmp_path)

    with patch("gate4_deploy.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = [AsyncMock(), None]
        exit_code = await g4.async_main(config_dir, "42")

    assert exit_code == 1
