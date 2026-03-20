"""Tests for drift-check.py — drift detection logic.

All tests mock the MCP ClientSession.call_tool to avoid real subprocess/network
calls. Tests exercise the comparison helpers and the top-level run_drift_check
function.
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

import drift_check as dc  # noqa: E402
from drift_check import (  # noqa: E402
    compare_fields,
    run_drift_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIREPILOT_TAG = "firepilot-managed"


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


def _rules_response(rules: list[dict], total: int | None = None) -> dict:
    """Build a paginated list_security_rules response."""
    if total is None:
        total = len(rules)
    return {"data": rules, "total": total, "limit": 200, "offset": 0}


def _make_rule(
    name: str,
    *,
    action: str = "allow",
    from_zones: list[str] | None = None,
    to_zones: list[str] | None = None,
    source: list[str] | None = None,
    destination: list[str] | None = None,
    application: list[str] | None = None,
    tag: list[str] | None = None,
    disabled: bool = False,
    description: str = "",
    **extra: object,
) -> dict:
    """Build a minimal SCM rule dict with sensible defaults."""
    return {
        "name": name,
        "action": action,
        "from": from_zones or ["any"],
        "to": to_zones or ["any"],
        "source": source or ["any"],
        "source_user": ["any"],
        "destination": destination or ["any"],
        "service": ["any"],
        "application": application or ["any"],
        "category": ["any"],
        "tag": tag or [FIREPILOT_TAG],
        "disabled": disabled,
        "description": description,
        "negate_source": False,
        "negate_destination": False,
        "log_start": False,
        "log_end": True,
        **extra,
    }


def _make_git_rule(
    name: str,
    *,
    action: str = "allow",
    from_zones: list[str] | None = None,
    to_zones: list[str] | None = None,
    source: list[str] | None = None,
    destination: list[str] | None = None,
    application: list[str] | None = None,
    tag: list[str] | None = None,
    description: str = "",
    **extra: object,
) -> dict:
    """Build a minimal Git YAML rule dict with sensible defaults."""
    return {
        "schema_version": 1,
        "name": name,
        "action": action,
        "from": from_zones or ["any"],
        "to": to_zones or ["any"],
        "source": source or ["any"],
        "source_user": ["any"],
        "destination": destination or ["any"],
        "service": ["any"],
        "application": application or ["any"],
        "category": ["any"],
        "tag": tag or [FIREPILOT_TAG],
        "description": description,
        "negate_source": False,
        "negate_destination": False,
        "log_start": False,
        "log_end": True,
        **extra,
    }


def _write_config(tmp_path: Path, rules: list[dict]) -> Path:
    """Write a minimal firewall-configs/ tree with given rules.

    Args:
        tmp_path: Temporary directory base.
        rules: List of Git YAML rule dicts. Each must have a 'name' key.

    Returns:
        config_dir (the tmp_path root).
    """
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


# ---------------------------------------------------------------------------
# Unit tests — compare_fields
# ---------------------------------------------------------------------------


def test_compare_fields_no_diff() -> None:
    """Identical rules produce empty diff."""
    rule = _make_rule("r1")
    assert compare_fields(rule, rule) == {}


def test_compare_fields_action_diff() -> None:
    """Different action field is detected."""
    git = _make_git_rule("r1", action="allow")
    scm = _make_rule("r1", action="deny")
    diffs = compare_fields(git, scm)
    assert "action" in diffs
    assert diffs["action"] == {"git": "allow", "scm": "deny"}


def test_compare_fields_description_diff() -> None:
    """Different description is detected."""
    git = _make_git_rule("r1", description="Git description")
    scm = _make_rule("r1", description="SCM description")
    diffs = compare_fields(git, scm)
    assert "description" in diffs


def test_compare_fields_list_order_ignored() -> None:
    """List fields compared as sets — order does not matter."""
    git = _make_git_rule("r1", application=["ssl", "web-browsing"])
    scm = _make_rule("r1", application=["web-browsing", "ssl"])
    assert compare_fields(git, scm) == {}


def test_compare_fields_tag_diff() -> None:
    """Different tags are detected."""
    git = _make_git_rule("r1", tag=[FIREPILOT_TAG])
    scm = _make_rule("r1", tag=[FIREPILOT_TAG, "extra-tag"])
    diffs = compare_fields(git, scm)
    assert "tag" in diffs


# ---------------------------------------------------------------------------
# Integration tests — run_drift_check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_drift(tmp_path: Path) -> None:
    """Git rules and SCM rules match → exit 0, result NO_DRIFT."""
    git_rule = _make_git_rule("allow-web", action="allow", description="Allow web")
    scm_rule = _make_rule("allow-web", action="allow", description="Allow web")

    config_dir = _write_config(tmp_path, [git_rule])
    mock_session = _make_session(
        {"list_security_rules": _rules_response([scm_rule])}
    )

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await run_drift_check(config_dir)

    assert exit_code == 0


@pytest.mark.asyncio
async def test_no_drift_report_structure(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """NO_DRIFT report has correct JSON structure."""
    git_rule = _make_git_rule("allow-web", action="allow", description="Allow web")
    scm_rule = _make_rule("allow-web", action="allow", description="Allow web")

    config_dir = _write_config(tmp_path, [git_rule])
    mock_session = _make_session(
        {"list_security_rules": _rules_response([scm_rule])}
    )

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        await run_drift_check(config_dir)

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["result"] == "NO_DRIFT"
    assert report["total_discrepancies"] == 0
    assert "timestamp" in report
    assert "mode" in report
    assert "folders_checked" in report


@pytest.mark.asyncio
async def test_modified_externally(tmp_path: Path) -> None:
    """SCM rule has different action → exit 1, drift_type modified_externally."""
    git_rule = _make_git_rule("rule-1", action="allow")
    scm_rule = _make_rule("rule-1", action="deny")

    config_dir = _write_config(tmp_path, [git_rule])
    mock_session = _make_session(
        {"list_security_rules": _rules_response([scm_rule])}
    )

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await run_drift_check(config_dir)

    assert exit_code == 1


@pytest.mark.asyncio
async def test_modified_externally_report(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """modified_externally report contains field_diffs with correct values."""
    git_rule = _make_git_rule("rule-1", action="allow", description="Git desc")
    scm_rule = _make_rule("rule-1", action="deny", description="SCM desc")

    config_dir = _write_config(tmp_path, [git_rule])
    mock_session = _make_session(
        {"list_security_rules": _rules_response([scm_rule])}
    )

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        await run_drift_check(config_dir)

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["result"] == "DRIFT_DETECTED"

    folder_result = report["folders_checked"][0]
    discrepancy = next(
        d for d in folder_result["discrepancies"] if d["rule_name"] == "rule-1"
    )
    assert discrepancy["drift_type"] == "modified_externally"
    assert "action" in discrepancy["field_diffs"]
    assert discrepancy["field_diffs"]["action"] == {"git": "allow", "scm": "deny"}
    assert "description" in discrepancy["field_diffs"]


@pytest.mark.asyncio
async def test_missing_from_scm(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Git has a rule not in SCM → exit 1, drift_type missing_from_scm."""
    git_rule = _make_git_rule("git-only-rule")
    config_dir = _write_config(tmp_path, [git_rule])
    mock_session = _make_session(
        {"list_security_rules": _rules_response([])}
    )

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await run_drift_check(config_dir)

    assert exit_code == 1

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    folder_result = report["folders_checked"][0]
    discrepancy = next(
        d for d in folder_result["discrepancies"]
        if d.get("rule_name") == "git-only-rule"
    )
    assert discrepancy["drift_type"] == "missing_from_scm"


@pytest.mark.asyncio
async def test_orphan_in_scm(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """SCM has a firepilot-managed rule not in Git → exit 1, drift_type orphan_in_scm."""
    # Git has no rules (empty rule_order, no YAML files)
    position_dir = tmp_path / "shared" / "pre"
    position_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "folder": "shared",
        "position": "pre",
        "rule_order": [],
    }
    (position_dir / "_rulebase.yaml").write_text(yaml.dump(manifest))

    scm_rule = _make_rule("orphan-rule", tag=[FIREPILOT_TAG])
    mock_session = _make_session(
        {"list_security_rules": _rules_response([scm_rule])}
    )

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await run_drift_check(tmp_path)

    assert exit_code == 1

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    folder_result = report["folders_checked"][0]
    discrepancy = next(
        d for d in folder_result["discrepancies"]
        if d.get("rule_name") == "orphan-rule"
    )
    assert discrepancy["drift_type"] == "orphan_in_scm"


@pytest.mark.asyncio
async def test_order_drift(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Same rules but different order → exit 1, drift_type order_drift."""
    rule_a = _make_git_rule("rule-a")
    rule_b = _make_git_rule("rule-b")

    config_dir = _write_config(tmp_path, [rule_a, rule_b])  # Git order: a, b

    # SCM returns them in reversed order
    scm_a = _make_rule("rule-a")
    scm_b = _make_rule("rule-b")
    mock_session = _make_session(
        {"list_security_rules": _rules_response([scm_b, scm_a])}  # SCM order: b, a
    )

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await run_drift_check(config_dir)

    assert exit_code == 1

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    folder_result = report["folders_checked"][0]
    order_disc = next(
        d for d in folder_result["discrepancies"] if d.get("drift_type") == "order_drift"
    )
    assert order_disc["git_order"] == ["rule-a", "rule-b"]
    assert order_disc["scm_order"] == ["rule-b", "rule-a"]


@pytest.mark.asyncio
async def test_non_firepilot_rules_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """SCM rules without firepilot-managed tag are not reported as drift."""
    git_rule = _make_git_rule("managed-rule")
    scm_managed = _make_rule("managed-rule")
    # This rule has no firepilot-managed tag — it must be ignored
    scm_unmanaged = _make_rule("manual-rule", tag=["some-other-tag"])

    config_dir = _write_config(tmp_path, [git_rule])
    mock_session = _make_session(
        {"list_security_rules": _rules_response([scm_managed, scm_unmanaged])}
    )

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await run_drift_check(config_dir)

    assert exit_code == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["result"] == "NO_DRIFT"
    # manual-rule must not appear in discrepancies
    folder_result = report["folders_checked"][0]
    assert not any(
        d.get("rule_name") == "manual-rule" for d in folder_result["discrepancies"]
    )


@pytest.mark.asyncio
async def test_pagination(tmp_path: Path) -> None:
    """When total > limit, additional calls are made with increasing offset."""
    git_rule_a = _make_git_rule("rule-a")
    git_rule_b = _make_git_rule("rule-b")
    config_dir = _write_config(tmp_path, [git_rule_a, git_rule_b])

    scm_a = _make_rule("rule-a")
    scm_b = _make_rule("rule-b")

    call_count = 0

    async def call_tool_paginated(tool_name: str, arguments: dict) -> MagicMock:
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        from mcp.types import TextContent

        if tool_name == "list_security_rules":
            offset = arguments.get("offset", 0)
            if offset == 0:
                # First page: only rule-a, but total says 2 rules exist
                data = {"data": [scm_a], "total": 2, "limit": 200, "offset": 0}
            else:
                # Second page: rule-b
                data = {"data": [scm_b], "total": 2, "limit": 200, "offset": 200}
            result.content = [TextContent(type="text", text=json.dumps(data))]
        else:
            result.content = [TextContent(type="text", text="{}")]
        return result

    mock_session = AsyncMock()
    mock_session.call_tool = call_tool_paginated

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await run_drift_check(config_dir)

    assert exit_code == 0
    # Must have made at least 2 calls (one per page)
    assert call_count >= 2


@pytest.mark.asyncio
async def test_mcp_connection_failure(tmp_path: Path) -> None:
    """connect_mcp_server returns None → exit 2."""
    git_rule = _make_git_rule("some-rule")
    config_dir = _write_config(tmp_path, [git_rule])

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = None
        exit_code = await run_drift_check(config_dir)

    assert exit_code == 2


@pytest.mark.asyncio
async def test_mcp_connection_failure_report(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Connection failure produces an ERROR result JSON on stdout."""
    git_rule = _make_git_rule("some-rule")
    config_dir = _write_config(tmp_path, [git_rule])

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = None
        await run_drift_check(config_dir)

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["result"] == "ERROR"


@pytest.mark.asyncio
async def test_tool_call_error(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """list_security_rules returns an error response → exit 2, result ERROR."""
    git_rule = _make_git_rule("some-rule")
    config_dir = _write_config(tmp_path, [git_rule])

    error_response = {"error": {"code": "SCM_API_ERROR", "message": "server error"}}
    mock_session = _make_session({"list_security_rules": error_response})

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await run_drift_check(config_dir)

    assert exit_code == 2

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["result"] == "ERROR"


@pytest.mark.asyncio
async def test_demo_mode_regression(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Demo mode: script executes without error and produces valid JSON report.

    This test simulates the demo fixtures returning a small set of rules.
    The exact drift count is not asserted here — see the module docstring for
    expected demo-mode output when run against the real firewall-configs/.
    """
    git_rule = _make_git_rule("demo-rule", action="allow", description="Demo rule")
    scm_rule = _make_rule("demo-rule", action="allow", description="Demo rule")

    config_dir = _write_config(tmp_path, [git_rule])
    mock_session = _make_session(
        {"list_security_rules": _rules_response([scm_rule])}
    )

    with patch("drift_check.connect_mcp_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_session
        exit_code = await run_drift_check(config_dir)

    # Script must exit 0 or 1 (not 2 = error)
    assert exit_code in (0, 1)

    # Must produce valid JSON on stdout
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert "result" in report
    assert "timestamp" in report
    assert "folders_checked" in report
    assert "total_discrepancies" in report
    assert report["result"] in ("NO_DRIFT", "DRIFT_DETECTED")
