"""Write tools for mcp-strata-cloud-manager.

Exposes create_security_rule, create_address, and create_address_group as MCP
tools mapped to SCM write API endpoints.

Enforces ticket_id server-side before any processing occurs on all write tools.

In demo mode (FIREPILOT_ENV=demo) the tools return realistic fixture responses
with no network calls, and created objects are persisted to the in-memory
SCMFixtureStore so subsequent list calls reflect them within the same session.
In live mode (FIREPILOT_ENV=live) the tools execute real HTTP POST calls against
the configured SCM API via SCMClient.
"""

import time
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from mcp_strata_cloud_manager.config import get_settings
from mcp_strata_cloud_manager.fixtures.store import get_fixture_store
from mcp_strata_cloud_manager.fixtures.strata import FIXTURE_FOLDER
from mcp_strata_cloud_manager.scm_client import (
    SCM_API_ERROR_CODE,
    SCM_AUTH_FAILURE_CODE,
    SCMAPIError,
    SCMAuthError,
    get_scm_client,
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

        if settings.firepilot_env == "live":
            client = get_scm_client()
            # Build SCM request body; map from_zones/to_zones → from/to (ADR-0004)
            body: dict[str, Any] = {
                "name": name,
                "action": action,
                "from": from_zones or [],
                "to": to_zones or [],
                "source": source or [],
                "source_user": source_user or ["any"],
                "destination": destination or [],
                "service": service or [],
                "application": application or [],
                "category": category or ["any"],
                "disabled": disabled,
                "negate_source": negate_source,
                "negate_destination": negate_destination,
                "log_start": log_start,
                "log_end": log_end,
            }
            # Exclude None-valued optional fields from the body
            if description is not None:
                body["description"] = description
            if tag is not None:
                body["tag"] = tag
            if source_hip is not None:
                body["source_hip"] = source_hip
            if destination_hip is not None:
                body["destination_hip"] = destination_hip
            if schedule is not None:
                body["schedule"] = schedule
            if profile_setting_group is not None:
                body["profile_setting"] = {"group": profile_setting_group}
            if log_setting is not None:
                body["log_setting"] = log_setting

            try:
                scm_result = await client.create_security_rule(folder, body, position)
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "tool_call",
                    tool_name="create_security_rule",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="success",
                    http_status=scm_result.http_status,
                    duration_ms=duration_ms,
                    ticket_id=ticket_id,
                    rejection_code=None,
                    scm_request_id=scm_result.scm_request_id,
                    error_codes=[],
                )
                return scm_result.data
            except SCMAuthError as exc:
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
                return {
                    "error": {
                        "code": SCM_AUTH_FAILURE_CODE,
                        "message": str(exc),
                    }
                }
            except SCMAPIError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="create_security_rule",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="failure",
                    http_status=exc.http_status,
                    duration_ms=duration_ms,
                    ticket_id=ticket_id,
                    rejection_code=None,
                    scm_request_id=exc.request_id,
                    error_codes=exc.error_codes,
                )
                return {
                    "error": {
                        "code": SCM_API_ERROR_CODE,
                        "message": str(exc),
                        "scm_request_id": exc.request_id,
                        "scm_error_codes": exc.error_codes,
                    }
                }

        # Demo mode: build rule dict and persist to session store
        rule_data: dict[str, Any] = {
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
        rule = get_fixture_store().add_security_rule(rule_data, position)
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

    @mcp.tool()
    async def create_address(
        ticket_id: str,
        folder: str,
        name: str,
        description: str | None = None,
        tag: list[str] | None = None,
        ip_netmask: str | None = None,
        ip_range: str | None = None,
        ip_wildcard: str | None = None,
        fqdn: str | None = None,
    ) -> dict[str, Any]:
        """Create an address object in SCM candidate configuration.

        Maps to: POST /config/objects/v1/addresses

        Enforces ticket_id server-side — calls without a non-empty ticket_id
        are rejected immediately with error code MISSING_TICKET_REF before
        any SCM interaction.

        Args:
            ticket_id: ITSM ticket reference (required, server-enforced).
            folder: Folder scope, max 64 chars (required).
            name: Address object name (required).
            description: Optional description.
            tag: Optional list of tags.
            ip_netmask: IP address with netmask (e.g. '10.0.0.0/24').
            ip_range: IP address range (e.g. '10.0.0.1-10.0.0.255').
            ip_wildcard: Wildcard IP address (e.g. '10.20.1.0/0.0.248.255').
            fqdn: Fully qualified domain name.

        Returns:
            The created address object echoed back with an assigned id field,
            or a structured error dict with code MISSING_TICKET_REF.
        """
        settings = get_settings()
        endpoint = "POST /config/objects/v1/addresses"
        start = time.monotonic()

        # Ticket enforcement — reject before any other processing
        if not ticket_id or not ticket_id.strip():
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "tool_call",
                tool_name="create_address",
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

        if settings.firepilot_env == "live":
            client = get_scm_client()
            body: dict[str, Any] = {"name": name}
            if description is not None:
                body["description"] = description
            if tag is not None:
                body["tag"] = tag
            if ip_netmask is not None:
                body["ip_netmask"] = ip_netmask
            if ip_range is not None:
                body["ip_range"] = ip_range
            if ip_wildcard is not None:
                body["ip_wildcard"] = ip_wildcard
            if fqdn is not None:
                body["fqdn"] = fqdn

            try:
                scm_result = await client.create_address(folder, body)
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "tool_call",
                    tool_name="create_address",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="success",
                    http_status=scm_result.http_status,
                    duration_ms=duration_ms,
                    ticket_id=ticket_id,
                    rejection_code=None,
                    scm_request_id=scm_result.scm_request_id,
                    error_codes=[],
                )
                return scm_result.data
            except SCMAuthError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="create_address",
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
                return {
                    "error": {
                        "code": SCM_AUTH_FAILURE_CODE,
                        "message": str(exc),
                    }
                }
            except SCMAPIError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="create_address",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="failure",
                    http_status=exc.http_status,
                    duration_ms=duration_ms,
                    ticket_id=ticket_id,
                    rejection_code=None,
                    scm_request_id=exc.request_id,
                    error_codes=exc.error_codes,
                )
                return {
                    "error": {
                        "code": SCM_API_ERROR_CODE,
                        "message": str(exc),
                        "scm_request_id": exc.request_id,
                        "scm_error_codes": exc.error_codes,
                    }
                }

        # Demo mode: build address dict and persist to session store
        address_data: dict[str, Any] = {
            "name": name,
            "description": description,
            "tag": tag or [],
            "ip_netmask": ip_netmask,
            "ip_range": ip_range,
            "ip_wildcard": ip_wildcard,
            "fqdn": fqdn,
        }
        address = get_fixture_store().add_address(address_data)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "tool_call",
            tool_name="create_address",
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
        return address

    @mcp.tool()
    async def create_address_group(
        ticket_id: str,
        folder: str,
        name: str,
        static: list[str] | None = None,
        description: str | None = None,
        tag: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create an address group in SCM candidate configuration.

        Maps to: POST /config/objects/v1/address-groups

        Only static address groups are supported (v1). Enforces ticket_id
        server-side — calls without a non-empty ticket_id are rejected
        immediately with error code MISSING_TICKET_REF before any SCM
        interaction.

        Args:
            ticket_id: ITSM ticket reference (required, server-enforced).
            folder: Folder scope, max 64 chars (required).
            name: Address group name (required).
            static: List of address object names to include in the group.
                    At least one member is required.
            description: Optional description.
            tag: Optional list of tags.

        Returns:
            The created address group echoed back with an assigned id field,
            or a structured error dict with code MISSING_TICKET_REF or
            INVALID_INPUT.
        """
        settings = get_settings()
        endpoint = "POST /config/objects/v1/address-groups"
        start = time.monotonic()

        # Ticket enforcement — reject before any other processing
        if not ticket_id or not ticket_id.strip():
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "tool_call",
                tool_name="create_address_group",
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

        # Input validation — static members required for v1
        if not static:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "tool_call",
                tool_name="create_address_group",
                mode=settings.firepilot_env,
                scm_endpoint=endpoint,
                folder=folder,
                outcome="rejected",
                http_status=None,
                duration_ms=duration_ms,
                ticket_id=ticket_id,
                rejection_code="INVALID_INPUT",
                scm_request_id=None,
                error_codes=[],
            )
            return {
                "error": {
                    "code": "INVALID_INPUT",
                    "message": "static is required; dynamic address groups are not supported in v1",
                }
            }

        if settings.firepilot_env == "live":
            client = get_scm_client()
            body: dict[str, Any] = {"name": name, "static": static}
            if description is not None:
                body["description"] = description
            if tag is not None:
                body["tag"] = tag

            try:
                scm_result = await client.create_address_group(folder, body)
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "tool_call",
                    tool_name="create_address_group",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="success",
                    http_status=scm_result.http_status,
                    duration_ms=duration_ms,
                    ticket_id=ticket_id,
                    rejection_code=None,
                    scm_request_id=scm_result.scm_request_id,
                    error_codes=[],
                )
                return scm_result.data
            except SCMAuthError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="create_address_group",
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
                return {
                    "error": {
                        "code": SCM_AUTH_FAILURE_CODE,
                        "message": str(exc),
                    }
                }
            except SCMAPIError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="create_address_group",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="failure",
                    http_status=exc.http_status,
                    duration_ms=duration_ms,
                    ticket_id=ticket_id,
                    rejection_code=None,
                    scm_request_id=exc.request_id,
                    error_codes=exc.error_codes,
                )
                return {
                    "error": {
                        "code": SCM_API_ERROR_CODE,
                        "message": str(exc),
                        "scm_request_id": exc.request_id,
                        "scm_error_codes": exc.error_codes,
                    }
                }

        # Demo mode: build group dict and persist to session store
        group_data: dict[str, Any] = {
            "name": name,
            "description": description,
            "tag": tag or [],
            "static": static,
            "dynamic": None,
        }
        group = get_fixture_store().add_address_group(group_data)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "tool_call",
            tool_name="create_address_group",
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
        return group
