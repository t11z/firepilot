# ADR-0003: CI/CD Pipeline Design and Policy Validation Toolchain

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0003                                                              |
| Title         | CI/CD Pipeline Design and Policy Validation Toolchain                 |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-19                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

ADR-0001 establishes Git as the single source of truth for firewall
configuration and mandates that no configuration change may reach the
firewall without first passing CI/CD validation. This ADR defines what
that pipeline looks like: which tool runs validation, what it validates,
and under what conditions a change is permitted to deploy.

FirePilot's CI/CD pipeline sits at the third constraint layer in the
system's defense-in-depth model:

```
Layer 1 — UI:            Input validation and field constraints
Layer 2 — Claude:        System prompt policy rules
Layer 3 — CI/CD:         Policy-as-Code validation before deployment  ← this ADR
Layer 4 — MCP/API:       Backend-side validation at the integration boundary
```

This layer must be independent of Claude. It must validate configuration
files on their own merits — not trust that Claude produced them correctly.

Key requirements for this layer:
- Validation logic must be declarative, version-controlled, and auditable
- Rules must be enforceable without human review for routine changes
- Pipeline must be executable locally for development and demo purposes
- No always-on infrastructure — GitHub Actions is the runtime

In scope: pipeline structure, validation toolchain selection, deployment
trigger conditions, and the categories of policy checks performed.

Out of scope: the specific policy rules enforced (content of OPA policies),
secrets management in CI, and the firewall deployment mechanism itself
(covered in the MCP server ADRs).

---

## Decision

We will implement the CI/CD pipeline using GitHub Actions, with Open Policy
Agent (OPA) as the policy validation engine for firewall configuration files.
Deployment to the firewall is triggered exclusively on merge to `main` after
all validation gates pass.

---

## Considered Alternatives

#### Option A: Custom Python validation scripts

- **Description**: A set of Python scripts validate configuration files against
  hardcoded rules (allowed ports, required fields, forbidden source ranges, etc.)
- **Pros**: No additional tooling dependency; straightforward to write and
  understand; full control over validation logic
- **Cons**: Policy logic is imperative and scattered across scripts; adding
  a new rule requires modifying code, not declaring a policy; no standard
  query language for expressing policy conditions; harder to audit — a
  reviewer must read code, not policy declarations; does not compose well
  as rule complexity grows

#### Option B: JSON Schema validation only

- **Description**: YAML configuration files are validated against a JSON Schema
  that enforces structural correctness and field constraints
- **Pros**: Schema validation is universally understood; tools are mature
  and widely available; catches structural errors early
- **Cons**: JSON Schema cannot express semantic policy (e.g., "deny any rule
  that opens port 22 from 0.0.0.0/0"); covers only syntactic validity, not
  security intent; insufficient as the sole validation layer for a security-
  critical system

#### Option C: OPA (Open Policy Agent) with Rego policies *(chosen)*

- **Description**: Configuration files are validated against Rego policies
  using OPA. Policies are declarative, version-controlled alongside
  configuration, and evaluated by the `opa eval` CLI in GitHub Actions
- **Pros**: Policy logic is declarative and readable without deep programming
  knowledge; separation of policy from code is a first-class design principle
  in OPA; policies are composable and independently testable with `opa test`;
  industry-standard toolchain used in production Kubernetes and security
  environments; strong portfolio signal for enterprise readiness
- **Cons**: Rego has a learning curve — its datalog-inspired syntax is
  unfamiliar to most engineers initially; adds OPA as a toolchain dependency;
  policy test coverage must be maintained alongside policies themselves

#### Option D: Commercial policy platforms (Checkov, Terrascan, etc.)

- **Description**: Use an existing security scanning tool with built-in rule
  libraries for infrastructure-as-code validation
- **Pros**: Pre-built rule libraries; less initial authoring effort
- **Cons**: Built for Terraform/CloudFormation, not custom YAML schemas;
  rule customization is constrained by the platform's extension model;
  introduces a vendor dependency for a core security control; overkill and
  ill-fitting for a bespoke configuration format

---

## Rationale

Option A is rejected because imperative validation scripts conflate policy
intent with implementation detail. As rule complexity grows, the gap between
"what the policy says" and "what the code does" widens — exactly the wrong
property for an audit-facing system.

Option B is a necessary but insufficient layer. JSON Schema validates
structure; it cannot validate security semantics. It should be used in
addition to OPA, not instead of it.

Option D is the wrong tool for the job. These platforms target standard
IaC formats; adapting them to FirePilot's custom YAML schema would fight
the toolchain more than leverage it.

Option C — OPA — is the correct choice because the separation of policy
from pipeline logic is itself the architectural goal. Rego policies are
declarative statements of intent ("no rule may permit traffic from the
internet directly to the database zone") that can be read, reviewed, and
tested independently of the pipeline implementation. This is the property
that makes the validation layer auditable.

JSON Schema validation (Option B) is retained as a complementary first
gate — structural correctness before semantic evaluation.

---

## Pipeline Structure

```
PR opened / updated
        │
        ▼
┌───────────────────┐
│  1. Lint & Schema │  JSON Schema validation — structural correctness
│     Validation    │  Fails fast on malformed YAML before OPA evaluation
└────────┬──────────┘
         │ pass
         ▼
┌───────────────────┐
│  2. OPA Policy    │  Rego policy evaluation — security semantics
│     Evaluation    │  Enforces: allowed ports, zone rules, required
│                   │  metadata, forbidden source ranges, naming conventions
└────────┬──────────┘
         │ pass
         ▼
┌───────────────────┐
│  3. Dry-Run       │  MCP strata tool called in validation mode
│     Validation    │  Confirms config is accepted by firewall API schema
│                   │  (mock mode in demo environment)
└────────┬──────────┘
         │ pass
         ▼
    PR mergeable
        │
        ▼ merge to main
┌───────────────────┐
│  4. Deployment    │  MCP strata tool called in commit mode
│                   │  Change request created via mcp-itsm
│                   │  Git tag applied on successful deployment
└───────────────────┘
```

Gates 1–3 run on every PR update. Gate 4 runs exclusively on merge to `main`.
A failure at any gate blocks the pipeline — no partial deployments.

---

## Consequences

- **Positive**: Policy intent is readable as Rego declarations — reviewable
  by security teams without pipeline expertise
- **Positive**: `opa test` enables policy unit testing; policy correctness
  is verifiable independently of the pipeline
- **Positive**: The pipeline is fully executable locally via `act` (GitHub
  Actions local runner) or by invoking OPA and schema validation directly —
  no always-on infrastructure required
- **Positive**: Every PR that fails validation produces a structured report
  citing the violated policy by name — traceable in the PR audit trail
- **Positive**: The dry-run gate catches API-level rejections before merge,
  reducing post-deployment rollback scenarios
- **Negative**: Rego authoring requires investment; initial policy set must
  be defined before the pipeline provides meaningful coverage
- **Negative**: Policy test suite must be maintained as a first-class
  artefact — untested policies are a false sense of security
- **Negative**: OPA must be installed in the GitHub Actions runner and
  locally; version pinning must be enforced to prevent policy drift
  across environments
- **Follow-up required**: Define the initial Rego policy set covering
  FirePilot's minimum security baseline
- **Follow-up required**: ADR for firewall configuration YAML schema
  (required by both JSON Schema and OPA policy authoring)

---

## Compliance & Security Considerations

- **SOC 2 CC8.1**: Automated change management controls are enforced at
  the pipeline level — no human can merge a configuration change that
  fails policy validation without bypassing Git branch protections
- **ISO 27001 A.14.2.3**: Technical review of configuration changes is
  structurally enforced; the OPA gate is the documented control
- **Audit Trail**: Every pipeline run produces a log of which policies
  were evaluated, which passed, and which failed. These logs are
  retained by GitHub Actions and referenced in the ITSM ticket created
  at deployment (Gate 4)
- **Pipeline Integrity**: The GitHub Actions workflow files under `ci/`
  are subject to the same branch protection rules as configuration files.
  Modifications to pipeline definitions require PR review — the validation
  layer cannot be silently weakened
- **Separation of Duties**: The CI/CD pipeline runs under a dedicated
  service account with write access scoped to `main` merges only.
  No human account should have equivalent unreviewed write access

---

## Review Trigger

- If OPA is deprecated or superseded by a materially better policy
  engine in the GitOps space, reassess at that point
- If the volume of configuration changes makes sequential gate execution
  a throughput bottleneck, consider parallelising gates 1 and 2
- If a compliance audit requires finer-grained evidence mapping between
  individual policy rules and specific controls, extend the Rego policy
  metadata schema accordingly
- If the firewall platform introduces native policy-as-code support that
  subsumes the OPA layer, evaluate whether the OPA gate remains necessary
  or becomes redundant
