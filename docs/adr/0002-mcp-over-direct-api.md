# ADR-0002: Use MCP Servers as the Integration Layer over Direct API Calls

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0002                                                              |
| Title         | Use MCP Servers as the Integration Layer over Direct API Calls        |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-19                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

FirePilot requires Claude to interact with two external systems:

1. **Palo Alto Networks Strata Cloud Manager (SCM)** — firewall rule management API
2. **ITSM platform (ServiceNow / Jira / ...)** — change request creation and audit trail

Claude must be able to read current firewall state, validate proposed
configurations, commit changes to Git, and create tickets — all within a
single orchestration flow driven by natural language input.

There are two principal approaches to connecting Claude to these external
systems: granting Claude direct HTTP access to each API, or exposing
system capabilities through MCP (Model Context Protocol) servers that
Claude calls as structured tools.

This decision has downstream consequences for security boundary design,
testability, mock-ability, and the long-term replaceability of individual
integrations.

In scope: the integration pattern between Claude and all external systems,
including both current integrations (SCM, ITSM) and future ones.

Out of scope: the internal implementation of individual MCP servers, the
specific tools each server exposes, and authentication mechanisms
(addressed in separate ADRs).

---

## Decision

We will implement all external system integrations as dedicated MCP servers.
Claude interacts exclusively with MCP tool calls — it never holds credentials
or constructs raw HTTP requests against external APIs directly.

---

## Considered Alternatives

#### Option A: Direct API Access — Claude constructs and executes HTTP requests

- **Description**: Claude is given API credentials and documentation, and
  constructs HTTP requests against SCM and ITSM APIs directly within its
  reasoning loop
- **Pros**: No additional abstraction layer; faster to prototype; Claude has
  full API surface available without pre-defining tools
- **Cons**: Credentials must be in Claude's context — expanding the blast
  radius of a prompt injection or context leak; no enforced boundary on
  what API operations Claude can invoke; impossible to mock without
  intercepting HTTP at the network level; tightly couples Claude's behavior
  to vendor API shapes, making platform migration expensive; no
  operator-controlled constraint layer between Claude and production systems

#### Option B: Thin Wrapper Functions — Claude calls Python/TS functions via code execution

- **Description**: A set of helper functions wraps each API call; Claude
  generates and executes code that invokes these functions
- **Pros**: More flexible than pre-defined tools; Claude can compose
  operations dynamically
- **Cons**: Code execution in production introduces a larger and harder-to-audit
  attack surface; function boundaries are soft and bypassable by Claude
  generating arbitrary code; still requires credentials in the execution
  environment with no structural constraint on which operations can be called;
  harder to mock and test in isolation

#### Option C: MCP Servers *(chosen)*

- **Description**: Each external system is encapsulated in a dedicated MCP
  server exposing a fixed, explicitly defined set of tools. Claude calls
  tools by name with structured inputs; the MCP server owns all credentials,
  HTTP logic, and response normalization
- **Pros**: Credentials never enter Claude's context; tool surface is
  operator-controlled and auditable; each server is independently mockable,
  testable, and replaceable; MCP is a structured protocol with defined
  input/output contracts; constraint enforcement (rate limiting, operation
  allowlisting) lives in the server, not in the prompt
- **Cons**: Requires upfront tool design — Claude can only do what the tools
  expose; adding new capabilities requires server changes and redeployment;
  MCP protocol adds a layer of indirection that must be understood by
  maintainers

---

## Rationale

Option A is disqualified on security grounds. Credentials in Claude's context
window are credentials at risk — from prompt injection, from context logging,
from model output. For a system that modifies network security policy, this
is not an acceptable trust model regardless of how the rest of the system
is designed.

Option B solves the credential problem partially but introduces code execution
as an attack surface. The absence of hard tool boundaries means Claude can
compose operations that no individual function was designed to permit. In a
security-critical domain, implicit composition is a risk, not a feature.

Option C makes the constraint layer structural rather than instructional.
The set of things Claude can do is defined by the tools the MCP server
exposes — not by what the system prompt tells Claude not to do. This is the
correct model for defense in depth: policy is enforced at the integration
boundary, not solely in the reasoning layer.

The additional design cost of pre-defining tools is also a forcing function:
it requires explicit decisions about what operations the system should be
capable of, documented in code rather than implied by API coverage.

---

## Consequences

- **Positive**: Credentials are isolated in MCP servers — Claude's context
  never contains secrets
- **Positive**: The tool surface is the de-facto allowlist of operations
  Claude can perform against external systems; expanding capabilities
  requires a deliberate code change, not a prompt adjustment
- **Positive**: Each MCP server can be independently mocked, enabling full
  demo and test execution without live infrastructure (see Mock-First
  Principle in CLAUDE.md)
- **Positive**: MCP servers are replaceable units — migrating from ServiceNow
  to Jira requires a new `mcp-itsm` implementation with the same tool
  interface, with no changes to Claude's orchestration logic
- **Positive**: Tool call logs provide a structured, server-side audit trail
  of every operation Claude performed against external systems
- **Negative**: Claude's capabilities are bounded by tool design; ad-hoc
  or exploratory API interactions require server changes
- **Negative**: Two MCP servers must be maintained as first-class components;
  they are not glue code
- **Follow-up required**: ADR for `mcp-strata` tool interface design
  (tool names, input schemas, error contracts)
- **Follow-up required**: ADR for `mcp-itsm` tool interface design
- **Follow-up required**: ADR for MCP server authentication and credential
  management

---

## Compliance & Security Considerations

- **Principle of Least Privilege**: MCP servers expose only the operations
  required for FirePilot's defined workflows. No tool grants Claude access
  to broader API capabilities than explicitly needed
- **Credential Isolation**: API keys and service account tokens are scoped
  to individual MCP servers and never transmitted to or stored in Claude's
  context window
- **Audit Trail**: Every MCP tool invocation must be logged server-side
  with tool name, sanitized input parameters, response status, and
  timestamp. These logs are the authoritative record of what Claude
  instructed external systems to do
- **Prompt Injection Defense**: By removing direct API access from Claude's
  capabilities, the blast radius of a successful prompt injection is
  bounded to the operations the MCP tool surface permits. This does not
  eliminate prompt injection risk but structurally limits its impact
- **SOC 2 CC6.3**: Access to external systems is mediated through defined
  integration points with controlled, auditable interfaces

---

## Review Trigger

- If Anthropic introduces a native, credential-isolated API integration
  mechanism that supersedes MCP for this use case, re-evaluate the
  abstraction layer
- If the MCP protocol undergoes a breaking version change, assess migration
  cost against alternatives at that point
- If a new external system integration is required and cannot be adequately
  expressed as a finite tool set (e.g., requires dynamic API exploration),
  this decision must be revisited before that integration is designed
