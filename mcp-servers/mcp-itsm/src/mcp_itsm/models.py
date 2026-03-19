"""Pydantic models for ITSM change management types.

Field names reflect ITSM concepts (change_request_id, status, event), not
GitHub-specific terminology. The v1 implementation maps these to GitHub Issues
internally, but the tool contract is designed to survive a backend swap.
"""

from enum import StrEnum

from pydantic import BaseModel


class AllowedEvent(StrEnum):
    """Valid audit event types for add_audit_comment.

    These represent the key lifecycle events in a FirePilot change workflow.
    """

    RULE_VALIDATED = "rule_validated"
    CANDIDATE_WRITTEN = "candidate_written"
    PUSH_INITIATED = "push_initiated"
    PUSH_SUCCEEDED = "push_succeeded"
    PUSH_FAILED = "push_failed"
    REQUEST_REJECTED = "request_rejected"


class AllowedStatusTransition(StrEnum):
    """Status values that FirePilot may programmatically set.

    Only terminal states (deployed, failed) are writable via the tool.
    Approval and rejection are performed by human reviewers via the GitHub UI.
    """

    DEPLOYED = "deployed"
    FAILED = "failed"


class ChangeRequest(BaseModel):
    """Represents a FirePilot change request with full lifecycle state."""

    change_request_id: str
    title: str
    url: str
    status: str
    labels: list[str]
    requestor: str
    config_reference: str
    created_at: str
    updated_at: str
    closed_at: str | None
    body: str


class AuditComment(BaseModel):
    """Represents a structured audit comment appended to a change request."""

    comment_id: str
    url: str
    created_at: str


class ChangeRequestStatusUpdate(BaseModel):
    """Result of a status update operation on a change request."""

    change_request_id: str
    status: str
    url: str
    closed: bool
