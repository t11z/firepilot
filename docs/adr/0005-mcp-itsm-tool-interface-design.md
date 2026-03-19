# ADR-0005: mcp-itsm Tool Interface Design

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0005                                                              |
| Title         | mcp-itsm Tool Interface Design                                        |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-19                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

ADR-0002 establishes that all external system integrations are implemented
as MCP servers. `mcp-itsm` provides FirePilot's change management and
audit trail integration. It is responsible for creating change requests,
tracking approval status, appending audit comments, and closing completed
requests.

### ITSM Backend — v1 Implementation: GitHub Issues

For v1, `mcp-itsm` is implemented against the GitHub Issues REST API.
This decision is deliberate: GitHub Issues co-locates the change
management audit trail with the firewall configuration repository,
making the entire change lifecycle — request, approval, configuration
diff, deployment — inspectable in a single place without external
system access. This directly supports FirePilot's portfolio goal of
external reviewability.

The server name `mcp-itsm` is intentionally generic. The tool interface
defined in this ADR is backend-agnostic. If FirePilot is later deployed
against ServiceNow or Jira, the tool interface remains unchanged and
only the server implementation is replaced.

### GitHub Issues API — Relevant Endpoints

**Base URL**: `https://api.github.com`

**Authentication**: Personal Access Token (PAT) or GitHub App token
via `Authorization: Bearer <token>` header. Credential handling is
covered in ADR-0006.

**Relevant endpoints**:

| Operation            | Endpoint                                                              |
|----------------------|-----------------------------------------------------------------------|
| Create issue         | `POST /repos/{owner}/{repo}/issues`                                   |
| Get issue            | `GET  /repos/{owner}/{repo}/issues/{issue_number}`                    |
| Update issue         | `PATCH /repos/{owner}/{repo}/issues/{issue_number}`                   |
| Add comment          | `POST /repos/{owner}/{repo}/issues/{issue_number}/comments`           |
| Add labels           | `POST /repos/{owner}/{repo}/issues/{issue_number}/labels`             |

**Approval model**: GitHub Issues has no native approval workflow.
FirePilot implements approval via label convention:

| Label              | Meaning                                          |
|--------------------|--------------------------------------------------|
| `firepilot:pending`    | Change request created, awaiting review      |
| `firepilot:approved`   | Approved — push may proceed                  |
| `firepilot:rejected`   | Rejected — push must not proceed             |
| `firepilot:deployed`   | Push completed successfully                  |
| `firepilot:failed`     | Push attempted but failed                    |

These labels must be pre-created in the target repository before
FirePilot is operated. Label creation is an operator setup step,
not an automated FirePilot action.

**Polling**: Claude polls `get_change_request` until the issue carries
`firepilot:approved` or `firepilot:rejected`, or until a configurable
timeout is reached (`ITSM_APPROVAL_TIMEOUT_SECONDS`, default 3600).
Poll interval is `ITSM_POLL_INTERVAL_SECONDS`, default 60.

In scope: tool definitions, input/output contracts, approval model,
polling behaviour, and tool call logging.

Out of scope: GitHub App vs PAT credential selection (ADR-0006),
label pre-creation (operator setup), repository access control.

---

## Decision

We will implement `mcp-itsm` with five tools mapped to GitHub Issues
API operations. The tool interface is defined as backend-agnostic — field
names reflect ITSM concepts, not GitHub-specific terminology. The v1
implementation maps these to GitHub Issues. Approval is tracked via
label convention.

---

## Considered Alternatives

#### Option A: Native ITSM platforms — ServiceNow or Jira

- **Description**: Implement `mcp-itsm` against an enterprise ITSM
  platform with native change management workflows, approval gates,
  and audit capabilities
- **Pros**: Purpose-built for change management; native approval
  workflows; standard in enterprise environments
- **Cons**: Requires a running ServiceNow or Jira instance with
  appropriate licensing; introduces an external dependency that
  prevents local demo execution; adds credential complexity; not
  accessible to external portfolio reviewers without accounts

#### Option B: GitHub Issues *(chosen for v1)*

- **Description**: Use GitHub Issues as the change request system,
  with approval tracked via label convention
- **Pros**: Zero additional infrastructure; co-located with the
  configuration repository; full audit trail visible to any GitHub
  user with repo access; supports the portfolio goal of external
  reviewability; PAT-based auth is trivial to configure; demo mode
  requires no live account
- **Cons**: No native approval workflow — label convention is a
  custom implementation; not suitable for production enterprise
  environments without replacement; approval model is not
  cryptographically verified

#### Option C: Custom approval microservice

- **Description**: Build a lightweight approval service specifically
  for FirePilot
- **Pros**: Full control over approval semantics
- **Cons**: Additional service to operate and maintain; adds
  infrastructure complexity; does not contribute to the portfolio
  narrative

---

## Tool Interface Specification

### Server Modes

Controlled by `FIREPILOT_ENV`:

| Value  | Behaviour                                                             |
|--------|-----------------------------------------------------------------------|
| `demo` | All tools return realistic fixture responses. No GitHub API calls.   |
| `live` | All tools execute against the configured GitHub repository.          |

The target repository is configured via `ITSM_GITHUB_REPO`
(`owner/repo` format) and `ITSM_GITHUB_TOKEN`. Both are required in
`live` mode. The server logs the active mode and target repository
(without token) on startup.

---

### Tools

#### `create_change_request`

Maps to: `POST /repos/{owner}/{repo}/issues`

Creates a new change request issue representing a proposed firewall
rule change. Sets the `firepilot:pending` label on creation.

```
Input:
  title:            str    required — short summary of the change
  description:      str    required — full change description including
                           intent, affected zones, and expected impact
  config_reference: str    required — Git commit SHA or PR URL of the
                           associated firewall configuration change
  requestor:        str    required — identity of the requesting
                           business unit or user

Output:
  change_request_id:  str    GitHub issue number (as string, used as
                             ticket_id in ADR-0004 tools)
  url:                str    HTML URL of the created issue
  status:             str    "pending"
  created_at:         str    ISO 8601 timestamp
```

The `change_request_id` returned here is the `ticket_id` value that
must be passed to all write and operations tools in
`mcp-strata-cloud-manager`.

---

#### `get_change_request`

Maps to: `GET /repos/{owner}/{repo}/issues/{issue_number}`

Retrieves the current state of a change request. Claude calls this
tool repeatedly to poll for approval.

```
Input:
  change_request_id:  str    required — GitHub issue number

Output:
  change_request_id:  str
  title:              str
  url:                str
  status:             "pending" | "approved" | "rejected"
                      | "deployed" | "failed"
  labels:             list[str]    all labels on the issue
  created_at:         str
  updated_at:         str
  closed_at:          str | null
  body:               str
```

`status` is derived from the `firepilot:*` label present on the issue.
If multiple `firepilot:*` labels are present, the most recent one
(by label application order) takes precedence. If no `firepilot:*`
label is present, `status` is `"pending"`.

Claude polls this tool until `status` is `"approved"` or `"rejected"`,
or until `ITSM_APPROVAL_TIMEOUT_SECONDS` is exceeded.

---

#### `add_audit_comment`

Maps to: `POST /repos/{owner}/{repo}/issues/{issue_number}/comments`

Appends a structured audit comment to an existing change request.
Used to record key events in the change lifecycle: rule validation
result, candidate config write, push initiation, push outcome.

```
Input:
  change_request_id:  str    required
  event:              str    required — one of:
                             "rule_validated" | "candidate_written"
                             | "push_initiated" | "push_succeeded"
                             | "push_failed" | "request_rejected"
  detail:             str    required — human-readable event detail
  scm_reference:      str    optional — SCM job ID or rule UUID

Output:
  comment_id:   str
  url:          str
  created_at:   str
```

Comments are formatted as structured Markdown by the server:

```markdown
**FirePilot Event**: `{event}`
**Time**: {timestamp}
**Detail**: {detail}
**SCM Reference**: {scm_reference | "—"}
```

---

#### `update_change_request_status`

Maps to:
- `POST /repos/{owner}/{repo}/issues/{issue_number}/labels`  (add label)
- `PATCH /repos/{owner}/{repo}/issues/{issue_number}`        (close if terminal)

Updates the status label of a change request and optionally closes
the issue when the change lifecycle is complete.

```
Input:
  change_request_id:  str      required
  status:             str      required — "deployed" | "failed"
  close_issue:        bool     optional, default true for terminal states

Output:
  change_request_id:  str
  status:             str
  url:                str
  closed:             bool
```

This tool removes the previous `firepilot:*` label and adds the new
one. On `"deployed"` or `"failed"`, the issue is closed by default
(`state: "closed"` via PATCH).

Only `"deployed"` and `"failed"` are valid inputs — intermediate status
transitions (`"pending"` → `"approved"`) are performed by human
reviewers via the GitHub UI, not by FirePilot.

---

### Polling Contract

Claude's approval polling loop uses `get_change_request` as follows:

```
interval:  ITSM_POLL_INTERVAL_SECONDS   (default 60s)
timeout:   ITSM_APPROVAL_TIMEOUT_SECONDS (default 3600s)

loop:
  status = get_change_request(change_request_id).status
  if status == "approved":  proceed to push
  if status == "rejected":  call add_audit_comment(event="request_rejected")
                            halt workflow
  if elapsed > timeout:     call add_audit_comment(event with timeout detail)
                            halt workflow
  wait interval
```

The poll loop runs within Claude's orchestration — it is not a
background process in the server. Claude is responsible for managing
the polling cadence and timeout logic using the tool call outputs.

---

### Tool Call Logging

Every tool invocation produces a structured log entry written before
the tool returns:

```
timestamp:        ISO 8601
tool_name:        str
mode:             "live" | "demo"
github_endpoint:  str         e.g. "POST /repos/org/repo/issues"
outcome:          "success" | "failure" | "rejected"
http_status:      int | null
duration_ms:      int
change_request_id: str | null
rejection_code:   str | null
error_message:    str | null
```

---

## Rationale

**GitHub Issues over enterprise ITSM for v1.** The decision is driven
by the portfolio constraint: zero always-on infrastructure. A
ServiceNow instance costs money and requires access credentials that
external reviewers cannot obtain. The entire FirePilot change audit
trail is visible to anyone with GitHub repository access — which is
the target audience for portfolio validation.

**Tool interface is backend-agnostic by design.** Field names like
`change_request_id`, `status`, and `event` are ITSM concepts, not
GitHub concepts. The label-to-status mapping is an implementation
detail of the v1 server, not part of the interface contract. A future
`mcp-itsm` implementation targeting ServiceNow replaces only the
server internals.

**Approval via label convention, not native workflow.** GitHub Issues
has no approval gate. The label convention is a deliberate constraint
of the v1 scope. It is sufficient to demonstrate the approval-gated
deployment pattern. The review trigger documents when this must be
replaced.

**Only `"deployed"` and `"failed"` are writable status values.**
FirePilot never programmatically sets `"approved"` or `"rejected"` —
those transitions belong to human reviewers. This separation of
concerns is enforced at the tool interface level.

---

## Consequences

- **Positive**: Zero external infrastructure dependency; entire change
  trail is co-located with the configuration repository and visible
  to external reviewers
- **Positive**: The `change_request_id` ↔ `ticket_id` linkage creates
  a verifiable chain from every SCM write operation back to an
  approved change request in GitHub
- **Positive**: `demo` mode requires no GitHub credentials or live
  repository, enabling full workflow demonstration locally
- **Negative**: Label-based approval is not suitable for regulated
  production environments; a real enterprise deployment requires
  replacement with a proper ITSM backend (see Review Trigger)
- **Negative**: Polling is Claude's responsibility — long approval
  wait times consume context window and may require workflow
  resumption logic in long-running scenarios
- **Negative**: The label convention requires operator setup before
  first use; undocumented labels will cause `status` to return
  `"pending"` indefinitely
- **Follow-up required**: Fixture response files for all tools under
  `demo/fixtures/mcp-itsm/`
- **Follow-up required**: Operator setup documentation for required
  GitHub labels and repository permissions
- **Follow-up required**: ADR-0006 must specify GitHub token type
  (PAT vs GitHub App) and credential injection

---

## Compliance & Security Considerations

- **Audit Trail Integrity**: GitHub Issues comments are append-only
  under normal operation. The `add_audit_comment` tool creates an
  immutable record of each lifecycle event. Issue edit history is
  preserved by GitHub for owned repositories
- **Separation of Duties**: FirePilot sets `"deployed"` and `"failed"`
  status only. Approval is a human action performed outside the
  automated system — FirePilot cannot self-approve a change request
- **Token Scope**: The GitHub token used by `mcp-itsm` must be scoped
  to `issues: write` on the target repository only. No repository
  write (`contents: write`) permission is required or should be
  granted to this server
- **SOC 2 CC6.1**: The change request lifecycle — creation, approval,
  deployment result — is documented in a tamper-evident audit trail
  linked to every SCM operation via `ticket_id`
- **GDPR**: The `requestor` field stored in issue bodies may contain
  personal identifiers (names, email addresses). Repository access
  control and retention policies must be applied accordingly

---

## Review Trigger

- If FirePilot is deployed in a production enterprise environment,
  replace the GitHub Issues backend with a proper ITSM platform
  (ServiceNow, Jira Service Management) via a superseding ADR;
  the tool interface defined here remains valid
- If GitHub introduces a native approval or review workflow for
  Issues, evaluate whether the label convention can be replaced
- If the polling approach causes context window problems in
  long-running approval scenarios, consider a webhook-based
  notification mechanism as an alternative to active polling
- If the `requestor` field scope expands to include additional PII,
  re-evaluate GDPR implications and consider pseudonymisation
