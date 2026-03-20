"""GitHub Issues HTTP client for mcp-itsm live mode.

This module is the sole credential boundary for all GitHub API communication.
No other module constructs HTTP requests or handles the GitHub token.

The token is stored in process memory only — it is never written to disk,
never included in log output, and never returned in tool responses (ADR-0006).

Usage:
    client = get_github_client()
    issue = await client.create_issue(title="...", body="...", labels=["firepilot:pending"])
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

import httpx
import structlog

from mcp_itsm.config import get_settings

logger = structlog.get_logger(__name__)

# GitHub API constants
_GITHUB_API_VERSION = "2022-11-28"
_GITHUB_ACCEPT = "application/vnd.github+json"

# Error code surfaced to the tool layer
GITHUB_API_ERROR_CODE: str = "GITHUB_API_ERROR"


class GitHubAPIError(Exception):
    """Raised when a GitHub Issues API call fails.

    Attributes:
        http_status: HTTP status code, or None on network/transport failure.
        error_message: Human-readable description of the failure.
        github_request_id: Value of the X-GitHub-Request-Id header, or None
                           if the header was not present or the error was a
                           network failure.
    """

    def __init__(
        self,
        message: str,
        http_status: int | None,
        github_request_id: str | None,
    ) -> None:
        """Initialise with message and structured HTTP error metadata.

        Args:
            message: Human-readable error description. Must not contain
                     credential values.
            http_status: HTTP status code, or None on network failure.
            github_request_id: GitHub request identifier for support escalation.
        """
        super().__init__(message)
        self.http_status = http_status
        self.github_request_id = github_request_id


class GitHubClient:
    """HTTP client for the GitHub Issues REST API.

    Encapsulates all GitHub API HTTP calls, authentication, error handling,
    and structured logging. A single httpx.AsyncClient instance is shared
    across all requests for connection pool reuse.

    Callers should use get_github_client() to obtain the shared singleton
    rather than constructing GitHubClient directly.

    The token is stored in process memory only — it is never written to
    disk, never included in log output, and never returned in tool responses
    (ADR-0006; threat model T3).

    Attributes:
        _base_url: GitHub API base URL for the configured repository.
        _headers: Standard request headers including the Bearer token.
        _http: Shared httpx.AsyncClient for connection reuse.
    """

    def __init__(self, token: str, repo: str) -> None:
        """Initialise the client with a GitHub token and target repository.

        Args:
            token: Fine-grained PAT with issues:write scope. Stored in
                   memory only — never logged or returned in responses.
            repo: Target repository in owner/repo format.
        """
        self._base_url = f"https://api.github.com/repos/{repo}"
        # Token stored in headers dict in process memory — never logged (ADR-0006)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": _GITHUB_ACCEPT,
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        }
        self._http = httpx.AsyncClient()

    def _raise_for_response(
        self,
        response: httpx.Response,
        tool_name: str,
        endpoint: str,
        duration_ms: int,
        change_request_id: str | None = None,
    ) -> None:
        """Raise GitHubAPIError if the response is non-2xx.

        Args:
            response: The httpx Response to inspect.
            tool_name: MCP tool name for structured log fields.
            endpoint: GitHub endpoint string for structured log fields.
            duration_ms: Elapsed duration for structured log fields.
            change_request_id: Change request ID if available.

        Raises:
            GitHubAPIError: If response.is_success is False.
        """
        if not response.is_success:
            github_request_id = response.headers.get("X-GitHub-Request-Id")
            logger.error(
                "tool_call",
                tool_name=tool_name,
                mode="live",
                github_endpoint=endpoint,
                outcome="failure",
                http_status=response.status_code,
                duration_ms=duration_ms,
                change_request_id=change_request_id,
            )
            raise GitHubAPIError(
                message=f"GitHub API returned HTTP {response.status_code}",
                http_status=response.status_code,
                github_request_id=github_request_id,
            )

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str],
    ) -> dict[str, Any]:  # Any: GitHub response body is untyped JSON from external API
        """Create a new GitHub issue.

        Maps to: POST /repos/{owner}/{repo}/issues

        Args:
            title: Issue title.
            body: Issue body as Markdown.
            labels: List of label names to apply. Must include "firepilot:pending".

        Returns:
            Created issue JSON dict from the GitHub API.

        Raises:
            GitHubAPIError: On non-2xx response or network/transport failure.
        """
        endpoint = "POST /repos/{owner}/{repo}/issues"
        start = time.monotonic()
        try:
            response = await self._http.post(
                f"{self._base_url}/issues",
                headers=self._headers,
                json={"title": title, "body": body, "labels": labels},
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            self._raise_for_response(response, "create_issue", endpoint, duration_ms)
            logger.info(
                "tool_call",
                tool_name="create_issue",
                mode="live",
                github_endpoint=endpoint,
                outcome="success",
                http_status=response.status_code,
                duration_ms=duration_ms,
                change_request_id=None,
            )
            result: dict[str, Any] = response.json()
            return result
        except GitHubAPIError:
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "tool_call",
                tool_name="create_issue",
                mode="live",
                github_endpoint=endpoint,
                outcome="failure",
                http_status=None,
                duration_ms=duration_ms,
                change_request_id=None,
            )
            raise GitHubAPIError(
                message=f"GitHub API request failed: {exc}",
                http_status=None,
                github_request_id=None,
            ) from exc

    async def get_issue(
        self, issue_number: int
    ) -> dict[str, Any]:  # Any: GitHub response body is untyped JSON from external API
        """Retrieve a GitHub issue by number.

        Maps to: GET /repos/{owner}/{repo}/issues/{issue_number}

        Args:
            issue_number: GitHub issue number.

        Returns:
            Issue JSON dict from the GitHub API.

        Raises:
            GitHubAPIError: On non-2xx response or network/transport failure.
        """
        endpoint = "GET /repos/{owner}/{repo}/issues/{issue_number}"
        start = time.monotonic()
        cr_id = str(issue_number)
        try:
            response = await self._http.get(
                f"{self._base_url}/issues/{issue_number}",
                headers=self._headers,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            self._raise_for_response(
                response, "get_issue", endpoint, duration_ms, change_request_id=cr_id
            )
            logger.info(
                "tool_call",
                tool_name="get_issue",
                mode="live",
                github_endpoint=endpoint,
                outcome="success",
                http_status=response.status_code,
                duration_ms=duration_ms,
                change_request_id=cr_id,
            )
            result: dict[str, Any] = response.json()
            return result
        except GitHubAPIError:
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "tool_call",
                tool_name="get_issue",
                mode="live",
                github_endpoint=endpoint,
                outcome="failure",
                http_status=None,
                duration_ms=duration_ms,
                change_request_id=cr_id,
            )
            raise GitHubAPIError(
                message=f"GitHub API request failed: {exc}",
                http_status=None,
                github_request_id=None,
            ) from exc

    async def add_comment(
        self, issue_number: int, body: str
    ) -> dict[str, Any]:  # Any: GitHub response body is untyped JSON from external API
        """Add a comment to a GitHub issue.

        Maps to: POST /repos/{owner}/{repo}/issues/{issue_number}/comments

        Args:
            issue_number: GitHub issue number.
            body: Comment body as Markdown.

        Returns:
            Created comment JSON dict from the GitHub API.

        Raises:
            GitHubAPIError: On non-2xx response or network/transport failure.
        """
        endpoint = "POST /repos/{owner}/{repo}/issues/{issue_number}/comments"
        start = time.monotonic()
        cr_id = str(issue_number)
        try:
            response = await self._http.post(
                f"{self._base_url}/issues/{issue_number}/comments",
                headers=self._headers,
                json={"body": body},
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            self._raise_for_response(
                response, "add_comment", endpoint, duration_ms, change_request_id=cr_id
            )
            logger.info(
                "tool_call",
                tool_name="add_comment",
                mode="live",
                github_endpoint=endpoint,
                outcome="success",
                http_status=response.status_code,
                duration_ms=duration_ms,
                change_request_id=cr_id,
            )
            result: dict[str, Any] = response.json()
            return result
        except GitHubAPIError:
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "tool_call",
                tool_name="add_comment",
                mode="live",
                github_endpoint=endpoint,
                outcome="failure",
                http_status=None,
                duration_ms=duration_ms,
                change_request_id=cr_id,
            )
            raise GitHubAPIError(
                message=f"GitHub API request failed: {exc}",
                http_status=None,
                github_request_id=None,
            ) from exc

    async def set_labels(
        self, issue_number: int, labels: list[str]
    ) -> list[dict[str, Any]]:  # Any: GitHub response body is untyped JSON from external API
        """Replace the full label set on a GitHub issue.

        Maps to: PUT /repos/{owner}/{repo}/issues/{issue_number}/labels

        This is intentional: FirePilot controls the complete label set on
        firepilot issues. Using PUT replaces all labels atomically.

        Args:
            issue_number: GitHub issue number.
            labels: Complete replacement label list.

        Returns:
            Updated label list JSON from the GitHub API.

        Raises:
            GitHubAPIError: On non-2xx response or network/transport failure.
        """
        endpoint = "PUT /repos/{owner}/{repo}/issues/{issue_number}/labels"
        start = time.monotonic()
        cr_id = str(issue_number)
        try:
            response = await self._http.put(
                f"{self._base_url}/issues/{issue_number}/labels",
                headers=self._headers,
                json={"labels": labels},
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            self._raise_for_response(
                response, "set_labels", endpoint, duration_ms, change_request_id=cr_id
            )
            logger.info(
                "tool_call",
                tool_name="set_labels",
                mode="live",
                github_endpoint=endpoint,
                outcome="success",
                http_status=response.status_code,
                duration_ms=duration_ms,
                change_request_id=cr_id,
            )
            result: list[dict[str, Any]] = response.json()
            return result
        except GitHubAPIError:
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "tool_call",
                tool_name="set_labels",
                mode="live",
                github_endpoint=endpoint,
                outcome="failure",
                http_status=None,
                duration_ms=duration_ms,
                change_request_id=cr_id,
            )
            raise GitHubAPIError(
                message=f"GitHub API request failed: {exc}",
                http_status=None,
                github_request_id=None,
            ) from exc

    async def close_issue(
        self, issue_number: int
    ) -> dict[str, Any]:  # Any: GitHub response body is untyped JSON from external API
        """Close a GitHub issue.

        Maps to: PATCH /repos/{owner}/{repo}/issues/{issue_number}

        Args:
            issue_number: GitHub issue number.

        Returns:
            Updated issue JSON dict from the GitHub API.

        Raises:
            GitHubAPIError: On non-2xx response or network/transport failure.
        """
        endpoint = "PATCH /repos/{owner}/{repo}/issues/{issue_number}"
        start = time.monotonic()
        cr_id = str(issue_number)
        try:
            response = await self._http.patch(
                f"{self._base_url}/issues/{issue_number}",
                headers=self._headers,
                json={"state": "closed"},
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            self._raise_for_response(
                response, "close_issue", endpoint, duration_ms, change_request_id=cr_id
            )
            logger.info(
                "tool_call",
                tool_name="close_issue",
                mode="live",
                github_endpoint=endpoint,
                outcome="success",
                http_status=response.status_code,
                duration_ms=duration_ms,
                change_request_id=cr_id,
            )
            result: dict[str, Any] = response.json()
            return result
        except GitHubAPIError:
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "tool_call",
                tool_name="close_issue",
                mode="live",
                github_endpoint=endpoint,
                outcome="failure",
                http_status=None,
                duration_ms=duration_ms,
                change_request_id=cr_id,
            )
            raise GitHubAPIError(
                message=f"GitHub API request failed: {exc}",
                http_status=None,
                github_request_id=None,
            ) from exc


@lru_cache(maxsize=1)
def get_github_client() -> GitHubClient:
    """Return the shared GitHubClient singleton.

    The client holds the httpx.AsyncClient connection pool. Using a singleton
    avoids unnecessary connection overhead across tool calls.

    Returns:
        The shared GitHubClient instance, constructed on first call using
        credentials from the current Settings.

    Note:
        This function must only be called in live mode. In demo mode the
        GitHubClient is never instantiated — credentials are not required.
    """
    settings = get_settings()
    return GitHubClient(token=settings.itsm_github_token, repo=settings.itsm_github_repo)
