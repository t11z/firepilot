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

If Claude produces a valid YAML proposal, the workflow continues through steps
4–13: computing a feature branch name, checking for existing branches/PRs
(idempotency guard), committing the rule file and manifest atomically, pushing
the branch, opening a PR, and posting a comment linking to the PR.

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
