# ADR-0000: Architecture Decision Record — Format and Process Definition

| Field       | Value                        |
|-------------|------------------------------|
| ID          | ADR-0000                      |
| Title       | ADR Format and Process Definition |
| Status      | **Approved**                 |
| Deciders    | FirePilot Core Team          |
| Date        | 2026-03-19                   |
| Supersedes  | —                            |
| Superseded by | —                          |

---

## Context

Architectural decisions in FirePilot carry security, compliance, and operational consequences. Undocumented or informally communicated decisions create auditability gaps, onboarding friction, and architectural drift over time.

This project requires a lightweight but rigorous process for recording decisions — one that captures not only *what* was decided but *why*, *what was rejected*, and *under what conditions the decision should be revisited*.

This document defines the canonical format and lifecycle for all Architecture Decision Records (ADRs) in FirePilot. It is self-referential: ADR-0000 is itself an ADR and conforms to the format it defines.

---

## Decision

All significant architectural, technological, and process decisions in FirePilot **must** be documented as ADRs following the format and process defined in this document. ADRs are versioned in Git alongside the codebase and are the authoritative record of architectural intent.

---

## ADR Format

Every ADR must contain the following sections. Sections may be brief but must not be omitted.

### Header Table

```markdown
| Field         | Value                          |
|---------------|--------------------------------|
| ID            | ADR-XXXX                        |
| Title         | Short imperative title         |
| Status        | [Draft | Proposed | Approved | Deprecated | Superseded] |
| Deciders      | Names or roles of decision makers |
| Date          | YYYY-MM-DD (date of status change to Approved) |
| Supersedes    | ADR-XXXX or —                   |
| Superseded by | ADR-XXXX or —                   |
```

### 1. Context

Describe the architectural problem, constraint, or requirement that necessitates a decision. Include:
- The technical or business pressure driving the decision
- Any constraints (compliance, cost, technology, team capability)
- The scope: what is and is not in scope for this decision

Do not argue for any option here. This section is purely descriptive.

### 2. Decision

State the decision clearly and directly. One or two sentences. No justification yet.

> Format: "We will [action] because [one-line rationale]."

### 3. Considered Alternatives

List all alternatives that were seriously considered. For each:

```markdown
#### Option N: [Name]
- **Description**: What this option entails
- **Pros**: Concrete advantages
- **Cons**: Concrete disadvantages or risks
```

A minimum of two alternatives must be documented. "Status quo / do nothing" counts as an alternative when applicable.

### 4. Rationale

Explain why the chosen decision is preferred over the alternatives. Reference the criteria used to evaluate options (e.g., operational cost, security posture, team expertise, auditability). Make implicit trade-offs explicit.

### 5. Consequences

Document the expected outcomes of this decision:

- **Positive**: What improves or becomes possible
- **Negative**: What becomes harder, more constrained, or requires mitigation
- **Neutral / Follow-up required**: Decisions that are now unblocked or must follow from this one

### 6. Compliance & Security Considerations

*Required for decisions touching network policy, data handling, authentication, API design, or CI/CD permissions.*

Describe how this decision relates to:
- Relevant regulatory or compliance requirements (e.g., GDPR, ISO 27001, SOC 2)
- Security boundaries or trust assumptions introduced or affected
- Audit trail implications

If not applicable, state: `Not applicable.`

### 7. Review Trigger

Define the conditions under which this decision should be revisited. Examples:
- A specific technology reaches end-of-life
- Volume or scale crosses a defined threshold
- A dependent system changes its API or licensing
- A compliance requirement changes

---

## Status Lifecycle

```
Draft → Proposed → Approved
                 ↘
                   Deprecated
                   Superseded (by ADR-XXXX)
```

| Status      | Meaning                                                                 |
|-------------|-------------------------------------------------------------------------|
| Draft       | Work in progress. Not ready for team review.                           |
| Proposed    | Ready for review. Open for structured objection or amendment.          |
| Approved    | Decision is active and binding for the project.                        |
| Deprecated  | Decision is no longer relevant. No replacement exists.                 |
| Superseded  | Replaced by a newer ADR. Header must reference the superseding ADR ID. |

---

## Process

### Creating an ADR

1. Copy `docs/adr/ADR-TEMPLATE.md` to `docs/adr/XXXXx-short-title.md`  
   Use the next available sequential ID. IDs are never reused.
2. Set status to `Draft`.
3. Fill all sections. Incomplete ADRs must not be proposed.
4. Open a Pull Request targeting `main` with the prefix `[ADR]` in the title.

### Review and Approval

1. Set status to `Proposed` when opening the PR.
2. At least one other team member must review the ADR.
3. Objections must be filed as PR comments referencing specific sections.
4. The author addresses objections by amending the ADR content, not only the PR discussion.
5. Approval requires explicit sign-off (GitHub PR approval). 
6. On merge: set status to `Approved` and record the date.

### Superseding an ADR

1. Create a new ADR in `Draft` following the standard process.
2. In the new ADR, set `Supersedes: ADR-XXXX`.
3. On approval of the new ADR, update the old ADR's status to `Superseded` and set `Superseded by: ADR-YYY`.
4. Both changes land in the same PR.

### Constraints

- ADRs are immutable once `Approved`, except for status and supersession fields.
- Retroactive rewrites of rationale or consequences are not permitted.
- If the decision was wrong, supersede it — do not silently edit it.

---

## File Naming Convention

```
docs/adr/0000-meta-adr-process.md
docs/adr/0001-gitops-as-source-of-truth.md
docs/adr/0002-mcp-over-direct-api.md
```

Format: `ADR-[zero-padded 3-digit ID]-[kebab-case-title].md`

---

## Considered Alternatives

#### Option A: No formal ADR process — use PR descriptions and inline comments
- **Pros**: Zero overhead, no template to maintain
- **Cons**: Decisions are buried in Git history, not searchable, not auditable as a set; new contributors have no architectural narrative to orient from

#### Option B: Use a commercial decision-tracking tool (Confluence, Notion, etc.)
- **Pros**: Rich formatting, linking, notifications
- **Cons**: Decoupled from code; requires account access for external reviewers; violates the principle that the repository is the single source of truth

#### Option C: Markdown ADRs in Git (chosen)
- **Pros**: Co-located with code, versioned, diff-able, accessible without authentication, portfolio-presentable
- **Cons**: Requires discipline to maintain; no automated enforcement without additional tooling

---

## Rationale

Option C is the only approach consistent with FirePilot's core principle that Git is the single source of truth. ADRs in Markdown require no infrastructure, are readable by any external reviewer without access credentials, and are directly linkable from the README.

The structured format — particularly the mandatory "Considered Alternatives" and "Review Trigger" sections — prevents ADRs from becoming post-hoc justifications and forces documentation of the decision space, not just the outcome.

---

## Consequences

- **Positive**: All architectural decisions are traceable, auditable, and accessible to external reviewers
- **Positive**: Onboarding cost is reduced; new contributors understand *why* the system is shaped as it is
- **Negative**: Requires discipline; unmaintained ADRs are worse than no ADRs
- **Follow-up**: An `ADR-TEMPLATE.md` must be created in `docs/adr/` immediately following approval of this document

---

## Compliance & Security Considerations

This ADR governs process, not technology. However, the ADR process itself supports compliance requirements:

- **Auditability**: All decisions are documented with deciders and dates, supporting SOC 2 change management controls
- **GDPR**: Decisions affecting personal data processing must invoke Section 6 (Compliance & Security Considerations) explicitly
- **Change Management**: The PR-based approval process creates a verifiable audit trail for all architectural changes

---

## Review Trigger

- If the team size exceeds 5 contributors, consider introducing a formal RFC process for cross-cutting concerns
- If a compliance audit requires richer decision metadata (e.g., risk ratings, control mappings), extend the format via a new ADR that supersedes this one
