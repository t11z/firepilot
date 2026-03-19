"""Write tools for mcp-strata-cloud-manager.

Exposes create_security_rule as an MCP tool mapped to the SCM write API.
Enforces ticket_id server-side before any processing occurs.
Live mode raises NotImplementedError — demo mode only in this implementation.
"""

import time
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from mcp_strata_cloud_manager.config import get_settings
from mcp_strata_cloud_manager.fixtures.strata import (
    FIXTURE_CREATED_RULE_ID,
    FIXTURE_FOLDER,
)

logger = structlog.get_logger(__name__)

# Sentinel value returned when ticket enforcement rejects a call
MISSING_TICKET_REF_CODE = "MISSING_TICKET_REF"


def register_write_tools(mcp: FastMCP) -> None:
    """Register all write tools on the provided FastMCP server instance.

    Args:
        mcp: The FastMCP server instance to register tools on.
    """

    @mcp.tool()
    async def create_security_rule(
        ticket_id: str,
        folder: str,
        position: str = "pre",
        name: str = "",
        action: str = "allow",
        from_zones: list[str] | None = None,
        to_zones: list[str] | None = None,
        source: list[str] | None = None,
        source_user: list[str] | None = None,
        destination: list[str] | None = None,
        service: list[str] | None = None,
        application: list[str] | None = None,
        category: list[str] | None = None,
        description: str | None = None,
        disabled: bool = False,
        tag: list[str] | None = None,
        negate_source: bool = False,
        negate_destination: bool = False,
        source_hip: list[str] | None = None,
        destination_hip: list[str] | None = None,
        schedule: str | None = None,
        profile_setting_group: list[str] | None = None,
        log_setting: str | None = None,
        log_start: bool = False,
        log_end: bool = True,
    ) -> dict[str, Any]:
        """Create a security rule in SCM candidate configuration.

        Maps to: POST /config/security/v1/security-rules

        Enforces ticket_id server-side — calls without a non-empty ticket_id
        are rejected immediately with error code MISSING_TICKET_REF before
        any SCM interaction.

        The SCM API uses 'from' and 'to' as field names for zones. These are
        passed as from_zones and to_zones here (since 'from' is a Python
        reserved word) and serialized as 'from'/'to' in the response.

        Args:
            ticket_id: ITSM ticket reference (required, server-enforced).
            folder: Folder scope, max 64 chars (required).
            position: Rule position, 'pre' or 'post'. Default 'pre'.
            name: Rule name (required).
            action: Rule action: allow, deny, drop, reset-both, reset-client,
                    reset-server.
            from_zones: Source zone(s) — serialized as 'from' in response.
            to_zones: Destination zone(s) — serialized as 'to' in response.
            source: Source address(es).
            source_user: Source user(s); use ['any'] if unscoped.
            destination: Destination address(es).
            service: Service(s).
            application: Application(s).
            category: URL category filter; use ['any'] if unscoped.
            description: Optional rule description.
            disabled: Whether the rule is disabled. Default False.
            tag: Optional list of tags.
            negate_source: Negate source address match. Default False.
            negate_destination: Negate destination address match. Default False.
            source_hip: Source HIP profile(s).
            destination_hip: Destination HIP profile(s).
            schedule: Optional schedule object name.
            profile_setting_group: Security profile group name(s).
            log_setting: Log forwarding profile name.
            log_start: Log at session start. Default False.
            log_end: Log at session end. Default True.

        Returns:
            The created security rule echoed back with an assigned id field,
            or a structured error dict with code MISSING_TICKET_REF.
        """
        settings = get_settings()
        endpoint = "POST /config/security/v1/security-rules"
        start = time.monotonic()

        # Ticket enforcement — reject before any other processing
        if not ticket_id or not ticket_id.strip():
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "tool_call",
                tool_name="create_security_rule",
                mode=settings.firepilot_env,
                scm_endpoint=endpoint,
                folder=folder,
                outcome="rejected",
                http_status=None,
                duration_ms=duration_ms,
                ticket_id=ticket_id,
                rejection_code=MISSING_TICKET_REF_CODE,
                scm_request_id=None,
                error_codes=[],
            )
            return {
                "error": {
                    "code": MISSING_TICKET_REF_CODE,
                    "message": "ticket_id is required and must not be empty",
                }
            }

        try:
            if settings.firepilot_env == "live":
                raise NotImplementedError("Live mode not yet implemented")

            # Demo mode: echo back the input as a SecurityRule with assigned id
            rule: dict[str, Any] = {
                "id": FIXTURE_CREATED_RULE_ID,
                "name": name,
                "folder": FIXTURE_FOLDER,
                "policy_type": "Security",
                "disabled": disabled,
                "description": description,
                "tag": tag or [],
                "from": from_zones or [],
                "to": to_zones or [],
                "source": source or [],
                "negate_source": negate_source,
                "source_user": source_user or ["any"],
                "destination": destination or [],
                "service": service or [],
                "schedule": schedule,
                "action": action,
                "negate_destination": negate_destination,
                "source_hip": source_hip or [],
                "destination_hip": destination_hip or [],
                "application": application or [],
                "category": category or ["any"],
                "profile_setting": {"group": profile_setting_group or []},
                "log_setting": log_setting,
                "log_start": log_start,
                "log_end": log_end,
                "tenant_restrictions": [],
            }
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "tool_call",
                tool_name="create_security_rule",
                mode=settings.firepilot_env,
                scm_endpoint=endpoint,
                folder=folder,
                outcome="success",
                http_status=None,
                duration_ms=duration_ms,
                ticket_id=ticket_id,
                rejection_code=None,
                scm_request_id=None,
                error_codes=[],
            )
            return rule
        except NotImplementedError:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "tool_call",
                tool_name="create_security_rule",
                mode=settings.firepilot_env,
                scm_endpoint=endpoint,
                folder=folder,
                outcome="failure",
                http_status=None,
                duration_ms=duration_ms,
                ticket_id=ticket_id,
                rejection_code=None,
                scm_request_id=None,
                error_codes=[],
            )
            raise
