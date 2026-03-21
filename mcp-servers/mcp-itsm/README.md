# mcp-itsm

MCP server providing change management and audit trail functionality for FirePilot. The tool interface is intentionally backend-agnostic — field names reflect ITSM concepts (`change_request_id`, `status`, `event`) rather than implementation-specific terminology, so the contract survives a backend swap to ServiceNow or Jira without interface changes. The v1 implementation maps all operations to the GitHub Issues REST API.

---

## Prerequisites

- Python 3.12+
- `uv` (recommended) or `pip`

---

## Setup

```bash
cd mcp-servers/mcp-itsm

# Copy environment configuration
cp .env.example .env

# Install dependencies (with dev extras for testing)
pip install -e ".[dev]"
# or with uv:
uv pip install -e ".[dev]"
```

---

## Running in Demo Mode

Demo mode requires no GitHub credentials. All tools return realistic in-memory fixture responses.

```bash
FIREPILOT_ENV=demo python -m mcp_itsm.server
```

The server starts with one pre-seeded change request (`change_request_id: "42"`, status: `pending`) to support demo queries without requiring a create step.

---

## Tool Reference

| Tool | Description | GitHub Endpoint |
|------|-------------|-----------------|
| `create_change_request` | Create a new change request with status `pending` | `POST /repos/{owner}/{repo}/issues` |
| `get_change_request` | Retrieve current state; used by Claude to poll for approval | `GET /repos/{owner}/{repo}/issues/{issue_number}` |
| `add_audit_comment` | Append a structured lifecycle event comment | `POST /repos/{owner}/{repo}/issues/{issue_number}/comments` |
| `update_change_request_status` | Set terminal status (`deployed` or `failed`) and close the issue | `POST …/labels` + `PATCH …/issues/{issue_number}` |
| `write_config_file` | Write a YAML configuration file to OUTPUT_DIR for Git commit | Local filesystem (no GitHub API call) |

### `create_change_request`

**Input**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | `str` | ✓ | Short summary of the change |
| `description` | `str` | ✓ | Full description — intent, affected zones, expected impact |
| `config_reference` | `str` | ✓ | Git commit SHA or PR URL |
| `requestor` | `str` | ✓ | Requesting business unit or user identity |

**Output**: `change_request_id`, `url`, `status` (`"pending"`), `created_at`

The returned `change_request_id` is the `ticket_id` value to pass to all write operation tools in `mcp-strata-cloud-manager`.

---

### `get_change_request`

**Input**: `change_request_id` (str, required)

**Output**: Full change request state including `status`, `labels`, `body`, `closed_at`.

Status is derived from the `firepilot:*` label on the issue. If no `firepilot:*` label is present, status defaults to `"pending"`.

---

### `add_audit_comment`

**Input**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `change_request_id` | `str` | ✓ | Target change request |
| `event` | `str` | ✓ | One of the allowed event types (see below) |
| `detail` | `str` | ✓ | Human-readable event detail |
| `scm_reference` | `str` | — | SCM job ID or rule UUID; displayed as `—` if omitted |

**Allowed event values**: `rule_validated`, `candidate_written`, `push_initiated`, `push_succeeded`, `push_failed`, `request_rejected`

**Output**: `comment_id`, `url`, `created_at`

---

### `update_change_request_status`

**Input**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `change_request_id` | `str` | ✓ | Target change request |
| `status` | `str` | ✓ | Must be `"deployed"` or `"failed"` |
| `close_issue` | `bool` | — | Close the issue on update (default: `true`) |

Only `"deployed"` and `"failed"` are accepted. FirePilot never programmatically sets `"approved"` or `"rejected"` — those transitions belong to human reviewers via the GitHub UI.

**Output**: `change_request_id`, `status`, `url`, `closed`

---

### `write_config_file`

**Purpose**: Write a YAML configuration file (security rule, address object, or rulebase manifest) to the output directory for Git commit by the workflow. Claude calls this tool once per configuration artefact during its agentic loop. The workflow script then scans `OUTPUT_DIR` for `.yaml` files to determine whether a valid proposal was produced (ADR-0015).

Both demo and live modes write to the local filesystem at `OUTPUT_DIR`. There is no fixture-based mock — the tool always performs real file I/O. The `OUTPUT_DIR` environment variable must be set before the server starts.

**Input**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `filename` | `str` | ✓ | File name including `.yaml` extension. For `security_rule`, must match the `name` field in the content. For `rulebase_manifest`, use `_rulebase.yaml`. |
| `content` | `str` | ✓ | Complete YAML content of the file, ADR-0007-compliant. Written verbatim — not re-serialised. |
| `file_type` | `str` | ✓ | One of: `security_rule`, `address_object`, `rulebase_manifest`. |

**Validation** (performed before writing, in this order):

| # | Rule |
|---|------|
| 1 | `filename` must end with `.yaml` |
| 2 | `filename` must not contain path separators (`/`, `\`) or `..` |
| 3 | `content` must be valid YAML (`yaml.safe_load()` succeeds) |
| 4 | For `security_rule`: content must contain `schema_version`, `name`, and `action` |
| 5 | For `rulebase_manifest`: content must contain `schema_version`, `folder`, `position`, and `rule_order` |
| 6 | For `security_rule` and non-`_rulebase.yaml` manifests: the `name` field must match the filename stem |

**Error codes**

| Code | Condition |
|------|-----------|
| `INVALID_FILENAME` | Rule 1 or 2 violated |
| `INVALID_YAML` | Rule 3 violated — content is not valid YAML |
| `SCHEMA_MISMATCH` | Rule 4 or 5 violated — required fields missing for the given `file_type` |
| `NAME_FILENAME_MISMATCH` | Rule 6 violated — `name` field does not match filename stem |
| `WRITE_FAILED` | OS-level write error (permissions, disk full, etc.) |
| `OUTPUT_DIR_NOT_SET` | `OUTPUT_DIR` environment variable is not configured |

**Output** (on success)

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | `str` | Absolute path of the written file |
| `file_type` | `str` | Echo of the input `file_type` |
| `file_size` | `int` | File size in bytes |

**Demo and live mode**: Both modes write to `OUTPUT_DIR`. In the GitHub Actions workflow, `OUTPUT_DIR` is set to `${{ runner.temp }}/firepilot-extracted` (a temporary directory on the runner). In demo mode for local testing, set `OUTPUT_DIR` to any writable directory.

---

## Label Convention

| Label | Status Value | Meaning |
|-------|-------------|---------|
| `firepilot:pending` | `"pending"` | Awaiting processing |
| `firepilot:rejected` | `"rejected"` | Rejected by Claude — no PR created |
| `firepilot:deployed` | `"deployed"` | Push completed successfully |
| `firepilot:failed` | `"failed"` | Push attempted but failed |

Labels must be pre-created in the target GitHub repository before operating in live mode.

---

## Running in Live Mode

Live mode makes real GitHub Issues REST API calls against a target repository.

### Token sources

**GitHub Actions (recommended):** The workflow generates a short-lived
installation token from the GitHub App credentials (`APP_ID` +
`APP_PRIVATE_KEY` repository secrets). This token is injected as
`ITSM_GITHUB_TOKEN` and expires after one hour. All actions appear
under the App's bot identity (e.g. `firepilot-bot[bot]`), providing
clean separation between human and automated actions in the audit
trail.

**Local development:** A fine-grained PAT with `issues:write` scope
works for local testing. Actions will appear under the PAT owner's
identity.

### Required environment variables

| Variable | Description |
|----------|-------------|
| `FIREPILOT_ENV` | Must be set to `live` |
| `ITSM_GITHUB_TOKEN` | Short-lived GitHub App installation token (CI) or fine-grained PAT with `issues:write` scope (local dev) — see Token sources above |
| `ITSM_GITHUB_REPO` | Target repository in `owner/repo` format |

Optional:

| Variable | Default | Description |
|----------|---------|-------------|
| `ITSM_APPROVAL_TIMEOUT_SECONDS` | `3600` | Maximum time Claude waits for a human approval label |
| `ITSM_POLL_INTERVAL_SECONDS` | `60` | Interval between get_change_request polling calls |

### GitHub repository prerequisites

Before running in live mode, the following labels must be pre-created in the target GitHub repository:

| Label | Meaning |
|-------|---------|
| `firepilot:pending` | Awaiting human review |
| `firepilot:approved` | Approved by human reviewer |
| `firepilot:rejected` | Rejected by human reviewer |
| `firepilot:deployed` | Deployment completed successfully |
| `firepilot:failed` | Deployment attempted but failed |

### Starting the server

```bash
cd mcp-servers/mcp-itsm
FIREPILOT_ENV=live \
  ITSM_GITHUB_TOKEN=ghp_your-token-here \
  ITSM_GITHUB_REPO=your-org/your-repo \
  python -m mcp_itsm.server
```

Alternatively, copy `.env.example` to `.env`, fill in the values, and run:

```bash
python -m mcp_itsm.server
```

### What each tool does in live mode

| Tool | GitHub API call |
|------|-----------------|
| `create_change_request` | `POST /repos/{owner}/{repo}/issues` — creates issue with `firepilot:pending` label |
| `get_change_request` | `GET /repos/{owner}/{repo}/issues/{number}` — derives status from `firepilot:*` label |
| `add_audit_comment` | `POST /repos/{owner}/{repo}/issues/{number}/comments` — appends structured Markdown event |
| `update_change_request_status` | `PUT …/labels` (replace labels) + optionally `PATCH …/issues/{number}` (close issue) |

The token is stored in process memory only — it is never written to disk, logged, or returned in tool responses (ADR-0006).

---

## Running Tests

```bash
cd mcp-servers/mcp-itsm
pytest
```

All tests run against demo mode and require no GitHub credentials. The fixture store is reset to a clean state before each test.

Live tool tests (in `tests/test_live_tools.py`) use a mocked GitHubClient and also require no credentials:

```bash
FIREPILOT_ENV=demo pytest tests/test_live_tools.py
```

GitHub client unit tests (in `tests/test_github_client.py`) use `respx` to mock HTTP transport:

```bash
pytest tests/test_github_client.py
```
