# ADR-0001: Use Git as the Single Source of Truth for Firewall Configuration

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0001                                                              |
| Title         | Use Git as the Single Source of Truth for Firewall Configuration      |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-19                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

Firewall rules in enterprise environments are historically managed through
direct API calls or manual UI interactions against the firewall management
platform. This creates several structural problems:

- The live system state is the only record of what rules exist and why
- Changes are not inherently reviewable, reversible, or auditable beyond
  vendor-provided logs
- There is no mechanism to enforce policy validation before a rule reaches
  the firewall
- Drift between intended configuration and actual system state is invisible
  until it causes an incident

FirePilot generates firewall configurations from natural language input via
Claude. Without a defined persistence and deployment model, generated
configurations would be applied directly to the firewall API — bypassing
review, validation, and audit entirely.

This decision defines where the authoritative state of all firewall
configuration lives and how changes flow from intent to deployment.

In scope: declarative firewall rule configuration, the deployment pipeline,
and the relationship between Claude-generated output and the live firewall state.

Out of scope: secrets management, branch protection rules, and the internal
format of firewall configuration files (addressed in a separate ADR).

---

## Decision

We will store all firewall configurations as declarative YAML files in a
dedicated Git repository, making Git the single source of truth. No
configuration change may reach the firewall without first being committed
to this repository and passing CI/CD validation.

---

## Considered Alternatives

#### Option A: Direct API Deployment — Claude writes rules directly to the firewall API

- **Description**: Claude generates a configuration and the MCP server applies
  it immediately to the Palo Alto Strata Cloud Manager API without intermediate
  persistence
- **Pros**: Lowest latency from intent to deployment; simplest initial implementation
- **Cons**: No audit trail owned by the operator; no pre-deployment validation;
  no rollback mechanism beyond vendor API; configuration state lives exclusively
  in the firewall platform; violates least-privilege and change-management
  requirements for regulated environments

#### Option B: Database as Source of Truth — configurations stored in a relational or document store

- **Description**: Claude-generated configurations are persisted in a database;
  a deployment service reads from the database and applies changes to the firewall
- **Pros**: Queryable state; easier programmatic access
- **Cons**: Introduces a stateful service that must be operated and backed up;
  no native diff/review workflow; auditability requires custom implementation;
  external reviewers cannot inspect state without database access

#### Option C: Git as Source of Truth *(chosen)*

- **Description**: All firewall configurations are stored as YAML files in a
  Git repository. Changes are introduced via Pull Requests, validated by CI/CD
  policy checks, and deployed to the firewall only after merge to `main`
- **Pros**: Native audit trail via Git history; diff-based review for every
  change; rollback is a revert commit; policy validation is enforced before
  deployment; state is inspectable without credentials; aligns with established
  GitOps patterns
- **Cons**: Adds PR-merge latency to the deployment path; requires CI/CD
  pipeline maintenance; emergency change procedures must be explicitly defined
  to avoid bypassing controls

---

## Rationale

Option A fails the most fundamental requirement: auditability. For a system
that modifies network security policy, an operator-owned record of every change
— including who requested it, what was validated, and what was deployed — is
non-negotiable. Vendor API logs do not substitute for this.

Option B solves the persistence problem but trades one operational dependency
(firewall API) for two (firewall API + database). It also requires custom
tooling to achieve what Git provides natively: versioning, diffing, and
access without infrastructure.

Option C maps directly to the compliance requirement for change management
(approval before deployment) and the architectural principle that the
repository is the single source of truth. The PR-based flow enforces a
human or automated review gate at zero additional tooling cost. The
deployment latency introduced by the merge step is acceptable for all
non-emergency changes; emergency procedures are defined in the Consequences
section below.

---

## Consequences

- **Positive**: Every configuration change is traceable to a commit, a PR,
  and an approval — satisfying SOC 2 CC6 and ISO 27001 A.12.1.2 change
  management controls out of the box
- **Positive**: Rollback is a standard Git revert; no custom undo mechanism
  required
- **Positive**: CI/CD policy validation (OPA or equivalent) runs automatically
  on every proposed change before it can be merged
- **Positive**: The repository is self-contained and inspectable by external
  reviewers without API access
- **Negative**: Emergency firewall changes (active incident response) cannot
  wait for a PR review cycle; a documented emergency bypass procedure must
  exist, including mandatory post-hoc PR creation within 24 hours
- **Negative**: Drift is possible if the firewall platform is modified outside
  of FirePilot; a reconciliation or drift-detection mechanism should be
  considered in a future ADR
- **Follow-up required**: ADR for declarative configuration file format (YAML
  schema, required fields, naming conventions)
- **Follow-up required**: ADR for CI/CD pipeline design and policy validation
  toolchain

---

## Compliance & Security Considerations

- **SOC 2 CC6.1 / CC6.8**: The PR-based merge gate enforces logical access
  controls and change approval before any configuration reaches production
- **ISO 27001 A.12.1.2**: Change management is structurally enforced —
  undocumented changes cannot enter the system through the standard path
- **GDPR**: No personal data is stored in firewall configuration files;
  however, commit metadata (author, timestamp) constitutes an audit record
  and must be retained in accordance with applicable retention policies
- **Trust boundary**: The Git repository is a trusted boundary. Write access
  to `main` must be restricted to the CI/CD pipeline service account and
  repository administrators. Direct pushes to `main` are prohibited (see
  CLAUDE.md)
- **Audit trail**: Git history is append-only under normal operation. Force
  pushes to `main` must be prohibited at the repository settings level to
  preserve the integrity of the audit trail

---

## Review Trigger

- If FirePilot is required to support sub-minute deployment latency, the
  PR-merge model must be re-evaluated
- If the firewall platform introduces native GitOps integration, the MCP
  deployment layer may be simplified or removed — revisit the deployment
  architecture ADR at that point
- If a drift incident occurs (live state diverges from Git state without a
  corresponding commit), this ADR must be reviewed and a drift-detection
  mechanism mandated
