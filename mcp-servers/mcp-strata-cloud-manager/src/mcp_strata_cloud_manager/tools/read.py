"""Read tools for mcp-strata-cloud-manager.

Exposes list_security_rules, list_security_zones, list_addresses,
and list_address_groups as MCP tools mapped to SCM read API endpoints.

In demo mode (FIREPILOT_ENV=demo) all tools return realistic fixture responses
with no network calls. In live mode (FIREPILOT_ENV=live) all tools execute
real HTTP calls against the configured SCM API via SCMClient (scm_client.py),
which is the sole credential boundary for token acquisition and HTTP transport.
"""

import time
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from mcp_strata_cloud_manager.config import get_settings
from mcp_strata_cloud_manager.fixtures.strata import (
    FIXTURE_ADDRESS_GROUPS,
    FIXTURE_ADDRESSES,
    FIXTURE_SECURITY_RULES_POST,
    FIXTURE_SECURITY_RULES_PRE,
    FIXTURE_SECURITY_ZONES,
)
from mcp_strata_cloud_manager.scm_client import (
    SCMAPIError,
    SCMAuthError,
    SCM_AUTH_FAILURE_CODE,
    SCM_API_ERROR_CODE,
    get_scm_client,
)

logger = structlog.get_logger(__name__)


def _apply_filters(
    items: list[dict],
    name: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Apply name filter and pagination to a fixture list.

    Args:
        items: Full list of fixture dicts.
        name: Optional name filter; if provided, only items whose 'name'
              field matches exactly are returned.
        limit: Maximum number of items to return.
        offset: Number of items to skip before returning results.

    Returns:
        Dict with 'data', 'limit', 'offset', and 'total' keys.
    """
    filtered = [item for item in items if name is None or item["name"] == name]
    total = len(filtered)
    page = filtered[offset : offset + limit]
    return {"data": page, "limit": limit, "offset": offset, "total": total}


def register_read_tools(mcp: FastMCP) -> None:
    """Register all read tools on the provided FastMCP server instance.

    Args:
        mcp: The FastMCP server instance to register tools on.
    """

    @mcp.tool()
    async def list_security_rules(
        folder: str,
        position: str = "pre",
        name: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List security rules from SCM for a given folder and position.

        Maps to: GET /config/security/v1/security-rules

        Args:
            folder: Folder scope for the query (required).
            position: Rule position, either 'pre' or 'post'. Default 'pre'.
            name: Optional name filter to return a specific rule.
            limit: Maximum number of results to return. Default 200.
            offset: Number of results to skip. Default 0.

        Returns:
            Paginated response with data, limit, offset, and total fields.
        """
        settings = get_settings()
        endpoint = "GET /config/security/v1/security-rules"
        start = time.monotonic()

        if settings.firepilot_env == "live":
            client = get_scm_client()
            try:
                scm_result = await client.list_security_rules(
                    folder, name=name, limit=limit, offset=offset, position=position
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "tool_call",
                    tool_name="list_security_rules",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="success",
                    http_status=scm_result.http_status,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=scm_result.scm_request_id,
                    error_codes=[],
                )
                return scm_result.data
            except SCMAuthError:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="list_security_rules",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="failure",
                    http_status=None,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=None,
                    error_codes=[],
                )
                return {
                    "error": {
                        "code": SCM_AUTH_FAILURE_CODE,
                        "message": "SCM authentication failed",
                    }
                }
            except SCMAPIError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="list_security_rules",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="failure",
                    http_status=exc.http_status,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=exc.request_id,
                    error_codes=exc.error_codes,
                )
                return {
                    "error": {
                        "code": SCM_API_ERROR_CODE,
                        "message": str(exc),
                    }
                }

        # Demo mode: return fixture data
        rules = (
            FIXTURE_SECURITY_RULES_PRE
            if position == "pre"
            else FIXTURE_SECURITY_RULES_POST
        )
        result = _apply_filters(rules, name, limit, offset)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "tool_call",
            tool_name="list_security_rules",
            mode=settings.firepilot_env,
            scm_endpoint=endpoint,
            folder=folder,
            outcome="success",
            http_status=None,
            duration_ms=duration_ms,
            ticket_id=None,
            rejection_code=None,
            scm_request_id=None,
            error_codes=[],
        )
        return result

    @mcp.tool()
    async def list_security_zones(
        folder: str,
        name: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List security zones from SCM for a given folder.

        Maps to: GET /config/network/v1/zones

        Args:
            folder: Folder scope for the query (required).
            name: Optional name filter to return a specific zone.
            limit: Maximum number of results to return. Default 200.
            offset: Number of results to skip. Default 0.

        Returns:
            Paginated response with data, limit, offset, and total fields.
        """
        settings = get_settings()
        endpoint = "GET /config/network/v1/zones"
        start = time.monotonic()

        if settings.firepilot_env == "live":
            client = get_scm_client()
            try:
                scm_result = await client.list_security_zones(
                    folder, name=name, limit=limit, offset=offset
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "tool_call",
                    tool_name="list_security_zones",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="success",
                    http_status=scm_result.http_status,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=scm_result.scm_request_id,
                    error_codes=[],
                )
                return scm_result.data
            except SCMAuthError:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="list_security_zones",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="failure",
                    http_status=None,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=None,
                    error_codes=[],
                )
                return {
                    "error": {
                        "code": SCM_AUTH_FAILURE_CODE,
                        "message": "SCM authentication failed",
                    }
                }
            except SCMAPIError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="list_security_zones",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="failure",
                    http_status=exc.http_status,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=exc.request_id,
                    error_codes=exc.error_codes,
                )
                return {
                    "error": {
                        "code": SCM_API_ERROR_CODE,
                        "message": str(exc),
                    }
                }

        # Demo mode: return fixture data
        result = _apply_filters(FIXTURE_SECURITY_ZONES, name, limit, offset)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "tool_call",
            tool_name="list_security_zones",
            mode=settings.firepilot_env,
            scm_endpoint=endpoint,
            folder=folder,
            outcome="success",
            http_status=None,
            duration_ms=duration_ms,
            ticket_id=None,
            rejection_code=None,
            scm_request_id=None,
            error_codes=[],
        )
        return result

    @mcp.tool()
    async def list_addresses(
        folder: str,
        name: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List address objects from SCM for a given folder.

        Maps to: GET /config/objects/v1/addresses

        Args:
            folder: Folder scope for the query (required).
            name: Optional name filter to return a specific address object.
            limit: Maximum number of results to return. Default 200.
            offset: Number of results to skip. Default 0.

        Returns:
            Paginated response with data, limit, offset, and total fields.
        """
        settings = get_settings()
        endpoint = "GET /config/objects/v1/addresses"
        start = time.monotonic()

        if settings.firepilot_env == "live":
            client = get_scm_client()
            try:
                scm_result = await client.list_addresses(
                    folder, name=name, limit=limit, offset=offset
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "tool_call",
                    tool_name="list_addresses",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="success",
                    http_status=scm_result.http_status,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=scm_result.scm_request_id,
                    error_codes=[],
                )
                return scm_result.data
            except SCMAuthError:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="list_addresses",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="failure",
                    http_status=None,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=None,
                    error_codes=[],
                )
                return {
                    "error": {
                        "code": SCM_AUTH_FAILURE_CODE,
                        "message": "SCM authentication failed",
                    }
                }
            except SCMAPIError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="list_addresses",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="failure",
                    http_status=exc.http_status,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=exc.request_id,
                    error_codes=exc.error_codes,
                )
                return {
                    "error": {
                        "code": SCM_API_ERROR_CODE,
                        "message": str(exc),
                    }
                }

        # Demo mode: return fixture data
        result = _apply_filters(FIXTURE_ADDRESSES, name, limit, offset)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "tool_call",
            tool_name="list_addresses",
            mode=settings.firepilot_env,
            scm_endpoint=endpoint,
            folder=folder,
            outcome="success",
            http_status=None,
            duration_ms=duration_ms,
            ticket_id=None,
            rejection_code=None,
            scm_request_id=None,
            error_codes=[],
        )
        return result

    @mcp.tool()
    async def list_address_groups(
        folder: str,
        name: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List address groups from SCM for a given folder.

        Maps to: GET /config/objects/v1/address-groups

        Args:
            folder: Folder scope for the query (required).
            name: Optional name filter to return a specific address group.
            limit: Maximum number of results to return. Default 200.
            offset: Number of results to skip. Default 0.

        Returns:
            Paginated response with data, limit, offset, and total fields.
        """
        settings = get_settings()
        endpoint = "GET /config/objects/v1/address-groups"
        start = time.monotonic()

        if settings.firepilot_env == "live":
            client = get_scm_client()
            try:
                scm_result = await client.list_address_groups(
                    folder, name=name, limit=limit, offset=offset
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "tool_call",
                    tool_name="list_address_groups",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="success",
                    http_status=scm_result.http_status,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=scm_result.scm_request_id,
                    error_codes=[],
                )
                return scm_result.data
            except SCMAuthError:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="list_address_groups",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="failure",
                    http_status=None,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=None,
                    error_codes=[],
                )
                return {
                    "error": {
                        "code": SCM_AUTH_FAILURE_CODE,
                        "message": "SCM authentication failed",
                    }
                }
            except SCMAPIError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="list_address_groups",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=folder,
                    outcome="failure",
                    http_status=exc.http_status,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=exc.request_id,
                    error_codes=exc.error_codes,
                )
                return {
                    "error": {
                        "code": SCM_API_ERROR_CODE,
                        "message": str(exc),
                    }
                }

        # Demo mode: return fixture data
        result = _apply_filters(FIXTURE_ADDRESS_GROUPS, name, limit, offset)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "tool_call",
            tool_name="list_address_groups",
            mode=settings.firepilot_env,
            scm_endpoint=endpoint,
            folder=folder,
            outcome="success",
            http_status=None,
            duration_ms=duration_ms,
            ticket_id=None,
            rejection_code=None,
            scm_request_id=None,
            error_codes=[],
        )
        return result
