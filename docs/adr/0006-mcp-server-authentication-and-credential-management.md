# ADR-0006: MCP Server Authentication and Credential Management

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0006                                                              |
| Title         | MCP Server Authentication and Credential Management                   |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-19                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

FirePilot operates two MCP servers that each require credentials to
interact with external systems:

- `mcp-strata-cloud-manager`: requires OAuth2 Client Credentials
  (client ID, client secret, TSG ID) to authenticate against the
  Palo Alto Networks SCM API
- `mcp-itsm`: requires a GitHub Personal Access Token (PAT) to
  authenticate against the GitHub Issues API

ADR-0002 establishes that credentials must never enter Claude's context
window. This ADR defines how credentials are stored, injected into the
servers at runtime, and rotated — across both local Docker/Compose
deployment and GitHub Actions CI.

Two additional authentication concerns are in scope:

1. **MCP server → Claude trust**: how Claude knows it is talking to a
   legitimate MCP server and not a malicious tool endpoint
2. **Token lifecycle for SCM**: the SCM OAuth2 access token is
   short-lived and must be refreshed automatically without surfacing
   credentials to Claude

Out of scope: network-level TLS termination, GitHub repository access
control, and SCM service account role assignment (referenced in ADR-0004).

---

## Decision

Credentials are injected into MCP servers exclusively via environment
variables. In local development and demo, environment variables are
sourced from a `.env` file that is never committed to the repository.
In GitHub Actions CI, environment variables are sourced from repository
secrets. The SCM OAuth2 token is acquired and refreshed internally by
`mcp-strata-cloud-manager` with no external coordination. The GitHub
PAT used by `mcp-itsm` is a fine-grained token scoped to `issues:
write` on the target repository only.

---

## Considered Alternatives

#### Option A: Credentials hardcoded in source or configuration files

- **Description**: API keys and secrets stored directly in code,
  `docker-compose.yml`, or YAML config files
- **Pros**: Zero setup friction
- **Cons**: Credentials committed to a public repository are
  immediately compromised; disqualified without further consideration

#### Option B: External secrets manager (HashiCorp Vault, AWS Secrets Manager)

- **Description**: Credentials stored in a dedicated secrets management
  system; servers fetch secrets at startup via the secrets manager API
- **Pros**: Centralised rotation; audit log on secret access; suitable
  for production enterprise deployment
- **Cons**: Requires a running secrets manager instance — incompatible
  with the zero-always-on-infrastructure constraint; adds significant
  operational complexity for a demo system; over-engineered for v1

#### Option C: Environment variables with `.env` locally and repository secrets in CI *(chosen)*

- **Description**: Credentials are injected as environment variables.
  Locally, a `.env` file (gitignored) is loaded by Docker Compose.
  In GitHub Actions, repository secrets are mapped to environment
  variables in the workflow definition
- **Pros**: No additional infrastructure; standard pattern for
  containerised applications; `.env.example` documents required
  variables without exposing values; GitHub Actions secrets are
  encrypted at rest and masked in logs; compatible with both demo
  and portfolio validation use cases
- **Cons**: `.env` files can be accidentally committed if `.gitignore`
  is misconfigured; no automatic rotation — rotation requires manual
  secret update; not suitable for production multi-tenant deployment

---

## Credential Inventory

### `mcp-strata-cloud-manager`

| Variable                  | Description                                      | Required |
|---------------------------|--------------------------------------------------|----------|
| `SCM_CLIENT_ID`           | OAuth2 client ID for the SCM service account     | live     |
| `SCM_CLIENT_SECRET`       | OAuth2 client secret                             | live     |
| `SCM_TSG_ID`              | Tenant Service Group identifier                  | live     |
| `SCM_API_BASE_URL`        | SCM API base URL (default: `https://api.strata.paloaltonetworks.com`) | live |
| `SCM_TOKEN_URL`           | OAuth2 token endpoint (default: `https://auth.apps.paloaltonetworks.com/oauth2/access_token`) | live |
| `SCM_PUSH_TIMEOUT_SECONDS`| Push job poll timeout (default: `300`)           | optional |
| `FIREPILOT_ENV`           | `live` or `demo`                                 | always   |

### `mcp-itsm`

| Variable                     | Description                                   | Required |
|------------------------------|-----------------------------------------------|----------|
| `ITSM_GITHUB_TOKEN`          | GitHub PAT with `issues: write` scope         | live     |
| `ITSM_GITHUB_REPO`           | Target repository in `owner/repo` format      | live     |
| `ITSM_APPROVAL_TIMEOUT_SECONDS` | Approval poll timeout (default: `3600`)    | optional |
| `ITSM_POLL_INTERVAL_SECONDS` | Approval poll interval (default: `60`)        | optional |
| `FIREPILOT_ENV`              | `live` or `demo`                              | always   |

No credentials are required in `demo` mode beyond `FIREPILOT_ENV=demo`.

---

## Local Development — `.env` File

Each MCP server directory contains an `.env.example` file committed
to the repository. The actual `.env` file is created by the operator
by copying `.env.example` and filling in real values.

```
mcp-servers/
├── mcp-strata-cloud-manager/
│   ├── .env.example     ← committed, placeholder values
│   └── .env             ← gitignored, real values
└── mcp-itsm/
    ├── .env.example     ← committed, placeholder values
    └── .env             ← gitignored, real values
```

`.env.example` format for `mcp-strata-cloud-manager`:

```dotenv
# FirePilot environment: "live" or "demo"
FIREPILOT_ENV=demo

# SCM OAuth2 credentials (required for FIREPILOT_ENV=live)
SCM_CLIENT_ID=your-client-id-here
SCM_CLIENT_SECRET=your-client-secret-here
SCM_TSG_ID=your-tsg-id-here

# SCM API endpoints (defaults shown, override only if needed)
# SCM_API_BASE_URL=https://api.strata.paloaltonetworks.com
# SCM_TOKEN_URL=https://auth.apps.paloaltonetworks.com/oauth2/access_token

# Push job timeout in seconds
# SCM_PUSH_TIMEOUT_SECONDS=300
```

`.env.example` format for `mcp-itsm`:

```dotenv
# FirePilot environment: "live" or "demo"
FIREPILOT_ENV=demo

# GitHub credentials (required for FIREPILOT_ENV=live)
ITSM_GITHUB_TOKEN=ghp_your-token-here
ITSM_GITHUB_REPO=your-org/your-repo

# Approval polling configuration (defaults shown)
# ITSM_APPROVAL_TIMEOUT_SECONDS=3600
# ITSM_POLL_INTERVAL_SECONDS=60
```

Docker Compose loads the `.env` file automatically when it is present
in the same directory as the `docker-compose.yml`. No explicit
`--env-file` flag is required.

`.gitignore` must include:

```
mcp-servers/**/.env
.env
```

A pre-commit hook must verify that no file matching `*.env` (excluding
`*.env.example`) is staged for commit. This is enforced via the
pre-commit configuration defined in `.pre-commit-config.yaml`.

---

## GitHub Actions CI

Repository secrets are defined at the repository level under
`Settings → Secrets and variables → Actions`. Each secret maps to
one environment variable.

Required repository secrets:

| Secret name               | Maps to environment variable  |
|---------------------------|-------------------------------|
| `SCM_CLIENT_ID`           | `SCM_CLIENT_ID`               |
| `SCM_CLIENT_SECRET`       | `SCM_CLIENT_SECRET`           |
| `SCM_TSG_ID`              | `SCM_TSG_ID`                  |
| `ITSM_GITHUB_TOKEN`       | `ITSM_GITHUB_TOKEN`           |
| `ITSM_GITHUB_REPO`        | `ITSM_GITHUB_REPO`            |

Workflow injection pattern:

```yaml
jobs:
  integration-test:
    runs-on: ubuntu-latest
    env:
      FIREPILOT_ENV: live
      SCM_CLIENT_ID: ${{ secrets.SCM_CLIENT_ID }}
      SCM_CLIENT_SECRET: ${{ secrets.SCM_CLIENT_SECRET }}
      SCM_TSG_ID: ${{ secrets.SCM_TSG_ID }}
      ITSM_GITHUB_TOKEN: ${{ secrets.ITSM_GITHUB_TOKEN }}
      ITSM_GITHUB_REPO: ${{ secrets.ITSM_GITHUB_REPO }}
```

GitHub Actions automatically masks secret values in workflow logs.
Secrets must not be echoed, printed, or written to workflow output
by any step.

---

## SCM OAuth2 Token Lifecycle

The SCM API issues short-lived JWT access tokens. `mcp-strata-cloud-manager`
manages the token lifecycle internally:

1. On first tool call requiring `live` mode, the server acquires a
   token via the OAuth2 Client Credentials flow using `SCM_CLIENT_ID`,
   `SCM_CLIENT_SECRET`, and `SCM_TSG_ID`
2. The token and its expiry timestamp are stored in process memory
   only — never written to disk or logs
3. Before each subsequent SCM API call, the server checks whether the
   token expires within the next 60 seconds. If so, it proactively
   acquires a new token before proceeding
4. If token acquisition fails, the tool call returns a structured
   error with code `SCM_AUTH_FAILURE` — the error does not expose
   credential values

The token is never passed to Claude, never written to the tool call
log, and never included in fixture responses.

---

## GitHub PAT Scope

The GitHub PAT used by `mcp-itsm` must be a fine-grained personal
access token with the following permissions on the target repository
only:

| Permission    | Access level |
|---------------|--------------|
| Issues        | Read and write |
| Metadata      | Read-only (required by GitHub for all fine-grained tokens) |

No other permissions should be granted. The PAT must not have access
to repository contents (`contents`), which would allow reading or
modifying firewall configuration files — that access belongs to the
CI/CD pipeline service account, not to `mcp-itsm`.

---

## Rationale

Environment variable injection via `.env` and GitHub Actions secrets
is the established standard for containerised applications at this
scale. It requires no additional infrastructure, is well understood by
any engineer reviewing the repository, and integrates transparently
with Docker Compose and GitHub Actions without custom tooling.

The alternative — a secrets manager — is the correct choice for
production multi-tenant deployment, but it introduces a hard
infrastructure dependency that contradicts FirePilot's zero-always-on
constraint. The Review Trigger documents when this decision must be
revisited.

Proactive token refresh (60-second buffer) is preferable to reactive
refresh (retry on 401) because it eliminates the possibility of a
failed tool call mid-workflow due to token expiry. A failed `push_candidate_config`
call that has already initiated a job but failed to receive the response
would leave the system in an ambiguous state. The proactive approach
prevents this class of failure.

---

## Consequences

- **Positive**: Zero additional infrastructure required for local demo
  or CI execution
- **Positive**: `.env.example` files serve as self-documenting
  credential requirements — any reviewer can understand what is
  needed without reading code
- **Positive**: GitHub Actions secret masking prevents accidental
  credential exposure in workflow logs
- **Positive**: SCM token lifecycle is fully encapsulated in
  `mcp-strata-cloud-manager` — no external coordination required
- **Negative**: `.env` files are a credential leak risk if
  `.gitignore` or pre-commit hooks are misconfigured; this risk
  is mitigated but not eliminated
- **Negative**: No automatic credential rotation — if `SCM_CLIENT_SECRET`
  or `ITSM_GITHUB_TOKEN` is compromised, rotation requires manual
  update in both the local `.env` file and GitHub repository secrets
- **Negative**: PAT-based authentication for `mcp-itsm` is tied to
  a personal account; a GitHub App token would be preferable for
  production use (see Review Trigger)
- **Follow-up required**: Pre-commit hook configuration to prevent
  `.env` file commits must be defined in `.pre-commit-config.yaml`
- **Follow-up required**: Operator setup documentation must list
  the exact steps for creating the SCM service account, generating
  the PAT, and configuring repository secrets

---

## Compliance & Security Considerations

- **Credential Isolation**: `SCM_CLIENT_SECRET` and `ITSM_GITHUB_TOKEN`
  are accessible only within the respective MCP server process. They
  are never passed to Claude, never written to logs, and never
  included in MCP tool responses
- **Least Privilege — SCM**: The SCM service account must be scoped
  as defined in ADR-0004. `SCM_CLIENT_SECRET` grants only the
  permissions of that service account — it does not grant broader
  SCM tenant access
- **Least Privilege — GitHub**: The PAT is scoped to `issues: write`
  on a single repository. It cannot read or modify firewall
  configuration files
- **Secret Scanning**: GitHub's built-in secret scanning must be
  enabled on the repository to detect accidental credential commits.
  This is a repository settings requirement, not a code requirement
- **Audit**: Token acquisition events are logged by the SCM server
  at INFO level (timestamp, outcome, token expiry — no credential
  values). This provides an audit record of authentication activity
  separate from tool call logs

---

## Review Trigger

- If FirePilot is deployed in a production environment, replace
  `.env` / GitHub secrets with a dedicated secrets manager
  (HashiCorp Vault, AWS Secrets Manager, or equivalent) via a
  superseding ADR
- If `mcp-itsm` is used in a team or organisational context, replace
  the PAT with a GitHub App installation token to decouple
  authentication from a personal account
- If the SCM service account secret is rotated, both the local `.env`
  file and the `SCM_CLIENT_SECRET` repository secret must be updated
  simultaneously — document this as an operational runbook step
- If any credential is suspected to be compromised, revoke it
  immediately via the respective platform console, then update all
  injection points; do not rely solely on rotation cadence
