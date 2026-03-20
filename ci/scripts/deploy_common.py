"""Shared deployment logic for FirePilot Gate 4 and retry-deploy workflows.

Provides the rule-creation loop and push/poll cycle used by both
gate4-deploy.py (original Gate 4 deployment) and retry-deploy.py
(push retry workflow for failed deployments).

Functions:
    discover_rules: Read rule files from config_dir in manifest order.
    create_rules_from_config: Create rules in SCM candidate config with
        optional E006 conflict tolerance.
    push_and_poll: Push candidate config, poll until terminal state, and
        record ITSM audit events.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import yaml
from mcp import ClientSession
from mcp.types import CallToolResult, TextContent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RULEBASE_MANIFEST = "_rulebase.yaml"

TERMINAL_JOB_STATUSES = frozenset({"FIN", "PUSHFAIL", "PUSHABORT", "PUSHTIMEOUT"})
JOB_POLL_INTERVAL_SECONDS = 10
DEFAULT_PUSH_TIMEOUT_SECONDS = 300

# SCM API error code for API-level errors
SCM_API_ERROR_CODE = "SCM_API_ERROR"

# SCM rule name conflict error code (Name Not Unique)
NAME_NOT_UNIQUE_CODE = "E006"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _result_to_dict(result: CallToolResult) -> dict:
    """Extract JSON from a CallToolResult, returning an empty dict on parse failure."""
    text_parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            text_parts.append(block.text)
    raw = "\n".join(text_parts)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


async def _call(session: ClientSession, tool: str, **kwargs) -> dict:
    """Call an MCP tool and return the parsed JSON result dict."""
    result: CallToolResult = await session.call_tool(tool, arguments=kwargs)
    return _result_to_dict(result)


def _is_name_conflict_error(err: dict) -> bool:
    """Return True if the error is a Name Not Unique (E006) SCM API error.

    Checks both the error message and scm_error_codes fields for E006.

    Args:
        err: Error dict extracted from a failed MCP tool call result.

    Returns:
        True if the error code is SCM_API_ERROR and E006 appears in the
        message or scm_error_codes list.
    """
    if err.get("code") != SCM_API_ERROR_CODE:
        return False
    message = err.get("message", "")
    if NAME_NOT_UNIQUE_CODE in message:
        return True
    scm_codes = err.get("scm_error_codes", [])
    if isinstance(scm_codes, list) and NAME_NOT_UNIQUE_CODE in scm_codes:
        return True
    return False


# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------


def discover_rules(config_dir: Path) -> list[tuple[str, str, dict]]:
    """Discover all rules in deployment order from config_dir.

    Reads each _rulebase.yaml manifest to determine rule ordering, then loads
    the corresponding rule files. Returns list of (folder, position, rule_dict).

    Args:
        config_dir: Root of the firewall-configs/ tree.

    Returns:
        Ordered list of (folder, position, rule_yaml_dict) tuples.
    """
    results: list[tuple[str, str, dict]] = []

    for folder_dir in sorted(config_dir.iterdir()):
        if not folder_dir.is_dir():
            continue
        for position_dir in sorted(folder_dir.iterdir()):
            if not position_dir.is_dir():
                continue
            manifest_path = position_dir / RULEBASE_MANIFEST
            if not manifest_path.exists():
                continue

            with manifest_path.open() as fh:
                manifest = yaml.safe_load(fh)

            folder = folder_dir.name
            position = position_dir.name
            rule_order: list[str] = manifest.get("rule_order", [])

            for rule_name in rule_order:
                rule_file = position_dir / f"{rule_name}.yaml"
                if not rule_file.exists():
                    print(
                        f"WARNING: Rule file '{rule_file}' listed in manifest but not found",
                        file=sys.stderr,
                    )
                    continue
                with rule_file.open() as fh:
                    rule_data = yaml.safe_load(fh)
                if isinstance(rule_data, dict):
                    results.append((folder, position, rule_data))

    return results


def _build_create_rule_args(
    ticket_id: str, folder: str, position: str, rule: dict
) -> dict:
    """Map YAML rule fields to create_security_rule tool parameters.

    'from' and 'to' YAML fields map to from_zones and to_zones (ADR-0004).
    folder and position are derived from directory structure, not YAML (ADR-0007).

    Args:
        ticket_id: ITSM ticket reference.
        folder: SCM folder derived from directory name.
        position: SCM position derived from directory name.
        rule: Parsed YAML rule dict.

    Returns:
        Dict of keyword arguments for the create_security_rule tool call.
    """
    args: dict = {
        "ticket_id": ticket_id,
        "folder": folder,
        "position": position,
        "name": rule.get("name", ""),
        "action": rule.get("action", "allow"),
        "from_zones": rule.get("from", []),
        "to_zones": rule.get("to", []),
        "source": rule.get("source", []),
        "source_user": rule.get("source_user", ["any"]),
        "destination": rule.get("destination", []),
        "service": rule.get("service", []),
        "application": rule.get("application", []),
        "category": rule.get("category", ["any"]),
        "tag": rule.get("tag", []),
        "disabled": rule.get("disabled", False),
        "negate_source": rule.get("negate_source", False),
        "negate_destination": rule.get("negate_destination", False),
        "log_start": rule.get("log_start", False),
        "log_end": rule.get("log_end", True),
    }
    # Optional fields — only include when present in YAML
    for optional in (
        "description",
        "schedule",
        "source_hip",
        "destination_hip",
        "log_setting",
    ):
        if optional in rule:
            args[optional] = rule[optional]

    profile_setting = rule.get("profile_setting", {})
    if isinstance(profile_setting, dict) and "group" in profile_setting:
        args["profile_setting_group"] = profile_setting["group"]

    return args


# ---------------------------------------------------------------------------
# Shared deployment functions
# ---------------------------------------------------------------------------


async def create_rules_from_config(
    scm: ClientSession,
    itsm: ClientSession,
    config_dir: Path,
    ticket_id: str,
    tolerate_name_conflict: bool = False,
) -> list[str] | None:
    """Create all firewall rules from config_dir in SCM candidate config.

    For each rule discovered in manifest order:
    - Calls create_security_rule on the SCM session.
    - If tolerate_name_conflict is True, a Name Not Unique (E006) error is
      treated as success — the rule already exists in candidate config.
    - Any other error records push_failed + failed status via ITSM and
      returns None to signal failure.
    - On success, records candidate_written via ITSM.

    Args:
        scm: Connected mcp-strata-cloud-manager session.
        itsm: Connected mcp-itsm session.
        config_dir: Root of the firewall-configs/ tree.
        ticket_id: ITSM ticket ID (GitHub issue number as string).
        tolerate_name_conflict: When True, E006 (Name Not Unique) errors on
            create_security_rule are treated as success. Use for retry
            deployments where rules may already be in candidate config.

    Returns:
        List of unique folder names that had rules created, or None on failure
        (ITSM already updated with push_failed and failed status).
    """
    rules = discover_rules(config_dir)
    if not rules:
        print(f"WARNING: No rules found under '{config_dir}'")
        return []

    folders_deployed: list[str] = []

    for folder, position, rule in rules:
        rule_name = rule.get("name", "<unknown>")
        print(f"Creating rule '{rule_name}' in {folder}/{position} ...")

        create_args = _build_create_rule_args(ticket_id, folder, position, rule)
        create_result = await _call(scm, "create_security_rule", **create_args)

        if "error" in create_result:
            err = create_result["error"]

            if tolerate_name_conflict and _is_name_conflict_error(err):
                print(
                    f"  NOTICE: Rule '{rule_name}' already exists in candidate config "
                    f"(E006 Name Not Unique) — treating as success."
                )
                if folder not in folders_deployed:
                    folders_deployed.append(folder)
                continue

            error_detail = (
                f"create_security_rule failed for '{rule_name}': "
                f"{err.get('message', err)}"
            )
            print(f"ERROR: {error_detail}", file=sys.stderr)

            await _call(
                itsm,
                "add_audit_comment",
                change_request_id=ticket_id,
                event="push_failed",
                detail=error_detail,
            )
            await _call(
                itsm,
                "update_change_request_status",
                change_request_id=ticket_id,
                status="failed",
            )
            return None

        rule_uuid = create_result.get("id", "")
        print(f"  Rule '{rule_name}' created — SCM id={rule_uuid}")

        await _call(
            itsm,
            "add_audit_comment",
            change_request_id=ticket_id,
            event="candidate_written",
            detail=f"Rule '{rule_name}' written to candidate config in {folder}/{position}.",
            scm_reference=rule_uuid,
        )

        if folder not in folders_deployed:
            folders_deployed.append(folder)

    return folders_deployed


async def push_and_poll(
    scm: ClientSession,
    itsm: ClientSession,
    ticket_id: str,
    folders: list[str],
    timeout_seconds: int,
) -> bool:
    """Push candidate config and poll until terminal state. Records ITSM events.

    Pushes the candidate config for the given folders, records push_initiated,
    then polls get_job_status until a terminal state is reached. Records
    push_succeeded or push_failed and updates the change request status.

    Args:
        scm: Connected mcp-strata-cloud-manager session.
        itsm: Connected mcp-itsm session.
        ticket_id: ITSM ticket ID.
        folders: SCM folders to push.
        timeout_seconds: Seconds to wait for push job to reach terminal state.

    Returns:
        True on successful push (result_str == "OK"), False on any failure
        (ITSM already updated with push_failed and failed status).
    """
    print(f"\nPushing candidate config for folders: {folders} ...")
    push_result = await _call(
        scm,
        "push_candidate_config",
        ticket_id=ticket_id,
        folders=folders,
    )

    if "error" in push_result:
        err = push_result["error"]
        error_detail = f"push_candidate_config failed: {err.get('message', err)}"
        print(f"ERROR: {error_detail}", file=sys.stderr)
        await _call(
            itsm,
            "add_audit_comment",
            change_request_id=ticket_id,
            event="push_failed",
            detail=error_detail,
        )
        await _call(
            itsm,
            "update_change_request_status",
            change_request_id=ticket_id,
            status="failed",
        )
        return False

    job_id = push_result.get("job_id", "")
    print(f"  Push job initiated — job_id={job_id}")

    await _call(
        itsm,
        "add_audit_comment",
        change_request_id=ticket_id,
        event="push_initiated",
        detail=f"Candidate config push initiated for folders: {folders}.",
        scm_reference=job_id,
    )

    # Poll job until terminal state
    deadline = time.monotonic() + timeout_seconds
    status_str = push_result.get("status_str", "")
    result_str = push_result.get("result_str", "")

    while status_str not in TERMINAL_JOB_STATUSES:
        if time.monotonic() >= deadline:
            timeout_detail = (
                f"Push job '{job_id}' did not reach terminal state within "
                f"{timeout_seconds}s. Last status: {status_str!r}"
            )
            print(f"ERROR: {timeout_detail}", file=sys.stderr)
            await _call(
                itsm,
                "add_audit_comment",
                change_request_id=ticket_id,
                event="push_failed",
                detail=timeout_detail,
                scm_reference=job_id,
            )
            await _call(
                itsm,
                "update_change_request_status",
                change_request_id=ticket_id,
                status="failed",
            )
            return False

        print(f"  Job status: {status_str!r} — polling in {JOB_POLL_INTERVAL_SECONDS}s ...")
        await asyncio.sleep(JOB_POLL_INTERVAL_SECONDS)

        job_response = await _call(scm, "get_job_status", job_id=job_id)
        if "error" in job_response:
            err = job_response["error"]
            error_detail = f"get_job_status failed: {err.get('message', err)}"
            print(f"ERROR: {error_detail}", file=sys.stderr)
            await _call(
                itsm,
                "add_audit_comment",
                change_request_id=ticket_id,
                event="push_failed",
                detail=error_detail,
                scm_reference=job_id,
            )
            await _call(
                itsm,
                "update_change_request_status",
                change_request_id=ticket_id,
                status="failed",
            )
            return False

        job_data = job_response.get("data", [{}])
        if job_data:
            status_str = job_data[0].get("status_str", status_str)
            result_str = job_data[0].get("result_str", result_str)

    print(f"  Job terminal — status={status_str!r} result={result_str!r}")

    if result_str == "OK":
        await _call(
            itsm,
            "add_audit_comment",
            change_request_id=ticket_id,
            event="push_succeeded",
            detail=f"Push job '{job_id}' completed successfully (status={status_str}).",
            scm_reference=job_id,
        )
        await _call(
            itsm,
            "update_change_request_status",
            change_request_id=ticket_id,
            status="deployed",
        )
        print("\nDeployment succeeded.")
        return True
    else:
        failure_detail = (
            f"Push job '{job_id}' ended with status={status_str!r} "
            f"result={result_str!r}"
        )
        await _call(
            itsm,
            "add_audit_comment",
            change_request_id=ticket_id,
            event="push_failed",
            detail=failure_detail,
            scm_reference=job_id,
        )
        await _call(
            itsm,
            "update_change_request_status",
            change_request_id=ticket_id,
            status="failed",
        )
        print(f"\nERROR: Deployment failed — {failure_detail}", file=sys.stderr)
        return False
