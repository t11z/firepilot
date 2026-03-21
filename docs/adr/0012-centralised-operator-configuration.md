# ADR-0012: Centralised Operator Configuration

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0012                                                              |
| Title         | Centralised Operator Configuration                                    |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-21                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

FirePilot requires several configuration values that are neither
architectural constants nor user inputs, but operator decisions
specific to a deployment environment. Examples include:

- **Default SCM folder and position**: Where new rules are placed.
  Currently hardcoded as `Shared`/`pre` across fixtures, workflow
  scripts, and prompt examples — but never declared as a single
  authoritative value.
- **Zone topology mapping**: Which SCM zone names map to which
  architectural roles. Currently stored as a standalone file at
  `firewall-configs/zones.yaml` (ADR-0008).
- **Mandatory tags**: The `firepilot-managed` tag is referenced in
  the system prompt (Layer 2), OPA policies (Layer 3), and drift
  detection (ADR-0011) — but its value is a string literal
  scattered across multiple files.
- **Rule defaults**: Log settings (`log_end: true`), default action,
  and similar values that an operator may want to override without
  modifying code or policies.

These values share three properties: they are deployment-specific
(different operators may choose different values), they are
referenced by multiple components (prompt, CI/CD, MCP workflow
scripts), and they are currently either hardcoded or implicitly
assumed.

The immediate trigger is a concrete problem: during issue processing,
Claude asked the user to specify the SCM target folder. This is not
the user's responsibility — it is an operator-level decision.
Similarly, the PigeonTrack demo scenario requires zone mappings that
match the demo environment, but the zone topology file is separated
from other environment-specific configuration, making it easy to
update one without the other.

In scope: the configuration file format, its location, the set of
configuration keys, and how each component (Claude system prompt,
CI/CD pipeline, MCP workflow scripts) consumes the configuration.

Out of scope: the zone role vocabulary and OPA policy definitions
(remain governed by ADR-0008); credential management (remains in
environment variables per ADR-0006); MCP tool interface design
(ADR-0004).

---

## Decision

We will consolidate all deployment-specific operator configuration
into a single declarative YAML file at `firepilot.yaml` in the
repository root. This file absorbs the zone topology mapping
currently at `firewall-configs/zones.yaml` and adds configuration
keys for SCM defaults, rule defaults, and the managed-rule tag
convention. All components that consume these values read from
`firepilot.yaml` as the single source of truth.

---

## Considered Alternatives

#### Option A: Status quo — distributed implicit configuration

- **Description**: Keep the current approach. Zone mapping remains
  a standalone file. Default folder is hardcoded in scripts. Tag
  convention is a string literal in the prompt and OPA policies.
- **Pros**: No migration effort; each value lives close to its
  primary consumer.
- **Cons**: No single source of truth; changing a deployment default
  requires editing multiple files across different components;
  inconsistency between components is inevitable; operators cannot
  review all environment-specific settings in one place; Claude's
  system prompt cannot reference a machine-readable default — it
  either hardcodes the value or asks the user.

#### Option B: Environment variables for all operator configuration

- **Description**: Define all operator configuration as environment
  variables (e.g., `FIREPILOT_DEFAULT_FOLDER=Shared`,
  `FIREPILOT_MANAGED_TAG=firepilot-managed`). Zone mapping remains
  a separate file.
- **Pros**: Consistent with the existing `FIREPILOT_ENV` pattern;
  no new file format; works natively in GitHub Actions and Docker.
- **Cons**: Zone mapping cannot be expressed as a single environment
  variable without serialisation (JSON-in-env-var is fragile and
  unreadable); environment variables are not version-controlled
  alongside the configuration they govern; operators cannot review
  or diff the full configuration in a PR; violates ADR-0001's
  principle that auditable configuration lives in Git.

#### Option C: Single YAML configuration file at repository root *(chosen)*

- **Description**: A `firepilot.yaml` file at the repository root
  contains all operator-configurable values: SCM defaults, zone
  topology mapping, rule defaults, and tag conventions. The file is
  validated by a JSON Schema in CI. Components load the file at
  startup or build time.
- **Pros**: Single source of truth; version-controlled and diffable;
  reviewable in PRs; validates against a schema; operators see
  every deployment-specific decision in one file; Claude's prompt
  can reference concrete values from the file rather than
  hardcoding or asking.
- **Cons**: Introduces a new file that all components must read;
  migration effort for existing consumers of `zones.yaml` and
  hardcoded defaults; a misconfigured file affects all components
  simultaneously (single point of misconfiguration — but the values
  are already single points of misconfiguration, just harder to
  find).

---

## Rationale

Option A is rejected because the PigeonTrack demo scenario exposed
exactly the failure mode it creates: Claude asked the user for the
SCM folder because no authoritative default exists in a location
Claude can reference. The folder value is hardcoded in three
different files, none of which is the system prompt. Adding it to
the prompt as another hardcoded value would solve the immediate
symptom but deepen the structural problem.

Option B is rejected because the zone topology mapping — the largest
and most complex operator configuration — cannot be meaningfully
expressed as environment variables. Splitting configuration across
two mechanisms (env vars for simple values, a YAML file for zone
mapping) creates the same fragmentation problem we are solving.

Option C applies the same principle ADR-0007 applied to rule
configuration: if a value is auditable, version-controlled, and
consumed by multiple components, it belongs in a declarative file in
Git. The `firepilot.yaml` file is the operator's counterpart to the
rule files — it describes the environment, not the rules.

Placing the file at the repository root (not inside `firewall-configs/`)
reflects its scope: it governs the entire FirePilot deployment, not
just the firewall configuration directory. The CI pipeline, the
system prompt, and the workflow scripts all consume it.

---

## File Schema

### Location
```
firepilot/
├── firepilot.yaml              # Operator configuration (this ADR)
├── firewall-configs/
│   └── shared/pre/             # Rule files (ADR-0007)
├── ci/
│   └── schemas/
│       └── firepilot-config.schema.json   # Schema for firepilot.yaml
└── ...
```

`firewall-configs/zones.yaml` is removed. Its content migrates into
the `zones` section of `firepilot.yaml`.

### Schema — `firepilot.yaml`
```yaml
schema_version: 1

# --- SCM Defaults ---
# These values govern where new rules are placed when the request
# does not specify a folder or position. Claude and the workflow
# scripts use these as authoritative defaults — they are not
# overridable by the requestor.
scm:
  default_folder: "Shared"
  default_position: "pre"

# --- Rule Defaults ---
# Default field values applied to new rules unless explicitly
# overridden in the generated configuration.
rule_defaults:
  tag: "firepilot-managed"
  log_end: true
  log_start: false

# --- Zone Topology Mapping ---
# Maps SCM zone names to architectural roles from the controlled
# vocabulary defined in ADR-0008. This section replaces the
# standalone firewall-configs/zones.yaml file.
zones:
  untrust-zone:
    role: internet
    description: "External internet-facing zone"
  web-zone:
    role: web-frontend
    description: "Web-facing frontend servers"
  app-zone:
    role: application
    description: "Application tier servers"
  db-zone:
    role: database
    description: "Database servers"
  dmz:
    role: dmz
    description: "Demilitarized zone for public-facing services"
  trust:
    role: internal
    description: "Internal trusted corporate network"
  clients:
    role: endpoints
    description: "End-user devices and workstations"
  mgmt:
    role: management
    description: "Out-of-band management network"
```

### Field Reference

| Field                        | Type             | Required | Description                                                        |
|------------------------------|------------------|----------|--------------------------------------------------------------------|
| `schema_version`             | int              | yes      | Must be `1`                                                        |
| `scm`                        | object           | yes      | SCM deployment defaults                                            |
| `scm.default_folder`         | string           | yes      | SCM folder for new rules. Max 64 chars                             |
| `scm.default_position`       | string           | yes      | `"pre"` or `"post"`                                                |
| `rule_defaults`              | object           | yes      | Default field values for generated rules                           |
| `rule_defaults.tag`          | string           | yes      | Tag applied to all FirePilot-managed rules                         |
| `rule_defaults.log_end`      | bool             | yes      | Default log-at-session-end setting                                 |
| `rule_defaults.log_start`    | bool             | yes      | Default log-at-session-start setting                               |
| `zones`                      | map[string, obj] | yes      | Zone topology mapping (migrated from `zones.yaml`, ADR-0008)       |
| `zones.{name}.role`          | string (enum)    | yes      | Architectural role from controlled vocabulary (ADR-0008)           |
| `zones.{name}.description`   | string           | yes      | Human-readable description of the zone's function                  |

The `zones.{name}.role` enum values remain as defined in ADR-0008:
`internet`, `internal`, `dmz`, `database`, `application`,
`web-frontend`, `endpoints`, `management`. Changes to this vocabulary
still require updating the JSON Schema, OPA policies, and ADR-0008 —
that governance is unchanged.

---

## Component Integration

### Claude System Prompt (Layer 2)

The system prompt is updated to reference `firepilot.yaml` explicitly:

- Default folder and position are read from `scm.default_folder` and
  `scm.default_position`. Claude never asks the user for the target
  folder.
- The managed-rule tag is read from `rule_defaults.tag`. Claude
  includes it in every rule without hardcoding the string value.
- Zone topology is available from the `zones` section for
  human-readable zone descriptions in analysis comments.

**Assumption**: The `firepilot.yaml` content is included in the
Claude API call context by the processing workflow (injected as a
system prompt appendix or as a user-message preamble alongside the
issue body). Claude does not read the file from disk.

### CI/CD Pipeline (Layer 3)

- `firepilot.yaml` is validated against
  `ci/schemas/firepilot-config.schema.json` as a pre-flight check
  in both `validate.yml` and `deploy.yml`.
- OPA input construction (`ci/scripts/build_opa_input.py` or
  equivalent) reads the `zones` section from `firepilot.yaml`
  instead of `firewall-configs/zones.yaml`.
- The `zone-mapping.schema.json` is superseded by the
  `firepilot-config.schema.json` which includes the zones section
  with identical validation constraints.

### Workflow Scripts

- `process-firewall-request.yml` and `process-issue.py` read
  `scm.default_folder` and `scm.default_position` from
  `firepilot.yaml` to determine where new rule files are placed.
- `deploy_common.py` continues to derive folder/position from the
  directory structure at deploy time (ADR-0007) — the operator
  config governs *creation*, the directory structure governs
  *deployment*.
- `drift-check.yml` reads `rule_defaults.tag` to identify managed
  rules in SCM.

---

## Migration from `zones.yaml`

The migration is a single atomic change:

1. Copy the `zones` content from `firewall-configs/zones.yaml` into
   the `zones` section of `firepilot.yaml`
2. Update all CI scripts that read `firewall-configs/zones.yaml` to
   read from `firepilot.yaml` instead
3. Update OPA input construction to source zone mapping from
   `firepilot.yaml`
4. Update CI test fixtures to include `firepilot.yaml` where
   `zones.yaml` was previously required
5. Delete `firewall-configs/zones.yaml`
6. Update `zone-mapping.schema.json` references to point to the
   zones section within `firepilot-config.schema.json`

The zone mapping content, role vocabulary, and OPA policy semantics
are unchanged. Only the file location changes.

---

## Consequences

- **Positive**: Single source of truth for all deployment-specific
  configuration — operators review one file to understand the
  environment
- **Positive**: Claude no longer asks users for operator-level
  decisions (folder, position) — these are authoritative and
  machine-readable
- **Positive**: Zone topology and SCM defaults are co-located,
  reducing the risk of updating one without the other
- **Positive**: The configuration file is validated by JSON Schema in
  CI, catching misconfiguration before it affects any component
- **Positive**: Adding a new operator-configurable value requires
  only a schema extension and a file update — no code changes to
  multiple consumers
- **Negative**: All components now depend on `firepilot.yaml` —
  a missing or corrupt file is a system-wide failure (mitigated by
  CI schema validation on every PR)
- **Negative**: Migration effort: CI scripts, test fixtures, OPA
  input construction, workflow scripts, and the system prompt all
  require updates
- **Negative**: `firewall-configs/` is no longer fully self-contained
  — zone topology lives one level up. Operators reviewing only the
  `firewall-configs/` directory will miss the zone definitions
- **Follow-up required**: Create `firepilot.yaml` with initial
  content migrated from `zones.yaml` and current hardcoded defaults
- **Follow-up required**: Create `ci/schemas/firepilot-config.schema.json`
- **Follow-up required**: Update CI scripts to read from
  `firepilot.yaml`
- **Follow-up required**: Update all test fixtures that reference
  `zones.yaml`
- **Follow-up required**: Update system prompt to reference
  `firepilot.yaml` for defaults
- **Follow-up required**: Delete `firewall-configs/zones.yaml` and
  `ci/schemas/zone-mapping.schema.json`
- **Follow-up required**: Update `CLAUDE.md`, `architecture.md`,
  and `README.md` to reflect the new file

---

## Compliance & Security Considerations

- **Audit Trail**: `firepilot.yaml` is version-controlled. Every
  change to operator configuration produces a Git commit with author,
  timestamp, and diff — fully auditable. This is an improvement over
  the current state where some operator decisions (default folder)
  are buried in script code with no distinct audit signal.
- **Change Management**: Changes to `firepilot.yaml` should be
  protected by CODEOWNERS rules. The file governs security-relevant
  defaults (zone topology, rule placement) and should require review
  from a designated operator or security engineer.
- **Separation of Concerns**: Operator configuration is distinct from
  security policy (OPA), architectural decisions (ADRs), and user
  input (issues). The file represents the operator's deployment
  intent, not the security team's policy or the user's request.

---

## Review Trigger

- If FirePilot supports multi-tenant deployments (multiple SCM
  folders with different zone topologies), the single-file model may
  need to evolve into a per-tenant configuration structure
- If the number of configuration keys exceeds ~20, consider whether
  the file should be split into logical sections with separate
  schemas
- If a configuration value needs to differ between CI environments
  (e.g., staging vs production folder), evaluate whether environment
  variable overrides should be supported alongside the file defaults
