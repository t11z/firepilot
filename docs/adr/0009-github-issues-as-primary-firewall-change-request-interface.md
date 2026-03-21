# ADR-0009: Use GitHub Issues as the Primary Firewall Change Request Interface

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0009                                                              |
| Title         | Use GitHub Issues as the Primary Firewall Change Request Interface    |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-19                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

FirePilot requires an entry point where business units submit firewall
change requests with supporting documentation. The original architecture
planned a custom FastAPI web UI for this purpose (`web-ui/` component).

ADR-0005 already establishes GitHub Issues as the ITSM backend for
change management and audit trail. However, ADR-0005 treats Issues as
an _output_ channel — Claude creates Issues to track change requests
it has already processed. The input channel (how requests enter the
system) remained assigned to the planned web UI.

This creates an architectural asymmetry: the audit trail lives in
GitHub Issues, but the request intake lives in a separate application.
The web UI exists solely as a form submission layer with no business
logic beyond input forwarding. Meanwhile, GitHub Issues natively
provides structured templates, file attachments, labels, assignees,
and a comment-based interaction model — all capabilities the web UI
would need to replicate.

Business units submitting firewall change requests typically provide:

1. A structured description of the requested change (application name,
   source/destination zones, required ports, business justification)
2. Supporting documentation (architecture diagrams, compliance
   certificates, application security assessments) — often as PDF files

The web UI would need to handle file uploads, store or forward PDFs,
render Claude's response, and implement an approval workflow. GitHub
Issues provides all of this natively, with the additional benefit that
the entire request lifecycle — submission, AI analysis, human review,
approval, deployment status — is visible in a single, auditable
artefact.

In scope: the request intake mechanism, the event-driven trigger for
Claude processing, PDF attachment handling, and the response/approval
flow within GitHub Issues.

Out of scope: the `mcp-itsm` tool interface (unchanged, defined in
ADR-0005), MCP server authentication (ADR-0006), the CI/CD validation
pipeline for generated configurations (ADR-0003), and the internal
prompt architecture.

---

## Decision

We will use GitHub Issues with a structured Issue Template as the
primary interface for firewall change requests, replacing the planned
custom web UI. A GitHub Actions workflow triggers on new issues,
extracts the structured request and any PDF attachments, invokes the
Claude API with the request context and attached documents, and posts
Claude's response as an issue comment. The approval and deployment
workflow remains within the same issue via label convention (ADR-0005).

The `web-ui/` component is removed from the repository structure.

---

## Considered Alternatives

#### Option A: Custom FastAPI Web UI (status quo)

- **Description**: A dedicated web application where business units
  submit change requests via a form. The backend calls the Claude API,
  renders the response, and provides an approval interface
- **Pros**: Full control over input validation (dynamic field logic,
  dependent dropdowns); custom UX tailored to non-technical users;
  decoupled from GitHub as a platform
- **Cons**: Additional application to build, deploy, and maintain;
  duplicates capabilities GitHub Issues already provides; requires
  its own authentication and authorization layer; file upload handling
  adds complexity; the approval workflow must be custom-built; not
  externally reviewable without running the application; increases
  scope significantly for a portfolio project

#### Option B: GitHub Issues with Issue Template *(chosen)*

- **Description**: A structured GitHub Issue Template captures the
  change request fields. Requestors attach supporting PDFs directly
  to the issue. A GitHub Actions workflow triggers Claude processing
  on issue creation. Claude's analysis, validation result, and
  generated configuration are posted as issue comments. Approval is
  tracked via the existing `firepilot:*` label convention (ADR-0005)
- **Pros**: Zero additional application infrastructure; native file
  attachment support; full audit trail in a single artefact; label-
  based approval workflow already designed in ADR-0005; externally
  reviewable — any GitHub user can follow the complete lifecycle;
  GitHub Actions integration stays within the approved CI/CD stack
  (ADR-0003); reduces overall system complexity
- **Cons**: Issue Template forms have limited input validation (no
  conditional logic, no dynamic field dependencies); GitHub is a
  hard platform dependency for the request interface; PDF attachment
  URLs require download and forwarding to the Claude API; requestors
  must have GitHub access (at minimum, issue creation permission)

#### Option C: Hybrid — GitHub Issues for intake, Web UI for review

- **Description**: Requests enter via GitHub Issues, but a lightweight
  web UI renders Claude's analysis and provides a richer approval
  interface
- **Pros**: Combines structured intake with a polished review
  experience
- **Cons**: Still requires building and maintaining a web application;
  splits the interaction across two interfaces; the approval state
  must be synchronised between the UI and GitHub labels; adds
  complexity without proportional benefit for a portfolio project

---

## Rationale

The evaluation criteria are: operational complexity, auditability,
external reviewability (portfolio goal), and alignment with existing
architectural decisions.

Option A fails on complexity. The web UI exists solely as a
pass-through layer — it collects form input, forwards it to Claude,
and displays the response. Every capability it provides (structured
input, file attachments, comments, status tracking) is natively
available in GitHub Issues. Building it introduces an additional
deployment target, an authentication layer, and a maintenance burden
with no architectural benefit.

Option C reduces the intake problem but reintroduces the review UI
problem. The approval workflow is already designed around GitHub labels
(ADR-0005). A separate review UI would need to stay synchronised with
label state, creating a consistency risk for zero additional
functionality.

Option B aligns with three existing architectural decisions:

- ADR-0001 (Git as source of truth): the request that triggers a
  configuration change lives in the same repository as the
  configuration itself
- ADR-0003 (CI/CD via GitHub Actions): the trigger mechanism is a
  GitHub Actions workflow, consistent with the existing pipeline
  infrastructure
- ADR-0005 (GitHub Issues as ITSM backend): the change request
  lifecycle is already modelled around GitHub Issues; this decision
  unifies intake and tracking in the same artefact

The input validation limitation of Issue Templates is real but
acceptable. Constraint Layer 2 (Claude's system prompt) and Constraint
Layer 3 (OPA validation in CI/CD) enforce policy regardless of input
quality. The Issue Template provides structural guidance; it does not
need to be a validation gate.

---

## Request Flow

### 1. Submission

The requestor creates a new issue using the `firewall-change-request`
Issue Template. The template captures:

| Field                  | Template Element  | Description                              |
|------------------------|-------------------|------------------------------------------|
| Application Name       | text input        | Name of the application or service       |
| Business Unit          | text input        | Requesting team or department             |
| Source Zone / Network  | text input        | Origin of the traffic                     |
| Destination Zone / Network | text input    | Target of the traffic                     |
| Required Ports / Services  | text input    | Ports or application-layer services       |
| Business Justification | textarea          | Why this change is needed                 |
| Supporting Documentation | file attachment  | Architecture diagrams, compliance docs    |

The template applies the `firepilot:pending` label automatically on
creation.

### 2. Trigger

A GitHub Actions workflow triggers on `issues: [opened]` with label
filter `firepilot:pending`. The workflow:

1. Extracts the issue body (structured fields from the template)
2. Parses PDF attachment URLs from the issue body using the GitHub
   Markdown image/link syntax for uploaded files
3. Downloads each PDF attachment via authenticated HTTP request
   (using `GITHUB_TOKEN` available to the workflow)
4. Calls the Claude API (`/v1/messages`) with:
   - System prompt loaded from `prompts/` (versioned)
   - Issue body as user message content
   - Each PDF as a `document`-type content block (base64-encoded,
     `media_type: application/pdf`)
   - MCP server connections for `mcp-strata-cloud-manager` and
     `mcp-itsm`
5. Posts Claude's response as an issue comment via the GitHub API

### 3. Review and Approval

The requestor and designated approvers review Claude's analysis in
the issue comments. Claude's response includes:

- Validation result (accepted or rejected with reasons)
- If accepted: the proposed YAML configuration (as a code block)
- References to relevant policy constraints
- Any warnings or recommendations

The approver sets the `firepilot:approved` or `firepilot:rejected`
label. This label transition is a human action — consistent with
ADR-0005's separation of duties principle.

### 4. Deployment

On `firepilot:approved`, a subsequent GitHub Actions workflow (or a
next step in the same workflow, triggered by label change) proceeds
with the deployment path defined in ADR-0003 and ADR-0004:

- Commit the generated YAML configuration to a feature branch
- Open a PR against `main`
- CI/CD validation (JSON Schema + OPA) runs on the PR
- On merge: deployment via `mcp-strata-cloud-manager`

The deployment result is posted back to the issue via
`update_change_request_status` (ADR-0005), setting the terminal
label (`firepilot:deployed` or `firepilot:failed`).

---

## PDF Attachment Handling

GitHub stores issue attachments as URLs under
`https://github.com/user-attachments/assets/...`. These URLs are
accessible with appropriate authentication.

The GitHub Actions workflow downloads attachments and passes them to
the Claude API as base64-encoded `document`-type content blocks. This
preserves the full document structure — tables, diagrams, formatting
— without an intermediate text extraction step that would lose
information.

**Assumption**: GitHub attachment URLs are accessible to GitHub Actions
workflows running in the same repository using the default
`GITHUB_TOKEN`. If this assumption proves incorrect (e.g., due to
private repository restrictions on user-uploaded assets), an
alternative download mechanism using a PAT or GitHub App token will
be required.

**Size constraint**: The Claude API accepts documents up to 32 MB per
file. The Issue Template should document this limit. Attachments
exceeding this limit are skipped with a warning comment on the issue.

---

## Issue Template Specification

The Issue Template is defined as a YAML form template at
`.github/ISSUE_TEMPLATE/firewall-change-request.yml`. GitHub renders
form-based templates as structured input fields rather than freeform
Markdown, ensuring consistent field presence.

The template must:

- Set `labels: ["firepilot:pending"]` to auto-apply the trigger label
- Use `type: input` for single-line fields and `type: textarea` for
  multi-line fields
- Mark all fields except file attachments as required
- Include a file attachment section with instructions for uploading
  supporting documentation

**Assumption**: GitHub Issue Template forms support the `type: input`
and `type: textarea` elements. File attachments are not a native
template form element — they are added by the requestor in the issue
body or as a follow-up comment. The template includes instructions
for attachment upload.

---

## Consequences

- **Positive**: The `web-ui/` component is eliminated, reducing the
  system's deployment surface and maintenance scope
- **Positive**: The entire change request lifecycle — submission,
  AI analysis, human review, approval, deployment result — is
  contained in a single GitHub Issue, maximising auditability
- **Positive**: External reviewers can follow the complete workflow
  in a public repository without running any application
- **Positive**: GitHub Actions is the sole orchestration runtime,
  consistent with ADR-0003
- **Positive**: PDF documents are passed to Claude without
  information loss, enabling rich context analysis of supporting
  documentation
- **Negative**: Requestors must have GitHub access with issue
  creation permission on the target repository; this may be a
  barrier in organisations where business units do not use GitHub
- **Negative**: Issue Template forms cannot enforce complex input
  validation (conditional fields, format checks); malformed
  requests rely on Claude (Layer 2) and OPA (Layer 3) to catch
  errors
- **Negative**: GitHub becomes a harder platform dependency — the
  request interface, ITSM backend, CI/CD runtime, and configuration
  repository are all GitHub-hosted
- **Follow-up required**: Create the Issue Template at
  `.github/ISSUE_TEMPLATE/firewall-change-request.yml`
- **Follow-up required**: Implement the GitHub Actions workflow for
  issue-triggered Claude invocation
- **Follow-up required**: Update `CLAUDE.md` repository structure to
  remove `web-ui/` and add `.github/ISSUE_TEMPLATE/`
- **Follow-up required**: Update `README.md` demo scenario to reflect
  the new intake flow
- **Follow-up required**: Evaluate whether `mcp-itsm` requires
  additional tools for reading issue content (currently the Actions
  workflow handles intake directly; `mcp-itsm` tools are used by
  Claude for writing back to the issue)

---

## Compliance & Security Considerations

- **Audit Trail Completeness**: The issue captures the original
  request, all supporting documentation, Claude's analysis, human
  approval decisions, and deployment outcome — forming a complete,
  tamper-evident audit record for each change. This strengthens the
  SOC 2 CC6.1 compliance posture beyond what the previous web UI
  design offered
- **Separation of Duties**: The requestor submits via issue creation.
  Claude analyses and proposes. A human approver (distinct from the
  requestor, enforceable via GitHub branch protection and CODEOWNERS)
  sets the approval label. FirePilot deploys only after human
  approval. No single actor controls the full lifecycle
- **Document Handling**: PDF attachments uploaded to GitHub Issues are
  stored on GitHub's infrastructure. They are transmitted to the
  Claude API via the GitHub Actions workflow. Supporting documents
  may contain sensitive information (network diagrams, IP ranges).
  The repository's access control settings must reflect this —
  private repositories are recommended for production use
- **GitHub Token Scope**: The GitHub Actions workflow uses the default
  `GITHUB_TOKEN` for issue operations (read body, post comments, set
  labels) and attachment downloads. No additional token scope beyond
  `issues: write` is required. This is consistent with ADR-0006
- **GDPR**: Issue bodies and comments may contain personal identifiers
  (requestor names, business unit contacts). GitHub's data processing
  terms apply. Retention policies for closed issues should be defined
  as part of operator setup

---

## Review Trigger

- If business units without GitHub access need to submit requests,
  introduce a lightweight intake proxy (email-to-issue, form-to-issue)
  rather than rebuilding a full web UI
- If GitHub changes its attachment URL scheme or access model for
  user-uploaded assets, the PDF download mechanism must be updated
- If the Claude API document input size limit changes, update the
  Issue Template instructions and the workflow's size-check logic
- If the volume of change requests exceeds what sequential GitHub
  Actions runs can handle (concurrent workflow limits), consider a
  queue-based processing model
- If GitHub Issue Template forms gain support for native file upload
  fields, simplify the attachment handling instructions

---

## Amendment: Flexible Request Modes (2026-03-21)

| Field     | Value                                   |
|-----------|-----------------------------------------|
| Amended   | Issue Template Specification, Request Flow §1 |
| Reason    | The original template assumes one rule per request. Real-world change requests — particularly document-driven ones — may require multiple rules extracted from a single submission. |
| Related   | ADR-0012 (Centralised Operator Configuration) |

---

### Problem Statement

The original Issue Template requires the requestor to fill in
Source Zone, Destination Zone, and Required Ports as mandatory text
inputs. This design maps each issue to exactly one firewall rule.

Three scenarios do not fit this model:

1. **Document-driven requests**: A business unit attaches an
   application operations manual that specifies multiple firewall
   rules (e.g., PigeonTrack FW-PT-01 through FW-PT-07). The
   requestor's intent is "implement the firewall requirements from
   this document" — they should not need to decompose the document
   into individual template submissions.

2. **Multi-rule structured requests**: A requestor knows the exact
   rules they need but there are several, each with different
   zone pairs and ports. Filing seven identical issues for one
   application deployment is operationally wasteful and breaks the
   audit trail (one application → one change request).

3. **Single structured rule**: The existing model. A requestor
   specifies exactly one source/destination/port combination.

Additionally, the original template did not account for the SCM
target folder, which is an operator-level decision (ADR-0012), not
a requestor input. Claude was observed asking users for the target
folder during processing — this must be prevented by design.

### Amended Issue Template Specification

The Issue Template is redesigned with a **request mode dropdown** that
determines which fields are semantically required. GitHub Issue
Template forms do not support conditional field visibility — all
fields are always rendered. The mode dropdown governs how Claude
(Layer 2) interprets the submission, not which fields GitHub displays.

#### Template Field Specification

| Field                        | Template Element | Condition                                           |
|------------------------------|------------------|-----------------------------------------------------|
| Application Name             | text input       | Always required                                     |
| Business Unit                | text input       | Always required                                     |
| Request Mode                 | dropdown         | Always required. Options: see below                 |
| Source Zone / Network        | text input       | Required for `Single Rule`. Informational otherwise  |
| Destination Zone / Network   | text input       | Required for `Single Rule`. Informational otherwise  |
| Required Ports / Services    | text input       | Required for `Single Rule`. Informational otherwise  |
| Additional Rules             | textarea         | Used for `Multiple Rules` mode. Optional otherwise   |
| Business Justification       | textarea         | Always required                                     |
| Supporting Documentation     | textarea (attachment) | Always available. Especially important for `Document-Based` mode |

#### Request Mode Options

The dropdown `request_mode` offers three options:

| Mode               | Label in dropdown                        | Meaning                                                                    |
|--------------------|------------------------------------------|----------------------------------------------------------------------------|
| `single_rule`      | Single rule — I'll specify the details   | Requestor fills in Source Zone, Destination Zone, Ports. Maps to one rule.  |
| `multiple_rules`   | Multiple rules — I'll list them          | Requestor fills in the metadata fields, then lists rules in the Additional Rules textarea (one rule per block, freeform or semi-structured). |
| `document_based`   | Document-based — see attached docs       | Requestor fills in metadata and attaches documentation. Claude extracts all required rules from the attached PDFs. Technical fields may be left empty or contain high-level summaries. |

#### Validation Responsibility by Mode

| Concern                         | `single_rule`         | `multiple_rules`      | `document_based`      |
|---------------------------------|-----------------------|-----------------------|-----------------------|
| Source/Dest/Ports filled in     | Layer 1 (Template)    | Layer 2 (Claude)      | Layer 2 (Claude)      |
| Rule count determination        | Implicit (1)          | Layer 2 (Claude)      | Layer 2 (Claude)      |
| Rule completeness               | Layer 1 + Layer 2     | Layer 2               | Layer 2               |
| Zone existence validation       | Layer 2               | Layer 2               | Layer 2               |
| Policy compliance               | Layer 3 (OPA)         | Layer 3 (OPA)         | Layer 3 (OPA)         |

In all modes, Layer 3 (OPA) and Layer 4 (MCP server-side) enforcement
remain unchanged — they validate the generated configuration
regardless of how it was requested.

### Amended Request Flow — §1 Submission

The requestor creates a new issue using the
`firewall-change-request` template. The template captures:

| Field                        | Template Element  | Description                                              |
|------------------------------|-------------------|----------------------------------------------------------|
| Application Name             | text input        | Name of the application or service                       |
| Business Unit                | text input        | Requesting team or department                            |
| Request Mode                 | dropdown          | `single_rule`, `multiple_rules`, or `document_based`     |
| Source Zone / Network        | text input        | Origin of the traffic (primary field for `single_rule`)  |
| Destination Zone / Network   | text input        | Target of the traffic (primary field for `single_rule`)  |
| Required Ports / Services    | text input        | Ports or services (primary field for `single_rule`)      |
| Additional Rules             | textarea          | Freeform rule descriptions for `multiple_rules` mode     |
| Business Justification       | textarea          | Why this change is needed                                |
| Supporting Documentation     | textarea          | PDF attachments (instructions unchanged from original)   |

The template applies the `firepilot:pending` label automatically on
creation.

### Claude Processing Behaviour by Mode

This section specifies how Claude (Layer 2) interprets each mode.
The processing workflow (§2 Trigger) is unchanged — Claude receives
the full issue body and attachments in all modes.

#### `single_rule` mode

Claude treats the Source Zone, Destination Zone, and Ports fields as
the primary specification. Attached documentation is supplementary
context. Processing follows the existing Step 1–11 workflow for a
single rule. If the technical fields are empty or contain
placeholders despite `single_rule` being selected, Claude asks the
requestor for clarification via an issue comment.

#### `multiple_rules` mode

Claude parses the Additional Rules textarea for rule specifications.
The format is deliberately flexible — requestors may use tables,
bullet lists, or prose. Claude extracts each distinct rule, validates
all of them (zone existence, conflict detection, policy compliance),
and generates a separate YAML rule file per rule. All rules are
committed to a single feature branch and PR, maintaining the
one-application-one-change-request principle.

If the Additional Rules field is ambiguous, Claude posts a
clarification request on the issue before generating configuration.

The Source Zone / Destination Zone / Ports fields, if filled in
alongside `multiple_rules` mode, are treated as the *first* rule.
Additional rules are additive.

#### `document_based` mode

Claude extracts firewall requirements from the attached PDF
documentation. The Source Zone, Destination Zone, and Ports fields
are treated as optional hints — if filled in, they provide
directional context but do not constrain the extraction.

Claude maps the document's network terminology to SCM zone names
using the zone topology from `firepilot.yaml` (ADR-0012). If the
mapping is ambiguous (e.g., the document says "DMZ" but multiple
zones could correspond), Claude posts a clarification request
listing the available zones and asking the requestor to confirm the
mapping.

As with `multiple_rules`, all extracted rules are committed to a
single feature branch and PR.

### Operator Configuration Integration (ADR-0012)

The Issue Template does not include any field for SCM folder or
position. These values are read from `firepilot.yaml`
(`scm.default_folder`, `scm.default_position`) by the processing
workflow and by Claude. The requestor has no ability to override
them.

The system prompt is updated to include an explicit instruction:
"Never ask the requestor for the target SCM folder or rulebase
position. These are operator-level settings defined in
`firepilot.yaml`."

### Consequences of this Amendment

- **Positive**: The PigeonTrack demo scenario is fully supported —
  a single issue with an attached operations manual triggers
  extraction of all seven firewall rules
- **Positive**: Requestors with detailed technical knowledge can
  use `single_rule` or `multiple_rules` mode for precise control
- **Positive**: Requestors without firewall expertise can use
  `document_based` mode, delegating extraction to Claude
- **Positive**: The audit trail remains one issue per application,
  regardless of how many rules are generated
- **Negative**: GitHub Issue Template forms cannot conditionally
  hide fields — in `document_based` mode, the Source Zone /
  Destination Zone / Ports fields are visible but semantically
  optional, which may confuse requestors. Mitigation: field
  descriptions and placeholder text explain this clearly per mode
- **Negative**: `document_based` mode places significantly more
  responsibility on Claude (Layer 2) for correct extraction. Layers
  3 and 4 still validate the output, but a missed rule in extraction
  is invisible to automated validation — only human review of the PR
  can catch it
- **Follow-up required**: Update the Issue Template YAML at
  `.github/ISSUE_TEMPLATE/firewall-change-request.yml`
- **Follow-up required**: Update the system prompt to handle the
  three request modes and to never ask for folder/position
- **Follow-up required**: Update `process-firewall-request.yml` to
  support multi-rule commits (multiple YAML files + manifest update
  per PR)
- **Follow-up required**: Update `ci/README.md` manual test
  instructions with a `document_based` test scenario
- **Follow-up required**: Update `demo/example-issue.md` to
  demonstrate the PigeonTrack `document_based` scenario
