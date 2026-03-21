# FirePilot — Threat Model

This document describes the security-relevant attack surfaces of FirePilot,
the threats each surface faces, and how existing architectural controls
mitigate those threats. It is structured around the four constraint layers
defined in [ADR-0003](adr/0003-cicd-pipeline-design-and-policy-validation-toolchain.md)
and the [Architecture Document](architecture.md).

FirePilot modifies network security policy. A compromised or manipulated
rule change can open paths into otherwise segmented networks. The
consequence ceiling is not data exfiltration from FirePilot itself — it
is a firewall misconfiguration that enables lateral movement or
unauthorized access elsewhere in the network.

---

## 1 — System Boundary

```
┌────────────────────────────────────────────────────────────────────────┐
│                        FirePilot Trust Boundary                        │
│                                                                        │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────────────────┐  │
│  │ GitHub Issues │   │ Claude API   │   │ MCP Servers               │  │
│  │ (intake)      │──▶│ (reasoning)  │──▶│  mcp-strata-cloud-manager │  │
│  │               │   │              │   │  mcp-itsm                 │  │
│  └──────────────┘   └──────────────┘   └──────────┬────────────────┘  │
│                                                     │                  │
│  ┌──────────────┐   ┌──────────────┐               │                  │
│  │ Git / GitHub  │   │ CI/CD        │               │                  │
│  │ (source of    │◀──│ (OPA + JSON  │               │                  │
│  │  truth)       │   │  Schema)     │               │                  │
│  └──────────────┘   └──────────────┘               │                  │
└─────────────────────────────────────────────────────┼──────────────────┘
                                                      │
                                               ┌──────▼──────┐
                                               │ Palo Alto   │
                                               │ Strata Cloud│
                                               │ Manager     │
                                               └─────────────┘
```

**External trust boundaries** (data crosses these):

- GitHub Issue → GitHub Actions workflow (user-supplied content enters
  the processing pipeline)
- GitHub Actions → Claude API (issue content + PDF attachments sent to
  Anthropic)
- Claude API → MCP servers (tool calls with parameters derived from
  user input)
- MCP server → SCM API (firewall configuration changes applied to
  production infrastructure)
- MCP server → GitHub API (issue comments and label changes written
  back)

---

## 2 — Threat Catalogue

### T1 — Prompt Injection via Issue Content

**Attack surface**: Layer 2 (Claude system prompt).

**Description**: An attacker submits a GitHub Issue whose body or
attached PDF contains adversarial instructions designed to override
Claude's system prompt. The goal is to make Claude generate a
permissive firewall rule that the attacker's request does not
justify — or to make Claude skip validation steps (zone check,
conflict detection, policy compliance checks).

**Consequence**: A rule is proposed that violates security policy.
If the human approver does not catch it, the rule enters the CI/CD
pipeline.

**Existing mitigations**:

| Control | Layer | How it helps |
|---------|-------|-------------|
| Claude's system prompt mandates a fixed, ordered workflow (Steps 1–7a) with autonomous decision-making within defined policy boundaries (ADR-0014) | 2 | Claude cannot skip steps without violating explicit instructions; autonomous decisions are documented in the analysis comment for audit trail purposes |
| write_config_file validation | 4 | The MCP tool validates YAML structure, schema version, and name/filename consistency before writing — malformed output from Claude is caught at write time, not post-hoc (ADR-0015) |
| OPA policies enforce topology constraints independently | 3 | Even if Claude proposes an internet-to-database rule, Gate 2 blocks it — OPA does not trust Claude (ADR-0003, ADR-0008) |
| JSON Schema validates structural correctness | 3 | Malformed YAML generated under injection is caught at Gate 1 |
| `ticket_id` enforcement is server-side in MCP | 4 | Claude cannot push a configuration without a valid change request, regardless of prompt manipulation (ADR-0004) |
| Human approval gate | 3/4 | PR merge requires human review — Claude never merges its own PR (ADR-0001, ADR-0010) |

**Residual risk**: A sophisticated injection could produce a rule
that is structurally valid, passes OPA policies, and appears
reasonable in the issue comment — but serves an adversarial purpose
(e.g., opening a port that OPA does not specifically block). This
residual risk is inherent to any system where an LLM translates
user intent into configuration. The human approval gate is the
primary control for this class of attack.

With ADR-0014, Claude no longer asks for user confirmation before
generating configuration. This removes a theoretical checkpoint but
does not weaken effective security — in the asynchronous GitHub
Issue workflow, the confirmation was never received (no human in
the loop during processing). The PR review gate remains the
effective control.

**Recommended hardening** (not yet implemented):

- Rate limiting on issue creation (GitHub repository settings or
  GitHub App webhook filtering) to prevent injection brute-forcing
- Anomaly detection: flag rules where Claude's proposed configuration
  diverges significantly from the stated business justification
  (requires a second LLM pass or heuristic comparison)

---

### T2 — Malicious PDF Attachment

**Attack surface**: Layer 2 (Claude context window).

**Description**: A PDF attached to a GitHub Issue contains adversarial
content — either prompt injection text embedded in the document, or
a crafted PDF structure designed to exploit the document parser. The
PDF is base64-encoded and sent to the Claude API as a `document`-type
content block.

**Consequence**: Similar to T1 — Claude may be influenced to generate
an inappropriate rule. Additionally, a malformed PDF could cause the
workflow to fail or behave unexpectedly.

**Existing mitigations**:

| Control | Layer | How it helps |
|---------|-------|-------------|
| 32 MB size limit on PDF attachments | 1/CI | Oversized files are skipped with a warning (ADR-0009, `process-issue.py`) |
| PDF content is processed by the Claude API's document handler, not by custom parsing code | 2 | No custom PDF parser attack surface; Anthropic is responsible for document parsing security |
| All Layer 3 and Layer 4 mitigations from T1 apply | 3/4 | Even if the PDF influences Claude's reasoning, the generated configuration still passes through OPA and human review |

**Residual risk**: If the Claude API's document parser has a
vulnerability, a crafted PDF could influence model behavior in
ways not anticipated by the system prompt. This is outside
FirePilot's control.

---

### T3 — Credential Exposure

**Attack surface**: Layer 4 (MCP servers), CI/CD environment.

**Description**: API credentials (SCM OAuth2 client secret, GitHub
PAT) are leaked through logs, error messages, Git commits, or
environment variable misconfiguration.

**Consequence**: An attacker with the SCM client secret can create
arbitrary firewall rules in the SCM tenant. An attacker with the
GitHub PAT can manipulate issue labels (including setting
`firepilot:approved` on their own request).

**Existing mitigations**:

| Control | Layer | How it helps |
|---------|-------|-------------|
| Credentials injected via environment variables only (ADR-0006) | 4 | No credentials in source code, config files, or Claude's context |
| `.env` files are gitignored; `.env.example` contains only placeholder values | 4 | Prevents accidental commits of real credentials |
| Pre-commit hook requirement for `.env` file detection (ADR-0006) | 4 | Defense-in-depth against gitignore misconfiguration |
| GitHub Actions secret masking | CI | Secret values are automatically redacted in workflow logs |
| SCM token stored in process memory only, never written to disk or logs (ADR-0006) | 4 | Token is ephemeral; no persistent token storage |
| GitHub PAT scoped to `issues: write` on a single repository (ADR-0006) | 4 | Compromised PAT cannot read or modify firewall configuration files |
| Claude never receives credentials; MCP servers are the credential boundary (ADR-0002) | 2/4 | Prompt injection cannot exfiltrate credentials that are not in the context window |
| GitHub secret scanning (repository setting) | CI | Detects accidentally committed credential patterns |

**Residual risk**: The pre-commit hook for `.env` detection is
defined as a requirement in ADR-0006 but must be implemented
(`.pre-commit-config.yaml`). Until implemented, the `.gitignore`
rule is the sole barrier against credential commits.

---

### T4 — CI/CD Pipeline Manipulation

**Attack surface**: Layer 3 (GitHub Actions workflows, OPA policies).

**Description**: An attacker with write access to the repository
modifies a workflow file, OPA policy, or JSON Schema to weaken
validation — then submits a firewall configuration change that
the weakened pipeline accepts.

**Consequence**: A firewall rule that would have been blocked by
Gate 2 or Gate 3 passes validation and is deployed.

**Existing mitigations**:

| Control | Layer | How it helps |
|---------|-------|-------------|
| Branch protection on `main` — all changes require PR review | 3 | Pipeline files cannot be modified without peer review (CLAUDE.md) |
| Workflow files under `ci/` are subject to the same path filter as config files | 3 | Changes to pipeline definitions trigger the validation workflow themselves |
| OPA policy tests (`firepilot_test.rego`) run as part of every validation | 3 | A policy weakening that breaks existing tests is caught before merge |
| Deploy workflow re-runs Gates 1–3 on merge (defense-in-depth) | 3 | Even if a PR is approved with weakened policies, the merge-time re-run uses the policies at that commit — not a cached result |

**Residual risk**: A reviewer who approves both the policy change
and the configuration change in the same PR defeats this control.
Separation of concerns (policy changes in dedicated PRs, config
changes in separate PRs) is a process discipline, not a technical
enforcement.

**Recommended hardening** (not yet implemented):

- CODEOWNERS rule requiring a dedicated security reviewer for
  changes to `ci/policies/`, `ci/schemas/`, and `.github/workflows/`
- Separate branch protection rules for pipeline files vs.
  configuration files (GitHub rulesets)

---

### T5 — MCP Tool Surface Abuse

**Attack surface**: Layer 4 (MCP server tool interface).

**Description**: Claude, whether through prompt injection (T1) or
a reasoning error, calls MCP tools in an unintended sequence or
with parameters that produce a harmful outcome — for example,
calling `push_candidate_config` without a corresponding
`create_security_rule`, or calling `create_security_rule` with
field values that exploit an SCM API parsing vulnerability.

**Consequence**: A firewall configuration change is applied that
does not match the approved change request.

**Existing mitigations**:

| Control | Layer | How it helps |
|---------|-------|-------------|
| `ticket_id` enforcement on all write and push operations (ADR-0004) | 4 | MCP server rejects calls before any SCM interaction if `ticket_id` is missing or empty — this is structural, not prompt-dependent |
| Tool surface is a finite, explicitly defined allowlist (ADR-0002). Write tools include `create_security_rule`, `create_address`, `create_address_group`, `push_candidate_config`, and `write_config_file`. | 4 | Claude cannot call operations that are not exposed as tools |
| `write_config_file` is restricted to OUTPUT_DIR with path traversal validation | 4 | Filename cannot contain path separators or `..`; writes are confined to the ephemeral workflow directory (ADR-0015) |
| Candidate/push separation (ADR-0004) | 4 | Writing a rule to candidate config does not make it live; `push_candidate_config` is a separate, explicit action |
| Server-side tool call logging with `structlog` | 4 | Every tool invocation is logged with tool name, sanitized parameters, outcome, and duration — auditable independently of Claude's output |
| SCM API validates payloads independently (Layer 4 backend) | 4 | Malformed or invalid field values are rejected by the SCM API itself |

**Residual risk**: If the SCM API accepts a payload that is
technically valid but semantically dangerous (e.g., a rule with
`application: ["any"]` and `service: ["any"]` that OPA does not
currently catch), the MCP server will not block it — it is a
pass-through for SCM-accepted payloads. Expanding OPA policy
coverage is the correct mitigation.

---

### T6 — Supply Chain Attack on CI Dependencies

**Attack surface**: Layer 3 (GitHub Actions workflow dependencies).

**Description**: A compromised or typosquatted dependency — an
Actions action (e.g., a tampered `actions/checkout`), a Python
package (e.g., `check-jsonschema`), or the OPA binary — is
pulled during workflow execution and executes malicious code in
the CI environment.

**Consequence**: Arbitrary code execution in the GitHub Actions
runner, which has access to repository secrets and write access
to `main` (in the deploy workflow).

**Existing mitigations**:

| Control | Layer | How it helps |
|---------|-------|-------------|
| Actions are pinned to major versions (`actions/checkout@v4`) | 3 | Reduces risk of unreviewed minor version changes |
| OPA is downloaded from the official release URL | 3 | Known-good source, though not integrity-verified |
| Python packages are installed via `pip` from PyPI | 3 | Standard supply chain, though not hash-pinned |

**Residual risk**: This is the weakest mitigation area in the
current architecture. No dependency is pinned to an exact commit
SHA or verified against a cryptographic hash.

**Recommended hardening** (not yet implemented):

- Pin GitHub Actions to full commit SHAs instead of version tags
  (e.g., `actions/checkout@<sha>` instead of `@v4`)
- Verify the OPA binary checksum after download
- Use `pip install --require-hashes` with a pinned requirements
  file for CI dependencies
- Consider GitHub's dependency review action to flag new or
  changed dependencies in PRs

---

### T7 — Approval Bypass

**Attack surface**: Layer 3 (PR merge permissions).

**Description**: An attacker with write access to the GitHub repository
merges their own firewall change PR without independent security review,
bypassing the intended human oversight gate.

**Consequence**: A firewall configuration change is deployed without
independent security review. Unlike the previous label-based approval
gate, this requires repository write access — a significantly higher
bar than label-management permission.

**Existing mitigations**:

| Control | Layer | How it helps |
|---------|-------|-------------|
| Branch protection on `main` requires PR review — direct pushes are prohibited (CLAUDE.md) | 3 | Self-merge requires a second account with write access to approve the PR |
| The PR is the sole approval artefact; no intermediate label step exists (ADR-0010) | 3 | The attack surface is reduced: no label-management shortcut to PR creation |
| Full audit trail in Git history and issue comments links every merge to a reviewer identity | 3 | Post-incident review can identify unauthorized merges |
| OPA and JSON Schema re-run on merge in `deploy.yml` (Gates 1–3) | 3 | Even a merged-but-malicious rule must pass all policy gates before deployment |

**Residual risk**: GitHub's `required_approving_review_count` setting
controls how many reviewers must approve before merge, but does not
enforce that the reviewer is different from the PR author by default
on all plans. In a production deployment, requiring at least one
approving review from a protected CODEOWNERS team would be necessary.

**Recommended hardening** (not yet implemented):

- CODEOWNERS rule requiring a dedicated security reviewer for all
  changes to `firewall-configs/` — prevents self-merge by the PR author
- Require a minimum number of distinct approvers via branch protection rules

---

### T8 — Configuration Drift

**Attack surface**: Layer 4 (SCM live state), Layer 3 (Git state).

**Description**: A firewall rule is created, modified, or deleted
directly in the SCM GUI or via another automation tool — bypassing
Git and FirePilot entirely. The live firewall state diverges from
the declared state in Git. Additionally, a push failure after merge
(device offline, SCM timeout) leaves rules in Git that are not
enforced on the firewall.

**Consequence**: The Git repository no longer reflects reality.
Security audits based on Git state are inaccurate. New rules
generated by FirePilot may conflict with undocumented live rules.
In the push-failure case, assumed segmentation controls may not be
enforced.

**Existing mitigations**:

| Control | Layer | How it helps |
|---------|-------|-------------|
| `firepilot-managed` tag on all FirePilot rules (ADR-0007) | 1/4 | Provides a scope marker to distinguish FirePilot-managed rules from unmanaged rules; enables targeted drift detection |
| `list_security_rules` called before every rule creation (system prompt Step 4) | 2 | Claude detects conflicts with existing rules — including rules created outside FirePilot |
| Scheduled drift detection workflow (ADR-0010) | 3/4 | Daily comparison of Git state against live SCM state via `mcp-strata-cloud-manager` read tools; discrepancies reported as GitHub Issues with `firepilot:drift-detected` label |
| Push retry mechanism (ADR-0010) | 4 | Failed deployments can be re-triggered via `firepilot:retry-deploy` label without creating a new PR; idempotent rule creation tolerates candidate config that already contains the rules |

**Drift detection coverage**:

| Drift type | Detected | Mechanism |
|------------|----------|-----------|
| Rule modified externally in SCM | Yes | Field-level comparison against Git YAML |
| Rule deleted externally from SCM | Yes | Rule in Git but absent in SCM response |
| Orphan rule in SCM (created with `firepilot-managed` tag outside Git) | Yes | Rule in SCM with tag but absent in Git |
| Rule ordering changed in SCM | Yes | Order comparison against `_rulebase.yaml` manifest |
| Push failure after merge | Yes | `firepilot:failed` label + drift check confirms rule missing from SCM |

**Residual risk**: Detection is not real-time. Drift occurring
between scheduled checks (default: daily) is invisible until the
next run. An operator who modifies a rule and reverts it before
the next check creates undetectable transient drift. Additionally,
if an operator removes the `firepilot-managed` tag from a rule in
SCM, that rule exits FirePilot's detection scope — the tag
convention is not cryptographically enforced.

---

## 3 — Threat-to-Layer Matrix

| Threat | L1 Issue Template | L2 Claude Prompt | L3 CI/CD | L4 MCP/API | Human Gate |
|--------|:-:|:-:|:-:|:-:|:-:|
| T1 Prompt injection | — | ◐ | ● | ● | ● |
| T2 Malicious PDF | ◑ | ◐ | ● | ● | ● |
| T3 Credential exposure | — | ● | ◑ | ● | — |
| T4 Pipeline manipulation | — | — | ◐ | — | ● |
| T5 Tool surface abuse | — | ◐ | — | ● | — |
| T6 Supply chain (CI) | — | — | ○ | — | ◑ |
| T7 Approval bypass | — | — | ◐ | — | ◐ |
| T8 Configuration drift | — | ◑ | ◐ | ● | — |

Legend: ● strong mitigation · ◐ partial mitigation · ◑ weak mitigation · ○ gap · — not applicable

---

## 4 — Prioritised Hardening Roadmap

| Priority | Threat | Action | Effort |
|----------|--------|--------|--------|
| 1 | T6 | Pin Actions to commit SHAs; verify OPA binary checksum; hash-pin Python CI dependencies | Low |
| 2 | T3 | Implement `.pre-commit-config.yaml` with `.env` leak detection (ADR-0006 follow-up) | Low |
| 3 | T7 | Add CODEOWNERS rule for `firewall-configs/` to prevent self-merge | Low |
| 4 | T4 | Add CODEOWNERS rule for `ci/`, `.github/workflows/`, and `ci/policies/` | Low |
| 5 | T8 | ~~Design drift detection mechanism~~ — Implemented (ADR-0011). Remaining: verify candidate config persistence with live SCM tenant; evaluate real-time detection if SCM adds event stream support | Low |
| 6 | T1/T2 | Explore secondary validation pass for prompt injection detection | High |

---

## 5 — Assumptions

- GitHub's infrastructure (Actions runners, API, secret storage) is
  trusted. Threats to GitHub itself are out of scope.
- Anthropic's Claude API processes input securely and does not leak
  context across conversations or tenants. Threats to the Claude API
  infrastructure are out of scope.
- The Palo Alto SCM API enforces its own authentication and
  authorization correctly. Threats to SCM's internal security are
  out of scope.
- The SCM service account used by FirePilot is scoped to the minimum
  required permissions as defined in ADR-0004. Over-provisioned
  service accounts are an operator error, not a FirePilot design flaw.

---

## 6 — Review Trigger

This threat model must be revisited when:

- A new external system integration is added (new MCP server = new
  attack surface)
- A prompt injection incident occurs in FirePilot or a comparable
  MCP-based system
- The SCM API introduces new operations that expand the tool surface
- GitHub changes its permissions model for labels, Actions, or secrets
- A new constraint layer is added or an existing layer is removed
- FirePilot transitions from portfolio/demo use to production deployment
