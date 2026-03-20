"""Operations tools for mcp-strata-cloud-manager.

Exposes push_candidate_config and get_job_status as MCP tools mapped to
SCM operations API endpoints. push_candidate_config enforces ticket_id
server-side.

In demo mode (FIREPILOT_ENV=demo) tools return realistic fixture responses
with no network calls. In live mode (FIREPILOT_ENV=live) tools execute real
HTTP calls against the configured SCM API via SCMClient.
"""

import time
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from mcp_strata_cloud_manager.config import get_settings
from mcp_strata_cloud_manager.fixtures.strata import (
    FIXTURE_JOB_ID,
    FIXTURE_JOB_TEMPLATE,
)
from mcp_strata_cloud_manager.scm_client import (
    SCM_API_ERROR_CODE,
    SCM_AUTH_FAILURE_CODE,
    SCMAPIError,
    SCMAuthError,
    get_scm_client,
)

logger = structlog.get_logger(__name__)

MISSING_TICKET_REF_CODE = "MISSING_TICKET_REF"


def register_operations_tools(mcp: FastMCP) -> None:
    """Register all operations tools on the provided FastMCP server instance.

    Args:
        mcp: The FastMCP server instance to register tools on.
    """

    @mcp.tool()
    async def push_candidate_config(
        ticket_id: str,
        folders: list[str],
        admin: list[str] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Push candidate configuration to running configuration on devices.

        Maps to: POST /config/operations/v1/config-versions/candidate:push

        This is the only tool that causes live changes on devices. Enforces
        ticket_id server-side — calls without a non-empty ticket_id are
        rejected immediately with error code MISSING_TICKET_REF.

        In demo mode, returns a fixture showing a completed push
        (status_str: 'FIN', result_str: 'OK').

        Args:
            ticket_id: ITSM ticket reference (required, server-enforced).
            folders: List of folder names to push. Each max 64 chars.
            admin: Optional list of admin or service account names.
                   Omit when pushing the 'All' folder.
            description: Optional description recorded on the resulting job.

        Returns:
            Job status response with job_id, status_str, result_str,
            percent, summary, and details fields, or a structured error
            dict with code MISSING_TICKET_REF.
        """
        settings = get_settings()
        endpoint = "POST /config/operations/v1/config-versions/candidate:push"
        start = time.monotonic()

        # Ticket enforcement — reject before any other processing
        if not ticket_id or not ticket_id.strip():
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "tool_call",
                tool_name="push_candidate_config",
                mode=settings.firepilot_env,
                scm_endpoint=endpoint,
                folder=str(folders),
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
            try:
                scm_result = await client.push_candidate_config(folders, admin, description)
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "tool_call",
                    tool_name="push_candidate_config",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=str(folders),
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
                    tool_name="push_candidate_config",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=str(folders),
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
                    tool_name="push_candidate_config",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=str(folders),
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

        # Demo mode: return a completed push fixture
        result: dict[str, Any] = {
            "job_id": FIXTURE_JOB_ID,
            "status_str": "FIN",
            "result_str": "OK",
            "percent": "100",
            "summary": "Commit and push completed successfully",
            "details": "",
        }
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "tool_call",
            tool_name="push_candidate_config",
            mode=settings.firepilot_env,
            scm_endpoint=endpoint,
            folder=str(folders),
            outcome="success",
            http_status=None,
            duration_ms=duration_ms,
            ticket_id=ticket_id,
            rejection_code=None,
            scm_request_id=None,
            error_codes=[],
        )
        return result

    @mcp.tool()
    async def get_job_status(
        job_id: str,
    ) -> dict[str, Any]:
        """Retrieve the status of an SCM job by its ID.

        Maps to: GET /config/operations/v1/jobs/:id

        Allows Claude to check push job status independently, supporting
        async approval workflows where status must be checked in a separate
        conversation turn.

        In demo mode, returns a completed job fixture with the provided job_id.

        Args:
            job_id: The SCM job identifier to query.

        Returns:
            Dict with a 'data' list containing one Job object matching
            the provided job_id.
        """
        settings = get_settings()
        endpoint = f"GET /config/operations/v1/jobs/{job_id}"
        start = time.monotonic()

        if settings.firepilot_env == "live":
            client = get_scm_client()
            try:
                scm_result = await client.get_job_status(job_id)
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "tool_call",
                    tool_name="get_job_status",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=None,
                    outcome="success",
                    http_status=scm_result.http_status,
                    duration_ms=duration_ms,
                    ticket_id=None,
                    rejection_code=None,
                    scm_request_id=scm_result.scm_request_id,
                    error_codes=[],
                )
                return scm_result.data
            except SCMAuthError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="get_job_status",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=None,
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
                        "message": str(exc),
                    }
                }
            except SCMAPIError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "tool_call",
                    tool_name="get_job_status",
                    mode=settings.firepilot_env,
                    scm_endpoint=endpoint,
                    folder=None,
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
                        "scm_request_id": exc.request_id,
                        "scm_error_codes": exc.error_codes,
                    }
                }

        # Demo mode: return a completed job fixture with the given job_id
        job = dict(FIXTURE_JOB_TEMPLATE)
        job["id"] = job_id
        result: dict[str, Any] = {"data": [job]}
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "tool_call",
            tool_name="get_job_status",
            mode=settings.firepilot_env,
            scm_endpoint=endpoint,
            folder=None,
            outcome="success",
            http_status=None,
            duration_ms=duration_ms,
            ticket_id=None,
            rejection_code=None,
            scm_request_id=None,
            error_codes=[],
        )
        return result
