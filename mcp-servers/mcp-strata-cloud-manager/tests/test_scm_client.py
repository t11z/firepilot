"""Unit tests for SCMClient: token lifecycle and API call behaviour.

All tests run without network access. httpx HTTP calls are mocked via
unittest.mock.AsyncMock. structlog output is captured by patching the module-level
logger in scm_client to verify that token values never appear in log entries.

Test categories:
  Token lifecycle:
    - Token acquired on first API call
    - Valid token reused without re-acquisition
    - Expiring token (< 60 s remaining) triggers proactive refresh
    - Failed token acquisition raises SCMAuthError with code SCM_AUTH_FAILURE
    - Token value is absent from all log output

  API calls:
    - list_security_zones sends the correct URL, query params, and auth header
    - SCM HTTP error response is translated into SCMAPIError with request_id and
      error_codes
    - Authorization header uses Bearer scheme
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_strata_cloud_manager.scm_client import (
    SCM_AUTH_FAILURE_CODE,
    SCMAPIError,
    SCMAuthError,
    SCMClient,
    SCMResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    token_url: str = "https://auth.example.com/oauth2/access_token",
    api_base_url: str = "https://api.example.com",
    tsg_id: str = "fake-tsg-id",
    client_id: str = "fake-client-id",
    client_secret: str = "fake-client-secret",
) -> MagicMock:
    """Return a mock Settings object with SCM credential fields."""
    s = MagicMock()
    s.scm_token_url = token_url
    s.scm_api_base_url = api_base_url
    s.scm_tsg_id = tsg_id
    s.scm_client_id = client_id
    s.scm_client_secret = client_secret
    return s


def _make_http_response(
    status_code: int,
    json_body: dict[str, Any],
    *,
    is_success: bool = True,
    request_id_header: str | None = None,
) -> MagicMock:
    """Return a mock httpx.Response with the given status code and JSON body.

    Args:
        status_code: HTTP status code for the mock response.
        json_body: Parsed JSON body returned by response.json().
        is_success: Whether is_success should return True (2xx).
        request_id_header: Value for X-Request-Id header, if any.
    """
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.is_success = is_success
    response.json.return_value = json_body
    response.raise_for_status.return_value = None
    headers: dict[str, str] = {}
    if request_id_header is not None:
        headers["X-Request-Id"] = request_id_header
    response.headers = headers
    return response


def _make_token_response(
    access_token: str = "test-access-token",
    expires_in: int = 3600,
) -> MagicMock:
    """Return a mock HTTP response that looks like an OAuth2 token endpoint reply."""
    return _make_http_response(
        200,
        {"access_token": access_token, "expires_in": expires_in},
        is_success=True,
    )


_EMPTY_LIST_RESPONSE: dict[str, Any] = {
    "data": [],
    "limit": 200,
    "offset": 0,
    "total": 0,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> MagicMock:
    """Return a mock Settings instance with fake SCM credentials."""
    return _make_settings()


@pytest.fixture
def client(settings: MagicMock) -> SCMClient:
    """Return an SCMClient with a mock settings object and no pre-existing token."""
    return SCMClient(settings)


@pytest.fixture
def client_with_valid_token(settings: MagicMock) -> SCMClient:
    """Return an SCMClient that already has a valid non-expiring token cached."""
    c = SCMClient(settings)
    c._token = "pre-cached-token"
    c._token_expiry = time.monotonic() + 7200  # expires in 2 hours
    return c


# ---------------------------------------------------------------------------
# Token lifecycle tests
# ---------------------------------------------------------------------------


class TestTokenAcquiredOnFirstCall:
    """Token is fetched from the token endpoint on the very first API call."""

    async def test_token_acquired_on_first_call(self, client: SCMClient) -> None:
        """POST to the token endpoint is made exactly once for the first API call."""
        client._http.post = AsyncMock(return_value=_make_token_response())
        client._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client.list_security_zones("Shared")

        client._http.post.assert_awaited_once()

    async def test_token_stored_after_acquisition(self, client: SCMClient) -> None:
        """After acquisition the token is stored in the instance, not on disk."""
        token_value = "stored-token-xyz"
        client._http.post = AsyncMock(
            return_value=_make_token_response(access_token=token_value)
        )
        client._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client.list_security_zones("Shared")

        assert client._token == token_value

    async def test_token_expiry_stored(self, client: SCMClient) -> None:
        """Token expiry is set to approximately now + expires_in seconds."""
        client._http.post = AsyncMock(
            return_value=_make_token_response(expires_in=1800)
        )
        client._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )
        before = time.monotonic()

        await client.list_security_zones("Shared")

        after = time.monotonic()
        # Expiry should be between before+1800 and after+1800
        assert before + 1800 <= client._token_expiry <= after + 1800


class TestValidTokenReused:
    """A cached non-expiring token is reused without calling the token endpoint."""

    async def test_valid_token_reused(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """Token endpoint is not called when the cached token is still valid."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_token_response()
        )
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client_with_valid_token.list_security_zones("Shared")
        await client_with_valid_token.list_security_zones("Shared")

        client_with_valid_token._http.post.assert_not_awaited()

    async def test_get_called_twice_with_same_token(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """Both API calls use the same pre-cached token in the Authorization header."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client_with_valid_token.list_security_zones("Shared")
        await client_with_valid_token.list_security_zones("Shared")

        assert client_with_valid_token._http.get.await_count == 2
        for c in client_with_valid_token._http.get.call_args_list:
            assert c.kwargs["headers"]["Authorization"] == "Bearer pre-cached-token"


class TestExpiringTokenRefresh:
    """A token expiring within 60 s triggers proactive acquisition before the call."""

    async def test_expiring_token_triggers_refresh(self, client: SCMClient) -> None:
        """Token endpoint is called when the cached token expires within 60 s."""
        client._token = "old-token"
        client._token_expiry = time.monotonic() + 30  # expires in 30 s (< 60 s buffer)
        client._http.post = AsyncMock(
            return_value=_make_token_response(access_token="refreshed-token")
        )
        client._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client.list_security_zones("Shared")

        client._http.post.assert_awaited_once()
        assert client._token == "refreshed-token"

    async def test_token_just_outside_buffer_not_refreshed(
        self, client: SCMClient
    ) -> None:
        """Token expiring in exactly 61 s is NOT refreshed (outside the 60 s buffer)."""
        client._token = "still-valid-token"
        client._token_expiry = time.monotonic() + 61
        client._http.post = AsyncMock(return_value=_make_token_response())
        client._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client.list_security_zones("Shared")

        client._http.post.assert_not_awaited()


class TestFailedTokenAcquisition:
    """A failed token acquisition raises SCMAuthError without leaking credentials."""

    async def test_network_error_raises_scm_auth_error(
        self, client: SCMClient
    ) -> None:
        """ConnectError during POST raises SCMAuthError, not the original exception."""
        client._http.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(SCMAuthError):
            await client._acquire_token()

    async def test_error_code_is_scm_auth_failure(self, client: SCMClient) -> None:
        """Raised SCMAuthError carries the SCM_AUTH_FAILURE code."""
        client._http.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(SCMAuthError) as exc_info:
            await client._acquire_token()

        assert exc_info.value.code == SCM_AUTH_FAILURE_CODE

    async def test_error_message_does_not_expose_client_secret(
        self, client: SCMClient
    ) -> None:
        """Error message must not contain the client_secret value (ADR-0006)."""
        client._http.post = AsyncMock(
            side_effect=Exception("HTTP 401 Unauthorized")
        )

        with pytest.raises(SCMAuthError) as exc_info:
            await client._acquire_token()

        assert "fake-client-secret" not in str(exc_info.value)
        assert "fake-client-id" not in str(exc_info.value)

    async def test_http_4xx_on_token_endpoint_raises_scm_auth_error(
        self, client: SCMClient
    ) -> None:
        """A 401 from the token endpoint raises SCMAuthError."""
        bad_response = _make_http_response(401, {"error": "invalid_client"})
        bad_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=MagicMock()
        )
        client._http.post = AsyncMock(return_value=bad_response)

        with pytest.raises(SCMAuthError):
            await client._acquire_token()


class TestTokenNotInLogs:
    """The token value must never appear in structured log output (ADR-0006, T3)."""

    async def test_token_value_absent_from_acquisition_log(
        self, client: SCMClient
    ) -> None:
        """structlog entries produced during _acquire_token do not contain the token."""
        secret_token = "super-secret-token-must-not-appear-in-logs"
        client._http.post = AsyncMock(
            return_value=_make_token_response(access_token=secret_token)
        )

        with patch("mcp_strata_cloud_manager.scm_client.logger") as mock_logger:
            await client._acquire_token()

        for logged_call in mock_logger.info.call_args_list + mock_logger.error.call_args_list:
            assert secret_token not in str(logged_call), (
                "Token value found in log output — ADR-0006 violation"
            )

    async def test_credentials_absent_from_failure_log(
        self, client: SCMClient
    ) -> None:
        """structlog entries on acquisition failure do not contain credentials."""
        client._http.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with patch("mcp_strata_cloud_manager.scm_client.logger") as mock_logger:
            with pytest.raises(SCMAuthError):
                await client._acquire_token()

        for logged_call in mock_logger.error.call_args_list:
            log_str = str(logged_call)
            assert "fake-client-id" not in log_str
            assert "fake-client-secret" not in log_str


# ---------------------------------------------------------------------------
# API call tests
# ---------------------------------------------------------------------------


class TestListSecurityZonesRequest:
    """list_security_zones sends the correct HTTP request."""

    async def test_correct_url(self, client_with_valid_token: SCMClient) -> None:
        """Request URL is constructed from api_base_url + the zones endpoint path."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client_with_valid_token.list_security_zones("Shared")

        called_url = client_with_valid_token._http.get.call_args.args[0]
        assert called_url == "https://api.example.com/config/network/v1/zones"

    async def test_folder_in_query_params(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """folder is included as a query parameter."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client_with_valid_token.list_security_zones("MyFolder")

        params = client_with_valid_token._http.get.call_args.kwargs["params"]
        assert params["folder"] == "MyFolder"

    async def test_optional_name_param_included_when_provided(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """name filter is included in query params when provided."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client_with_valid_token.list_security_zones(
            "Shared", name="trust-zone", limit=50, offset=10
        )

        params = client_with_valid_token._http.get.call_args.kwargs["params"]
        assert params["name"] == "trust-zone"
        assert params["limit"] == 50
        assert params["offset"] == 10

    async def test_none_params_excluded_from_query(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """None-valued optional params are not sent in the query string."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client_with_valid_token.list_security_zones("Shared", name=None)

        params = client_with_valid_token._http.get.call_args.kwargs["params"]
        assert "name" not in params

    async def test_authorization_header_is_bearer_token(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """Authorization header uses the Bearer scheme with the cached token."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client_with_valid_token.list_security_zones("Shared")

        headers = client_with_valid_token._http.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer pre-cached-token"

    async def test_returns_scm_result_with_data(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """A 200 response is returned as an SCMResult with the parsed JSON body."""
        body = {"data": [{"id": "z1", "name": "trust-zone"}], "total": 1, "limit": 200, "offset": 0}
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, body, request_id_header="req-abc")
        )

        result = await client_with_valid_token.list_security_zones("Shared")

        assert isinstance(result, SCMResult)
        assert result.data == body
        assert result.http_status == 200
        assert result.scm_request_id == "req-abc"


class TestSCMAPIErrorHandling:
    """HTTP error responses from the SCM API are translated into SCMAPIError."""

    async def test_404_raises_scm_api_error(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """A 404 response raises SCMAPIError with the correct http_status."""
        error_body = {
            "_errors": [{"code": "E006", "message": "Requested object not found"}],
            "_request_id": "req-xyz",
        }
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(404, error_body, is_success=False)
        )

        with pytest.raises(SCMAPIError) as exc_info:
            await client_with_valid_token.list_security_zones("Shared")

        exc = exc_info.value
        assert exc.http_status == 404

    async def test_error_codes_extracted_from_body(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """SCM error codes are extracted from _errors[].code in the response body."""
        error_body = {
            "_errors": [
                {"code": "E006", "message": "Not found"},
                {"code": "E016", "message": "Bad input"},
            ],
            "_request_id": "req-xyz",
        }
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(422, error_body, is_success=False)
        )

        with pytest.raises(SCMAPIError) as exc_info:
            await client_with_valid_token.list_security_zones("Shared")

        assert "E006" in exc_info.value.error_codes
        assert "E016" in exc_info.value.error_codes

    async def test_request_id_extracted_from_body(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """_request_id from the SCM error body is exposed on the raised exception."""
        error_body = {
            "_errors": [{"code": "E013", "message": "Internal error"}],
            "_request_id": "body-request-id-123",
        }
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(500, error_body, is_success=False)
        )

        with pytest.raises(SCMAPIError) as exc_info:
            await client_with_valid_token.list_security_zones("Shared")

        assert exc_info.value.request_id == "body-request-id-123"

    async def test_request_id_falls_back_to_header(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """When _request_id is absent from the body, X-Request-Id header is used."""
        error_body = {"_errors": [{"code": "E003", "message": "Forbidden"}]}
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(
                403,
                error_body,
                is_success=False,
                request_id_header="header-request-id-456",
            )
        )

        with pytest.raises(SCMAPIError) as exc_info:
            await client_with_valid_token.list_security_zones("Shared")

        assert exc_info.value.request_id == "header-request-id-456"

    async def test_network_error_raises_scm_api_error(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """A network-level exception is wrapped in SCMAPIError with http_status=None."""
        client_with_valid_token._http.get = AsyncMock(
            side_effect=httpx.ConnectError("Network unreachable")
        )

        with pytest.raises(SCMAPIError) as exc_info:
            await client_with_valid_token.list_security_zones("Shared")

        assert exc_info.value.http_status is None


class TestAllReadEndpoints:
    """All four read methods call _get with the correct endpoint paths."""

    async def test_list_security_rules_endpoint(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """list_security_rules targets /config/security/v1/security-rules."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client_with_valid_token.list_security_rules("Shared")

        called_url = client_with_valid_token._http.get.call_args.args[0]
        assert "/config/security/v1/security-rules" in called_url

    async def test_list_security_rules_maps_position_to_rulebase(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """list_security_rules sends 'rulebase' query param, not 'position'."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client_with_valid_token.list_security_rules(
            "Shared", position="pre"
        )

        call_kwargs = client_with_valid_token._http.get.call_args
        sent_params = call_kwargs.kwargs.get("params", {})
        assert "rulebase" in sent_params
        assert sent_params["rulebase"] == "pre"
        assert "position" not in sent_params

    async def test_list_security_rules_no_position_omits_rulebase(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """list_security_rules without position omits rulebase from query."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client_with_valid_token.list_security_rules("Shared")

        call_kwargs = client_with_valid_token._http.get.call_args
        sent_params = call_kwargs.kwargs.get("params", {})
        assert "rulebase" not in sent_params
        assert "position" not in sent_params

    async def test_list_addresses_endpoint(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """list_addresses targets /config/objects/v1/addresses."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client_with_valid_token.list_addresses("Shared")

        called_url = client_with_valid_token._http.get.call_args.args[0]
        assert "/config/objects/v1/addresses" in called_url

    async def test_list_address_groups_endpoint(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """list_address_groups targets /config/objects/v1/address-groups."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _EMPTY_LIST_RESPONSE)
        )

        await client_with_valid_token.list_address_groups("Shared")

        called_url = client_with_valid_token._http.get.call_args.args[0]
        assert "/config/objects/v1/address-groups" in called_url


# ---------------------------------------------------------------------------
# _post() tests
# ---------------------------------------------------------------------------


_CREATED_RULE_BODY: dict[str, Any] = {
    "id": "rule-id-001",
    "name": "allow-web",
    "folder": "Shared",
    "action": "allow",
}


class TestPostMethod:
    """_post() sends the correct HTTP POST request and handles errors."""

    async def test_correct_url(self, client_with_valid_token: SCMClient) -> None:
        """POST URL is constructed from api_base_url + the endpoint path."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _CREATED_RULE_BODY)
        )

        await client_with_valid_token._post(
            "test_tool",
            "/config/security/v1/security-rules",
            json_body={"name": "rule"},
        )

        called_url = client_with_valid_token._http.post.call_args.args[0]
        assert called_url == "https://api.example.com/config/security/v1/security-rules"

    async def test_authorization_header_is_bearer_token(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """Authorization header uses the Bearer scheme with the cached token."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _CREATED_RULE_BODY)
        )

        await client_with_valid_token._post(
            "test_tool",
            "/config/security/v1/security-rules",
            json_body={"name": "rule"},
        )

        headers = client_with_valid_token._http.post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer pre-cached-token"

    async def test_json_body_passed_to_post(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """The json_body dict is passed as the json kwarg to httpx.post."""
        body = {"name": "my-rule", "action": "allow"}
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _CREATED_RULE_BODY)
        )

        await client_with_valid_token._post(
            "test_tool",
            "/config/security/v1/security-rules",
            json_body=body,
        )

        sent_json = client_with_valid_token._http.post.call_args.kwargs["json"]
        assert sent_json == body

    async def test_query_params_with_none_excluded(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """None-valued query params are not sent in the query string."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _CREATED_RULE_BODY)
        )

        await client_with_valid_token._post(
            "test_tool",
            "/config/security/v1/security-rules",
            json_body={"name": "rule"},
            folder="Shared",
            position=None,
        )

        params = client_with_valid_token._http.post.call_args.kwargs["params"]
        assert "folder" in params
        assert "position" not in params

    async def test_query_params_included_when_provided(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """Non-None query params are included in the request."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _CREATED_RULE_BODY)
        )

        await client_with_valid_token._post(
            "test_tool",
            "/config/security/v1/security-rules",
            json_body={"name": "rule"},
            folder="MyFolder",
            position="pre",
        )

        params = client_with_valid_token._http.post.call_args.kwargs["params"]
        assert params["folder"] == "MyFolder"
        assert params["position"] == "pre"

    async def test_returns_scm_result_on_success(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """A 201 response is returned as an SCMResult with the parsed JSON body."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(
                201, _CREATED_RULE_BODY, request_id_header="req-post-abc"
            )
        )

        result = await client_with_valid_token._post(
            "test_tool",
            "/config/security/v1/security-rules",
            json_body={"name": "rule"},
        )

        assert isinstance(result, SCMResult)
        assert result.data == _CREATED_RULE_BODY
        assert result.http_status == 201
        assert result.scm_request_id == "req-post-abc"

    async def test_non_2xx_raises_scm_api_error(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """A 4xx response raises SCMAPIError with the correct http_status."""
        error_body = {
            "_errors": [{"code": "E006", "message": "Name not unique"}],
            "_request_id": "req-409",
        }
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(409, error_body, is_success=False)
        )

        with pytest.raises(SCMAPIError) as exc_info:
            await client_with_valid_token._post(
                "test_tool",
                "/config/security/v1/security-rules",
                json_body={"name": "rule"},
            )

        exc = exc_info.value
        assert exc.http_status == 409
        assert "E006" in exc.error_codes
        assert exc.request_id == "req-409"

    async def test_network_error_raises_scm_api_error_with_none_status(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """A network-level exception is wrapped in SCMAPIError with http_status=None."""
        client_with_valid_token._http.post = AsyncMock(
            side_effect=httpx.ConnectError("Network unreachable")
        )

        with pytest.raises(SCMAPIError) as exc_info:
            await client_with_valid_token._post(
                "test_tool",
                "/config/security/v1/security-rules",
                json_body={"name": "rule"},
            )

        assert exc_info.value.http_status is None


# ---------------------------------------------------------------------------
# create_security_rule() tests
# ---------------------------------------------------------------------------


class TestCreateSecurityRule:
    """create_security_rule sends the correct POST request."""

    async def test_correct_endpoint_path(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """create_security_rule targets /config/security/v1/security-rules."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _CREATED_RULE_BODY)
        )

        await client_with_valid_token.create_security_rule("Shared", {"name": "rule"})

        called_url = client_with_valid_token._http.post.call_args.args[0]
        assert "/config/security/v1/security-rules" in called_url

    async def test_folder_in_query_params(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """folder is sent as a query parameter, not in the body."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _CREATED_RULE_BODY)
        )

        await client_with_valid_token.create_security_rule("MyFolder", {"name": "rule"})

        params = client_with_valid_token._http.post.call_args.kwargs["params"]
        assert params["folder"] == "MyFolder"

    async def test_position_in_query_params(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """position is sent as a query parameter with the provided value."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _CREATED_RULE_BODY)
        )

        await client_with_valid_token.create_security_rule(
            "Shared", {"name": "rule"}, position="post"
        )

        params = client_with_valid_token._http.post.call_args.kwargs["params"]
        assert params["position"] == "post"

    async def test_default_position_is_pre(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """Default position is 'pre' when not explicitly provided."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _CREATED_RULE_BODY)
        )

        await client_with_valid_token.create_security_rule("Shared", {"name": "rule"})

        params = client_with_valid_token._http.post.call_args.kwargs["params"]
        assert params["position"] == "pre"

    async def test_rule_body_passed_as_json(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """The rule_body dict is sent as the POST JSON body unchanged."""
        rule_body = {
            "name": "allow-web",
            "from": ["untrust"],
            "to": ["trust"],
            "action": "allow",
        }
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _CREATED_RULE_BODY)
        )

        await client_with_valid_token.create_security_rule("Shared", rule_body)

        sent_json = client_with_valid_token._http.post.call_args.kwargs["json"]
        assert sent_json == rule_body

    async def test_returns_scm_result(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """A 201 response is returned as an SCMResult."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _CREATED_RULE_BODY)
        )

        result = await client_with_valid_token.create_security_rule(
            "Shared", {"name": "rule"}
        )

        assert isinstance(result, SCMResult)
        assert result.data == _CREATED_RULE_BODY


# ---------------------------------------------------------------------------
# push_candidate_config() tests
# ---------------------------------------------------------------------------


_PUSH_RESPONSE_BODY: dict[str, Any] = {"id": "push-job-001", "job_status": "FIN"}


class TestPushCandidateConfig:
    """push_candidate_config sends the correct POST request."""

    async def test_correct_endpoint_path(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """push_candidate_config targets the candidate:push endpoint."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _PUSH_RESPONSE_BODY)
        )

        await client_with_valid_token.push_candidate_config(["Shared"])

        called_url = client_with_valid_token._http.post.call_args.args[0]
        assert "/config/operations/v1/config-versions/candidate:push" in called_url

    async def test_folders_mapped_to_folder_in_body(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """The folders list is serialised as 'folder' in the request body."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _PUSH_RESPONSE_BODY)
        )

        await client_with_valid_token.push_candidate_config(["Shared", "Corp"])

        sent_json = client_with_valid_token._http.post.call_args.kwargs["json"]
        assert sent_json["folder"] == ["Shared", "Corp"]

    async def test_admin_included_when_provided(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """admin is included in the body when provided."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _PUSH_RESPONSE_BODY)
        )

        await client_with_valid_token.push_candidate_config(
            ["Shared"], admin=["admin-user"]
        )

        sent_json = client_with_valid_token._http.post.call_args.kwargs["json"]
        assert sent_json["admin"] == ["admin-user"]

    async def test_admin_excluded_when_none(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """admin is excluded from the body when None (required for 'All' folder push)."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _PUSH_RESPONSE_BODY)
        )

        await client_with_valid_token.push_candidate_config(["Shared"], admin=None)

        sent_json = client_with_valid_token._http.post.call_args.kwargs["json"]
        assert "admin" not in sent_json

    async def test_description_included_when_provided(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """description is included in the body when provided."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _PUSH_RESPONSE_BODY)
        )

        await client_with_valid_token.push_candidate_config(
            ["Shared"], description="Deploy new rules"
        )

        sent_json = client_with_valid_token._http.post.call_args.kwargs["json"]
        assert sent_json["description"] == "Deploy new rules"

    async def test_description_excluded_when_none(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """description is excluded from the body when None."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _PUSH_RESPONSE_BODY)
        )

        await client_with_valid_token.push_candidate_config(["Shared"])

        sent_json = client_with_valid_token._http.post.call_args.kwargs["json"]
        assert "description" not in sent_json

    async def test_no_query_params_sent(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """push_candidate_config does not send any query parameters."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _PUSH_RESPONSE_BODY)
        )

        await client_with_valid_token.push_candidate_config(["Shared"])

        params = client_with_valid_token._http.post.call_args.kwargs["params"]
        assert params == {}

    async def test_returns_scm_result(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """A 201 response is returned as an SCMResult."""
        client_with_valid_token._http.post = AsyncMock(
            return_value=_make_http_response(201, _PUSH_RESPONSE_BODY)
        )

        result = await client_with_valid_token.push_candidate_config(["Shared"])

        assert isinstance(result, SCMResult)
        assert result.data == _PUSH_RESPONSE_BODY


# ---------------------------------------------------------------------------
# get_job_status() tests
# ---------------------------------------------------------------------------


_JOB_RESPONSE_BODY: dict[str, Any] = {
    "data": [
        {
            "id": "job-001",
            "status_str": "FIN",
            "result_str": "OK",
            "percent": 100,
        }
    ]
}


class TestGetJobStatus:
    """get_job_status sends the correct GET request."""

    async def test_correct_endpoint_path_with_job_id(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """get_job_status targets /config/operations/v1/jobs/{job_id}."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _JOB_RESPONSE_BODY)
        )

        await client_with_valid_token.get_job_status("job-abc-123")

        called_url = client_with_valid_token._http.get.call_args.args[0]
        assert "/config/operations/v1/jobs/job-abc-123" in called_url

    async def test_no_folder_query_param(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """get_job_status does not send a folder query parameter."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _JOB_RESPONSE_BODY)
        )

        await client_with_valid_token.get_job_status("job-001")

        params = client_with_valid_token._http.get.call_args.kwargs["params"]
        assert "folder" not in params

    async def test_authorization_header_present(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """Authorization header is present with the Bearer token."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _JOB_RESPONSE_BODY)
        )

        await client_with_valid_token.get_job_status("job-001")

        headers = client_with_valid_token._http.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer pre-cached-token"

    async def test_returns_scm_result(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """A 200 response is returned as an SCMResult."""
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(200, _JOB_RESPONSE_BODY)
        )

        result = await client_with_valid_token.get_job_status("job-001")

        assert isinstance(result, SCMResult)
        assert result.data == _JOB_RESPONSE_BODY

    async def test_404_raises_scm_api_error(
        self, client_with_valid_token: SCMClient
    ) -> None:
        """A 404 response (E005) raises SCMAPIError."""
        error_body = {
            "_errors": [{"code": "E005", "message": "Object not present"}],
            "_request_id": "req-404-job",
        }
        client_with_valid_token._http.get = AsyncMock(
            return_value=_make_http_response(404, error_body, is_success=False)
        )

        with pytest.raises(SCMAPIError) as exc_info:
            await client_with_valid_token.get_job_status("nonexistent-job")

        exc = exc_info.value
        assert exc.http_status == 404
        assert "E005" in exc.error_codes
