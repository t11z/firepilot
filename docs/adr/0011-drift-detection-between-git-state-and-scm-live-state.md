# ADR-0011: Drift Detection Between Git State and SCM Live State

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0011                                                              |
| Title         | Drift Detection Between Git State and SCM Live State                  |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-20                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

ADR-0001 establishes Git as the single source of truth for firewall
configuration. ADR-0007 defines the `firepilot-managed` tag as the
scope boundary between FirePilot-managed rules and rules managed by
other means. The threat model documents configuration drift as T8 —
currently the weakest mitigation area in the architecture.

Drift occurs when the live SCM state diverges from the declared Git
state. Three root causes exist:

1. **Push failure after merge.** A PR is merged to `main`, Gate 4
   creates the rule in SCM candidate config, but the push to running
   config fails (device offline, timeout, SCM error). Git says the
   rule exists; the firewall does not enforce it.

2. **Out-of-band modification.** An operator modifies or deletes a
   `firepilot-managed` rule directly in the SCM GUI or via another
   automation tool, bypassing Git entirely. The live firewall state
   no longer matches the declared configuration.

3. **Out-of-band creation.** An operator creates a rule in SCM with
   the `firepilot-managed` tag that does not exist in Git. This
   corrupts the scope boundary and may conflict with future
   FirePilot deployments.

The consequence ceiling is not a data integrity issue within
FirePilot — it is a **false sense of security**. Auditors,
operators, and automated systems that trust the Git state as
authoritative will make decisions based on a configuration that
does not reflect reality. In a network security context, this
means assumed segmentation controls may not be enforced.

The current architecture has no mechanism to detect, report, or
resolve any of these drift scenarios. Claude's Step 4 (conflict
check before rule creation) provides incidental detection when a
new change request happens to touch the same folder — but this is
neither systematic nor timely.

In scope: detection mechanism, comparison logic, reporting,
alerting, and the push-retry workflow for post-merge failures.

Out of scope: automatic remediation that modifies SCM state
without human approval (this would violate the human-gate
principle established in ADR-0001). Address object and address
group drift (v1 scope is security rules only). Zone mapping drift
(noted in ADR-0008 as a separate concern that should be included
in Gate 3 dry-run validation, not in this periodic check).

---

## Decision

We will implement a scheduled drift detection workflow as a GitHub
Actions cron job that compares the Git-declared firewall configuration
against the live SCM state via `mcp-strata-cloud-manager` read tools.
Drift is reported as a GitHub Issue with structured details. Failed
deployments can be retried via a `firepilot:retry-deploy` label on
the original change request issue.

---

## Considered Alternatives

#### Option A: No automated drift detection — rely on manual inspection

- **Description**: Operators periodically compare SCM state against
  Git by running `list_security_rules` manually or during change
  request processing
- **Pros**: Zero implementation cost; no additional workflow
  complexity
- **Cons**: Drift is invisible between change requests; detection
  depends on human discipline; does not address push failures at
  all; leaves T8 as a documented gap indefinitely; incompatible
  with the auditability standard established by the rest of the
  architecture

#### Option B: Real-time webhook-based detection

- **Description**: SCM emits events (webhooks or syslog) on rule
  changes; a listener compares each change against Git state in
  real time
- **Pros**: Near-instant detection; minimal latency between drift
  and alert
- **Cons**: SCM does not expose a webhook or event stream for
  configuration changes in the standard API surface; would require
  syslog integration or a polling-based approximation that
  resembles Option C anyway; adds always-on infrastructure,
  violating the portfolio constraint

#### Option C: Scheduled comparison workflow *(chosen)*

- **Description**: A GitHub Actions cron job runs periodically,
  queries SCM via `mcp-strata-cloud-manager`, compares against
  Git state, and reports discrepancies as a GitHub Issue
- **Pros**: No always-on infrastructure; uses existing MCP tools
  and GitHub Actions; detection latency is bounded by schedule
  interval; consistent with the project's operational model;
  externally reviewable
- **Cons**: Not real-time — drift between check intervals is
  undetected; adds a scheduled workflow that consumes GitHub
  Actions minutes; SCM API rate limits may constrain check
  frequency for large rulebases

#### Option D: Drift detection as a CI/CD gate (pre-merge check)

- **Description**: Gate 3 (dry-run validation) is extended to
  compare the full Git state against SCM, not just the rules in
  the current PR
- **Pros**: Drift is detected before every merge; no separate
  workflow needed
- **Cons**: Increases Gate 3 execution time significantly for
  large rulebases; conflates two concerns (PR validation vs.
  global state reconciliation); does not detect drift between
  PRs; does not address push failures

---

## Rationale

Option A is rejected because it leaves the architecture's most
significant residual risk (T8) permanently unaddressed. The entire
system is built on the premise that Git is authoritative — without
verification, that premise is an assertion, not a fact.

Option B would be ideal but is not feasible without SCM-side event
infrastructure that does not exist in the standard API surface. A
polling approximation converges on Option C without the clarity of a
dedicated workflow.

Option D is attractive but misplaced. Drift detection is a global
state concern, not a per-PR concern. Running a full state comparison
on every PR is wasteful and slow. It also fails to detect drift
between PRs — the most likely window for out-of-band changes.

Option C provides bounded detection latency, uses only existing
infrastructure (GitHub Actions + MCP tools), and cleanly separates
drift detection from the deployment pipeline. The scheduled interval
is configurable; daily is the recommended default for the portfolio
context, with the option to increase frequency in production.

---

## Detection Mechanism

### Comparison Logic

The drift detection script connects to `mcp-strata-cloud-manager`
via MCP stdio (same pattern as `gate3-dry-run.py`) and executes the
following comparison for each `{folder}/{position}/` directory in
`firewall-configs/`:

**Step 1: Fetch live rules.**
Call `list_security_rules(folder, position)`. Filter the response
to rules where `tag` contains `firepilot-managed`.

**Step 2: Load Git rules.**
Read all rule YAML files from `firewall-configs/{folder}/{position}/`
and the `_rulebase.yaml` manifest.

**Step 3: Compare by rule name.**

| Git state | SCM state | Classification |
|-----------|-----------|----------------|
| Rule exists | Rule exists with matching fields | No drift |
| Rule exists | Rule exists with different fields | **Modified externally** |
| Rule exists | Rule does not exist | **Missing from SCM** (failed deploy or deleted externally) |
| Rule does not exist | Rule exists with `firepilot-managed` tag | **Orphan in SCM** (created externally with FirePilot tag) |

**Step 4: Compare ordering.**
If the set of rules matches but the ordering in SCM (determined by
rule position in the `list_security_rules` response) differs from
the `rule_order` in `_rulebase.yaml`, classify as **order drift**.

**Field comparison scope**: The following fields are compared. Fields
not in this list are ignored (they may be set by SCM defaults or
internal state and are not part of the declared configuration):
`name`, `action`, `from`, `to`, `source`, `source_user`,
`destination`, `service`, `application`, `category`, `disabled`,
`description`, `tag`, `negate_source`, `negate_destination`,
`log_start`, `log_end`.

### Reporting

Drift is reported as a GitHub Issue with the label
`firepilot:drift-detected`. The issue body contains:

- Timestamp of the check
- Summary: number of rules checked, number of discrepancies
- For each discrepancy: rule name, folder, position, drift type,
  and a field-level diff for modified rules
- Link to the most recent successful drift check (if available)

If a `firepilot:drift-detected` issue already exists and is open,
the workflow appends a comment with the new check results rather
than creating a duplicate issue.

### Schedule

The workflow runs on a cron schedule. Recommended default:
`0 6 * * *` (daily at 06:00 UTC). The schedule is configurable via
a repository variable `DRIFT_CHECK_SCHEDULE`.

In `demo` mode (`FIREPILOT_ENV=demo`): the workflow runs the
comparison against demo fixtures and always reports zero drift. This
validates the comparison logic without live infrastructure.

---

## Push Retry Mechanism

### Problem

When Gate 4 fails after `create_security_rule` succeeds but
`push_candidate_config` fails (device offline, timeout), the rules
exist in SCM candidate config but are not live. The Git state shows
a merged configuration that is not enforced.

### Mechanism

A new label `firepilot:retry-deploy` is added to the label
convention. When applied to a change request issue (the original
issue that triggered the deployment), a GitHub Actions workflow
triggers and:

1. Reads the issue to extract the associated commit SHA or branch
2. Identifies the `firewall-configs/` files changed in that commit
3. Runs Gate 4 (`gate4-deploy.py`) with the same `TICKET_ID`
4. If successful: removes `firepilot:retry-deploy`, sets
   `firepilot:deployed`, posts a comment
5. If failed again: posts a comment with the error, leaves
   `firepilot:retry-deploy` for manual investigation

This does not re-run Gates 1–3 (the configuration was already
validated before merge). It only re-attempts the SCM push.

### Candidate Config Staleness

**Assumption**: SCM candidate config persists across sessions.
Rules written by `create_security_rule` remain in candidate config
until pushed or explicitly discarded. If this assumption is
incorrect (e.g., SCM auto-discards candidate config after a
timeout), the retry mechanism must re-create the rules before
pushing. This must be verified during integration testing.

---

## Consequences

- **Positive**: Drift between Git and SCM is detected within the
  schedule interval, closing the T8 gap documented in the threat
  model
- **Positive**: Push failures are recoverable without creating a
  new PR — reducing operational friction for transient failures
- **Positive**: The drift report as a GitHub Issue integrates into
  the existing notification and triage workflow
- **Positive**: The `firepilot-managed` tag scope boundary
  (ADR-0007) is actively verified, not just assumed
- **Positive**: Demo mode validates the comparison logic without
  live infrastructure, consistent with the portfolio constraint
- **Negative**: Scheduled checks consume GitHub Actions minutes;
  at daily frequency this is negligible, but higher frequencies
  (hourly) accumulate
- **Negative**: Detection is not real-time; drift occurring minutes
  after a check is invisible until the next scheduled run
- **Negative**: The push retry mechanism adds a workflow and a
  label to the operational surface; operators must understand when
  to apply `firepilot:retry-deploy` vs. investigating the root
  cause
- **Follow-up required**: Implement the drift detection script
  (`ci/scripts/drift-check.py`) using the `mcp_connect.py` shared
  utility
- **Follow-up required**: Create the GitHub Actions workflow
  (`.github/workflows/drift-check.yml`) with cron trigger
- **Follow-up required**: Create the retry workflow
  (`.github/workflows/retry-deploy.yml`) triggered by the
  `firepilot:retry-deploy` label
- **Follow-up required**: Pre-create the `firepilot:drift-detected`
  and `firepilot:retry-deploy` labels in the repository
- **Follow-up required**: Update `docs/threat-model.md` to upgrade
  T8 mitigation status from ◑ (weak) to ◐ (partial) or ● (strong)
  once drift detection is operational
- **Follow-up required**: Verify candidate config persistence
  behaviour during integration testing with a real SCM tenant

---

## Compliance & Security Considerations

- **SOC 2 CC6.1 / CC8.1**: Drift detection provides continuous
  assurance that the declared configuration matches the enforced
  configuration. Without it, the Git-as-source-of-truth claim
  (ADR-0001) is unverifiable between deployments
- **ISO 27001 A.12.1.2**: Drift detection is the monitoring
  counterpart to the change management controls enforced by the
  CI/CD pipeline. Change management without monitoring is
  incomplete
- **Audit Trail**: Every drift check result is recorded — either
  as a new issue or as a comment on an existing drift issue. The
  complete history of drift checks is visible in the repository's
  issue timeline
- **No Automatic Remediation**: Drift detection reports only. It
  does not modify SCM state or Git state. Any remediation action
  requires human decision and follows the standard change request
  flow (ADR-0001) or the push retry mechanism defined above. This
  preserves the separation of duties principle

---

## Review Trigger

- If drift detection consistently reports zero discrepancies over
  an extended period (>90 days), evaluate whether the check
  frequency can be reduced to conserve Actions minutes
- If out-of-band SCM changes are frequent (>1 per week), consider
  increasing check frequency to hourly and evaluate whether the
  `firepilot-managed` tag is being respected by all operators
- If SCM introduces a configuration change event stream (webhook
  or audit log API), re-evaluate Option B as a replacement for
  or complement to scheduled checks
- If the rulebase grows beyond 500 `firepilot-managed` rules,
  evaluate whether the comparison logic needs pagination
  optimization or incremental comparison (comparing only rules
  modified since the last check)
- If candidate config persistence proves unreliable (auto-discard
  after timeout), the push retry mechanism must be extended to
  re-create rules before pushing — supersede this ADR accordingly
