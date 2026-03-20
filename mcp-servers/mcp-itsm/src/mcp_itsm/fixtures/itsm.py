"""Demo fixture data and in-memory state store for mcp-itsm.

Provides a FixtureStore singleton that maintains stateful change request
lifecycle data for demo mode. Unlike stateless fixture layers, the ITSM
lifecycle requires state because tools reference each other by ID across
tool calls (create → get → add comment → update status).
"""

from datetime import datetime, timezone

from mcp_itsm.models import AuditComment, ChangeRequest

# Pre-seeded fixture constants
FIXTURE_PRESEEDED_ID = "42"
FIXTURE_DEMO_REPO = "firepilot-demo/firepilot-configs"
FIXTURE_BASE_URL = f"https://github.com/{FIXTURE_DEMO_REPO}/issues"


def _format_issue_body(requestor: str, config_reference: str, description: str) -> str:
    """Format a change request issue body as structured Markdown.

    Args:
        requestor: Identity of the requesting business unit or user.
        config_reference: Git commit SHA or PR URL.
        description: Full change description.

    Returns:
        Formatted Markdown string for the issue body.
    """
    return (
        f"## Change Request\n\n"
        f"**Requestor**: {requestor}\n"
        f"**Config Reference**: {config_reference}\n\n"
        f"---\n\n"
        f"{description}"
    )


def _format_comment_body(
    event: str,
    timestamp: str,
    detail: str,
    scm_reference: str | None,
) -> str:
    """Format an audit comment as structured Markdown.

    Args:
        event: The AllowedEvent value for this audit entry.
        timestamp: ISO 8601 timestamp string.
        detail: Human-readable event detail.
        scm_reference: Optional SCM job ID or rule UUID.

    Returns:
        Formatted Markdown string for the comment body.
    """
    ref_display = scm_reference if scm_reference else "—"
    return (
        f"**FirePilot Event**: `{event}`\n"
        f"**Time**: {timestamp}\n"
        f"**Detail**: {detail}\n"
        f"**SCM Reference**: {ref_display}"
    )


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class FixtureStore:
    """In-memory state store for demo mode change requests.

    Maintains the full lifecycle state of change requests created during a
    server session. Pre-seeded with one pending change request to support
    immediate demo queries without requiring a create step.

    Attributes:
        _change_requests: Mapping of change_request_id to ChangeRequest.
        _comments: Mapping of change_request_id to list of AuditComments.
        _next_id: Auto-incrementing issue number for new requests.
        _next_comment_id: Auto-incrementing comment ID for new comments.
    """

    def __init__(self) -> None:
        """Initialize the store and seed with the demo change request."""
        self._change_requests: dict[str, ChangeRequest] = {}
        self._comments: dict[str, list[AuditComment]] = {}
        self._next_id: int = 43  # Starts after the pre-seeded entry
        self._next_comment_id: int = 1001

        self._seed()

    def _seed(self) -> None:
        """Populate the store with the pre-seeded demo change request (status: pending)."""
        preseeded_description = (
            "Allow HTTPS traffic from the web-zone to the app-zone to support "
            "customer portal backend connectivity. Expected impact: enables port 443 "
            "inbound to app-zone from web-zone. No other zones affected."
        )
        body = _format_issue_body(
            requestor="Platform Engineering",
            config_reference="abc123def456",
            description=preseeded_description,
        )
        request = ChangeRequest(
            change_request_id=FIXTURE_PRESEEDED_ID,
            title="Allow HTTPS from web-zone to app-zone for customer portal",
            url=f"{FIXTURE_BASE_URL}/{FIXTURE_PRESEEDED_ID}",
            status="pending",
            labels=["firepilot:pending"],
            requestor="Platform Engineering",
            config_reference="abc123def456",
            created_at="2026-03-19T10:00:00Z",
            updated_at="2026-03-19T10:15:00Z",
            closed_at=None,
            body=body,
        )
        self._change_requests[FIXTURE_PRESEEDED_ID] = request
        self._comments[FIXTURE_PRESEEDED_ID] = []

    def create_change_request(
        self,
        title: str,
        description: str,
        config_reference: str,
        requestor: str,
    ) -> ChangeRequest:
        """Create a new change request in the store with status 'pending'.

        Args:
            title: Short summary of the change.
            description: Full change description.
            config_reference: Git commit SHA or PR URL.
            requestor: Identity of the requesting business unit or user.

        Returns:
            The newly created ChangeRequest.
        """
        change_request_id = str(self._next_id)
        self._next_id += 1
        now = _now_iso()
        body = _format_issue_body(
            requestor=requestor,
            config_reference=config_reference,
            description=description,
        )
        request = ChangeRequest(
            change_request_id=change_request_id,
            title=title,
            url=f"{FIXTURE_BASE_URL}/{change_request_id}",
            status="pending",
            labels=["firepilot:pending"],
            requestor=requestor,
            config_reference=config_reference,
            created_at=now,
            updated_at=now,
            closed_at=None,
            body=body,
        )
        self._change_requests[change_request_id] = request
        self._comments[change_request_id] = []
        return request

    def get_change_request(self, change_request_id: str) -> ChangeRequest | None:
        """Retrieve a change request by ID.

        Args:
            change_request_id: The change request identifier to look up.

        Returns:
            The ChangeRequest if found, or None if not found.
        """
        return self._change_requests.get(change_request_id)

    def add_audit_comment(
        self,
        change_request_id: str,
        event: str,
        detail: str,
        scm_reference: str | None,
    ) -> AuditComment | None:
        """Append a structured audit comment to a change request.

        Args:
            change_request_id: The change request to comment on.
            event: The AllowedEvent value for this audit entry.
            detail: Human-readable event detail.
            scm_reference: Optional SCM job ID or rule UUID.

        Returns:
            The created AuditComment, or None if the change request does not exist.
        """
        if change_request_id not in self._change_requests:
            return None

        comment_id = str(self._next_comment_id)
        self._next_comment_id += 1
        now = _now_iso()

        # Format the comment body (stored for reference; not returned in output)
        _format_comment_body(
            event=event,
            timestamp=now,
            detail=detail,
            scm_reference=scm_reference,
        )

        comment = AuditComment(
            comment_id=comment_id,
            url=f"{FIXTURE_BASE_URL}/{change_request_id}#issuecomment-{comment_id}",
            created_at=now,
        )
        self._comments[change_request_id].append(comment)
        return comment

    def update_change_request_status(
        self,
        change_request_id: str,
        status: str,
        close_issue: bool = True,
    ) -> ChangeRequest | None:
        """Update the status of a change request.

        Only "deployed" and "failed" are accepted as valid status transitions.
        The store does not enforce this constraint — callers must validate before
        calling this method.

        Args:
            change_request_id: The change request to update.
            status: New status value ("deployed" or "failed").
            close_issue: Whether to close the issue (set closed_at timestamp).

        Returns:
            The updated ChangeRequest, or None if the change request does not exist.
        """
        request = self._change_requests.get(change_request_id)
        if request is None:
            return None

        now = _now_iso()
        label = f"firepilot:{status}"

        # Replace existing firepilot:* labels with the new status label
        other_labels = [lbl for lbl in request.labels if not lbl.startswith("firepilot:")]
        new_labels = other_labels + [label]

        updated = request.model_copy(
            update={
                "status": status,
                "labels": new_labels,
                "updated_at": now,
                "closed_at": now if close_issue else request.closed_at,
            }
        )
        self._change_requests[change_request_id] = updated
        return updated


# Module-level singleton — one store per server process
_store: FixtureStore | None = None


def get_fixture_store() -> FixtureStore:
    """Return the module-level FixtureStore singleton, initializing on first call.

    Returns:
        The shared FixtureStore instance for this server process.
    """
    global _store
    if _store is None:
        _store = FixtureStore()
    return _store


def reset_fixture_store() -> None:
    """Reset the module-level singleton to a fresh FixtureStore.

    Intended for use in tests to ensure a clean initial state.
    """
    global _store
    _store = FixtureStore()
