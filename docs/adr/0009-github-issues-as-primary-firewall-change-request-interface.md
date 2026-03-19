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
