## Quick start — local validation

```bash
# Check that required tools are installed
make check-deps

# Run the full validation pipeline (Gates 1–3)
make validate

# Run OPA policy tests only
make test-policies
```

---

# FirePilot CI Pipeline

Reference: [ADR-0003 — CI/CD Pipeline Design and Policy Validation Toolchain](../docs/adr/0003-cicd-pipeline-design-and-policy-validation-toolchain.md)

---

## Pipeline Architecture

Three workflow files implement the pipeline:

| Workflow | Trigger | Gates |
|---|---|---|
| `.github/workflows/validate.yml` | Pull request targeting `main` | Gates 1–3 |
| `.github/workflows/deploy.yml` | Push to `main` | Gates 1–3 (re-validation) + Gate 4 |
| `.github/workflows/retry-deploy.yml` | Issue labeled `firepilot:retry-deploy` | Push retry (no validation re-run) |

Gates execute sequentially. A failure at any gate blocks all subsequent gates.
The deploy workflow re-runs Gates 1–3 before Gate 4 as a defense-in-depth measure —
ensuring that nothing bypasses validation between PR approval and merge.

Path filters: both workflows trigger only when `firewall-configs/**` or `ci/**` changes.

---

## Gate Descriptions

### Gate 1 — Schema Validation

**Tool**: `check-jsonschema`

Validates the structural correctness of all configuration files against their JSON Schemas:

- `firepilot.yaml` → `ci/schemas/firepilot-config.schema.json`
- `firewall-configs/{folder}/{position}/_rulebase.yaml` → `ci/schemas/rulebase-manifest.schema.json`
- `firewall-configs/{folder}/{position}/*.yaml` (rule files) → `ci/schemas/security-rule.schema.json`

All errors across all directories are collected before failing, so a single run
reports the full set of violations rather than stopping at the first.

### Gate 2 — OPA Policy Evaluation

**Tool**: `opa eval`

Evaluates the `data.firepilot.validate.deny` rule in `ci/policies/firepilot.rego`
against each `{folder}/{position}/` directory. The OPA input is assembled by
`ci/scripts/build-opa-input.py`, which reads the manifest, rule files, and
(when present) zone topology from `firepilot.yaml`.

A non-empty `deny` set means the configuration violates at least one declared
security policy. The violation message is printed and the gate fails.

### Gate 3 — Dry-Run Validation

**Script**: `ci/scripts/gate3-dry-run.sh` → delegates to `ci/scripts/gate3-dry-run.py` in live mode

In `live` mode:
- Connects to `mcp-strata-cloud-manager` via MCP stdio subprocess
- For each rule file in `firewall-configs/{folder}/{position}/`:
  - Calls `list_security_zones` to verify every zone in `from`/`to` exists in SCM
  - Calls `list_addresses` to verify address objects in `source`/`destination` exist
    (skips values that are `any` or CIDR notation — those are not address objects)
  - Calls `list_security_rules` to detect name conflicts with existing rules
- Does NOT write anything — read-only validation only
- Exits 0 if all checks pass; exits 1 and reports all violations if any found

In `demo` mode: mock pass — MCP server not required.

Required environment variables (live mode):
- `SCM_CLIENT_ID`, `SCM_CLIENT_SECRET`, `SCM_TSG_ID` — passed to MCP server subprocess

### Gate 4 — Deployment

**Script**: `ci/scripts/gate4-deploy.sh` → delegates to `ci/scripts/gate4-deploy.py` in live mode

In `live` mode:
1. Connects to both `mcp-strata-cloud-manager` and `mcp-itsm` via MCP stdio subprocesses
2. For each rule in `firewall-configs/{folder}/{position}/` (manifest order):
   - Calls `create_security_rule` to write the rule to SCM candidate config
   - Calls `add_audit_comment` on the ITSM ticket with event `candidate_written`
3. Calls `push_candidate_config` for all unique folders
4. Calls `add_audit_comment` with event `push_initiated`
5. Polls `get_job_status` every 10 seconds until terminal state
   (`FIN`, `PUSHFAIL`, `PUSHABORT`, `PUSHTIMEOUT`)
6. On `result_str=OK`: records `push_succeeded`, sets ITSM status to `deployed`. Exit 0.
7. On any other result: records `push_failed`, sets ITSM status to `failed`. Exit 1.

Requires `TICKET_ID` environment variable (the GitHub issue number from the originating
change request — extracted from the merge commit branch name in `deploy.yml`).

On success, the deploy workflow tags the commit:
`deploy-{YYYYMMDDTHHMMSSZ}-{short-sha}`

In `demo` mode: runs gate4-deploy.py with MCP mock fixtures — creates rules in demo store, simulates push, and records ITSM events. No credentials required.

Required environment variables (live mode):
- `TICKET_ID` — ITSM ticket reference (GitHub issue number)
- `SCM_CLIENT_ID`, `SCM_CLIENT_SECRET`, `SCM_TSG_ID` — SCM credentials
- `ITSM_GITHUB_TOKEN` — GitHub App installation token (generated at workflow runtime)
- `ITSM_GITHUB_REPO` — target repository in `owner/repo` format (derived from `github.repository`)
- `SCM_PUSH_TIMEOUT_SECONDS` — push job poll timeout in seconds (default: 300)

---

## Push Retry

Reference: [ADR-0011 — Drift Detection Between Git State and SCM Live State](../docs/adr/0011-drift-detection-between-git-state-and-scm-live-state.md)

---

### When to use `firepilot:retry-deploy`

When Gate 4 runs after a merge to `main` and the push step fails (device
offline, SCM timeout, or SCM API error), the configuration rules exist in Git
but are not live. The issue is set to `firepilot:failed`.

Apply the `firepilot:retry-deploy` label to the **original change request issue**
to re-trigger the deployment without creating a new PR. Gates 1–3 are **not**
re-run — the configuration was already validated before the original merge.

Do not create a new PR or issue. The retry workflow reads the merged configuration
from the current state of `firewall-configs/` and re-attempts the push.

### What the retry workflow does

The retry workflow (`ci/scripts/retry-deploy.py`) implements Strategy B with
conflict tolerance:

1. **Re-creates each security rule** from `firewall-configs/` in manifest order
   by calling `create_security_rule` on the SCM MCP server.
2. **Tolerates E006 (Name Not Unique) conflicts** — if a rule already exists in
   the candidate config from the failed Gate 4 run, the E006 error is treated as
   success. Any other error aborts and records failure via ITSM.
3. **Pushes the candidate config** for all affected folders via
   `push_candidate_config`.
4. **Polls `get_job_status`** every 10 seconds until the job reaches a terminal
   state (`FIN`, `PUSHFAIL`, `PUSHABORT`, `PUSHTIMEOUT`).
5. On `result_str=OK`: records `push_succeeded`, sets ITSM status to `deployed`,
   removes `firepilot:retry-deploy` and `firepilot:failed` labels, adds
   `firepilot:deployed`. Exit 0.
6. On any other result: records `push_failed`, sets ITSM status to `failed`,
   leaves `firepilot:retry-deploy` for manual investigation. Exit 1.

This approach is idempotent: the retry succeeds whether or not the failed Gate 4
run had written rules to candidate config before failing.

### How to trigger a retry

```bash
# Using the GitHub CLI
gh issue edit <issue-number> --add-label "firepilot:retry-deploy"
```

Or apply the label via the GitHub web interface on the original change request issue.

### How to monitor the retry workflow run

Navigate to **Actions → Retry Failed Deployment** in the repository. Each run
corresponds to a label event on an issue. The issue will receive a comment
indicating success or failure, with a link to the workflow run on failure.

### Label setup (one-time operator step)

The `firepilot:retry-deploy` label must be created in the repository before the
workflow can use it:

```bash
gh label create "firepilot:retry-deploy" --color "E4E669" --description "Re-trigger deployment for a failed Gate 4 push"
```

No credentials appear in workflow logs or issue comments — SCM credentials are
passed only via environment variables to the MCP subprocess (ADR-0006).

---

## Running Locally

### Install dependencies

```bash
pip install check-jsonschema

# Install OPA (Linux)
curl -L -o /usr/local/bin/opa \
  https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static
chmod +x /usr/local/bin/opa
```

### Run all validation gates (1–3)

```bash
FIREPILOT_ENV=demo bash ci/scripts/validate-all.sh
```

### Run OPA policy unit tests only

```bash
opa test ci/policies/ -v
```

### Run individual gates

```bash
# Gate 3 mock
FIREPILOT_ENV=demo bash ci/scripts/gate3-dry-run.sh

# Gate 4 mock
FIREPILOT_ENV=demo bash ci/scripts/gate4-deploy.sh
```

---

## Environment Variables

| Variable | Values | Description |
|---|---|---|
| `FIREPILOT_ENV` | `demo` (default), `live` | Controls mock vs. live execution for Gates 3 and 4 |

**Live mode secrets** (injected from repository secrets when MCP servers are integrated —
see ADR-0006 for credential management design):

- `SCM_CLIENT_ID` — Palo Alto SCM OAuth client ID
- `SCM_CLIENT_SECRET` — Palo Alto SCM OAuth client secret
- `SCM_TSG_ID` — Palo Alto SCM tenant service group ID
- `APP_ID` — GitHub App ID; used to generate `ITSM_GITHUB_TOKEN` at workflow runtime
- `APP_PRIVATE_KEY` — PEM private key for the GitHub App; used alongside `APP_ID`

`ITSM_GITHUB_TOKEN` is generated at runtime by `actions/create-github-app-token@v1`
using `APP_ID` and `APP_PRIVATE_KEY`. It is never stored as a repository secret.
`ITSM_GITHUB_REPO` is derived from `github.repository` in each workflow — it is
not a repository secret.

Do not set these values in workflow files. SCM credentials are referenced via
`${{ secrets.NAME }}` syntax; the ITSM token is generated per-run.

---

## File Layout

```
ci/
├── README.md                    # This file
├── schemas/
│   ├── rulebase-manifest.schema.json   # Schema for _rulebase.yaml
│   ├── security-rule.schema.json       # Schema for individual rule files
│   └── firepilot-config.schema.json    # Schema for firepilot.yaml (ADR-0012)
├── policies/
│   ├── firepilot.rego           # OPA policy definitions
│   └── firepilot_test.rego      # OPA policy unit tests
├── scripts/
│   ├── build-opa-input.py       # Assembles OPA input JSON from a config directory
│   ├── config_discovery.py      # Shared config discovery helpers (discover_rule_dirs, load_rule_files)
│   ├── deploy_common.py         # Shared deployment logic (create_rules_from_config, push_and_poll)
│   ├── drift-check.py           # Drift detection: compares Git config against live SCM state
│   ├── mcp_connect.py           # Shared MCP server connection helper
│   ├── process-issue.py         # Claude agentic loop for firewall change requests
│   ├── retry-deploy.py          # Push retry: re-create rules + push, with E006 conflict tolerance
│   ├── validate-all.sh          # Orchestrates Gates 1–3
│   ├── gate3-dry-run.sh         # Gate 3: shell entry point (demo/live dispatch)
│   ├── gate3-dry-run.py         # Gate 3: live validation via mcp-strata-cloud-manager
│   ├── gate4-deploy.sh          # Gate 4: shell entry point (demo/live dispatch)
│   ├── gate4-deploy.py          # Gate 4: live deployment via MCP servers
│   ├── test_drift_check.py      # Pytest tests for drift-check.py
│   ├── test_gate3_dry_run.py    # Pytest tests for gate3-dry-run.py
│   ├── test_gate4_deploy.py     # Pytest tests for gate4-deploy.py
│   └── test_retry_deploy.py     # Pytest tests for retry-deploy.py
└── fixtures/
    ├── firewall-configs/        # Valid fixture set (mirrors production layout)
    └── invalid/                 # Invalid fixtures for OPA policy testing
```

---

## Testing the Processing-to-PR Workflow

This section describes how to manually verify the end-to-end flow from issue
creation to PR, implemented by `.github/workflows/process-firewall-request.yml`.

**Prerequisites**:

- A GitHub repository with the `firepilot:pending` and related labels
  pre-created (see ADR-0005).
- The repository's Actions must be enabled and the workflow file committed to
  the default branch.
- You need issue-creation permission on the repository and an
  `ANTHROPIC_API_KEY` secret configured.

---

### Step-by-step manual test

**Step 1 — Create a firewall change request issue**

Open a new GitHub Issue using the `firewall-change-request` template.  Fill in
all required fields.  The template automatically applies the `firepilot:pending`
label on creation, which triggers `.github/workflows/process-firewall-request.yml`.

**Step 2 — Observe the processing workflow run**

Navigate to **Actions → Process Firewall Change Request**.  The workflow runs
Claude's full agentic analysis loop against both MCP servers in demo mode.

If Claude writes configuration files to the output directory via
`write_config_file`, the workflow continues through subsequent steps: computing
a feature branch name, checking for existing branches/PRs (idempotency guard),
committing all generated rule files and the rulebase manifest atomically,
pushing the branch, opening a PR, and posting a comment linking to the PR.
For document-based requests, Claude extracts rules from attached PDFs
autonomously. Multiple rule files and a rulebase manifest are committed in a
single PR.

If Claude rejects the request, only an issue comment is posted and
`firepilot:rejected` is applied — no branch or PR is created.

**Step 3 — Verify the PR**

A PR titled `[FirePilot] {rule-name} — Issue #{n}` should appear targeting
`main`.  The PR body links to the originating issue and summarises the rule
(source zone → destination zone, action, services).

**Step 4 — Verify CI validation triggers**

Because the PR modifies files under `firewall-configs/**`, the
`.github/workflows/validate.yml` workflow triggers automatically.  Confirm
that Gates 1–3 run without manual intervention:

- Gate 1: JSON Schema validation
- Gate 2: OPA policy evaluation
- Gate 3: SCM dry-run (mock in demo mode)

**Step 5 — Verify idempotency**

Close and reopen the issue.  The workflow should detect the existing branch and
PR, post a comment on the issue linking to the existing PR, and exit
successfully without creating duplicates.

---

## Drift Detection

Reference: [ADR-0011 — Drift Detection Between Git State and SCM Live State](../docs/adr/0011-drift-detection-between-git-state-and-scm-live-state.md)

---

### What it checks

The drift detection workflow compares every firewall rule in Git (`firewall-configs/`)
against the live state returned by `mcp-strata-cloud-manager`. It only examines rules
tagged `firepilot-managed` — rules managed outside FirePilot are ignored.

Four drift types are reported:

| Drift type | Meaning |
|---|---|
| `modified_externally` | Rule exists in both Git and SCM but fields differ |
| `missing_from_scm` | Rule is in Git but not found in SCM |
| `orphan_in_scm` | Rule is in SCM (tagged `firepilot-managed`) but not in Git |
| `order_drift` | Same rules exist in both but their rulebase order differs |

The output is a JSON report on stdout (see example below) and a human-readable
summary on stderr.

### Schedule

The workflow runs **daily at 06:00 UTC** via a cron schedule. The cron expression
is defined in `.github/workflows/drift-check.yml` and can be overridden by editing
that file directly. The mode (`demo` or `live`) is controlled by the
`FIREPILOT_ENV` repository variable (defaults to `demo`).

### How to run manually

**Via GitHub UI:**

Navigate to **Actions → Drift Detection → Run workflow** and click **Run workflow**.

**Via CLI (`gh`):**

```bash
gh workflow run drift-check.yml
```

**Locally (demo mode — no credentials required):**

```bash
pip install PyYAML ./mcp-servers/mcp-strata-cloud-manager
FIREPILOT_ENV=demo python ci/scripts/drift-check.py --config-dir firewall-configs/
```

The script exits 0 (no drift), 1 (drift detected), or 2 (error).

**Locally (live mode):**

```bash
export FIREPILOT_ENV=live
export SCM_CLIENT_ID=...
export SCM_CLIENT_SECRET=...
export SCM_TSG_ID=...
python ci/scripts/drift-check.py --config-dir firewall-configs/
```

### How to read the drift report

The report is written as JSON to stdout and saved as `drift-report.json` in the
workflow run. Example structure:

```json
{
  "timestamp": "2026-03-20T06:00:00Z",
  "mode": "live",
  "folders_checked": [
    {
      "folder": "shared",
      "position": "pre",
      "git_rule_count": 3,
      "scm_rule_count": 3,
      "discrepancies": [
        {
          "rule_name": "allow-web-to-app",
          "drift_type": "modified_externally",
          "field_diffs": {
            "action": {"git": "allow", "scm": "deny"},
            "description": {"git": "Allow web traffic", "scm": "Modified by admin"}
          }
        }
      ]
    }
  ],
  "total_discrepancies": 1,
  "result": "DRIFT_DETECTED"
}
```

`result` is one of `NO_DRIFT`, `DRIFT_DETECTED`, or `ERROR`.

### `firepilot:drift-detected` label

When drift is detected, the workflow creates or updates a GitHub Issue labelled
`firepilot:drift-detected`. If an open issue with this label already exists, the
new report is appended as a comment rather than creating a duplicate.

The `firepilot:drift-detected` label must be created in the repository before the
workflow can use it. This is a one-time operator setup step:

```bash
gh label create "firepilot:drift-detected" --color "D93F0B" --description "Drift detected between Git config and live SCM state"
```

No credentials appear in the drift report JSON or in workflow logs — rule names,
field values, and drift types are logged, but SCM credentials are passed only via
environment variables to the MCP subprocess (ADR-0006).

---

## Adding a New OPA Policy

1. Add the deny rule to `ci/policies/firepilot.rego`:
   ```rego
   deny[msg] {
     # condition
     msg := "Human-readable violation description"
   }
   ```

2. Add a test to `ci/policies/firepilot_test.rego`:
   ```rego
   test_my_new_policy_deny {
     count(data.firepilot.validate.deny) > 0 with input as { ... }
   }

   test_my_new_policy_allow {
     count(data.firepilot.validate.deny) == 0 with input as { ... }
   }
   ```

3. Add an invalid fixture under `ci/fixtures/invalid/` that triggers the new rule,
   so the test exercises a real YAML file rather than only inline input.

4. Verify: `opa test ci/policies/ -v` — all tests must pass.
