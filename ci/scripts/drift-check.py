"""Drift detection: compare Git-declared firewall config against live SCM state.

Reads all {folder}/{position}/ directories under --config-dir, fetches the
corresponding live (or demo) SCM security rules via mcp-strata-cloud-manager,
and compares them field-by-field. Produces a JSON drift report on stdout and
a human-readable summary on stderr.

Usage:
    python ci/scripts/drift-check.py --config-dir firewall-configs/

Required environment variables:
    FIREPILOT_ENV  — "live" or "demo"

SCM credentials (live mode only — inherited from environment per ADR-0006):
    SCM_CLIENT_ID, SCM_CLIENT_SECRET, SCM_TSG_ID

Exit codes:
    0 — no drift detected
    1 — drift detected (one or more discrepancies found)
    2 — error (MCP connection failure or tool call failure)

Demo mode behaviour
-------------------
When FIREPILOT_ENV=demo the script connects to mcp-strata-cloud-manager in
demo mode, which returns fixture data from
mcp-servers/mcp-strata-cloud-manager/src/mcp_strata_cloud_manager/fixtures/strata.py.

The fixture data and the Git YAML files in firewall-configs/ are intentionally
different — the fixtures represent a historical SCM state while the YAML
descriptions were written independently. Expected demo-mode output:

  shared/pre:
    - allow-web-to-app: modified_externally
        description: "Permit HTTPS traffic..." (Git) vs "Allow web tier..." (SCM)
        disabled: None (not set in YAML) vs False (explicit in SCM response)
    - allow-app-to-db: modified_externally
        description: "Permit MySQL traffic..." (Git) vs "Allow application tier..." (SCM)
        disabled: None vs False
    - deny-direct-db-access: modified_externally
        description: "Block all direct access..." (Git) vs "Block direct access..." (SCM)
        disabled: None vs False

  shared/post:
    - default-deny-all: missing_from_scm
        (FIXTURE_SECURITY_RULES_POST is empty — the post rulebase has no fixture rules)

  total_discrepancies: 4, result: "DRIFT_DETECTED", exit code: 1

This is expected behaviour for the demo. It exercises all comparison code paths
and validates that the script connects, paginates, compares, and reports correctly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path

import yaml
from mcp import ClientSession
from mcp.types import CallToolResult, TextContent

# Allow importing local modules from the same directory
sys.path.insert(0, str(Path(__file__).parent))
from config_discovery import RULEBASE_MANIFEST, discover_rule_dirs, load_rule_files  # noqa: E402
from mcp_connect import connect_mcp_server  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCM_MODULE = "mcp_strata_cloud_manager.server"
FIREPILOT_TAG = "firepilot-managed"
DEFAULT_LIMIT = 200

#: Fields compared between Git YAML and SCM live state (per ADR-0011).
COMPARED_FIELDS: list[str] = [
    "name",
    "action",
    "from",
    "to",
    "source",
    "source_user",
    "destination",
    "service",
    "application",
    "category",
    "disabled",
    "description",
    "tag",
    "negate_source",
    "negate_destination",
    "log_start",
    "log_end",
]

#: Fields whose values are unordered sets — compared after sorting.
_LIST_FIELDS: frozenset[str] = frozenset(
    {
        "from",
        "to",
        "source",
        "source_user",
        "destination",
        "service",
        "application",
        "category",
        "tag",
    }
)

#: Boolean fields whose absence in Git YAML implies False (the SCM default).
#: Treating None and False as equivalent for these fields avoids false-positive
#: drift reports when the YAML omits the field because it is the default value.
_BOOL_DEFAULT_FALSE: frozenset[str] = frozenset({"disabled"})

# ---------------------------------------------------------------------------
# MCP call helper
# ---------------------------------------------------------------------------


def _result_to_dict(result: CallToolResult) -> dict:
    """Extract JSON from a CallToolResult, returning an empty dict on failure."""
    text_parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            text_parts.append(block.text)
    raw = "\n".join(text_parts)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


async def _call(session: ClientSession, tool: str, **kwargs: object) -> dict:
    """Call an MCP tool and return the parsed JSON result dict."""
    result: CallToolResult = await session.call_tool(tool, arguments=kwargs)
    return _result_to_dict(result)


# ---------------------------------------------------------------------------
# Field comparison
# ---------------------------------------------------------------------------


def _normalize(field: str, value: object) -> object:
    """Normalize a field value for comparison.

    Two normalizations are applied:
    - List fields are sorted so that element order within a field does not
      produce false-positive drift reports.
    - Boolean fields that default to False in the SCM API are normalized so
      that an absent YAML key (None) compares equal to an explicit False from
      the SCM response, avoiding false-positive drift for fields that YAML
      authors routinely omit when accepting the default.
    """
    if isinstance(value, list) and field in _LIST_FIELDS:
        return sorted(str(v) for v in value)
    if value is None and field in _BOOL_DEFAULT_FALSE:
        return False
    return value


def compare_fields(git_rule: dict, scm_rule: dict) -> dict[str, dict[str, object]]:
    """Return a dict of field-level differences between git_rule and scm_rule.

    Only fields listed in COMPARED_FIELDS are examined. Each entry in the
    returned dict maps the field name to {"git": <git_value>, "scm": <scm_value>}.

    Args:
        git_rule: Rule dict loaded from Git YAML.
        scm_rule: Rule dict from SCM API response (raw JSON keys, e.g. "from").

    Returns:
        Dict of differing fields. Empty dict means no drift.
    """
    diffs: dict[str, dict[str, object]] = {}
    for field in COMPARED_FIELDS:
        git_val = _normalize(field, git_rule.get(field))
        scm_val = _normalize(field, scm_rule.get(field))
        if git_val != scm_val:
            diffs[field] = {"git": git_val, "scm": scm_val}
    return diffs


# ---------------------------------------------------------------------------
# SCM fetch with pagination
# ---------------------------------------------------------------------------


async def fetch_scm_rules(
    session: ClientSession,
    folder: str,
    position: str,
) -> list[dict]:
    """Fetch all security rules for a folder/position, handling pagination.

    Calls list_security_rules repeatedly with increasing offsets until all
    rules have been retrieved (total > DEFAULT_LIMIT pages).

    Args:
        session: Connected SCM MCP session.
        folder: SCM folder scope (e.g. "shared").
        position: Rule position ("pre" or "post").

    Returns:
        Full list of rule dicts from the SCM API.

    Raises:
        RuntimeError: If list_security_rules returns an error response.
    """
    all_rules: list[dict] = []
    offset = 0

    while True:
        response = await _call(
            session,
            "list_security_rules",
            folder=folder,
            position=position,
            limit=DEFAULT_LIMIT,
            offset=offset,
        )

        if "error" in response:
            err = response["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise RuntimeError(f"list_security_rules error for {folder}/{position}: {msg}")

        batch: list[dict] = response.get("data", [])
        all_rules.extend(batch)

        total: int = response.get("total", len(all_rules))
        if len(all_rules) >= total:
            break
        offset += DEFAULT_LIMIT

    return all_rules


# ---------------------------------------------------------------------------
# Per-folder/position drift check
# ---------------------------------------------------------------------------


async def check_folder_position(
    session: ClientSession,
    folder: str,
    position: str,
    position_dir: Path,
) -> dict:
    """Compare Git state against SCM state for one folder/position directory.

    Args:
        session: Connected SCM MCP session.
        folder: SCM folder name (e.g. "shared").
        position: Rule position ("pre" or "post").
        position_dir: Path to the {folder}/{position}/ directory in Git.

    Returns:
        A dict with keys: folder, position, git_rule_count, scm_rule_count,
        discrepancies (list of drift entries).

    Raises:
        RuntimeError: Propagated from fetch_scm_rules on API errors.
    """
    # --- Load Git state ---
    manifest_path = position_dir / RULEBASE_MANIFEST
    manifest_data: dict = yaml.safe_load(manifest_path.read_text())
    git_rule_order: list[str] = manifest_data.get("rule_order", [])

    git_rules_list = load_rule_files(position_dir)
    git_rules: dict[str, dict] = {r["name"]: r for r in git_rules_list}

    # --- Fetch SCM state ---
    all_scm_rules = await fetch_scm_rules(session, folder, position)

    # Filter to rules that FirePilot owns (firepilot-managed tag)
    fp_scm_rules = [
        r for r in all_scm_rules if FIREPILOT_TAG in r.get("tag", [])
    ]
    scm_rules: dict[str, dict] = {r["name"]: r for r in fp_scm_rules}
    scm_rule_order: list[str] = [r["name"] for r in fp_scm_rules]

    # --- Compare rule sets ---
    discrepancies: list[dict] = []
    all_names = sorted(set(git_rules.keys()) | set(scm_rules.keys()))

    for name in all_names:
        in_git = name in git_rules
        in_scm = name in scm_rules

        if in_git and in_scm:
            diffs = compare_fields(git_rules[name], scm_rules[name])
            if diffs:
                discrepancies.append(
                    {
                        "rule_name": name,
                        "drift_type": "modified_externally",
                        "field_diffs": diffs,
                    }
                )
        elif in_git and not in_scm:
            discrepancies.append(
                {
                    "rule_name": name,
                    "drift_type": "missing_from_scm",
                }
            )
        else:
            # in_scm and not in_git
            discrepancies.append(
                {
                    "rule_name": name,
                    "drift_type": "orphan_in_scm",
                }
            )

    # --- Compare ordering (only when sets are identical) ---
    if set(git_rule_order) == set(scm_rule_order) and git_rule_order != scm_rule_order:
        discrepancies.append(
            {
                "drift_type": "order_drift",
                "git_order": git_rule_order,
                "scm_order": scm_rule_order,
            }
        )

    return {
        "folder": folder,
        "position": position,
        "git_rule_count": len(git_rules),
        "scm_rule_count": len(scm_rules),
        "discrepancies": discrepancies,
    }


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


async def run_drift_check(config_dir: Path) -> int:
    """Connect to SCM and compare all rule directories against live state.

    Args:
        config_dir: Root of the firewall-configs/ tree.

    Returns:
        0 if no drift, 1 if drift detected, 2 on connection/tool error.
    """
    firepilot_env = os.environ.get("FIREPILOT_ENV", "demo")
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with AsyncExitStack() as stack:
        session = await connect_mcp_server(
            stack, SCM_MODULE, {"FIREPILOT_ENV": firepilot_env}
        )

        if session is None:
            report = {
                "timestamp": timestamp,
                "mode": firepilot_env,
                "folders_checked": [],
                "total_discrepancies": 0,
                "result": "ERROR",
                "error": "Failed to connect to mcp-strata-cloud-manager",
            }
            print(json.dumps(report, indent=2))
            print(
                "ERROR: Failed to connect to mcp-strata-cloud-manager. "
                "Check that the MCP server package is installed and credentials are set.",
                file=sys.stderr,
            )
            return 2

        rule_dirs = discover_rule_dirs(config_dir)
        if not rule_dirs:
            print(f"WARNING: No rule directories found under '{config_dir}'", file=sys.stderr)
            report = {
                "timestamp": timestamp,
                "mode": firepilot_env,
                "folders_checked": [],
                "total_discrepancies": 0,
                "result": "NO_DRIFT",
            }
            print(json.dumps(report, indent=2))
            return 0

        folders_checked: list[dict] = []
        error_occurred = False

        for folder, position, position_dir in rule_dirs:
            print(f"Checking {folder}/{position} ...", file=sys.stderr)
            try:
                result = await check_folder_position(session, folder, position, position_dir)
                folders_checked.append(result)
            except RuntimeError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                folders_checked.append(
                    {
                        "folder": folder,
                        "position": position,
                        "git_rule_count": 0,
                        "scm_rule_count": 0,
                        "discrepancies": [
                            {"drift_type": "error", "message": str(exc)}
                        ],
                    }
                )
                error_occurred = True

    total_discrepancies = sum(len(f["discrepancies"]) for f in folders_checked)

    if error_occurred:
        result_status = "ERROR"
    elif total_discrepancies == 0:
        result_status = "NO_DRIFT"
    else:
        result_status = "DRIFT_DETECTED"

    report = {
        "timestamp": timestamp,
        "mode": firepilot_env,
        "folders_checked": folders_checked,
        "total_discrepancies": total_discrepancies,
        "result": result_status,
    }

    print(json.dumps(report, indent=2))

    # Human-readable summary to stderr for CI log readability
    print(f"\n--- Drift Detection Summary ---", file=sys.stderr)
    print(f"Mode:                {firepilot_env}", file=sys.stderr)
    print(f"Result:              {result_status}", file=sys.stderr)
    print(f"Total discrepancies: {total_discrepancies}", file=sys.stderr)
    for folder_result in folders_checked:
        folder = folder_result["folder"]
        position = folder_result["position"]
        count = len(folder_result["discrepancies"])
        if count:
            print(f"  {folder}/{position}: {count} discrepancy(ies)", file=sys.stderr)
            for d in folder_result["discrepancies"]:
                dtype = d.get("drift_type", "unknown")
                rname = d.get("rule_name", "")
                if rname:
                    print(f"    [{dtype}] {rname}", file=sys.stderr)
                else:
                    print(f"    [{dtype}]", file=sys.stderr)
        else:
            print(f"  {folder}/{position}: OK", file=sys.stderr)

    if error_occurred:
        return 2
    return 0 if total_discrepancies == 0 else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments and run the async drift check."""
    parser = argparse.ArgumentParser(
        description="Drift detection: compare Git firewall config against live SCM state."
    )
    parser.add_argument(
        "--config-dir",
        required=True,
        type=Path,
        help="Root directory of firewall-configs/.",
    )
    args = parser.parse_args()

    if not args.config_dir.is_dir():
        print(
            f"ERROR: --config-dir '{args.config_dir}' is not a directory.",
            file=sys.stderr,
        )
        sys.exit(2)

    exit_code = asyncio.run(run_drift_check(args.config_dir))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
