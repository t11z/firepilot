"""Change management tools for mcp-itsm.

Exposes four tools covering the full ITSM change request lifecycle:
  - create_change_request
  - get_change_request
  - add_audit_comment
  - update_change_request_status

In demo mode, tools operate against the in-memory FixtureStore.
In live mode, tools call the GitHubClient which makes real GitHub Issues
REST API calls using credentials from Settings (ADR-0005, ADR-0006).

Tool names and field names are backend-agnostic (ITSM concepts, not GitHub
terminology) per ADR-0005.
"""

import time
from datetime import datetime, timezone
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from mcp_itsm.config import get_settings
from mcp_itsm.fixtures.itsm import get_fixture_store
from mcp_itsm.formatting import format_comment_body, format_issue_body
from mcp_itsm.github_client import GITHUB_API_ERROR_CODE, GitHubAPIError, get_github_client
from mcp_itsm.models import AllowedEvent, AllowedStatusTransition

logger = structlog.get_logger(__name__)

# Error codes returned in structured error responses
ERROR_CHANGE_REQUEST_NOT_FOUND = "CHANGE_REQUEST_NOT_FOUND"
ERROR_INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
ERROR_INVALID_EVENT = "INVALID_EVENT"

# GitHub endpoint strings used in log entries (reflects v1 backend mapping)
_ENDPOINT_CREATE = "POST /repos/{owner}/{repo}/issues"
_ENDPOINT_GET = "GET /repos/{owner}/{repo}/issues/{issue_number}"
_ENDPOINT_COMMENT = "POST /repos/{owner}/{repo}/issues/{issue_number}/comments"
_ENDPOINT_UPDATE_LABELS = "PUT /repos/{owner}/{repo}/issues/{issue_number}/labels"
_ENDPOINT_CLOSE = "PATCH /repos/{owner}/{repo}/issues/{issue_number}"

# Valid event values for fast lookup
_VALID_EVENTS: frozenset[str] = frozenset(e.value for e in AllowedEvent)

# Valid status transition values for fast lookup
_VALID_STATUS_TRANSITIONS: frozenset[str] = frozenset(
    s.value for s in AllowedStatusTransition
)

# Status values that are rejected to prevent programmatic approval/rejection
_HUMAN_ONLY_STATUS = frozenset({"approved", "rejected", "pending"})

# Label prefix used to derive status from GitHub issue labels
_FIREPILOT_LABEL_PREFIX = "firepilot:"


def _log_tool_call(
    *,
    tool_name: str,
    mode: str,
    github_endpoint: str,
    outcome: str,
    duration_ms: int,
    http_status: int | None = None,
    change_request_id: str | None = None,
    rejection_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Emit a structured log entry for a completed tool invocation.

    Args:
        tool_name: Name of the MCP tool that was called.
        mode: Server mode — "demo" or "live".
        github_endpoint: GitHub API endpoint string (for audit trail).
        outcome: Result — "success", "failure", or "rejected".
        duration_ms: Wall-clock duration of the tool call in milliseconds.
        http_status: HTTP status code (None in demo mode).
        change_request_id: Change request identifier if applicable.
        rejection_code: Structured error code if outcome is "rejected" or "failure".
        error_message: Human-readable error message if applicable.
    """
    log_fn = logger.info if outcome == "success" else logger.warning
    log_fn(
        "tool_call",
        tool_name=tool_name,
        mode=mode,
        github_endpoint=github_endpoint,
        outcome=outcome,
        http_status=http_status,
        duration_ms=duration_ms,
        change_request_id=change_request_id,
        rejection_code=rejection_code,
        error_message=error_message,
    )


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _derive_status_from_labels(labels: list[dict[str, Any]]) -> str:  # Any: GitHub API JSON
    """Derive status string from GitHub issue label list.

    Finds the first label whose name starts with "firepilot:" and returns the
    suffix. Defaults to "pending" if no firepilot:* label is present.

    Args:
        labels: List of label dicts from the GitHub API (each has a "name" key).

    Returns:
        Status string (e.g. "pending", "approved", "deployed", "failed").
    """
    for label in labels:
        name = label.get("name", "")
        if name.startswith(_FIREPILOT_LABEL_PREFIX):
            return name[len(_FIREPILOT_LABEL_PREFIX):]
    return "pending"


def _extract_field_from_body(body: str | None, field: str) -> str:
    """Extract a named field value from the structured Markdown issue body.

    Looks for a line of the form "**Field**: value" and returns the value.
    Returns a default empty string (or "unknown" for requestor) if not found.

    Args:
        body: Issue body Markdown text, or None.
        field: Field name as it appears in bold in the Markdown (e.g. "Requestor").

    Returns:
        The field value string, or "" if not found.
    """
    if not body:
        return ""
    prefix = f"**{field}**: "
    for line in body.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def register_change_request_tools(mcp: FastMCP) -> None:
    """Register all change request tools on the provided FastMCP server instance.

    Args:
        mcp: The FastMCP server instance to register tools on.
    """

    @mcp.tool()
    async def create_change_request(
        title: str,
        description: str,
        config_reference: str,
        requestor: str,
    ) -> dict[str, Any]:
        """Create a new change request representing a proposed firewall rule change.

        Maps to: POST /repos/{owner}/{repo}/issues

        Creates the change request with status 'pending' and adds the
        firepilot:pending label. The returned change_request_id is the ticket_id
        value to pass to all write operation tools in mcp-strata-cloud-manager.

        Args:
            title: Short summary of the change (required).
            description: Full change description including intent, affected zones,
                and expected impact (required).
            config_reference: Git commit SHA or PR URL of the associated firewall
                configuration change (required).
            requestor: Identity of the requesting business unit or user (required).

        Returns:
            Dict with change_request_id, url, status ("pending"), and created_at,
            or a structured error dict on failure.
        """
        settings = get_settings()
        start = time.monotonic()

        if settings.firepilot_env == "live":
            client = get_github_client()
            body = format_issue_body(
                requestor=requestor,
                config_reference=config_reference,
                description=description,
            )
            try:
                response = await client.create_issue(
                    title=title,
                    body=body,
                    labels=["firepilot:pending"],
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                change_request_id = str(response["number"])
                _log_tool_call(
                    tool_name="create_change_request",
                    mode="live",
                    github_endpoint=_ENDPOINT_CREATE,
                    outcome="success",
                    duration_ms=duration_ms,
                    http_status=201,
                    change_request_id=change_request_id,
                )
                return {
                    "change_request_id": change_request_id,
                    "url": response["html_url"],
                    "status": "pending",
                    "created_at": response["created_at"],
                }
            except GitHubAPIError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                _log_tool_call(
                    tool_name="create_change_request",
                    mode="live",
                    github_endpoint=_ENDPOINT_CREATE,
                    outcome="failure",
                    duration_ms=duration_ms,
                    http_status=exc.http_status,
                    error_message=str(exc),
                )
                return {"error": {"code": GITHUB_API_ERROR_CODE, "message": str(exc)}}

        store = get_fixture_store()
        request = store.create_change_request(
            title=title,
            description=description,
            config_reference=config_reference,
            requestor=requestor,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            tool_name="create_change_request",
            mode=settings.firepilot_env,
            github_endpoint=_ENDPOINT_CREATE,
            outcome="success",
            duration_ms=duration_ms,
            change_request_id=request.change_request_id,
        )
        return {
            "change_request_id": request.change_request_id,
            "url": request.url,
            "status": request.status,
            "created_at": request.created_at,
        }

    @mcp.tool()
    async def get_change_request(
        change_request_id: str,
    ) -> dict[str, Any]:
        """Retrieve the current state of a change request.

        Maps to: GET /repos/{owner}/{repo}/issues/{issue_number}

        Claude calls this tool repeatedly to poll for approval. Status is derived
        from the firepilot:* label on the issue. If no firepilot:* label is
        present, status defaults to "pending".

        Args:
            change_request_id: The change request identifier (issue number as string).

        Returns:
            Dict with full change request state, or a structured error dict with
            code CHANGE_REQUEST_NOT_FOUND if the ID does not exist.
        """
        settings = get_settings()
        start = time.monotonic()

        if settings.firepilot_env == "live":
            client = get_github_client()
            try:
                response = await client.get_issue(int(change_request_id))
                duration_ms = int((time.monotonic() - start) * 1000)
                status = _derive_status_from_labels(response.get("labels", []))
                label_names = [lbl["name"] for lbl in response.get("labels", [])]
                requestor = _extract_field_from_body(response.get("body"), "Requestor")
                config_reference = _extract_field_from_body(
                    response.get("body"), "Config Reference"
                )
                _log_tool_call(
                    tool_name="get_change_request",
                    mode="live",
                    github_endpoint=_ENDPOINT_GET,
                    outcome="success",
                    duration_ms=duration_ms,
                    http_status=200,
                    change_request_id=change_request_id,
                )
                return {
                    "change_request_id": str(response["number"]),
                    "title": response["title"],
                    "url": response["html_url"],
                    "status": status,
                    "labels": label_names,
                    "requestor": requestor if requestor else "unknown",
                    "config_reference": config_reference,
                    "created_at": response["created_at"],
                    "updated_at": response["updated_at"],
                    "closed_at": response["closed_at"],
                    "body": response["body"],
                }
            except GitHubAPIError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                if exc.http_status == 404:
                    _log_tool_call(
                        tool_name="get_change_request",
                        mode="live",
                        github_endpoint=_ENDPOINT_GET,
                        outcome="rejected",
                        duration_ms=duration_ms,
                        http_status=exc.http_status,
                        change_request_id=change_request_id,
                        rejection_code=ERROR_CHANGE_REQUEST_NOT_FOUND,
                        error_message=f"Change request '{change_request_id}' not found",
                    )
                    return {
                        "error": {
                            "code": ERROR_CHANGE_REQUEST_NOT_FOUND,
                            "message": f"Change request '{change_request_id}' not found",
                        }
                    }
                _log_tool_call(
                    tool_name="get_change_request",
                    mode="live",
                    github_endpoint=_ENDPOINT_GET,
                    outcome="failure",
                    duration_ms=duration_ms,
                    http_status=exc.http_status,
                    change_request_id=change_request_id,
                    error_message=str(exc),
                )
                return {"error": {"code": GITHUB_API_ERROR_CODE, "message": str(exc)}}

        store = get_fixture_store()
        request = store.get_change_request(change_request_id)

        if request is None:
            duration_ms = int((time.monotonic() - start) * 1000)
            _log_tool_call(
                tool_name="get_change_request",
                mode=settings.firepilot_env,
                github_endpoint=_ENDPOINT_GET,
                outcome="rejected",
                duration_ms=duration_ms,
                change_request_id=change_request_id,
                rejection_code=ERROR_CHANGE_REQUEST_NOT_FOUND,
                error_message=f"Change request '{change_request_id}' not found",
            )
            return {
                "error": {
                    "code": ERROR_CHANGE_REQUEST_NOT_FOUND,
                    "message": f"Change request '{change_request_id}' not found",
                }
            }

        duration_ms = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            tool_name="get_change_request",
            mode=settings.firepilot_env,
            github_endpoint=_ENDPOINT_GET,
            outcome="success",
            duration_ms=duration_ms,
            change_request_id=change_request_id,
        )
        return {
            "change_request_id": request.change_request_id,
            "title": request.title,
            "url": request.url,
            "status": request.status,
            "labels": request.labels,
            "created_at": request.created_at,
            "updated_at": request.updated_at,
            "closed_at": request.closed_at,
            "body": request.body,
        }

    @mcp.tool()
    async def add_audit_comment(
        change_request_id: str,
        event: str,
        detail: str,
        scm_reference: str | None = None,
    ) -> dict[str, Any]:
        """Append a structured audit comment to an existing change request.

        Maps to: POST /repos/{owner}/{repo}/issues/{issue_number}/comments

        Used to record key events in the change lifecycle: rule validation result,
        candidate config write, push initiation, and push outcome.

        The event field is validated against the allowed set:
          rule_validated | candidate_written | push_initiated |
          push_succeeded | push_failed | request_rejected

        Args:
            change_request_id: The change request to comment on (required).
            event: Lifecycle event type — must be one of the AllowedEvent values (required).
            detail: Human-readable event detail (required).
            scm_reference: Optional SCM job ID or rule UUID. Displayed as "—" if omitted.

        Returns:
            Dict with comment_id, url, and created_at, or a structured error dict
            with code INVALID_EVENT or CHANGE_REQUEST_NOT_FOUND.
        """
        settings = get_settings()
        start = time.monotonic()

        # Validate event before any store interaction
        if event not in _VALID_EVENTS:
            duration_ms = int((time.monotonic() - start) * 1000)
            _log_tool_call(
                tool_name="add_audit_comment",
                mode=settings.firepilot_env,
                github_endpoint=_ENDPOINT_COMMENT,
                outcome="rejected",
                duration_ms=duration_ms,
                change_request_id=change_request_id,
                rejection_code=ERROR_INVALID_EVENT,
                error_message=f"Invalid event '{event}'",
            )
            valid_events = sorted(_VALID_EVENTS)
            return {
                "error": {
                    "code": ERROR_INVALID_EVENT,
                    "message": (
                        f"Invalid event '{event}'. "
                        f"Must be one of: {', '.join(valid_events)}"
                    ),
                }
            }

        if settings.firepilot_env == "live":
            client = get_github_client()
            timestamp = _now_iso()
            body = format_comment_body(
                event=event,
                timestamp=timestamp,
                detail=detail,
                scm_reference=scm_reference,
            )
            try:
                response = await client.add_comment(int(change_request_id), body=body)
                duration_ms = int((time.monotonic() - start) * 1000)
                _log_tool_call(
                    tool_name="add_audit_comment",
                    mode="live",
                    github_endpoint=_ENDPOINT_COMMENT,
                    outcome="success",
                    duration_ms=duration_ms,
                    http_status=201,
                    change_request_id=change_request_id,
                )
                return {
                    "comment_id": str(response["id"]),
                    "url": response["html_url"],
                    "created_at": response["created_at"],
                }
            except GitHubAPIError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                if exc.http_status == 404:
                    _log_tool_call(
                        tool_name="add_audit_comment",
                        mode="live",
                        github_endpoint=_ENDPOINT_COMMENT,
                        outcome="rejected",
                        duration_ms=duration_ms,
                        http_status=exc.http_status,
                        change_request_id=change_request_id,
                        rejection_code=ERROR_CHANGE_REQUEST_NOT_FOUND,
                        error_message=f"Change request '{change_request_id}' not found",
                    )
                    return {
                        "error": {
                            "code": ERROR_CHANGE_REQUEST_NOT_FOUND,
                            "message": f"Change request '{change_request_id}' not found",
                        }
                    }
                _log_tool_call(
                    tool_name="add_audit_comment",
                    mode="live",
                    github_endpoint=_ENDPOINT_COMMENT,
                    outcome="failure",
                    duration_ms=duration_ms,
                    http_status=exc.http_status,
                    change_request_id=change_request_id,
                    error_message=str(exc),
                )
                return {"error": {"code": GITHUB_API_ERROR_CODE, "message": str(exc)}}

        store = get_fixture_store()
        comment = store.add_audit_comment(
            change_request_id=change_request_id,
            event=event,
            detail=detail,
            scm_reference=scm_reference,
        )

        if comment is None:
            duration_ms = int((time.monotonic() - start) * 1000)
            _log_tool_call(
                tool_name="add_audit_comment",
                mode=settings.firepilot_env,
                github_endpoint=_ENDPOINT_COMMENT,
                outcome="rejected",
                duration_ms=duration_ms,
                change_request_id=change_request_id,
                rejection_code=ERROR_CHANGE_REQUEST_NOT_FOUND,
                error_message=f"Change request '{change_request_id}' not found",
            )
            return {
                "error": {
                    "code": ERROR_CHANGE_REQUEST_NOT_FOUND,
                    "message": f"Change request '{change_request_id}' not found",
                }
            }

        duration_ms = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            tool_name="add_audit_comment",
            mode=settings.firepilot_env,
            github_endpoint=_ENDPOINT_COMMENT,
            outcome="success",
            duration_ms=duration_ms,
            change_request_id=change_request_id,
        )
        return {
            "comment_id": comment.comment_id,
            "url": comment.url,
            "created_at": comment.created_at,
        }

    @mcp.tool()
    async def update_change_request_status(
        change_request_id: str,
        status: str,
        close_issue: bool = True,
    ) -> dict[str, Any]:
        """Update the status label of a change request and optionally close it.

        Maps to:
          PUT /repos/{owner}/{repo}/issues/{issue_number}/labels  (replace labels)
          PATCH /repos/{owner}/{repo}/issues/{issue_number}       (close if terminal)

        Only "deployed" and "failed" are accepted as valid status values.
        FirePilot never programmatically sets "approved" or "rejected" — those
        transitions belong to human reviewers via the GitHub UI. Attempts to
        set any other status are rejected with INVALID_STATUS_TRANSITION.

        Args:
            change_request_id: The change request to update (required).
            status: New status — must be "deployed" or "failed" (required).
            close_issue: Whether to close the issue when updating to a terminal
                state. Defaults to True.

        Returns:
            Dict with change_request_id, status, url, and closed, or a structured
            error dict with code INVALID_STATUS_TRANSITION or CHANGE_REQUEST_NOT_FOUND.
        """
        settings = get_settings()
        start = time.monotonic()

        # Enforce status transition constraint before any store interaction
        if status not in _VALID_STATUS_TRANSITIONS:
            duration_ms = int((time.monotonic() - start) * 1000)
            if status in _HUMAN_ONLY_STATUS:
                message = (
                    f"Status '{status}' cannot be set programmatically. "
                    f"Approval and rejection are performed by human reviewers "
                    f"via the GitHub UI. FirePilot may only set: deployed, failed."
                )
            else:
                message = (
                    f"Invalid status '{status}'. "
                    f"FirePilot may only set terminal states: deployed, failed."
                )
            _log_tool_call(
                tool_name="update_change_request_status",
                mode=settings.firepilot_env,
                github_endpoint=_ENDPOINT_UPDATE_LABELS,
                outcome="rejected",
                duration_ms=duration_ms,
                change_request_id=change_request_id,
                rejection_code=ERROR_INVALID_STATUS_TRANSITION,
                error_message=message,
            )
            return {
                "error": {
                    "code": ERROR_INVALID_STATUS_TRANSITION,
                    "message": message,
                }
            }

        if settings.firepilot_env == "live":
            client = get_github_client()
            issue_number = int(change_request_id)
            try:
                # Fetch current labels to rebuild the list
                current_issue = await client.get_issue(issue_number)
                current_labels = [
                    lbl["name"]
                    for lbl in current_issue.get("labels", [])
                    if not lbl["name"].startswith(_FIREPILOT_LABEL_PREFIX)
                ]
                new_labels = current_labels + [f"firepilot:{status}"]

                await client.set_labels(issue_number, new_labels)

                if close_issue:
                    closed_issue = await client.close_issue(issue_number)
                    issue_url = closed_issue["html_url"]
                else:
                    issue_url = current_issue["html_url"]

                duration_ms = int((time.monotonic() - start) * 1000)
                _log_tool_call(
                    tool_name="update_change_request_status",
                    mode="live",
                    github_endpoint=_ENDPOINT_UPDATE_LABELS,
                    outcome="success",
                    duration_ms=duration_ms,
                    http_status=200,
                    change_request_id=change_request_id,
                )
                return {
                    "change_request_id": change_request_id,
                    "status": status,
                    "url": issue_url,
                    "closed": close_issue,
                }
            except GitHubAPIError as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                if exc.http_status == 404:
                    _log_tool_call(
                        tool_name="update_change_request_status",
                        mode="live",
                        github_endpoint=_ENDPOINT_UPDATE_LABELS,
                        outcome="rejected",
                        duration_ms=duration_ms,
                        http_status=exc.http_status,
                        change_request_id=change_request_id,
                        rejection_code=ERROR_CHANGE_REQUEST_NOT_FOUND,
                        error_message=f"Change request '{change_request_id}' not found",
                    )
                    return {
                        "error": {
                            "code": ERROR_CHANGE_REQUEST_NOT_FOUND,
                            "message": f"Change request '{change_request_id}' not found",
                        }
                    }
                _log_tool_call(
                    tool_name="update_change_request_status",
                    mode="live",
                    github_endpoint=_ENDPOINT_UPDATE_LABELS,
                    outcome="failure",
                    duration_ms=duration_ms,
                    http_status=exc.http_status,
                    change_request_id=change_request_id,
                    error_message=str(exc),
                )
                return {"error": {"code": GITHUB_API_ERROR_CODE, "message": str(exc)}}

        store = get_fixture_store()
        updated = store.update_change_request_status(
            change_request_id=change_request_id,
            status=status,
            close_issue=close_issue,
        )

        if updated is None:
            duration_ms = int((time.monotonic() - start) * 1000)
            _log_tool_call(
                tool_name="update_change_request_status",
                mode=settings.firepilot_env,
                github_endpoint=_ENDPOINT_UPDATE_LABELS,
                outcome="rejected",
                duration_ms=duration_ms,
                change_request_id=change_request_id,
                rejection_code=ERROR_CHANGE_REQUEST_NOT_FOUND,
                error_message=f"Change request '{change_request_id}' not found",
            )
            return {
                "error": {
                    "code": ERROR_CHANGE_REQUEST_NOT_FOUND,
                    "message": f"Change request '{change_request_id}' not found",
                }
            }

        duration_ms = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            tool_name="update_change_request_status",
            mode=settings.firepilot_env,
            github_endpoint=_ENDPOINT_UPDATE_LABELS,
            outcome="success",
            duration_ms=duration_ms,
            change_request_id=change_request_id,
        )
        return {
            "change_request_id": updated.change_request_id,
            "status": updated.status,
            "url": updated.url,
            "closed": updated.closed_at is not None,
        }
