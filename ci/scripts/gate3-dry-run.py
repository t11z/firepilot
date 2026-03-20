"""Gate 3: Dry-run validation against the live SCM API.

Parses firewall-configs/ to find all {folder}/{position}/ directories, then
calls mcp-strata-cloud-manager read tools to verify:
  1. Every zone referenced in 'from' and 'to' exists in SCM.
  2. Every address in 'source' and 'destination' that is not 'any' or a CIDR
     exists as an address object in SCM.
  3. No existing rule in the same folder/position already uses the same name.

Does NOT write anything. Exits 0 if all checks pass, 1 if any violations found.

Usage:
    python ci/scripts/gate3-dry-run.py --config-dir firewall-configs/

Required environment variables:
    FIREPILOT_ENV  — must be "live" (demo mode is handled by gate3-dry-run.sh)

SCM credentials (live mode only — inherited from environment per ADR-0006):
    SCM_CLIENT_ID, SCM_CLIENT_SECRET, SCM_TSG_ID
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import yaml
from mcp import ClientSession
from mcp.types import CallToolResult, TextContent

# Allow importing mcp_connect from the same directory
sys.path.insert(0, str(Path(__file__).parent))
from mcp_connect import connect_mcp_server  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCM_MODULE = "mcp_strata_cloud_manager.server"
RULEBASE_MANIFEST = "_rulebase.yaml"

TERMINAL_STATUSES = frozenset({"FIN", "PUSHFAIL", "PUSHABORT", "PUSHTIMEOUT"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_cidr_or_any(value: str) -> bool:
    """Return True if value is 'any' or a valid IPv4/IPv6 CIDR or host address."""
    if value.lower() == "any":
        return True
    try:
        ipaddress.ip_network(value, strict=False)
        return True
    except ValueError:
        return False


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


async def _call(session: ClientSession, tool: str, **kwargs) -> dict:
    """Call an MCP tool and return the parsed JSON result dict."""
    result: CallToolResult = await session.call_tool(tool, arguments=kwargs)
    return _result_to_dict(result)


# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------


def discover_rule_dirs(config_dir: Path) -> list[tuple[str, str, Path]]:
    """Yield (folder, position, dir_path) for each {folder}/{position}/ directory.

    Args:
        config_dir: Root of the firewall-configs/ tree.

    Returns:
        List of (folder_name, position_name, directory_path) tuples.
    """
    results: list[tuple[str, str, Path]] = []
    for folder_dir in sorted(config_dir.iterdir()):
        if not folder_dir.is_dir():
            continue
        for position_dir in sorted(folder_dir.iterdir()):
            if not position_dir.is_dir():
                continue
            manifest = position_dir / RULEBASE_MANIFEST
            if not manifest.exists():
                continue
            results.append((folder_dir.name, position_dir.name, position_dir))
    return results


def load_rule_files(position_dir: Path) -> list[dict]:
    """Load all rule YAML files (excluding _rulebase.yaml) from a position dir.

    Args:
        position_dir: The {folder}/{position}/ directory.

    Returns:
        List of parsed YAML dicts for each rule file.
    """
    rules: list[dict] = []
    for yaml_file in sorted(position_dir.glob("*.yaml")):
        if yaml_file.name == RULEBASE_MANIFEST:
            continue
        with yaml_file.open() as fh:
            data = yaml.safe_load(fh)
        if isinstance(data, dict):
            data["_source_file"] = str(yaml_file)
            rules.append(data)
    return rules


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------


async def validate_zones(
    session: ClientSession,
    folder: str,
    rule: dict,
    violations: list[str],
) -> None:
    """Check that all zones in 'from' and 'to' exist in SCM.

    Args:
        session: Connected SCM MCP session.
        folder: SCM folder scope.
        rule: Parsed rule YAML dict.
        violations: Mutable list to append violation messages to.
    """
    response = await _call(session, "list_security_zones", folder=folder)
    if "error" in response:
        violations.append(
            f"FAIL  [{rule['name']}] list_security_zones error: "
            f"{response['error'].get('message', response['error'])}"
        )
        return

    known_zones: set[str] = {z["name"] for z in response.get("data", [])}

    for direction, field in [("from", "from"), ("to", "to")]:
        for zone in rule.get(field, []):
            if zone not in known_zones:
                violations.append(
                    f"FAIL  [{rule['name']}] Unknown zone '{zone}' in '{direction}' "
                    f"(folder={folder})"
                )
            else:
                print(f"PASS  [{rule['name']}] Zone '{zone}' ({direction}) exists")


async def validate_addresses(
    session: ClientSession,
    folder: str,
    rule: dict,
    violations: list[str],
) -> None:
    """Check that address references in source/destination exist in SCM.

    Skips values that are 'any' or CIDR notation (those are not address objects).

    Args:
        session: Connected SCM MCP session.
        folder: SCM folder scope.
        rule: Parsed rule YAML dict.
        violations: Mutable list to append violation messages to.
    """
    response = await _call(session, "list_addresses", folder=folder)
    if "error" in response:
        violations.append(
            f"FAIL  [{rule['name']}] list_addresses error: "
            f"{response['error'].get('message', response['error'])}"
        )
        return

    known_addrs: set[str] = {a["name"] for a in response.get("data", [])}

    for field in ("source", "destination"):
        for addr in rule.get(field, []):
            if _is_cidr_or_any(addr):
                print(
                    f"PASS  [{rule['name']}] Address '{addr}' ({field}) is CIDR/any — skipped"
                )
                continue
            if addr not in known_addrs:
                violations.append(
                    f"FAIL  [{rule['name']}] Unknown address object '{addr}' in '{field}' "
                    f"(folder={folder})"
                )
            else:
                print(f"PASS  [{rule['name']}] Address '{addr}' ({field}) exists")


async def validate_name_conflicts(
    session: ClientSession,
    folder: str,
    position: str,
    rules: list[dict],
    violations: list[str],
) -> None:
    """Check that no proposed rule name already exists in SCM.

    Args:
        session: Connected SCM MCP session.
        folder: SCM folder scope.
        position: Rule position ('pre' or 'post').
        rules: List of parsed rule dicts to check.
        violations: Mutable list to append violation messages to.
    """
    response = await _call(
        session, "list_security_rules", folder=folder, position=position
    )
    if "error" in response:
        violations.append(
            f"FAIL  [folder={folder}/{position}] list_security_rules error: "
            f"{response['error'].get('message', response['error'])}"
        )
        return

    existing_names: set[str] = {r["name"] for r in response.get("data", [])}

    for rule in rules:
        name = rule.get("name", "")
        if name in existing_names:
            violations.append(
                f"FAIL  [{name}] Rule name conflict: '{name}' already exists "
                f"in SCM folder={folder}/{position}"
            )
        else:
            print(f"PASS  [{name}] No name conflict in {folder}/{position}")


# ---------------------------------------------------------------------------
# Main validation runner
# ---------------------------------------------------------------------------


async def run_validation(config_dir: Path) -> int:
    """Connect to SCM and validate all rule files in config_dir.

    Args:
        config_dir: Root of the firewall-configs/ tree.

    Returns:
        0 if all checks pass, 1 if any violations found or on error.
    """
    firepilot_env = os.environ.get("FIREPILOT_ENV", "demo")
    env_overrides = {"FIREPILOT_ENV": firepilot_env}

    violations: list[str] = []

    async with AsyncExitStack() as stack:
        session = await connect_mcp_server(stack, SCM_MODULE, env_overrides)
        if session is None:
            print(
                "ERROR: Failed to connect to mcp-strata-cloud-manager. "
                "Check that the MCP server package is installed and credentials are set.",
                file=sys.stderr,
            )
            return 1

        rule_dirs = discover_rule_dirs(config_dir)
        if not rule_dirs:
            print(f"WARNING: No rule directories found under '{config_dir}'")
            return 0

        for folder, position, position_dir in rule_dirs:
            print(f"\n--- Validating {folder}/{position} ---")
            rules = load_rule_files(position_dir)

            if not rules:
                print(f"  No rule files found in {position_dir}")
                continue

            # Check name conflicts once per folder/position
            try:
                await validate_name_conflicts(
                    session, folder, position, rules, violations
                )
            except Exception as exc:  # noqa: BLE001
                violations.append(
                    f"FAIL  [folder={folder}/{position}] "
                    f"name conflict check failed: {exc}"
                )

            # Check each rule's zones and addresses
            for rule in rules:
                rule_name = rule.get("name", "<unknown>")
                print(f"  Checking rule: {rule_name}")

                try:
                    await validate_zones(session, folder, rule, violations)
                except Exception as exc:  # noqa: BLE001
                    violations.append(
                        f"FAIL  [{rule_name}] zone validation failed: {exc}"
                    )

                try:
                    await validate_addresses(session, folder, rule, violations)
                except Exception as exc:  # noqa: BLE001
                    violations.append(
                        f"FAIL  [{rule_name}] address validation failed: {exc}"
                    )

    print("\n--- Summary ---")
    if violations:
        print(f"Violations found ({len(violations)}):")
        for v in violations:
            print(f"  {v}")
        return 1

    print("All checks passed.")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments and run the async validation."""
    parser = argparse.ArgumentParser(
        description="Gate 3: Dry-run validation of firewall config against live SCM."
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
        sys.exit(1)

    exit_code = asyncio.run(run_validation(args.config_dir))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
