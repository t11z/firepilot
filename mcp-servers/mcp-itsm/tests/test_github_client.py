"""Unit tests for GitHubClient HTTP methods.

Uses respx to mock httpx transport so no real HTTP calls are made.
Tests cover happy-path responses, non-2xx error mapping, and network
failure mapping to GitHubAPIError.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_itsm.github_client import GitHubAPIError, GitHubClient

# Shared test credentials — never real values
_TEST_TOKEN = "ghp_test-token-value"
_TEST_REPO = "test-org/test-repo"
_BASE_URL = f"https://api.github.com/repos/{_TEST_REPO}"


def _make_client() -> GitHubClient:
    """Return a GitHubClient pointed at the test repository."""
    return GitHubClient(token=_TEST_TOKEN, repo=_TEST_REPO)


# ---------------------------------------------------------------------------
# create_issue
# ---------------------------------------------------------------------------


class TestCreateIssue:
    """GitHubClient.create_issue wraps POST /repos/{owner}/{repo}/issues."""

    @respx.mock
    async def test_success_returns_issue_json(self) -> None:
        """Successful 201 response returns the parsed issue dict."""
        respx.post(f"{_BASE_URL}/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "number": 99,
                    "html_url": "https://github.com/test-org/test-repo/issues/99",
                    "created_at": "2026-03-20T10:00:00Z",
                    "title": "Test issue",
                    "body": "Test body",
                    "labels": [{"name": "firepilot:pending"}],
                    "state": "open",
                    "updated_at": "2026-03-20T10:00:00Z",
                    "closed_at": None,
                },
            )
        )
        client = _make_client()
        result = await client.create_issue(
            title="Test issue",
            body="Test body",
            labels=["firepilot:pending"],
        )
        assert result["number"] == 99
        assert "html_url" in result

    @respx.mock
    async def test_sends_correct_payload(self) -> None:
        """create_issue sends title, body, and labels in the request body."""
        route = respx.post(f"{_BASE_URL}/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "number": 1,
                    "html_url": "https://github.com/test-org/test-repo/issues/1",
                    "created_at": "2026-03-20T10:00:00Z",
                },
            )
        )
        client = _make_client()
        await client.create_issue(
            title="My title",
            body="My body",
            labels=["firepilot:pending"],
        )
        request = route.calls.last.request
        import json

        payload = json.loads(request.content)
        assert payload["title"] == "My title"
        assert payload["body"] == "My body"
        assert payload["labels"] == ["firepilot:pending"]

    @respx.mock
    async def test_422_raises_github_api_error(self) -> None:
        """422 validation error is raised as GitHubAPIError with correct http_status."""
        respx.post(f"{_BASE_URL}/issues").mock(
            return_value=httpx.Response(
                422,
                headers={"X-GitHub-Request-Id": "req-422"},
                json={"message": "Validation Failed"},
            )
        )
        client = _make_client()
        with pytest.raises(GitHubAPIError) as exc_info:
            await client.create_issue(title="T", body="B", labels=[])
        assert exc_info.value.http_status == 422
        assert exc_info.value.github_request_id == "req-422"

    @respx.mock
    async def test_network_error_raises_github_api_error_with_none_status(
        self,
    ) -> None:
        """Network failure raises GitHubAPIError with http_status=None."""
        respx.post(f"{_BASE_URL}/issues").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        client = _make_client()
        with pytest.raises(GitHubAPIError) as exc_info:
            await client.create_issue(title="T", body="B", labels=[])
        assert exc_info.value.http_status is None


# ---------------------------------------------------------------------------
# get_issue
# ---------------------------------------------------------------------------


class TestGetIssue:
    """GitHubClient.get_issue wraps GET /repos/{owner}/{repo}/issues/{number}."""

    @respx.mock
    async def test_success_returns_issue_json(self) -> None:
        """Successful 200 response returns the parsed issue dict."""
        respx.get(f"{_BASE_URL}/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "number": 42,
                    "title": "Allow HTTPS",
                    "html_url": "https://github.com/test-org/test-repo/issues/42",
                    "state": "open",
                    "labels": [{"name": "firepilot:pending", "color": "ededed"}],
                    "body": "## Change Request\n\n**Requestor**: Ops",
                    "created_at": "2026-03-19T10:00:00Z",
                    "updated_at": "2026-03-19T10:15:00Z",
                    "closed_at": None,
                },
            )
        )
        client = _make_client()
        result = await client.get_issue(42)
        assert result["number"] == 42
        assert result["title"] == "Allow HTTPS"

    @respx.mock
    async def test_404_raises_github_api_error(self) -> None:
        """404 response raises GitHubAPIError with http_status=404."""
        respx.get(f"{_BASE_URL}/issues/9999").mock(
            return_value=httpx.Response(
                404,
                headers={"X-GitHub-Request-Id": "req-404"},
                json={"message": "Not Found"},
            )
        )
        client = _make_client()
        with pytest.raises(GitHubAPIError) as exc_info:
            await client.get_issue(9999)
        assert exc_info.value.http_status == 404

    @respx.mock
    async def test_network_error_raises_github_api_error_with_none_status(
        self,
    ) -> None:
        """Network failure raises GitHubAPIError with http_status=None."""
        respx.get(f"{_BASE_URL}/issues/1").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        client = _make_client()
        with pytest.raises(GitHubAPIError) as exc_info:
            await client.get_issue(1)
        assert exc_info.value.http_status is None


# ---------------------------------------------------------------------------
# add_comment
# ---------------------------------------------------------------------------


class TestAddComment:
    """GitHubClient.add_comment wraps POST /repos/{owner}/{repo}/issues/{n}/comments."""

    @respx.mock
    async def test_success_returns_comment_json(self) -> None:
        """Successful 201 response returns the parsed comment dict."""
        respx.post(f"{_BASE_URL}/issues/42/comments").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 5001,
                    "html_url": "https://github.com/test-org/test-repo/issues/42#issuecomment-5001",
                    "created_at": "2026-03-20T11:00:00Z",
                    "body": "FirePilot Event: rule_validated",
                },
            )
        )
        client = _make_client()
        result = await client.add_comment(42, body="FirePilot Event: rule_validated")
        assert result["id"] == 5001
        assert "html_url" in result

    @respx.mock
    async def test_404_raises_github_api_error(self) -> None:
        """404 on comment creation raises GitHubAPIError with http_status=404."""
        respx.post(f"{_BASE_URL}/issues/9999/comments").mock(
            return_value=httpx.Response(
                404, json={"message": "Not Found"}
            )
        )
        client = _make_client()
        with pytest.raises(GitHubAPIError) as exc_info:
            await client.add_comment(9999, body="body")
        assert exc_info.value.http_status == 404

    @respx.mock
    async def test_network_error_raises_github_api_error_with_none_status(
        self,
    ) -> None:
        """Network failure raises GitHubAPIError with http_status=None."""
        respx.post(f"{_BASE_URL}/issues/1/comments").mock(
            side_effect=httpx.ConnectError("refused")
        )
        client = _make_client()
        with pytest.raises(GitHubAPIError) as exc_info:
            await client.add_comment(1, body="body")
        assert exc_info.value.http_status is None


# ---------------------------------------------------------------------------
# set_labels
# ---------------------------------------------------------------------------


class TestSetLabels:
    """GitHubClient.set_labels wraps PUT /repos/{owner}/{repo}/issues/{n}/labels."""

    @respx.mock
    async def test_success_returns_label_list(self) -> None:
        """Successful 200 response returns the label list."""
        respx.put(f"{_BASE_URL}/issues/42/labels").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"name": "firepilot:deployed", "color": "0e8a16"},
                ],
            )
        )
        client = _make_client()
        result = await client.set_labels(42, ["firepilot:deployed"])
        assert isinstance(result, list)
        assert result[0]["name"] == "firepilot:deployed"

    @respx.mock
    async def test_422_raises_github_api_error(self) -> None:
        """422 from label PUT raises GitHubAPIError with correct http_status."""
        respx.put(f"{_BASE_URL}/issues/42/labels").mock(
            return_value=httpx.Response(422, json={"message": "Validation Failed"})
        )
        client = _make_client()
        with pytest.raises(GitHubAPIError) as exc_info:
            await client.set_labels(42, ["nonexistent-label"])
        assert exc_info.value.http_status == 422


# ---------------------------------------------------------------------------
# close_issue
# ---------------------------------------------------------------------------


class TestCloseIssue:
    """GitHubClient.close_issue wraps PATCH /repos/{owner}/{repo}/issues/{n}."""

    @respx.mock
    async def test_success_returns_updated_issue(self) -> None:
        """Successful 200 response returns the updated issue dict."""
        respx.patch(f"{_BASE_URL}/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "number": 42,
                    "state": "closed",
                    "html_url": "https://github.com/test-org/test-repo/issues/42",
                    "closed_at": "2026-03-20T12:00:00Z",
                },
            )
        )
        client = _make_client()
        result = await client.close_issue(42)
        assert result["state"] == "closed"
        assert result["closed_at"] is not None

    @respx.mock
    async def test_404_raises_github_api_error(self) -> None:
        """404 on close raises GitHubAPIError with http_status=404."""
        respx.patch(f"{_BASE_URL}/issues/9999").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        client = _make_client()
        with pytest.raises(GitHubAPIError) as exc_info:
            await client.close_issue(9999)
        assert exc_info.value.http_status == 404

    @respx.mock
    async def test_network_error_raises_github_api_error_with_none_status(
        self,
    ) -> None:
        """Network failure raises GitHubAPIError with http_status=None."""
        respx.patch(f"{_BASE_URL}/issues/1").mock(
            side_effect=httpx.ConnectError("refused")
        )
        client = _make_client()
        with pytest.raises(GitHubAPIError) as exc_info:
            await client.close_issue(1)
        assert exc_info.value.http_status is None
