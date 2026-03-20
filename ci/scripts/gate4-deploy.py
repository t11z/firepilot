"""Gate 4: Deploy validated firewall configuration to SCM and record via ITSM.

Workflow:
  1. Connect to mcp-strata-cloud-manager and mcp-itsm as stdio subprocesses.
  2. Parse firewall-configs/ to collect all rule files in {folder}/{position}/ order.
  3. For each rule: call create_security_rule, then add_audit_comment(candidate_written).
  4. Call push_candidate_config for all unique folders.
  5. Call add_audit_comment(push_initiated).
  6. Poll get_job_status until terminal (FIN/PUSHFAIL/PUSHABORT/PUSHTIMEOUT).
  7. On success: add_audit_comment(push_succeeded), update_change_request_status(deployed).
     On failure: add_audit_comment(push_failed), update_change_request_status(failed).

Usage:
    python ci/scripts/gate4-deploy.py \\
        --config-dir firewall-configs/ \\
        --ticket-id 42

Required environment variables:
    FIREPILOT_ENV           — must be "live"
    SCM_CLIENT_ID           — SCM OAuth2 client ID (live mode)
    SCM_CLIENT_SECRET       — SCM OAuth2 client secret (live mode)
    SCM_TSG_ID              — SCM tenant service group ID (live mode)
    ITSM_GITHUB_TOKEN       — GitHub PAT with issues:write scope (live mode)
    ITSM_GITHUB_REPO        — GitHub repo in owner/repo format (live mode)

Optional environment variables:
    SCM_PUSH_TIMEOUT_SECONDS — push job poll timeout in seconds (default 300)
    TICKET_ID               — fallback if --ticket-id not provided
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path

import yaml
from mcp import ClientSession
from mcp.types import CallToolResult, TextContent

sys.path.insert(0, str(Path(__file__).parent))
from mcp_connect import connect_mcp_server  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCM_MODULE = "mcp_strata_cloud_manager.server"
ITSM_MODULE = "mcp_itsm.server"
RULEBASE_MANIFEST = "_rulebase.yaml"

TERMINAL_JOB_STATUSES = frozenset({"FIN", "PUSHFAIL", "PUSHABORT", "PUSHTIMEOUT"})
JOB_POLL_INTERVAL_SECONDS = 10
DEFAULT_PUSH_TIMEOUT_SECONDS = 300

# ---------------------------------------------------------------------------
# Helpers
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
# Deployment workflow
# ---------------------------------------------------------------------------


async def run_deployment(
    scm: ClientSession,
    itsm: ClientSession,
    config_dir: Path,
    ticket_id: str,
    push_timeout: int,
) -> int:
    """Execute the full Gate 4 deployment workflow.

    Args:
        scm: Connected mcp-strata-cloud-manager session.
        itsm: Connected mcp-itsm session.
        config_dir: Root of the firewall-configs/ tree.
        ticket_id: ITSM ticket ID (GitHub issue number as string).
        push_timeout: Seconds to wait for push job to reach terminal state.

    Returns:
        0 on success, 1 on failure.
    """
    rules = discover_rules(config_dir)
    if not rules:
        print(f"WARNING: No rules found under '{config_dir}'")
        return 0

    folders_deployed: list[str] = []

    # Step 3: Create each rule and record via ITSM
    for folder, position, rule in rules:
        rule_name = rule.get("name", "<unknown>")
        print(f"Creating rule '{rule_name}' in {folder}/{position} ...")

        create_args = _build_create_rule_args(ticket_id, folder, position, rule)
        create_result = await _call(scm, "create_security_rule", **create_args)

        if "error" in create_result:
            err = create_result["error"]
            error_detail = (
                f"create_security_rule failed for '{rule_name}': "
                f"{err.get('message', err)}"
            )
            print(f"ERROR: {error_detail}", file=sys.stderr)

            # Record failure via ITSM before aborting
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
            return 1

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

    # Step 4: Push candidate config
    print(f"\nPushing candidate config for folders: {folders_deployed} ...")
    push_result = await _call(
        scm,
        "push_candidate_config",
        ticket_id=ticket_id,
        folders=folders_deployed,
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
        return 1

    job_id = push_result.get("job_id", "")
    print(f"  Push job initiated — job_id={job_id}")

    # Step 5: Record push initiated
    await _call(
        itsm,
        "add_audit_comment",
        change_request_id=ticket_id,
        event="push_initiated",
        detail=f"Candidate config push initiated for folders: {folders_deployed}.",
        scm_reference=job_id,
    )

    # Step 6: Poll job until terminal
    deadline = time.monotonic() + push_timeout
    status_str = push_result.get("status_str", "")
    result_str = push_result.get("result_str", "")

    while status_str not in TERMINAL_JOB_STATUSES:
        if time.monotonic() >= deadline:
            timeout_detail = (
                f"Push job '{job_id}' did not reach terminal state within "
                f"{push_timeout}s. Last status: {status_str!r}"
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
            return 1

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
            return 1

        job_data = job_response.get("data", [{}])
        if job_data:
            status_str = job_data[0].get("status_str", status_str)
            result_str = job_data[0].get("result_str", result_str)

    print(f"  Job terminal — status={status_str!r} result={result_str!r}")

    # Step 7: Record outcome
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
        return 0
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
        return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def async_main(config_dir: Path, ticket_id: str) -> int:
    """Connect to both MCP servers and run the deployment workflow."""
    firepilot_env = os.environ.get("FIREPILOT_ENV", "demo")
    push_timeout = int(
        os.environ.get("SCM_PUSH_TIMEOUT_SECONDS", str(DEFAULT_PUSH_TIMEOUT_SECONDS))
    )
    env_overrides = {"FIREPILOT_ENV": firepilot_env}

    async with AsyncExitStack() as stack:
        scm = await connect_mcp_server(stack, SCM_MODULE, env_overrides)
        itsm = await connect_mcp_server(stack, ITSM_MODULE, env_overrides)

        if scm is None:
            print(
                "ERROR: Failed to connect to mcp-strata-cloud-manager.",
                file=sys.stderr,
            )
            return 1
        if itsm is None:
            print("ERROR: Failed to connect to mcp-itsm.", file=sys.stderr)
            return 1

        return await run_deployment(scm, itsm, config_dir, ticket_id, push_timeout)


def main() -> None:
    """Parse arguments and run the async deployment."""
    parser = argparse.ArgumentParser(
        description="Gate 4: Deploy validated firewall config to SCM via MCP."
    )
    parser.add_argument(
        "--config-dir",
        required=True,
        type=Path,
        help="Root directory of firewall-configs/.",
    )
    parser.add_argument(
        "--ticket-id",
        default=None,
        help="ITSM ticket ID (overrides TICKET_ID env var).",
    )
    args = parser.parse_args()

    ticket_id: str = args.ticket_id or os.environ.get("TICKET_ID", "")
    if not ticket_id:
        print(
            "ERROR: --ticket-id argument or TICKET_ID environment variable is required.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.config_dir.is_dir():
        print(
            f"ERROR: --config-dir '{args.config_dir}' is not a directory.",
            file=sys.stderr,
        )
        sys.exit(1)

    exit_code = asyncio.run(async_main(args.config_dir, ticket_id))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
