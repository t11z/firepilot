# ADR-0007: Declarative Firewall Configuration YAML Schema

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0007                                                              |
| Title         | Declarative Firewall Configuration YAML Schema                        |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-19                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

ADR-0001 establishes Git as the single source of truth for firewall
configuration. ADR-0003 mandates JSON Schema validation (structural
correctness) and OPA/Rego evaluation (security semantics) as CI/CD
gates before any configuration reaches the firewall. ADR-0004 defines
the `create_security_rule` MCP tool interface with field names taken
verbatim from the official Palo Alto Networks SCM API documentation.

This ADR defines the missing piece: the declarative YAML schema that
lives in Git, is validated by CI/CD, and serves as the input for
deployment via `mcp-strata-cloud-manager`.

### Design Constraints

**Ordering is critical.** Palo Alto NGFW security rules follow a
first-match evaluation model. The position of a rule in the rulebase
determines whether it is ever evaluated. A schema that cannot
faithfully represent rule ordering — or that loses ordering information
on file deletion or modification — is fundamentally broken.

**Coexistence with manual rules.** Not all rules in a production SCM
environment are managed by FirePilot. Rules created manually via the
SCM GUI or by other automation tools exist alongside FirePilot-managed
rules. The schema must define a clear scope boundary so that drift
detection (future ADR) can distinguish FirePilot-managed rules from
unmanaged ones.

**Field names must trace to the official API.** ADR-0004 requires that
tool interface field names are taken verbatim from the SCM API
documentation. The YAML schema follows the same principle: field names
in configuration files must match the SCM API field names exactly. No
invented aliases, no renamed fields, no abstraction layer between
what the operator writes in YAML and what the SCM API accepts.

In scope: YAML file structure, directory layout, schema fields for
security rules and rulebase manifests, naming conventions, and the
`firepilot-managed` scope marker.

Out of scope: JSON Schema and OPA policy definitions (content of
validation rules), drift detection mechanism (separate ADR), address
object and address group configuration files (v1 scope is security
rules only).

---

## Decision

We will store firewall configurations as individual YAML files per
security rule, organised by folder and position in the directory
hierarchy. Rule ordering is declared in a dedicated rulebase manifest
file per folder/position combination. All FirePilot-managed rules
carry a mandatory `firepilot-managed` tag in both the YAML
configuration and the SCM rule object, establishing the scope boundary
for drift detection.

---

## Considered Alternatives

#### Option A: Single file per rulebase — all rules in one YAML file per folder/position

- **Description**: Each `{folder}/{position}/rulebase.yaml` file
  contains an ordered list of complete rule definitions. Rule order
  is implicit in the list position within the file
- **Pros**: Ordering is inherent in the YAML list structure; no
  separate manifest needed; single file to read for a complete
  picture of the rulebase
- **Cons**: Merge conflicts are near-certain when two PRs modify
  different rules in the same rulebase; diffs are noisy — a change
  to one rule shows the entire file as modified in the PR; file
  size grows unboundedly; individual rule changes cannot be
  attributed to a single file in the Git history

#### Option B: One file per rule, ordering via filename prefix (e.g. `0010-rule-name.yaml`)

- **Description**: Each rule is a separate YAML file. Lexicographic
  filename ordering determines rule position. Gaps in numbering
  (10, 20, 30) allow insertions without renaming
- **Pros**: Simple; ordering is visible in directory listing; each
  rule is independently diffable
- **Cons**: Reordering requires renaming multiple files — each
  rename is a delete+create in Git, polluting history; parallel
  insertions at the same position collide silently (two PRs both
  adding rule 0015); deletion of a file creates a gap that is
  invisible to validation unless explicitly checked; numbering
  exhaustion between adjacent rules requires bulk renaming

#### Option C: One file per rule, ordering via relative position reference (e.g. `position: after: other-rule`)

- **Description**: Each rule file contains a field referencing the
  rule it should follow. Ordering is reconstructed by resolving the
  reference chain
- **Pros**: No separate manifest; position is self-contained per file
- **Cons**: Deletion of a referenced rule breaks the chain — creates
  an orphan that requires repair in a different file (implicit
  side effect); circular references are possible and must be
  detected; reconstructing total order from pairwise references
  requires a topological sort with error handling for cycles and
  broken references; merge conflicts in reference chains are
  non-obvious to reviewers

#### Option D: Manifest plus individual rule files *(chosen)*

- **Description**: Each folder/position combination contains a
  `_rulebase.yaml` manifest that declares rule ordering as a flat
  list of rule names, plus one YAML file per rule containing the
  full rule configuration without any position information. The
  manifest is the single source of truth for ordering; rule files
  are the single source of truth for rule content
- **Pros**: Ordering lives at exactly one location — the manifest;
  deletion of a rule file without removing it from the manifest is
  a detectable validation error; reordering is a single-file change
  to the manifest with a clean, reviewable diff; rule content
  changes do not affect ordering and vice versa — concerns are
  separated; manifest is a trivially comparable ordered list for
  drift detection against SCM API state; merge conflicts on ordering
  are localised to the manifest file where they belong
- **Cons**: Every rule addition or removal requires changes to two
  files (manifest + rule file); an operator who edits only one of
  the two creates an inconsistent state that must be caught by
  validation

---

## Rationale

The fundamental challenge is mapping an ordered list (firewall
rulebase) onto a filesystem (unordered set of files). Options A
through C each embed ordering information in a location that creates
fragility: in list position within a monolithic file (merge conflict
hell), in filenames (rename cascades), or in inter-file references
(broken chains on deletion).

Option D separates the two concerns — ordering and content — into
dedicated artefacts. The manifest is a short, flat, human-readable
list that changes only when rules are added, removed, or reordered.
Rule files change only when rule content changes. This separation
produces clean diffs, localised merge conflicts, and straightforward
validation rules.

The two-file-change requirement (manifest + rule file) is a feature,
not a defect. It makes additions and removals explicitly visible in
two dimensions: "what rule was added" (rule file diff) and "where in
the rulebase it was placed" (manifest diff). Reviewers see both
concerns addressed. If only one file is changed, CI/CD validation
fails — preventing the class of error where a rule file is added but
never referenced, or a manifest entry points to a nonexistent file.

Option B was the closest alternative. It fails specifically on the
reordering case: moving a rule from position 5 to position 2 in a
50-rule rulebase requires renaming files, which Git represents as
delete+create pairs. A reviewer sees file deletions and creations
rather than a reorder — the semantic intent is lost in the diff. In
Option D, the same operation is a two-line move in the manifest.

---

## Directory Layout

```
firewall-configs/
└── {folder}/
    └── {position}/
        ├── _rulebase.yaml              # ordering manifest
        ├── {rule-name}.yaml            # one file per rule
        ├── {rule-name}.yaml
        └── ...
```

Concrete example:

```
firewall-configs/
└── shared/
    ├── pre/
    │   ├── _rulebase.yaml
    │   ├── allow-web-to-app.yaml
    │   ├── allow-app-to-db.yaml
    │   └── deny-direct-db-access.yaml
    └── post/
        ├── _rulebase.yaml
        └── default-deny-all.yaml
```

### Naming Conventions

| Element         | Convention                                                    |
|-----------------|---------------------------------------------------------------|
| Folder name     | Matches SCM folder name exactly (case-sensitive)              |
| Position        | `pre` or `post` — matches SCM `position` parameter           |
| Manifest file   | `_rulebase.yaml` — underscore prefix ensures sort-first in    |
|                 | directory listings and distinguishes it from rule files        |
| Rule file       | `{name}.yaml` where `name` matches the `name` field inside   |
|                 | the YAML file and the SCM rule name                           |

Rule file names must conform to the SCM name pattern. Characters
allowed: `a-zA-Z0-9`, hyphen, underscore, period, space. Maximum
63 characters. The file extension `.yaml` is appended and does not
count toward the character limit.

---

## Schema Definition

### Rulebase Manifest — `_rulebase.yaml`

```yaml
schema_version: 1
folder: "shared"
position: "pre"
rule_order:
  - allow-web-to-app
  - allow-app-to-db
  - deny-direct-db-access
```

| Field            | Type         | Required | Description                                        |
|------------------|--------------|----------|----------------------------------------------------|
| `schema_version` | int          | yes      | Schema version. Must be `1` for this ADR           |
| `folder`         | string       | yes      | SCM folder name. Max 64 chars, pattern `^[a-zA-Z\d\-_\. ]+$` |
| `position`       | string       | yes      | `"pre"` or `"post"`                                |
| `rule_order`     | list[string] | yes      | Ordered list of rule names. Each entry must         |
|                  |              |          | correspond to a `{name}.yaml` file in the same     |
|                  |              |          | directory. No duplicates permitted                  |

Validation invariants (enforced by CI/CD):

1. Every entry in `rule_order` must have a corresponding
   `{name}.yaml` file in the same directory
2. Every `{name}.yaml` file in the directory (excluding
   `_rulebase.yaml`) must appear in `rule_order`
3. No duplicate entries in `rule_order`
4. `folder` must match the parent directory name
5. `position` must match the directory name (`pre` or `post`)

---

### Security Rule File — `{name}.yaml`

Field names are taken verbatim from the official Palo Alto Networks
SCM API documentation for `POST /config/security/v1/security-rules`.
No fields are renamed, aliased, or abstracted.

```yaml
schema_version: 1

# --- Identification (FirePilot metadata) ---
name: "allow-web-to-app"
description: "Permit HTTPS traffic from web zone to application zone"
tag:
  - "firepilot-managed"
  - "app:customer-portal"

# --- Zone and Address ---
from:
  - "web-zone"
to:
  - "app-zone"
source:
  - "web-subnet-10.1.0.0-24"
negate_source: false
destination:
  - "app-subnet-10.2.0.0-24"
negate_destination: false

# --- User and Application ---
source_user:
  - "any"
application:
  - "ssl"
  - "web-browsing"
category:
  - "any"

# --- Service and Action ---
service:
  - "application-default"
action: "allow"

# --- Optional: Security Profiles ---
profile_setting:
  group:
    - "best-practice"

# --- Optional: Logging ---
log_setting: "default-log-profile"
log_start: false
log_end: true

# --- Optional: Scheduling and HIP ---
# schedule: null
# source_hip: []
# destination_hip: []
# disabled: false
# tenant_restrictions: []
```

#### Field Reference

**Required fields:**

| Field            | Type         | Description                                          |
|------------------|--------------|------------------------------------------------------|
| `schema_version` | int          | Must be `1`. FirePilot metadata, not sent to SCM     |
| `name`           | string       | Rule name. Must match filename (without `.yaml`)     |
| `from`           | list[string] | Source security zone(s)                              |
| `to`             | list[string] | Destination security zone(s)                         |
| `source`         | list[string] | Source address(es) or address object names            |
| `source_user`    | list[string] | Source user(s). `["any"]` if unscoped                |
| `destination`    | list[string] | Destination address(es) or address object names       |
| `service`        | list[string] | Service(s) being accessed                            |
| `application`    | list[string] | Application(s) being accessed                        |
| `category`       | list[string] | URL categories. `["any"]` if unscoped                |
| `action`         | string       | `"allow"`, `"deny"`, `"drop"`, `"reset-both"`,      |
|                  |              | `"reset-client"`, or `"reset-server"`                |
| `tag`            | list[string] | Must include `"firepilot-managed"`. Additional       |
|                  |              | tags permitted                                       |

**Optional fields:**

| Field                | Type         | Default   | Description                              |
|----------------------|--------------|-----------|------------------------------------------|
| `description`        | string       | null      | Human-readable rule description          |
| `disabled`           | bool         | false     | Whether the rule is disabled             |
| `negate_source`      | bool         | false     | Negate source address(es)                |
| `negate_destination` | bool         | false     | Negate destination address(es)           |
| `source_hip`         | list[string] | []        | Source Host Integrity Profile(s)         |
| `destination_hip`    | list[string] | []        | Destination Host Integrity Profile(s)    |
| `schedule`           | string       | null      | Schedule name                            |
| `profile_setting`    | object       | null      | Security profile configuration           |
| `profile_setting.group` | list[string] | []     | Security profile group(s)                |
| `log_setting`        | string       | null      | External log forwarding profile          |
| `log_start`          | bool         | false     | Log at session start                     |
| `log_end`            | bool         | true      | Log at session end                       |
| `policy_type`        | string       | "Security"| Policy type. Omit unless non-default     |
| `tenant_restrictions`| list[string] | []        | Tenant restriction(s)                    |

#### Fields NOT Present in Rule Files

The following SCM API fields are intentionally absent from rule YAML
files because they are determined by directory structure or assigned
by SCM at creation time:

| Field      | Reason for exclusion                                           |
|------------|----------------------------------------------------------------|
| `id`       | UUID assigned by SCM on creation. Not operator-controlled      |
| `folder`   | Derived from the parent directory name in the file path        |
| `position` | Derived from the directory name (`pre` or `post`)              |

The deployment pipeline reads `folder` and `position` from the
directory structure and passes them as parameters to
`create_security_rule`. This eliminates the possibility of a rule
file declaring a folder or position that contradicts its location
in the directory hierarchy.

---

## The `firepilot-managed` Tag

Every security rule managed by FirePilot must include
`"firepilot-managed"` in its `tag` list. This tag serves as the
scope boundary between FirePilot-managed rules and rules managed
by other means (manual GUI configuration, other automation tools).

CI/CD validation enforces that `"firepilot-managed"` is present
in every rule file's `tag` list. The deployment pipeline passes
this tag to the SCM API when creating rules.

The drift detection mechanism (future ADR) uses this tag to
determine which rules in SCM fall within FirePilot's scope:

- Rules in SCM with `firepilot-managed` tag → compare against
  Git state; deviations are drift
- Rules in SCM without `firepilot-managed` tag → outside
  FirePilot's scope; ignored by drift detection

This convention allows FirePilot to coexist with manually managed
rules in the same SCM folder without interference.

---

## Deployment Mapping

The deployment pipeline translates the YAML file structure into
`create_security_rule` MCP tool calls as follows:

```
For each folder in firewall-configs/:
  For each position (pre, post) in folder:
    Read _rulebase.yaml → extract rule_order
    For each rule_name in rule_order (in order):
      Read {rule_name}.yaml
      Call create_security_rule with:
        - folder:   from directory path
        - position: from directory path
        - ticket_id: from ITSM change request
        - all other fields: from YAML file content
```

Rule ordering in SCM is determined by creation order. Rules are
created in the sequence declared by `rule_order`. This means the
deployment pipeline must process rules sequentially, not in parallel.

---

## Consequences

- **Positive**: Rule ordering is declared at exactly one location
  (`_rulebase.yaml`) — no ordering information is scattered across
  filenames, rule file content, or inter-file references
- **Positive**: Deletion of a rule file without updating the manifest
  (or vice versa) is a hard CI/CD validation failure — no silent
  drift within the repository
- **Positive**: Reordering rules is a single-file diff in the
  manifest; rule content changes are single-file diffs in the rule
  file — concerns are separated in the Git history
- **Positive**: The `firepilot-managed` tag establishes a clear scope
  boundary for coexistence with non-FirePilot rules and enables
  targeted drift detection in a future ADR
- **Positive**: Field names match the SCM API verbatim — no mapping
  table or translation layer between Git state and API calls
- **Positive**: `folder` and `position` are derived from directory
  structure, eliminating an entire class of inconsistency where file
  content contradicts file location
- **Negative**: Every rule addition or removal requires changes to
  two files (manifest + rule file); a single-file change is always
  invalid and blocked by CI/CD
- **Negative**: The `firepilot-managed` tag is a convention, not a
  technical enforcement. A manual SCM user could add or remove this
  tag, corrupting the scope boundary. Drift detection must account
  for this
- **Negative**: Rule ordering depends on sequential creation via the
  SCM API. If the API does not guarantee that creation order
  determines rulebase position, an explicit ordering mechanism
  (rule move API) would be required — this is not available in the
  v1 tool set (ADR-0004)
- **Follow-up required**: JSON Schema definition for both
  `_rulebase.yaml` and `{name}.yaml`, to be used by the CI/CD
  schema validation gate (ADR-0003, Gate 1)
- **Follow-up required**: OPA/Rego policies enforcing the validation
  invariants listed in this ADR (bidirectional manifest/file
  consistency, mandatory `firepilot-managed` tag, field constraints)
- **Follow-up required**: ADR for drift detection mechanism —
  reconciliation between Git state and live SCM state, scoped to
  rules carrying the `firepilot-managed` tag
- **Follow-up required**: Verify that SCM API creation order
  determines rulebase position. If not, the deployment pipeline
  must use a rule-move or rule-reorder API call after creation,
  which requires extending the tool set defined in ADR-0004

---

## Compliance & Security Considerations

- **SOC 2 CC6.1 / CC8.1**: Every rule configuration is version-
  controlled with full Git history. Changes are traceable to a
  commit, a PR, and an ITSM change request via the `ticket_id`
  linkage defined in ADR-0004 and ADR-0005
- **ISO 27001 A.12.1.2**: The two-file change requirement (manifest
  + rule file) creates a structural review surface — reviewers
  must inspect both ordering intent and rule content before
  approval
- **Audit Trail**: The `firepilot-managed` tag in SCM links every
  deployed rule back to the Git-managed configuration. Combined
  with the MCP tool call log (`ticket_id` + `scm_request_id`),
  this creates a complete chain: ITSM request → Git commit →
  SCM rule object
- **Scope Isolation**: The `firepilot-managed` tag convention
  ensures that FirePilot's automated validation and deployment
  pipeline does not interfere with rules managed outside its
  scope. This is critical in environments where FirePilot manages
  a subset of the rulebase
- **No Secrets in Configuration**: Rule YAML files contain only
  declarative configuration — zone names, address references,
  service names, and action types. No credentials, tokens, or
  sensitive identifiers are present. This is consistent with
  ADR-0006's requirement that credentials are injected
  exclusively via environment variables

---

## Review Trigger

- If the SCM API does not guarantee that creation order determines
  rulebase position, the deployment pipeline must be redesigned
  and the tool set in ADR-0004 must be extended with a rule-move
  or rule-reorder capability. This ADR must be amended to document
  the corrected ordering mechanism
- If FirePilot's scope expands to manage address objects or address
  groups as declarative configuration (not just reference them by
  name in rules), extend this schema via a superseding ADR
- If drift detection (future ADR) reveals that the
  `firepilot-managed` tag convention is insufficient for reliable
  scope isolation — e.g., due to tag manipulation in the SCM GUI —
  evaluate stronger scope markers (dedicated folder, naming
  convention prefix, or SCM API metadata)
- If a compliance audit requires cryptographic integrity verification
  of configuration files beyond Git commit signatures, reassess
  whether the YAML-in-Git model is sufficient or whether a signed
  configuration artefact is needed
- If `schema_version` is incremented beyond `1`, define and document
  the migration path for existing configuration files in the
  superseding ADR
