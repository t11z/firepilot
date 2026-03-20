# mcp-strata-cloud-manager

An MCP server that exposes Palo Alto Networks Strata Cloud Manager (SCM) API
operations as tools for the FirePilot AI-driven firewall change workflow. The
server provides seven tools covering security rule management, zone and address
lookups, and configuration push operations — all following the candidate/running
configuration lifecycle required by SCM. A `demo` mode (default) returns
realistic fixture responses without requiring live credentials, enabling full
end-to-end workflow testing at any time.

---

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip`

---

## Setup

```bash
cd mcp-servers/mcp-strata-cloud-manager

# Copy environment template
cp .env.example .env
# Edit .env if needed (demo mode works with defaults)

# Install with uv
uv pip install -e ".[dev]"

# Or with pip
pip install -e ".[dev]"
```

---

## Running in Demo Mode

```bash
FIREPILOT_ENV=demo python -m mcp_strata_cloud_manager.server
```

The server communicates over stdio using the MCP protocol. Connect it to any
MCP-compatible client (e.g. Claude Desktop, `mcp` CLI) to invoke tools.

---

## Tool Reference

| Tool | SCM Endpoint | Description |
|---|---|---|
| `list_security_rules` | `GET /config/security/v1/security-rules` | List security rules in a folder (pre or post position) |
| `list_security_zones` | `GET /config/network/v1/zones` | List security zones in a folder |
| `list_addresses` | `GET /config/objects/v1/addresses` | List address objects in a folder |
| `list_address_groups` | `GET /config/objects/v1/address-groups` | List address groups in a folder |
| `create_security_rule` | `POST /config/security/v1/security-rules` | Create a security rule in candidate config (requires ticket_id) |
| `push_candidate_config` | `POST /config/operations/v1/config-versions/candidate:push` | Push candidate config to running config on devices (requires ticket_id) |
| `get_job_status` | `GET /config/operations/v1/jobs/:id` | Poll the status of a push job |

All read tools accept `folder` (required), optional `name` filter, and
`limit`/`offset` for pagination. Write and operations tools require a non-empty
`ticket_id` (ITSM change reference) enforced server-side.

---

## Live Mode

Set `FIREPILOT_ENV=live` and provide the SCM OAuth2 credentials to run against
the real Palo Alto Networks Strata Cloud Manager API.

```bash
cp .env.example .env
# Edit .env — fill in SCM_CLIENT_ID, SCM_CLIENT_SECRET, SCM_TSG_ID
FIREPILOT_ENV=live python -m mcp_strata_cloud_manager.server
```

### What works in live mode

| Tool | Live mode |
|---|---|
| `list_security_zones` | Real SCM API call |
| `list_security_rules` | Real SCM API call |
| `list_addresses` | Real SCM API call |
| `list_address_groups` | Real SCM API call |
| `create_security_rule` | Real SCM API call |
| `push_candidate_config` | Real SCM API call |
| `get_job_status` | Real SCM API call |

> **Note on push_candidate_config**: The official SCM API does not document the
> 201 response schema for the push endpoint. The tool returns whatever the API
> provides. If the response format differs from the expected job object structure,
> the tool output should be inspected during integration testing.

### Required environment variables (live mode)

See `.env.example` for the full list. All three SCM credential variables are
required; the endpoint URLs default to the Palo Alto production endpoints.

| Variable | Description |
|---|---|
| `SCM_CLIENT_ID` | OAuth2 client ID for the SCM service account |
| `SCM_CLIENT_SECRET` | OAuth2 client secret |
| `SCM_TSG_ID` | Tenant Service Group identifier |
| `SCM_API_BASE_URL` | SCM API base URL (default: `https://api.strata.paloaltonetworks.com`) |
| `SCM_TOKEN_URL` | OAuth2 token endpoint (default: `https://auth.apps.paloaltonetworks.com/oauth2/access_token`) |

The token is acquired lazily on the first tool call and proactively refreshed
when it expires within 60 seconds. The token value is never logged, written
to disk, or returned in any tool response.

---

## Running Tests

```bash
pytest
```

All tests run against demo mode fixtures. No live credentials or network access
are required.

```bash
# With verbose output
pytest -v

# Run a specific test file
pytest tests/test_read_tools.py
```
