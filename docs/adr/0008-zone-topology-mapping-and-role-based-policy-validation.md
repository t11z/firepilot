# ADR-0008: Zone Topology Mapping and Role-Based Policy Validation

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0008                                                              |
| Title         | Zone Topology Mapping and Role-Based Policy Validation                |
| Status        | **Draft**                                                             |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-19                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

ADR-0007 defines the declarative YAML schema for security rules stored in Git.
ADR-0003 mandates OPA/Rego as the policy validation engine in the CI/CD
pipeline. Together, they enable structural and basic semantic validation of
firewall configurations before deployment.

However, the current policy set cannot express topology-aware security
constraints. Consider the rule: "No security rule may permit traffic directly
from the internet to the database tier." Enforcing this requires knowledge that
the OPA policies do not currently possess: which SCM zone names correspond to
which network function.

SCM zone names are operator-defined strings (untrust, db-zone, app-zone, etc.)
with no inherent semantic meaning. Without a mapping from zone names to their
architectural role, OPA can validate field presence and format but cannot reason
about whether a rule violates network segmentation principles.

A secondary concern is human readability. Claude's orchestration layer
(Constraint Layer 2) translates between business users and firewall
configuration. When Claude presents a proposed rule to a user, it should use
recognisable terms ("Internet zone", "Database tier") rather than raw SCM zone
identifiers. This requires the same mapping.

In scope: the zone mapping file format, its location in the repository, the
controlled role vocabulary, and the topology-aware OPA policies enabled by the
mapping.

Out of scope: automated synchronisation between the zone mapping and live SCM
zone state (this is a drift detection concern, deferred to a future ADR).
Address object topology and service object taxonomy are also out of scope.

---

## Decision

We will store a zone topology mapping as a declarative YAML file at
`firewall-configs/zones.yaml`. The mapping assigns each SCM zone name a role
from a controlled vocabulary. OPA policies use these role assignments to enforce
topology-aware security constraints that prevent structurally dangerous traffic
flows. The CI/CD pipeline validates that every zone referenced in a security
rule file exists in the zone mapping.

---

## Considered Alternatives

#### Option A: No zone mapping — enforce topology rules by zone name pattern

- **Description**: OPA policies match zone names directly using naming
  conventions (e.g., names containing `db` or `database` are treated as
  database zones)
- **Pros**: No additional configuration file; works with existing schema
- **Cons**: Fragile — relies on naming conventions that operators may not
  follow; false positives on zones like `db-admin-tools` that contain `db`
  but are not database tiers; false negatives on zones named `data-store` or
  `rds`; policy intent is obscured by regex patterns rather than declared as
  semantic mappings

#### Option B: Embed role metadata in each rule file

- **Description**: Each rule file includes a `zone_roles` section that declares
  the roles of its source and destination zones
- **Pros**: Self-contained per rule; no external file dependency
- **Cons**: Duplicates role assignments across every rule that references the
  same zone; inconsistency between rule files is inevitable; no single source
  of truth for zone topology; contradicts the separation of concerns established
  in ADR-0007

#### Option C: Global zone mapping file with controlled role vocabulary *(chosen)*

- **Description**: A single `zones.yaml` file at the root of
  `firewall-configs/` maps every SCM zone name to a role from a fixed
  enumeration. OPA policies reference roles, not zone names, when evaluating
  topology constraints
- **Pros**: Single source of truth for zone topology; role vocabulary is
  controlled and auditable; OPA policies express intent in terms of network
  function ("internet to database") rather than implementation detail
  ("untrust to db-zone"); zone mapping is independently reviewable and
  versioned; Claude can use the mapping for human-readable presentation without
  additional configuration
- **Cons**: An additional file to maintain; zone additions in SCM require a
  corresponding update to `zones.yaml` or rules referencing the new zone will
  fail validation; the role vocabulary is a design decision that may not cover
  all future network topologies

---

## Rationale

Option A is rejected because pattern-matching on zone names conflates naming
convention with security policy. A policy that says `deny if zone_name contains
"db"` is testing a string property, not a network architecture property. It
fails the moment an operator names their database zone `data-store` or their
debug zone `db-tools`.

Option B is rejected because it distributes topology knowledge across every
rule file. If `db-zone` changes its role (or if a new zone is introduced),
every rule referencing that zone must be updated. This is the same class of
problem that ADR-0007 solved for rule ordering by separating the manifest from
rule content.

Option C applies the same separation principle: topology knowledge lives at
exactly one location. Rule files reference zone names; the zone mapping defines
what those names mean architecturally; OPA policies operate on the architectural
meaning. Each concern is independently modifiable. Renaming a zone requires
updating `zones.yaml` and the rule files that reference it — but the OPA
policies remain unchanged because they reason about roles, not names.

The controlled vocabulary is essential. A free-form role string would make the
mapping a documentation artefact rather than a policy input. With a fixed
enumeration, OPA policies can exhaustively match on role values, and a new role
requires a deliberate schema change — which is the correct friction for a
security-relevant taxonomy.

---

## File Location and Schema

### Location

```
firewall-configs/
├── zones.yaml                          # zone topology mapping (this ADR)
└── {folder}/
    └── {position}/
        ├── _rulebase.yaml
        └── {rule-name}.yaml
```

`zones.yaml` is placed at the root of `firewall-configs/` because zone
definitions are global to the SCM tenant, not scoped to a specific folder or
rulebase position. All folders and positions reference the same set of zones.

### Schema — `zones.yaml`

```yaml
schema_version: 1
zones:
  untrust:
    role: internet
    description: "External internet-facing zone"
  trust:
    role: internal
    description: "Internal trusted corporate network"
  dmz:
    role: dmz
    description: "Demilitarized zone for public-facing services"
  web-zone:
    role: web-frontend
    description: "Web-facing frontend servers"
  app-zone:
    role: application
    description: "Application tier servers"
  db-zone:
    role: database
    description: "Database servers"
  clients:
    role: endpoints
    description: "End-user devices and workstations"
  mgmt:
    role: management
    description: "Out-of-band management network"
```

### Field Reference

| Field                      | Type             | Required | Description                                          |
|----------------------------|------------------|----------|------------------------------------------------------|
| `schema_version`           | int              | yes      | Must be `1`                                          |
| `zones`                    | map[string,object] | yes    | Map of SCM zone name to zone metadata                |
| `zones.{name}.role`        | string (enum)    | yes      | Architectural role from controlled vocabulary        |
| `zones.{name}.description` | string           | yes      | Human-readable description of the zone's function    |

### Controlled Role Vocabulary

| Role           | Semantic meaning                                                          |
|----------------|---------------------------------------------------------------------------|
| `internet`     | Untrusted external network (public internet, WAN uplinks)                 |
| `internal`     | General trusted internal network (corporate LAN)                          |
| `dmz`          | Demilitarized zone for services exposed to external clients               |
| `database`     | Database tier (SQL, NoSQL, data stores)                                   |
| `application`  | Application tier (middleware, backend services)                           |
| `web-frontend` | Web-facing frontend tier (reverse proxies, web servers)                   |
| `endpoints`    | End-user devices (workstations, laptops, BYOD)                            |
| `management`   | Management and out-of-band network (IPMI, iLO, jump hosts)               |

The role vocabulary is enforced by JSON Schema (enum) and validated by OPA.
Adding a new role requires updating the JSON Schema, the OPA policies, and this
ADR. This friction is intentional — a new network tier is an architectural
decision, not a configuration change.

### Naming Conventions

The zone name keys in `zones.yaml` must match SCM zone names exactly
(case-sensitive). This is the same convention used for zone references in
security rule `from` and `to` fields (ADR-0007).

---

## OPA Policy Integration

The zone mapping is included in the OPA input object alongside the existing
fields defined in ADR-0007:

```json
{
  "manifest": { "..." : "..." },
  "rule_files": { "..." : "..." },
  "directory": { "..." : "..." },
  "zone_mapping": {
    "untrust": { "role": "internet", "description": "..." },
    "db-zone": { "role": "database", "description": "..." }
  }
}
```

### New OPA Policies

#### `zone_reference_valid`

Every zone referenced in a rule file's `from` or `to` field must exist as a
key in `input.zone_mapping`. The literal value `"any"` is exempt. This catches
typos and references to zones not yet registered in the mapping before the
configuration reaches the dry-run gate.

#### `no_internet_to_database`

No security rule with `action: "allow"` may have a source zone with role
`internet` and a destination zone with role `database`.

#### `no_internet_to_management`

No security rule with `action: "allow"` may have a source zone with role
`internet` and a destination zone with role `management`.

#### `no_overly_permissive_internet_rule`

No security rule with `action: "allow"` may have a source zone with role
`internet` combined with `source: ["any"]` and `destination: ["any"]`.

---

## Claude Integration (Layer 2)

Claude reads `zones.yaml` at the start of its orchestration workflow (before
Step 1 in the system prompt). When presenting proposed rules to users, Claude
uses the `description` field to translate zone names into human-readable terms:

- Instead of: "Source zone: untrust"
- Claude says: "Source zone: untrust (External internet-facing zone)"

This is a presentation concern only. Claude does not use the zone mapping to
bypass or override the OPA validation layer. The `role` field is consumed by
OPA policies; the `description` field is consumed by Claude's user-facing
output.

---

## Consequences

- **Positive**: OPA policies can now enforce topology-aware security constraints
  — the three highest-impact rules (no internet to database, no internet to
  management, no overly permissive internet rules) are expressible and testable
- **Positive**: Zone reference validation catches typos and unregistered zones
  at CI/CD time, before the dry-run gate — reducing wasted approval cycles on
  configurations that would fail deployment
- **Positive**: The controlled role vocabulary makes policy intent readable:
  `role == "internet"` is self-documenting in a way that `zone_name == "untrust"`
  is not
- **Positive**: Claude can present zone information in business-readable terms
  without additional configuration
- **Negative**: `zones.yaml` must be maintained in sync with the actual SCM
  zone inventory. A zone added in SCM but not in `zones.yaml` will cause rule
  validation failures for any rule referencing it. This is conservative-fail
  (safe) but requires operator discipline
- **Negative**: The role vocabulary is finite and opinionated. Network
  architectures with zone functions not covered by the v1 vocabulary require a
  schema change (see Review Trigger)
- **Follow-up required**: JSON Schema for `zones.yaml`
- **Follow-up required**: Update `build-opa-input.py` to include `zone_mapping`
  in the OPA input object
- **Follow-up required**: OPA test cases for all four new policies
- **Follow-up required**: Update Claude system prompt to reference `zones.yaml`
  at workflow start

---

## Compliance & Security Considerations

- **Defense in Depth**: The topology policies enforce network segmentation
  principles at the CI/CD layer (Layer 3), independently of Claude's reasoning
  (Layer 2). Even if Claude's system prompt is circumvented or a rule is
  manually committed to the repository, the OPA gate will reject configurations
  that violate topology constraints
- **SOC 2 CC6.6**: Network segmentation controls are codified as testable,
  version-controlled policy declarations — not implicit knowledge held by
  individual operators
- **Audit Trail**: The zone mapping is version-controlled in Git. Changes to
  zone role assignments are visible in the commit history, reviewable in PRs,
  and subject to the same branch protection rules as firewall configurations
- **No Secrets**: `zones.yaml` contains only zone names, roles, and
  descriptions. No IP addresses, credentials, or sensitive network topology
  details are stored. IP addressing is a property of address objects referenced
  in rule files, not of zones

---

## Review Trigger

- If the controlled role vocabulary does not cover a zone function required by
  a new deployment, extend the vocabulary via a superseding ADR. Do not add
  ad-hoc role strings without updating the JSON Schema and OPA policies
- If FirePilot is deployed in an environment with dynamic zone provisioning
  (zones created and destroyed frequently), evaluate whether `zones.yaml`
  should be auto-generated from SCM state rather than manually maintained
- If drift detection (future ADR) is implemented, it must verify that every
  zone in the SCM inventory with a corresponding `firepilot-managed` rule has
  an entry in `zones.yaml`
- If the zone mapping is found to be a bottleneck in onboarding (operators
  forget to update it when adding SCM zones), consider a CI/CD check that
  compares `zones.yaml` against `list_security_zones` output as part of Gate 3
  (dry-run validation)
