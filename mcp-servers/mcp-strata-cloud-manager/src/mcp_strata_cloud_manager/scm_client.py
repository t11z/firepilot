"""SCM HTTP client for mcp-strata-cloud-manager.

This module is the sole credential boundary for all SCM API communication.
No other module constructs HTTP requests or handles OAuth2 tokens.

The access token is stored in process memory only — it is never written
to disk, never included in log output, and never returned in tool responses
(ADR-0006, threat model T3).

Token lifecycle (ADR-0006):
1. Acquired lazily on the first API call requiring live mode.
2. Stored in instance attributes along with its computed expiry timestamp.
3. Proactively refreshed when it expires within the next 60 seconds.
4. On acquisition failure, SCMAuthError is raised with code SCM_AUTH_FAILURE
   and a message that does not contain credential values.
"""

from __future__ import annotations

import dataclasses
import time
from functools import lru_cache
from typing import Any

import httpx
import structlog

from mcp_strata_cloud_manager.config import Settings, get_settings

logger = structlog.get_logger(__name__)

# ADR-0006: proactively refresh the token when it expires within this window.
_TOKEN_REFRESH_BUFFER_SECONDS: int = 60

# Error codes surfaced to the tool layer.
SCM_AUTH_FAILURE_CODE: str = "SCM_AUTH_FAILURE"
SCM_API_ERROR_CODE: str = "SCM_API_ERROR"


class SCMAuthError(Exception):
    """Raised when OAuth2 token acquisition fails.

    The error message must not contain credential values. Consumers should
    translate this into a tool response with code SCM_AUTH_FAILURE.
    """

    code: str = SCM_AUTH_FAILURE_CODE


class SCMAPIError(Exception):
    """Raised when an SCM API HTTP call returns a non-2xx status.

    Attributes:
        http_status: HTTP status code returned by SCM, or None on network error.
        request_id: _request_id from the SCM error body, or X-Request-Id header
                    value; None if neither is present.
        error_codes: SCM error codes extracted from _errors[].code in the body.
    """

    def __init__(
        self,
        message: str,
        http_status: int | None,
        request_id: str | None,
        error_codes: list[str],
    ) -> None:
        """Initialise with message and structured HTTP error metadata.

        Args:
            message: Human-readable error description. Must not contain
                     credential values.
            http_status: HTTP status code, or None on network failure.
            request_id: SCM request identifier for support escalation.
            error_codes: SCM-specific error codes from the response body.
        """
        super().__init__(message)
        self.http_status = http_status
        self.request_id = request_id
        self.error_codes = error_codes


@dataclasses.dataclass(frozen=True, slots=True)
class SCMResult:
    """Container for a successful SCM API response.

    Attributes:
        data: Parsed JSON response body matching the SCM API contract (ADR-0004).
        http_status: HTTP status code from the response (2xx on success).
        scm_request_id: Value of the X-Request-Id response header, or None if
                        the header was not present.
    """

    data: dict[str, Any]  # Any: SCM response body is untyped JSON from external API
    http_status: int
    scm_request_id: str | None


class SCMClient:
    """HTTP client for the Palo Alto Networks Strata Cloud Manager API.

    Manages the OAuth2 Client Credentials token lifecycle internally.
    The access token is stored in process memory only — it is never written
    to disk, never included in log output, and never returned in tool responses
    (ADR-0006; threat model T3).

    All API methods acquire a token lazily on the first call. Subsequent calls
    reuse the cached token unless it expires within the next 60 seconds, in
    which case a new token is acquired proactively before the request proceeds.

    A single httpx.AsyncClient instance is shared across all requests for
    connection pool reuse. Callers should use get_scm_client() to obtain the
    shared singleton rather than constructing SCMClient directly.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise the client with server configuration.

        Args:
            settings: Server settings providing SCM credentials and endpoints.
                      Credentials are read from the settings object — they are
                      not passed as direct constructor arguments.
        """
        self._settings = settings
        self._token: str | None = None
        self._token_expiry: float = 0.0  # monotonic timestamp (seconds)
        self._http: httpx.AsyncClient = httpx.AsyncClient()

    async def _ensure_token(self) -> str:
        """Return a valid access token, acquiring or refreshing as necessary.

        Checks whether the current token expires within _TOKEN_REFRESH_BUFFER_SECONDS
        and proactively acquires a new one if so (ADR-0006).

        Returns:
            A valid Bearer token string.

        Raises:
            SCMAuthError: If token acquisition fails for any reason. The error
                          message does not expose credential values.
        """
        now = time.monotonic()
        if self._token is None or now + _TOKEN_REFRESH_BUFFER_SECONDS >= self._token_expiry:
            await self._acquire_token()
        assert self._token is not None  # guaranteed by _acquire_token raising on failure
        return self._token

    async def _acquire_token(self) -> None:
        """Acquire a new OAuth2 token via the Client Credentials flow.

        POST to scm_token_url with form-encoded grant_type and scope, using
        HTTP Basic auth with scm_client_id and scm_client_secret. Stores the
        token and computed expiry timestamp in instance attributes.

        Raises:
            SCMAuthError: On HTTP error, network error, or missing fields in the
                          token response. The message never contains credential
                          values (ADR-0006; threat model T3).
        """
        start = time.monotonic()
        try:
            response = await self._http.post(
                self._settings.scm_token_url,
                data={
                    "grant_type": "client_credentials",
                    "scope": f"tsg_id:{self._settings.scm_tsg_id}",
                },
                auth=(self._settings.scm_client_id, self._settings.scm_client_secret),
            )
            response.raise_for_status()
            payload = response.json()
            # Store token in memory — never write to disk or logs (ADR-0006)
            self._token = payload["access_token"]
            expires_in = int(payload.get("expires_in", 3600))
            self._token_expiry = time.monotonic() + expires_in
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "scm_token_acquired",
                outcome="success",
                expires_in=expires_in,
                duration_ms=duration_ms,
                # token value intentionally excluded from all log fields (ADR-0006)
            )
        except SCMAuthError:
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "scm_token_acquisition_failed",
                outcome="failure",
                duration_ms=duration_ms,
                # credential values intentionally excluded (ADR-0006)
            )
            raise SCMAuthError(
                "SCM token acquisition failed. Verify SCM_CLIENT_ID, "
                "SCM_CLIENT_SECRET, SCM_TSG_ID, and SCM_TOKEN_URL."
            ) from exc

    async def _get(
        self,
        tool_name: str,
        endpoint_path: str,
        folder: str | None = None,
        **params: Any,  # Any: SCM query params are mixed types (str | int | None)
    ) -> SCMResult:
        """Execute an authenticated GET request against the SCM API.

        Ensures a valid token before sending the request. On non-2xx responses,
        extracts _errors and _request_id from the body and raises SCMAPIError.

        Args:
            tool_name: MCP tool name, included in structured log entries per
                       ADR-0004 tool call logging contract.
            endpoint_path: SCM API path (e.g. '/config/network/v1/zones').
            folder: Folder scope query parameter. Required by all read endpoints;
                    may be None for endpoints where folder is not a query param
                    (e.g. job status lookups where the id is in the path).
            **params: Additional query parameters. None values are omitted from
                      the request so optional params don't pollute the query string.

        Returns:
            SCMResult containing the parsed JSON body, HTTP status, and the
            value of the X-Request-Id response header.

        Raises:
            SCMAuthError: If a valid token cannot be acquired.
            SCMAPIError: If the SCM API returns a non-2xx status, or on network
                         failure.
        """
        token = await self._ensure_token()
        url = f"{self._settings.scm_api_base_url}{endpoint_path}"
        # Any: httpx accepts str | int | float | bool for query params
        query_params: dict[str, Any] = {}
        if folder is not None:
            query_params["folder"] = folder
        for key, value in params.items():
            if value is not None:
                query_params[key] = value

        start = time.monotonic()
        try:
            response = await self._http.get(
                url,
                params=query_params,
                headers={"Authorization": f"Bearer {token}"},
            )
            http_status = response.status_code
            scm_request_id = response.headers.get("X-Request-Id")
            duration_ms = int((time.monotonic() - start) * 1000)

            if not response.is_success:
                # Any: SCM error body is untyped JSON from the external API
                error_body: dict[str, Any] = {}
                try:
                    error_body = response.json()
                except Exception:
                    pass
                error_codes = [
                    str(e.get("code", "")) for e in error_body.get("_errors", [])
                ]
                request_id = error_body.get("_request_id") or scm_request_id
                logger.error(
                    "scm_api_call",
                    tool_name=tool_name,
                    scm_endpoint=f"GET {endpoint_path}",
                    folder=folder,
                    outcome="failure",
                    http_status=http_status,
                    duration_ms=duration_ms,
                    scm_request_id=request_id,
                    error_codes=error_codes,
                )
                raise SCMAPIError(
                    message=f"SCM API returned HTTP {http_status}",
                    http_status=http_status,
                    request_id=request_id,
                    error_codes=error_codes,
                )

            logger.info(
                "scm_api_call",
                tool_name=tool_name,
                scm_endpoint=f"GET {endpoint_path}",
                folder=folder,
                outcome="success",
                http_status=http_status,
                duration_ms=duration_ms,
                scm_request_id=scm_request_id,
                error_codes=[],
            )
            return SCMResult(
                data=response.json(),
                http_status=http_status,
                scm_request_id=scm_request_id,
            )

        except (SCMAuthError, SCMAPIError):
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "scm_api_call",
                tool_name=tool_name,
                scm_endpoint=f"GET {endpoint_path}",
                folder=folder,
                outcome="failure",
                http_status=None,
                duration_ms=duration_ms,
                scm_request_id=None,
                error_codes=[],
            )
            raise SCMAPIError(
                message=f"SCM API request failed: {exc}",
                http_status=None,
                request_id=None,
                error_codes=[],
            ) from exc

    async def _post(
        self,
        tool_name: str,
        endpoint_path: str,
        json_body: dict[str, Any],  # Any: request body is untyped JSON for external API
        **query_params: Any,  # Any: SCM query params are mixed types (str | int | None)
    ) -> SCMResult:
        """Execute an authenticated POST request against the SCM API.

        Ensures a valid token before sending the request. On non-2xx responses,
        extracts _errors and _request_id from the body and raises SCMAPIError.

        Args:
            tool_name: MCP tool name, included in structured log entries per
                       ADR-0004 tool call logging contract.
            endpoint_path: SCM API path (e.g. '/config/security/v1/security-rules').
            json_body: Request body serialised as JSON. Must not contain credential
                       values.
            **query_params: Query parameters. None values are omitted from the
                            request so optional params don't pollute the query string.

        Returns:
            SCMResult containing the parsed JSON body, HTTP status, and the
            value of the X-Request-Id response header.

        Raises:
            SCMAuthError: If a valid token cannot be acquired.
            SCMAPIError: If the SCM API returns a non-2xx status, or on network
                         failure.
        """
        token = await self._ensure_token()
        url = f"{self._settings.scm_api_base_url}{endpoint_path}"
        # Any: httpx accepts str | int | float | bool for query params
        params: dict[str, Any] = {
            key: value for key, value in query_params.items() if value is not None
        }
        folder = query_params.get("folder")

        start = time.monotonic()
        try:
            response = await self._http.post(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                json=json_body,
            )
            http_status = response.status_code
            scm_request_id = response.headers.get("X-Request-Id")
            duration_ms = int((time.monotonic() - start) * 1000)

            if not response.is_success:
                # Any: SCM error body is untyped JSON from the external API
                error_body: dict[str, Any] = {}
                try:
                    error_body = response.json()
                except Exception:
                    pass
                error_codes = [
                    str(e.get("code", "")) for e in error_body.get("_errors", [])
                ]
                request_id = error_body.get("_request_id") or scm_request_id
                logger.error(
                    "scm_api_call",
                    tool_name=tool_name,
                    scm_endpoint=f"POST {endpoint_path}",
                    folder=folder,
                    outcome="failure",
                    http_status=http_status,
                    duration_ms=duration_ms,
                    scm_request_id=request_id,
                    error_codes=error_codes,
                )
                raise SCMAPIError(
                    message=f"SCM API returned HTTP {http_status}",
                    http_status=http_status,
                    request_id=request_id,
                    error_codes=error_codes,
                )

            logger.info(
                "scm_api_call",
                tool_name=tool_name,
                scm_endpoint=f"POST {endpoint_path}",
                folder=folder,
                outcome="success",
                http_status=http_status,
                duration_ms=duration_ms,
                scm_request_id=scm_request_id,
                error_codes=[],
            )
            return SCMResult(
                data=response.json(),
                http_status=http_status,
                scm_request_id=scm_request_id,
            )

        except (SCMAuthError, SCMAPIError):
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "scm_api_call",
                tool_name=tool_name,
                scm_endpoint=f"POST {endpoint_path}",
                folder=folder,
                outcome="failure",
                http_status=None,
                duration_ms=duration_ms,
                scm_request_id=None,
                error_codes=[],
            )
            raise SCMAPIError(
                message=f"SCM API request failed: {exc}",
                http_status=None,
                request_id=None,
                error_codes=[],
            ) from exc

    async def list_security_zones(
        self, folder: str, **params: Any  # Any: mixed SCM query param types
    ) -> SCMResult:
        """List security zones for a folder.

        Maps to: GET /config/network/v1/zones

        Args:
            folder: Folder scope (required).
            **params: Optional query parameters accepted by the endpoint:
                      name (str), limit (int), offset (int).

        Returns:
            SCMResult with paginated zone list matching the ADR-0004 schema.

        Raises:
            SCMAuthError: On token acquisition failure.
            SCMAPIError: On HTTP error or network failure.
        """
        return await self._get(
            "list_security_zones", "/config/network/v1/zones", folder, **params
        )

    async def list_security_rules(
        self, folder: str, **params: Any  # Any: mixed SCM query param types
    ) -> SCMResult:
        """List security rules for a folder.

        Maps to: GET /config/security/v1/security-rules

        Args:
            folder: Folder scope (required).
            **params: Optional query parameters: name (str), limit (int),
                      offset (int), position ('pre' | 'post').

        Returns:
            SCMResult with paginated security rule list matching ADR-0004 schema.

        Raises:
            SCMAuthError: On token acquisition failure.
            SCMAPIError: On HTTP error or network failure.
        """
        return await self._get(
            "list_security_rules",
            "/config/security/v1/security-rules",
            folder,
            **params,
        )

    async def list_addresses(
        self, folder: str, **params: Any  # Any: mixed SCM query param types
    ) -> SCMResult:
        """List address objects for a folder.

        Maps to: GET /config/objects/v1/addresses

        Args:
            folder: Folder scope (required).
            **params: Optional query parameters: name (str), limit (int),
                      offset (int).

        Returns:
            SCMResult with paginated address object list matching ADR-0004 schema.

        Raises:
            SCMAuthError: On token acquisition failure.
            SCMAPIError: On HTTP error or network failure.
        """
        return await self._get(
            "list_addresses", "/config/objects/v1/addresses", folder, **params
        )

    async def list_address_groups(
        self, folder: str, **params: Any  # Any: mixed SCM query param types
    ) -> SCMResult:
        """List address groups for a folder.

        Maps to: GET /config/objects/v1/address-groups

        Args:
            folder: Folder scope (required).
            **params: Optional query parameters: name (str), limit (int),
                      offset (int).

        Returns:
            SCMResult with paginated address group list matching ADR-0004 schema.

        Raises:
            SCMAuthError: On token acquisition failure.
            SCMAPIError: On HTTP error or network failure.
        """
        return await self._get(
            "list_address_groups", "/config/objects/v1/address-groups", folder, **params
        )

    async def create_security_rule(
        self,
        folder: str,
        rule_body: dict[str, Any],  # Any: rule fields are untyped JSON for external API
        position: str = "pre",
    ) -> SCMResult:
        """Create a security rule in SCM candidate configuration.

        Maps to: POST /config/security/v1/security-rules

        The caller is responsible for mapping Python parameter names to SCM API
        field names before passing rule_body (e.g. from_zones → 'from',
        to_zones → 'to').

        Args:
            folder: Folder scope query parameter (required, max 64 chars).
            rule_body: Request body dict with SCM field names. Must include all
                       required fields per the SCM API contract.
            position: Rule position query parameter, 'pre' or 'post'. Default 'pre'.

        Returns:
            SCMResult with the created rule object including server-assigned id.

        Raises:
            SCMAuthError: On token acquisition failure.
            SCMAPIError: On HTTP error or network failure.
        """
        return await self._post(
            "create_security_rule",
            "/config/security/v1/security-rules",
            json_body=rule_body,
            folder=folder,
            position=position,
        )

    async def create_address(
        self,
        folder: str,
        address_body: dict[str, Any],  # Any: request body is untyped JSON for external API
    ) -> SCMResult:
        """Create an address object in SCM candidate configuration.

        Maps to: POST /config/objects/v1/addresses

        Args:
            folder: Folder scope query parameter (required, max 64 chars).
            address_body: Request body dict with SCM field names. Must include
                          the required 'name' field.

        Returns:
            SCMResult with the created address object including server-assigned id.

        Raises:
            SCMAuthError: On token acquisition failure.
            SCMAPIError: On HTTP error or network failure.
        """
        return await self._post(
            "create_address",
            "/config/objects/v1/addresses",
            json_body=address_body,
            folder=folder,
        )

    async def create_address_group(
        self,
        folder: str,
        group_body: dict[str, Any],  # Any: request body is untyped JSON for external API
    ) -> SCMResult:
        """Create an address group in SCM candidate configuration.

        Maps to: POST /config/objects/v1/address-groups

        Args:
            folder: Folder scope query parameter (required, max 64 chars).
            group_body: Request body dict with SCM field names. Must include
                        the required 'name' and 'static' fields.

        Returns:
            SCMResult with the created address group including server-assigned id.

        Raises:
            SCMAuthError: On token acquisition failure.
            SCMAPIError: On HTTP error or network failure.
        """
        return await self._post(
            "create_address_group",
            "/config/objects/v1/address-groups",
            json_body=group_body,
            folder=folder,
        )

    async def push_candidate_config(
        self,
        folders: list[str],
        admin: list[str] | None = None,
        description: str | None = None,
    ) -> SCMResult:
        """Push candidate configuration to running configuration on devices.

        Maps to: POST /config/operations/v1/config-versions/candidate:push

        The 'admin' field is omitted from the request body when None. Per the
        official SCM docs, omitting admin is required when pushing the 'All' folder.

        Args:
            folders: List of folder names to push (mapped to 'folder' in body).
            admin: Optional list of admin or service account names. Omit when
                   pushing the 'All' folder.
            description: Optional description recorded on the resulting job.

        Returns:
            SCMResult with the job response from the SCM API. The 201 response
            schema is not documented; the full body is returned for inspection.

        Raises:
            SCMAuthError: On token acquisition failure.
            SCMAPIError: On HTTP error or network failure.
        """
        body: dict[str, Any] = {"folder": folders}
        if admin is not None:
            body["admin"] = admin
        if description is not None:
            body["description"] = description
        return await self._post(
            "push_candidate_config",
            "/config/operations/v1/config-versions/candidate:push",
            json_body=body,
        )

    async def get_job_status(self, job_id: str) -> SCMResult:
        """Retrieve the status of an SCM job by its ID.

        Maps to: GET /config/operations/v1/jobs/{id}

        Args:
            job_id: The SCM job identifier to query (path parameter).

        Returns:
            SCMResult with {"data": [<Job object>]} matching the ADR-0004 schema.

        Raises:
            SCMAuthError: On token acquisition failure.
            SCMAPIError: On HTTP error or network failure. E005 (object not
                         present) is raised as SCMAPIError on 404.
        """
        return await self._get(
            "get_job_status",
            f"/config/operations/v1/jobs/{job_id}",
        )


@lru_cache(maxsize=1)
def get_scm_client() -> SCMClient:
    """Return the shared SCMClient singleton.

    The client holds OAuth2 token state and the httpx.AsyncClient connection
    pool. Using a singleton avoids unnecessary token acquisitions and enables
    connection reuse across tool calls.

    Returns:
        The shared SCMClient instance, constructed on first call.
    """
    return SCMClient(get_settings())
