# ADR-0004: mcp-strata-cloud-manager Tool Interface Design

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0004                                                              |
| Title         | mcp-strata-cloud-manager Tool Interface Design                        |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-19                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

ADR-0002 establishes that all external system integrations are implemented
as MCP servers. `mcp-strata-cloud-manager` encapsulates the Palo Alto
Networks Strata Cloud Manager (SCM) API — the firewall management platform
FirePilot targets. This ADR defines the tool interface: which SCM API
operations are exposed as MCP tools, and what their exact input/output
contracts are.

### SCM API — Established Facts

All information in this section is sourced directly from the official
Palo Alto Networks SCM API documentation. Field names, types, constraints,
and semantics are taken verbatim from the official spec.

**Base URL**: `https://api.strata.paloaltonetworks.com`

**Authentication**: OAuth2 Client Credentials flow. The server handles
token acquisition and refresh internally — credentials never enter
Claude's context. Authentication design is covered in ADR-0006.

**Scoping**: FirePilot operates exclusively in `folder` scope. Every
configuration API call requires `folder` as a query parameter. The `snippet`
and `device` scope variants are not used.

**Configuration Lifecycle**: SCM uses a candidate/running model. All
write operations modify the *candidate configuration* — changes are not
live on devices until a push job completes.

```
Write operations  →  candidate configuration  (not live)
                              │
    POST /config/operations/v1/config-versions/candidate:push
                              │
                     async job created (type_str: CommitAndPush)
                              │
          GET /config/operations/v1/jobs/:id  (poll until FIN)
                              │
                    running configuration  (live on devices)
```

Push jobs are tracked via `status_str` values `ACT`, `FIN`, `PEND`,
`PUSHSENT`, `PUSHFAIL`, `PUSHABORT`, `PUSHTIMEOUT` and `result_str`
values `OK`, `FAIL`, `PEND`, `WAIT`, `CANCELLED`, `TIMEOUT`.

**FirePilot's required SCM operations** (scope of this ADR):

| Operation            | Endpoint                                                      |
|----------------------|---------------------------------------------------------------|
| List security rules  | `GET /config/security/v1/security-rules`                      |
| List security zones  | `GET /config/network/v1/zones`                                |
| List addresses       | `GET /config/objects/v1/addresses`                            |
| List address groups  | `GET /config/objects/v1/address-groups`                       |
| Create security rule | `POST /config/security/v1/security-rules`                     |
| Push candidate config| `POST /config/operations/v1/config-versions/candidate:push`   |
| Get job status       | `GET /config/operations/v1/jobs/:id`                          |

In scope: tool definitions, input/output contracts, server operating
modes, and tool call logging.

Out of scope: OAuth2 token lifecycle (ADR-0006), YAML configuration
schema (ADR-0007), rule update and deletion (not required for v1).

---

## Decision

We will implement `mcp-strata-cloud-manager` with seven tools mapped
directly to the SCM API operations required by FirePilot's v1 workflow.
All write and operations tools enforce a `ticket_id` parameter
server-side before any SCM API interaction. The server operates in
`live` or `demo` mode controlled by `FIREPILOT_ENV`.

---

## Considered Alternatives

#### Option A: Thin passthrough — expose the full SCM API surface as tools

- **Description**: Generate MCP tool definitions from the complete SCM
  API surface
- **Pros**: Maximum flexibility; no upfront tool design
- **Cons**: Exposes device management, certificate operations, network
  configuration, and other capabilities outside FirePilot's scope;
  violates least-privilege; tool surface becomes unauditable

#### Option B: Workflow-level tools — one tool per FirePilot use case

- **Description**: Coarse tools such as `process_firewall_request` where
  Claude passes an intent description and the tool handles all SCM
  interactions internally
- **Pros**: Minimal surface
- **Cons**: Removes Claude's ability to inspect intermediate state;
  embeds orchestration logic in the server rather than in Claude where
  it belongs; each SCM call becomes invisible in the audit trail

#### Option C: Operation-level tools aligned to SCM API *(chosen)*

- **Description**: One MCP tool per required SCM API operation, with
  input/output schemas derived directly from the official API documentation
- **Pros**: Each tool maps traceably to a known SCM endpoint; Claude
  retains full orchestration responsibility; surface is minimal and
  auditable; each tool is independently mockable and testable
- **Cons**: Adding new SCM capabilities requires explicit server changes
  and a new or amended ADR

---

## Tool Interface Specification

### Server Modes

Controlled by `FIREPILOT_ENV`:

| Value  | Behaviour                                                             |
|--------|-----------------------------------------------------------------------|
| `demo` | All tools return realistic fixture responses. No SCM API calls made. |
| `live` | All tools execute against the configured SCM API endpoint.           |

The server logs the active mode on startup. Fixture responses in `demo`
mode must be structurally identical to live API responses so that
Claude's orchestration logic is exercised faithfully in both modes.

---

### Read Tools

#### `list_security_rules`

Maps to: `GET /config/security/v1/security-rules`

```
Input:
  folder:    str                  required
  position:  "pre" | "post"       required, default "pre"
  name:      str                  optional — filter by name
  limit:     int                  optional, default 200
  offset:    int                  optional, default 0

Output:
  data:      list[SecurityRule]
  limit:     int
  offset:    int
  total:     int

SecurityRule:
  id:                  str (UUID)
  name:                str
  folder:              str
  policy_type:         str              default "Security"
  disabled:            bool             default false
  description:         str | null
  tag:                 list[str]
  from:                list[str]        source zone(s)
  to:                  list[str]        destination zone(s)
  source:              list[str]        source address(es)
  negate_source:       bool             default false
  source_user:         list[str]
  destination:         list[str]
  service:             list[str]
  schedule:            str | null
  action:              "allow" | "deny" | "drop" | "reset-both"
                       | "reset-client" | "reset-server"
  negate_destination:  bool             default false
  source_hip:          list[str]
  destination_hip:     list[str]
  application:         list[str]
  category:            list[str]
  profile_setting:
    group:             list[str]
  log_setting:         str | null
  log_start:           bool
  log_end:             bool
  tenant_restrictions: list[str]
```

Claude uses this tool to detect conflicting or redundant rules before
proposing a new rule.

---

#### `list_security_zones`

Maps to: `GET /config/network/v1/zones`

```
Input:
  folder:    str    required
  name:      str    optional — filter by name
  limit:     int    optional, default 200
  offset:    int    optional, default 0

Output:
  data:      list[SecurityZone]
  limit:     int
  offset:    int
  total:     int

SecurityZone:
  id:                          str (UUID)
  name:                        str
  folder:                      str
  enable_user_identification:  bool
  enable_device_identification: bool
  dos_profile:                 str | null
  dos_log_setting:             str | null
  network:                     list[str]
  zone_protection_profile:     str | null
  enable_packet_buffer_protection: bool
  log_setting:                 str | null
  user_acl:
    include_list:              list[str]
    exclude_list:              list[str]
  device_acl:
    include_list:              list[str]
    exclude_list:              list[str]
```

Claude uses this tool to validate that source and destination zones
referenced in a requested rule actually exist before generating the
rule configuration.

---

#### `list_addresses`

Maps to: `GET /config/objects/v1/addresses`

```
Input:
  folder:    str    required
  name:      str    optional — filter by name
  limit:     int    optional, default 200
  offset:    int    optional, default 0

Output:
  data:      list[AddressObject]
  limit:     int
  offset:    int
  total:     int

AddressObject:
  id:           str (UUID)
  name:         str
  description:  str | null
  tag:          list[str]
  # exactly one of:
  ip_netmask:   str | null    e.g. "192.168.80.0/24"
  ip_range:     str | null    e.g. "10.0.0.1-10.0.0.10"
  ip_wildcard:  str | null
  fqdn:         str | null    e.g. "app.example.com"
```

Claude uses this tool to check whether address objects already exist
before referencing `any` or a raw IP in a new rule, avoiding
unnecessary object proliferation.

---

#### `list_address_groups`

Maps to: `GET /config/objects/v1/address-groups`

```
Input:
  folder:    str    required
  name:      str    optional — filter by name
  limit:     int    optional, default 200
  offset:    int    optional, default 0

Output:
  data:      list[AddressGroup]
  limit:     int
  offset:    int
  total:     int

AddressGroup:
  id:           str (UUID)
  name:         str             max 63 chars, pattern ^[ a-zA-Z\d._-]+$
  description:  str | null
  tag:          list[str]
  # one of:
  static:       list[str]       member address object names
  dynamic:      object | null   dynamic filter expression
```

Claude checks address groups alongside individual address objects to
prefer existing named groupings over raw addresses in new rules.

---

### Write Tools

All write and operations tools enforce `ticket_id` server-side.
A call without a non-empty `ticket_id` is rejected immediately with
error code `MISSING_TICKET_REF` — no SCM API interaction occurs.

#### `create_security_rule`

Maps to: `POST /config/security/v1/security-rules`

```
Input:
  ticket_id:           str               required (server-enforced)
  folder:              str               required, max 64 chars
  position:            "pre" | "post"    required, default "pre"
  name:                str               required
  action:              str               required
                                         "allow"|"deny"|"drop"|
                                         "reset-both"|"reset-client"|
                                         "reset-server"
  from:                list[str]         required — source zone(s)
  to:                  list[str]         required — destination zone(s)
  source:              list[str]         required — source address(es)
  source_user:         list[str]         required — use ["any"] if unscoped
  destination:         list[str]         required — destination address(es)
  service:             list[str]         required — service(s)
  application:         list[str]         required — application(s)
  category:            list[str]         required — use ["any"] if unscoped
  description:         str               optional
  disabled:            bool              optional, default false
  tag:                 list[str]         optional
  negate_source:       bool              optional, default false
  negate_destination:  bool              optional, default false
  source_hip:          list[str]         optional
  destination_hip:     list[str]         optional
  schedule:            str               optional
  profile_setting:
    group:             list[str]         optional
  log_setting:         str               optional
  log_start:           bool              optional
  log_end:             bool              optional
  tenant_restrictions: list[str]         optional

Output (HTTP 201):
  id:           str (UUID)    SCM-assigned rule identifier
  name:         str
  folder:       str
  # all fields as submitted, echoed in response
```

Writes to candidate configuration only. Not live on devices until
`push_candidate_config` is called and its job reaches `result_str: OK`.

---

### Operations Tools

#### `push_candidate_config`

Maps to: `POST /config/operations/v1/config-versions/candidate:push`

Initiates a `CommitAndPush` job that promotes the current candidate
configuration to the running configuration on target devices.
**This is the only tool that causes live changes on devices.**

```
Input:
  ticket_id:    str          required (server-enforced)
  folders:      list[str]    required, each max 64 chars
                             pattern ^[a-zA-Z\d-_\. ]+$
  admin:        list[str]    optional — list of admins/service accounts
                             omit when pushing the "All" folder
  description:  str          optional — recorded on the resulting job

Output:
  # HTTP 201, no body returned by the API.
  # Server immediately polls GET /config/operations/v1/jobs/:id
  # and returns the first observed job status.
  job_id:       str
  status_str:   "ACT" | "FIN" | "PEND" | "PUSHSENT"
                | "PUSHFAIL" | "PUSHABORT" | "PUSHTIMEOUT"
  result_str:   "OK" | "FAIL" | "PEND" | "WAIT"
                | "CANCELLED" | "TIMEOUT"
  percent:      str
  summary:      str
  details:      str          JSON string, present on failure
```

The server polls `GET /config/operations/v1/jobs/:id` until `status_str`
reaches a terminal state (`FIN`, `PUSHFAIL`, `PUSHABORT`, `PUSHTIMEOUT`)
or a configurable timeout (`SCM_PUSH_TIMEOUT_SECONDS`, default 300).

This tool must be called explicitly as a separate step after ITSM
approval is confirmed. No other tool triggers a push.

---

#### `get_job_status`

Maps to: `GET /config/operations/v1/jobs/:id`

Exposed as a tool to allow Claude to check push job status independently
of the blocking poll in `push_candidate_config`. Useful for long-running
jobs or async approval workflows.

```
Input:
  job_id:    str    required

Output:
  data:      list[Job]    (API returns a list; typically one item for :id lookup)

Job:
  id:           str
  device_name:  str
  type_str:     "CommitAll" | "CommitAndPush" | "NGFW-Bootstrap-Push"
                | "Validate"
  status_str:   "ACT" | "FIN" | "PEND" | "PUSHSENT" | "PUSHFAIL"
                | "PUSHABORT" | "PUSHTIMEOUT"
  result_str:   "OK" | "FAIL" | "PEND" | "WAIT" | "CANCELLED" | "TIMEOUT"
  percent:      str
  summary:      str
  description:  str | null
  details:      str | null   JSON string with error details on failure
  uname:        str          email of the service account that created the job
  start_ts:     str
  end_ts:       str
  parent_id:    str
  job_result:   str
  job_status:   str
  job_type:     str
```

---

### Tool Call Logging

Every tool invocation produces a structured log entry written before
the tool returns:

```
timestamp:       ISO 8601
tool_name:       str
mode:            "live" | "demo"
scm_endpoint:    str           e.g. "POST /config/security/v1/security-rules"
folder:          str | null
outcome:         "success" | "failure" | "rejected"
http_status:     int | null    null on rejection before API call
duration_ms:     int
ticket_id:       str | null
rejection_code:  str | null    e.g. "MISSING_TICKET_REF"
scm_request_id:  str | null    value of _request_id from error responses
error_codes:     list[str]     SCM error codes, e.g. ["E006", "E016"]
```

Request bodies are excluded from logs to prevent configuration detail
leakage. The `ticket_id` + `scm_endpoint` + `timestamp` triple provides
sufficient traceability for audit purposes. On SCM API errors, the
`_request_id` from the response is logged to support Palo Alto support
escalation.

---

## Rationale

The tool set is derived directly from FirePilot's v1 workflow requirements
and bounded strictly to those requirements. The mapping is one tool per
SCM API operation — no aggregation, no abstraction above the API level.

Claude's orchestration logic determines the call sequence. A typical
rule creation flow is:

```
list_security_zones        → validate requested zones exist
list_addresses             → check for reusable address objects
list_address_groups        → check for reusable address groups
list_security_rules        → detect conflicts in candidate rulebase
create_security_rule       → write rule to candidate config
push_candidate_config      → promote candidate to running (post-approval)
get_job_status             → verify push outcome
```

The push step is decoupled from rule creation by design. In FirePilot's
workflow, push is triggered after ITSM approval is confirmed — not
immediately after rule creation. This preserves a human gate between
candidate configuration and live production impact.

`get_job_status` is exposed as a standalone tool rather than hidden
inside `push_candidate_config` because async approval workflows may
require Claude to check job status minutes or hours after the push was
initiated, in a separate conversation turn.

The `ticket_id` enforcement on `create_security_rule` and
`push_candidate_config` is structural — the server rejects calls before
any SCM interaction occurs. This cannot be bypassed by prompt
construction.

---

## Consequences

- **Positive**: Every tool contract maps traceably to an official SCM
  API endpoint with field names taken verbatim from the official
  documentation — no invented schemas
- **Positive**: The candidate/push separation is explicit and enforced
  at the tool interface level; there is no ambiguity about when
  configuration becomes live
- **Positive**: `demo` mode provides per-tool fixture responses,
  enabling full end-to-end workflow testing without SCM credentials
  or live infrastructure
- **Positive**: SCM error codes (`E003`, `E005`, `E006`, `E007`,
  `E009`, `E012`, `E013`, `E016`) and `_request_id` are surfaced in
  logs, making failures diagnosable without access to SCM internals
- **Negative**: Rule creation requires four read tool calls before
  writing — zone validation, address lookup, address group lookup,
  and conflict check. This is intentional but adds latency to the
  workflow
- **Negative**: No rule update or deletion in v1; these require a
  superseding ADR when the use case is defined
- **Follow-up required**: Fixture response files for all tools under
  `demo/fixtures/mcp-strata-cloud-manager/`, covering both success
  and representative error responses per tool
- **Follow-up required**: ADR-0006 must specify OAuth2 credential
  injection and token refresh strategy for this server

---

## Compliance & Security Considerations

- **Least Privilege**: The SCM service account requires read access
  on security rules (`/config/security/v1/security-rules`), zones
  (`/config/network/v1/zones`), addresses and address groups
  (`/config/objects/v1/addresses`, `/config/objects/v1/address-groups`);
  write access on security rules; and push permission on the Operations
  API. No device management, network configuration, or user
  administration permissions are required or should be granted
- **No Implicit Activation**: Only `push_candidate_config` promotes
  changes to running configuration. `create_security_rule` has no
  live impact until push is explicitly called with a valid `ticket_id`
- **Audit Trail**: Tool call logs keyed by `ticket_id` +
  `scm_endpoint` + `scm_request_id` provide an independent audit
  record supplementing the Git commit trail and ITSM tickets
- **SOC 2 CC6.1**: All write and operations actions are mediated
  through a single audited integration point with mandatory ITSM
  change reference enforced at the server layer

---

## Review Trigger

- If rule update, rule deletion, or rule move/reorder are added to
  FirePilot's scope, extend the tool set via a superseding ADR
- If the SCM API introduces breaking changes to any mapped endpoint
  (field renames, removed fields, changed enumerations), update the
  tool contracts in the same PR as the implementation fix and
  flag for ADR supersession if the change is significant
- If the push/job polling model is replaced by a synchronous
  mechanism in a future SCM API version, reassess
  `push_candidate_config` and `get_job_status` semantics

---

## Amendment: Address Object and Address Group Write Tools (2026-03-21)

| Field     | Value                                                                |
|-----------|----------------------------------------------------------------------|
| Amended   | Write Tools section                                                  |
| Reason    | Claude must be able to create address objects and address groups dynamically when processing firewall change requests. Without write tools for addresses, Claude is forced to either use raw IPs in rules (anti-pattern in SCM — creates duplication and complicates IP changes) or abort when a required address object does not exist. |
| Related   | ADR-0009 Amendment (document-driven requests extract multiple rules with distinct addresses), ADR-0012 (operator configuration) |

---

### Problem Statement

The original tool surface assumes that all address objects and address
groups referenced in security rules already exist in SCM. Claude can
look them up (`list_addresses`, `list_address_groups`) but cannot
create them.

This assumption breaks in the document-driven request mode (ADR-0009
Amendment): a PigeonTrack deployment manual specifies seven firewall
rules referencing six distinct IP addresses and subnets. None of these
exist as SCM address objects until FirePilot processes the request.

The correct workflow is:

1. Claude extracts required addresses from the request
2. Claude calls `list_addresses` to check which already exist
3. For missing addresses, Claude calls `create_address`
4. Claude references the (existing or newly created) address object
   names in the security rule

This is the same lookup-then-create pattern used for security rules
and is consistent with SCM's candidate configuration model — newly
created address objects are part of the candidate config and only
become live after the push.

### New Write Tools

All new write tools enforce `ticket_id` server-side, consistent with
the existing `create_security_rule` pattern. A call without a
non-empty `ticket_id` is rejected immediately with error code
`MISSING_TICKET_REF`.

#### `create_address`

Maps to: `POST /config/objects/v1/addresses`
```
Input:
  ticket_id:     str               required (server-enforced)
  folder:        str               required, max 64 chars
  name:          str               required, max 63 chars
  description:   str               optional, max 1023 chars
  tag:           list[str]         optional, max 64 entries
  # exactly one of the following address types:
  ip_netmask:    str               IP with optional CIDR, e.g. "192.168.80.0/24"
  ip_range:      str               IP range, e.g. "10.0.0.1-10.0.0.10"
  ip_wildcard:   str               IP wildcard mask
  fqdn:          str               Fully qualified domain name

Output (HTTP 201):
  id:            str (UUID)        SCM-assigned address object identifier
  name:          str
  folder:        str
  description:   str | null
  tag:           list[str]
  # the address type field that was submitted, echoed in response
  ip_netmask:    str | null
  ip_range:      str | null
  ip_wildcard:   str | null
  fqdn:          str | null
```

Exactly one address type field must be provided. The SCM API rejects
requests with zero or multiple address type fields.

Error codes follow the same pattern as `create_security_rule`:

| HTTP | Code | Meaning                                         |
|------|------|-------------------------------------------------|
| 400  | E003 | Input format mismatch, missing body, invalid object |
| 401  | E016 | Authentication failure                           |
| 403  | E007 | Authorization failure                            |
| 409  | E006 | Name Not Unique — address with this name already exists |
| 409  | E016 | Object Not Unique                                |

Claude's expected behaviour on E006 (Name Not Unique): treat as
success — the address already exists. Call `list_addresses` with the
name to retrieve the existing object and use it. This is the same
idempotency pattern used for `create_security_rule` in retry
scenarios.

Writes to candidate configuration only. The address object is
available for reference in security rules immediately within the same
candidate config session, before a push.

#### `create_address_group`

Maps to: `POST /config/objects/v1/address-groups`
```
Input:
  ticket_id:     str               required (server-enforced)
  folder:        str               required, max 64 chars
  name:          str               required, max 63 chars
                                   pattern: ^[ a-zA-Z\d._-]+$
  description:   str               optional, max 1023 chars
  tag:           list[str]         optional, max 64 entries
  # exactly one of:
  static:        list[str]         member address object names, each max 63 chars
  dynamic:       object            dynamic filter expression

Output (HTTP 201):
  id:            str (UUID)        SCM-assigned address group identifier
  name:          str
  folder:        str
  description:   str | null
  tag:           list[str]
  static:        list[str] | null
  dynamic:       object | null
```

Static groups reference existing address objects by name. All
referenced address objects must exist in the candidate config before
the group is created — Claude must create individual address objects
first, then group them.

Error codes are identical to `create_address`.

Claude's expected behaviour on E006 (Name Not Unique): same as
`create_address` — treat as success, retrieve existing group.

### Updated Tool Inventory

The complete `mcp-strata-cloud-manager` tool surface after this
amendment:

| Tool                      | Type       | Ticket required | Purpose                                    |
|---------------------------|------------|:---------------:|--------------------------------------------|
| `list_security_rules`     | Read       | —               | Read current rules                         |
| `list_security_zones`     | Read       | —               | Validate zone references                   |
| `list_addresses`          | Read       | —               | Check existing address objects             |
| `list_address_groups`     | Read       | —               | Check existing address groups              |
| `create_address`          | Write      | ✓               | Create address object in candidate config  |
| `create_address_group`    | Write      | ✓               | Create address group in candidate config   |
| `create_security_rule`    | Write      | ✓               | Create security rule in candidate config   |
| `push_candidate_config`   | Operations | ✓               | Push candidate to running config           |
| `get_job_status`          | Operations | —               | Poll push job status                       |

### Claude Workflow Integration

The system prompt workflow (Phase 1, Step 3) is extended:

**Step 3 (amended): Check and create address objects.**

1. Call `list_addresses(folder=...)` and `list_address_groups(folder=...)`
2. For each address referenced in the request:
   - If a matching address object exists: note the object name for
     use in the rule
   - If no match: call `create_address` with the appropriate address
     type, a descriptive name, and the `firepilot-managed` tag
3. If the request references multiple addresses that logically form
   a group (e.g., a database cluster with primary and replica):
   create individual address objects first, then call
   `create_address_group` with the member names

Address object names follow the convention
`{application}-{function}-{address}`, e.g.,
`pigeontrack-db-primary-10.10.5.10`,
`pigeontrack-dmz-server-10.20.0.50`. This convention is guidance
for Claude, not an MCP-enforced constraint.

### Demo Mode Behaviour

In demo mode (`FIREPILOT_ENV=demo`), `create_address` and
`create_address_group` return fixture responses that mirror the
201 response schema. The created objects are added to the in-memory
fixture store so that subsequent `list_addresses` /
`list_address_groups` calls within the same session return them.
This ensures that the lookup-then-create-then-reference workflow is
fully exercisable in demo mode.

### Consequences of this Amendment

- **Positive**: Claude can handle requests that reference addresses
  not yet in SCM — the full address lifecycle is within the tool
  surface
- **Positive**: The PigeonTrack demo scenario works end-to-end
  without pre-seeding address fixtures
- **Positive**: Address objects get the `firepilot-managed` tag,
  making them visible to drift detection (ADR-0011)
- **Positive**: The E006 idempotency pattern makes retries safe —
  re-processing an issue does not fail on already-created addresses
- **Negative**: Two new write tools expand the attack surface (T5
  in the threat model) — a prompt injection could attempt to create
  misleading address objects. Mitigation: address objects in
  candidate config are not live until push; the PR review gate
  catches unexpected object creation; OPA could be extended to
  validate address objects in a future iteration
- **Negative**: Address object naming is convention-based, not
  enforced — Claude may produce inconsistent names across requests.
  Mitigation: acceptable for v1; a naming policy can be added to
  OPA later
- **Follow-up required**: Implement `create_address` tool in
  `mcp-strata-cloud-manager` (write module + demo fixtures + live
  client method)
- **Follow-up required**: Implement `create_address_group` tool
  (same scope)
- **Follow-up required**: Update SCMClient with
  `create_address` and `create_address_group` methods
- **Follow-up required**: Update system prompt Step 3
- **Follow-up required**: Update `docs/architecture.md` tool
  inventory table
- **Follow-up required**: Update threat model T5 to reflect
  expanded tool surface
