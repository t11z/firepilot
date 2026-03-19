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
