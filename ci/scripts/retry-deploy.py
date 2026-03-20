"""Retry a failed Gate 4 deployment.

Re-creates all firewall rules from the current config directory (tolerating
Name Not Unique / E006 conflicts — rules may already be in candidate config
from the failed attempt) and re-pushes the candidate config to running config.

This implements the push retry mechanism defined in ADR-0011. It is triggered
by the firepilot:retry-deploy label on the original change request issue.
Gate 1–3 validation is not re-run — the configuration was already validated
before the original merge.

Usage:
    python ci/scripts/retry-deploy.py \\
        --config-dir firewall-configs/ \\
        --ticket-id 42

Required environment variables:
    FIREPILOT_ENV           — "live" or "demo"
    SCM_CLIENT_ID           — SCM OAuth2 client ID (live mode)
    SCM_CLIENT_SECRET       — SCM OAuth2 client secret (live mode)
    SCM_TSG_ID              — SCM tenant service group ID (live mode)
    ITSM_GITHUB_TOKEN       — GitHub PAT with issues:write scope (live mode)
    ITSM_GITHUB_REPO        — GitHub repo in owner/repo format (live mode)

Optional environment variables:
    SCM_PUSH_TIMEOUT_SECONDS — push job poll timeout in seconds (default 300)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession

sys.path.insert(0, str(Path(__file__).parent))
from deploy_common import (  # noqa: E402
    DEFAULT_PUSH_TIMEOUT_SECONDS,
    create_rules_from_config,
    push_and_poll,
)
from mcp_connect import connect_mcp_server  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCM_MODULE = "mcp_strata_cloud_manager.server"
ITSM_MODULE = "mcp_itsm.server"

# ---------------------------------------------------------------------------
# Retry deployment workflow
# ---------------------------------------------------------------------------


async def run_retry(
    scm: ClientSession,
    itsm: ClientSession,
    config_dir: Path,
    ticket_id: str,
    push_timeout: int,
) -> int:
    """Execute the retry deployment workflow.

    Re-creates rules with E006 conflict tolerance (rules may already be in
    candidate config from the failed Gate 4 run) then pushes candidate config.

    Args:
        scm: Connected mcp-strata-cloud-manager session.
        itsm: Connected mcp-itsm session.
        config_dir: Root of the firewall-configs/ tree.
        ticket_id: ITSM ticket ID (GitHub issue number as string).
        push_timeout: Seconds to wait for push job to reach terminal state.

    Returns:
        0 on success, 1 on failure.
    """
    folders = await create_rules_from_config(
        scm, itsm, config_dir, ticket_id, tolerate_name_conflict=True
    )
    if folders is None:
        return 1
    if not folders:
        print(f"WARNING: No rules found under '{config_dir}'")
        return 0

    success = await push_and_poll(scm, itsm, ticket_id, folders, push_timeout)
    return 0 if success else 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def async_main(config_dir: Path, ticket_id: str) -> int:
    """Connect to both MCP servers and run the retry deployment workflow."""
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

        return await run_retry(scm, itsm, config_dir, ticket_id, push_timeout)


def main() -> None:
    """Parse arguments and run the async retry deployment."""
    parser = argparse.ArgumentParser(
        description="Retry a failed Gate 4 deployment via MCP."
    )
    parser.add_argument(
        "--config-dir",
        required=True,
        type=Path,
        help="Root directory of firewall-configs/.",
    )
    parser.add_argument(
        "--ticket-id",
        required=True,
        help="ITSM ticket ID (GitHub issue number).",
    )
    args = parser.parse_args()

    if not args.config_dir.is_dir():
        print(
            f"ERROR: --config-dir '{args.config_dir}' is not a directory.",
            file=sys.stderr,
        )
        sys.exit(1)

    exit_code = asyncio.run(async_main(args.config_dir, args.ticket_id))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
