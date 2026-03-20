"""Tests for retry-deploy.py — push retry workflow logic.

All tests mock MCP ClientSession.call_tool to avoid real subprocess/network calls.
Tests exercise run_retry for happy-path and all documented failure modes.
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

import retry_deploy as rd  # noqa: E402
from retry_deploy import run_retry  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_gate4_deploy.py)
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


# Standard responses
_RULE_CREATED = {"id": "rule-uuid-abc123", "name": "allow-web"}
_E006_ERROR = {
    "error": {
        "code": "SCM_API_ERROR",
        "message": "E006: Name Not Unique — rule already exists in candidate config",
    }
}
_E003_ERROR = {
    "error": {
        "code": "SCM_API_ERROR",
        "message": "E003: Invalid input — bad request",
    }
}
_AUDIT_COMMENT = {
    "comment_id": "c1",
    "url": "https://example.com/c1",
    "created_at": "2026-01-01T00:00:00Z",
}
_PUSH_FIN_OK = {"job_id": "job-001", "status_str": "FIN", "result_str": "OK"}
_JOB_FIN_OK = {"data": [{"id": "job-001", "status_str": "FIN", "result_str": "OK"}]}
_PUSH_FAIL = {"job_id": "job-002", "status_str": "PUSHFAIL", "result_str": "FAIL"}
_STATUS_DEPLOYED = {
    "change_request_id": "42",
    "status": "deployed",
    "url": "https://example.com",
    "closed": True,
}


# ---------------------------------------------------------------------------
# Happy path — rules already in candidate config (all E006)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rules_already_in_candidate_config_exit_0(tmp_path: Path) -> None:
    """create_security_rule returns E006 for all rules → treated as success → exit 0."""
    config_dir = _make_config(tmp_path)

    scm = _FakeSession(
        {
            "create_security_rule": _E006_ERROR,
            "push_candidate_config": _PUSH_FIN_OK,
            "get_job_status": _JOB_FIN_OK,
        }
    )
    itsm = _FakeSession(
        {
            "add_audit_comment": _AUDIT_COMMENT,
            "update_change_request_status": _STATUS_DEPLOYED,
        }
    )

    exit_code = await run_retry(scm, itsm, config_dir, "42", push_timeout=30)
    assert exit_code == 0

    # No candidate_written for E006 (rule already existed), but push events recorded
    audit_calls = itsm.calls.get("add_audit_comment", [])
    events = [c["event"] for c in audit_calls]
    assert "push_initiated" in events
    assert "push_succeeded" in events

    status_calls = itsm.calls.get("update_change_request_status", [])
    assert any(c["status"] == "deployed" for c in status_calls)


# ---------------------------------------------------------------------------
# Happy path — rules not in candidate config (all succeed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rules_not_in_candidate_config_exit_0(tmp_path: Path) -> None:
    """create_security_rule succeeds for all rules → push succeeds → exit 0."""
    config_dir = _make_config(tmp_path)

    scm = _FakeSession(
        {
            "create_security_rule": _RULE_CREATED,
            "push_candidate_config": _PUSH_FIN_OK,
            "get_job_status": _JOB_FIN_OK,
        }
    )
    itsm = _FakeSession(
        {
            "add_audit_comment": _AUDIT_COMMENT,
            "update_change_request_status": _STATUS_DEPLOYED,
        }
    )

    exit_code = await run_retry(scm, itsm, config_dir, "42", push_timeout=30)
    assert exit_code == 0

    audit_calls = itsm.calls.get("add_audit_comment", [])
    events = [c["event"] for c in audit_calls]
    assert "candidate_written" in events
    assert "push_initiated" in events
    assert "push_succeeded" in events

    status_calls = itsm.calls.get("update_change_request_status", [])
    assert any(c["status"] == "deployed" for c in status_calls)


# ---------------------------------------------------------------------------
# Mixed — some rules exist (E006), some don't
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_rules_some_exist_exit_0(tmp_path: Path) -> None:
    """First rule returns E006, second succeeds → both treated as success → exit 0."""
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

    # First rule: E006 (already exists), second rule: created successfully
    scm = _FakeSession(
        {
            "create_security_rule": [_E006_ERROR, _RULE_CREATED],
            "push_candidate_config": _PUSH_FIN_OK,
            "get_job_status": _JOB_FIN_OK,
        }
    )
    itsm = _FakeSession(
        {
            "add_audit_comment": _AUDIT_COMMENT,
            "update_change_request_status": _STATUS_DEPLOYED,
        }
    )

    exit_code = await run_retry(scm, itsm, config_dir, "42", push_timeout=30)
    assert exit_code == 0

    # candidate_written recorded for the successfully created rule (rule-b)
    audit_calls = itsm.calls.get("add_audit_comment", [])
    events = [c["event"] for c in audit_calls]
    assert "candidate_written" in events
    assert "push_initiated" in events
    assert "push_succeeded" in events

    status_calls = itsm.calls.get("update_change_request_status", [])
    assert any(c["status"] == "deployed" for c in status_calls)


# ---------------------------------------------------------------------------
# Push failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_failure_records_itsm_and_exits_1(tmp_path: Path) -> None:
    """Rules created (or E006-skipped) successfully but push returns PUSHFAIL → exit 1."""
    config_dir = _make_config(tmp_path)

    scm = _FakeSession(
        {
            "create_security_rule": _RULE_CREATED,
            "push_candidate_config": _PUSH_FAIL,
        }
    )
    itsm = _FakeSession(
        {"add_audit_comment": _AUDIT_COMMENT, "update_change_request_status": {}}
    )

    exit_code = await run_retry(scm, itsm, config_dir, "42", push_timeout=30)
    assert exit_code == 1

    status_calls = itsm.calls.get("update_change_request_status", [])
    assert any(c["status"] == "failed" for c in status_calls)


# ---------------------------------------------------------------------------
# Rule creation failure (non-E006)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_e006_rule_creation_failure_exits_1(tmp_path: Path) -> None:
    """create_security_rule returns E003 (not E006) → ITSM records failure → exit 1."""
    config_dir = _make_config(tmp_path)

    scm = _FakeSession({"create_security_rule": _E003_ERROR})
    itsm = _FakeSession(
        {"add_audit_comment": _AUDIT_COMMENT, "update_change_request_status": {}}
    )

    exit_code = await run_retry(scm, itsm, config_dir, "42", push_timeout=30)
    assert exit_code == 1

    audit_calls = itsm.calls.get("add_audit_comment", [])
    events = [c["event"] for c in audit_calls]
    assert "push_failed" in events

    status_calls = itsm.calls.get("update_change_request_status", [])
    assert any(c["status"] == "failed" for c in status_calls)


# ---------------------------------------------------------------------------
# Poll timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_timeout_records_itsm_and_exits_1(tmp_path: Path) -> None:
    """get_job_status never reaches terminal state within timeout → exit 1."""
    config_dir = _make_config(tmp_path)

    scm = _FakeSession(
        {
            "create_security_rule": _RULE_CREATED,
            "push_candidate_config": {"job_id": "job-003", "status_str": "ACT", "result_str": ""},
            "get_job_status": {"data": [{"id": "job-003", "status_str": "ACT", "result_str": ""}]},
        }
    )
    itsm = _FakeSession(
        {"add_audit_comment": _AUDIT_COMMENT, "update_change_request_status": {}}
    )

    # Patch asyncio.sleep in deploy_common to avoid actual waiting
    with patch("deploy_common.asyncio.sleep", new_callable=AsyncMock):
        exit_code = await run_retry(
            scm, itsm, config_dir, "42", push_timeout=0  # immediate timeout
        )

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

    with patch("retry_deploy.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = [None, AsyncMock()]
        exit_code = await rd.async_main(config_dir, "42")

    assert exit_code == 1


@pytest.mark.asyncio
async def test_itsm_server_unavailable_exits_1(tmp_path: Path) -> None:
    """async_main with connect_mcp_server returning None for ITSM → exit 1."""
    config_dir = _make_config(tmp_path)

    with patch("retry_deploy.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = [AsyncMock(), None]
        exit_code = await rd.async_main(config_dir, "42")

    assert exit_code == 1
