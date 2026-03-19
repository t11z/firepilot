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
