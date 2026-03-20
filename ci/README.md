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

Two workflow files implement the pipeline:

| Workflow | Trigger | Gates |
|---|---|---|
| `.github/workflows/validate.yml` | Pull request targeting `main` | Gates 1–3 |
| `.github/workflows/deploy.yml` | Push to `main` | Gates 1–3 (re-validation) + Gate 4 |

Gates execute sequentially. A failure at any gate blocks all subsequent gates.
The deploy workflow re-runs Gates 1–3 before Gate 4 as a defense-in-depth measure —
ensuring that nothing bypasses validation between PR approval and merge.

Path filters: both workflows trigger only when `firewall-configs/**` or `ci/**` changes.

---

## Gate Descriptions

### Gate 1 — Schema Validation

**Tool**: `check-jsonschema`

Validates the structural correctness of all configuration files against their JSON Schemas:

- `firewall-configs/zones.yaml` → `ci/schemas/zone-mapping.schema.json`
- `firewall-configs/{folder}/{position}/_rulebase.yaml` → `ci/schemas/rulebase-manifest.schema.json`
- `firewall-configs/{folder}/{position}/*.yaml` (rule files) → `ci/schemas/security-rule.schema.json`

All errors across all directories are collected before failing, so a single run
reports the full set of violations rather than stopping at the first.

### Gate 2 — OPA Policy Evaluation

**Tool**: `opa eval`

Evaluates the `data.firepilot.validate.deny` rule in `ci/policies/firepilot.rego`
against each `{folder}/{position}/` directory. The OPA input is assembled by
`ci/scripts/build-opa-input.py`, which reads the manifest, rule files, and
(when present) zone topology from `zones.yaml`.

A non-empty `deny` set means the configuration violates at least one declared
security policy. The violation message is printed and the gate fails.

### Gate 3 — Dry-Run Validation

**Script**: `ci/scripts/gate3-dry-run.sh`

In `live` mode: calls `mcp-strata-cloud-manager` in validation mode to confirm
the candidate configuration is accepted by the Palo Alto SCM API schema before
any changes are committed.

In `demo` mode: mock pass — MCP server not required.

### Gate 4 — Deployment

**Script**: `ci/scripts/gate4-deploy.sh`

In `live` mode:
1. Calls `mcp-strata-cloud-manager` to push the candidate configuration
2. Creates a change request via `mcp-itsm`
3. Records the deployment outcome on the change request

On success, the deploy workflow tags the commit:
`deploy-{YYYYMMDDTHHMMSSZ}-{short-sha}`

In `demo` mode: mock pass with simulated deployment log — no credentials required.

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
- `ITSM_GITHUB_TOKEN` — ITSM integration token
- `ITSM_GITHUB_REPO` — ITSM target repository

Do not set these values in workflow files. They are referenced via `${{ secrets.NAME }}` syntax.

---

## File Layout

```
ci/
├── README.md                    # This file
├── schemas/
│   ├── rulebase-manifest.schema.json   # Schema for _rulebase.yaml
│   ├── security-rule.schema.json       # Schema for individual rule files
│   └── zone-mapping.schema.json        # Schema for zones.yaml
├── policies/
│   ├── firepilot.rego           # OPA policy definitions
│   └── firepilot_test.rego      # OPA policy unit tests
├── scripts/
│   ├── build-opa-input.py       # Assembles OPA input JSON from a config directory
│   ├── validate-all.sh          # Orchestrates Gates 1–3
│   ├── gate3-dry-run.sh         # Gate 3: dry-run validation (mock in v1)
│   └── gate4-deploy.sh          # Gate 4: deployment (mock in v1)
└── fixtures/
    ├── firewall-configs/        # Valid fixture set (mirrors production layout)
    └── invalid/                 # Invalid fixtures for OPA policy testing
```

---

## Testing the Approval-to-PR Workflow

This section describes how to manually verify the end-to-end approval-to-PR
path implemented by `.github/workflows/approve-and-commit.yml`.

**Prerequisites**:

- A GitHub repository with the `firepilot:pending`, `firepilot:approved`, and
  related labels pre-created (see ADR-0005).
- The repository's Actions must be enabled and the workflow file committed to
  the default branch.
- You need issue-creation permission and label-management permission on the
  repository.

---

### Step-by-step manual test

**Step 1 — Create a firewall change request issue**

Open a new GitHub Issue using the `firewall-change-request` template.  Fill in
all required fields.  The template automatically applies the `firepilot:pending`
label on creation.

**Step 2 — Add a YAML proposal comment**

Manually add a comment to the issue containing a fenced YAML code block that
represents a valid FirePilot security rule.  The comment must include a
` ```yaml ` block with at minimum: `schema_version`, `name`, `action`, `from`,
`to`, `source`, `source_user`, `destination`, `service`, `application`,
`category`, and `tag` (including `"firepilot-managed"`).

Example comment body:

~~~markdown
FirePilot analysis complete. Proposed configuration:

```yaml
schema_version: 1
name: "allow-api-to-cache"
description: "Permit Redis traffic from application zone to cache zone"
tag:
  - "firepilot-managed"
from:
  - "app-zone"
to:
  - "cache-zone"
source:
  - "app-subnet-10.2.0.0-24"
negate_source: false
destination:
  - "cache-subnet-10.4.0.0-24"
negate_destination: false
source_user:
  - "any"
application:
  - "redis"
category:
  - "any"
service:
  - "application-default"
action: "allow"
log_end: true
```
~~~

> **Optional placement hints**: If you include `folder` and `position` keys in
> the YAML block, the workflow uses them to determine the target directory.  If
> absent, the workflow defaults to `firewall-configs/shared/pre/`.  These keys
> are stripped before the file is committed (per ADR-0007).

**Step 3 — Add the `firepilot:approved` label**

In the GitHub UI, click **Labels** on the issue sidebar and add
`firepilot:approved`.  This triggers `.github/workflows/approve-and-commit.yml`.

**Step 4 — Observe the workflow run**

Navigate to **Actions → Approve and Commit Firewall Change**.  The workflow
run should complete all 13 steps:

1. Checkout
2. Set up Python
3. Install dependencies
4. Extract YAML from issue comments (locates the block from Step 2)
5. Compute feature branch name (`firepilot/issue-{n}-{rule-name}`)
6. Check for existing branch/PR (idempotency guard)
7. Configure git identity
8. Create feature branch
9. Place rule YAML file in `firewall-configs/{folder}/{position}/`
10. Update `_rulebase.yaml` manifest
11. Commit both files atomically
12. Push the feature branch
13. Open PR + post comment on the issue

**Step 5 — Verify the PR**

A PR titled `[FirePilot] {rule-name} — Issue #{n}` should appear targeting
`main`.  The PR body links to the originating issue and summarises the rule
(source zone → destination zone, action, services).

**Step 6 — Verify CI validation triggers**

Because the PR modifies files under `firewall-configs/**`, the
`.github/workflows/validate.yml` workflow triggers automatically.  Confirm
that Gates 1–3 run without manual intervention:

- Gate 1: JSON Schema validation
- Gate 2: OPA policy evaluation
- Gate 3: SCM dry-run (mock in demo mode)

**Step 7 — Verify idempotency**

Remove and re-add the `firepilot:approved` label.  The workflow should detect
the existing branch and PR, post a comment on the issue linking to the existing
PR, and exit successfully without creating duplicates.

---

### Error path verification

To verify the error handling path (acceptance criterion 4), create a new issue
and add the `firepilot:approved` label *without* first posting a YAML comment.
The workflow should:

1. Fail at the "Extract YAML" step.
2. Post a comment on the issue explaining that no valid YAML block was found.
3. Exit with a non-zero status (visible as a failed workflow run in Actions).

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
