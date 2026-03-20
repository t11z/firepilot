"""Shared formatting utilities for mcp-itsm change request content.

Both demo mode (FixtureStore) and live mode (GitHubClient) produce
identical issue body and comment body Markdown — this module is the
single source of truth for that formatting.
"""


def format_issue_body(requestor: str, config_reference: str, description: str) -> str:
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


def format_comment_body(
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
