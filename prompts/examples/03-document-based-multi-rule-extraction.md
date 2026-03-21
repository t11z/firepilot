# Example: Full Document Extraction — Multi-Rule Processing (Confident Tier)

This example demonstrates how Claude processes a document_based request where
all extracted rules are valid and proceed to configuration output without
skips or questions. It is the canonical reference for how Step 7 iterates
once per validated rule.

---

## Scenario

A business user from the Logistics Department submits a GitHub Issue in
document_based mode, attaching the PigeonTrack carrier management operations
manual. All connectivity requirements are fully specified in the document.
Claude extracts three rules, validates all three against firepilot.yaml zones,
and writes one configuration file per rule.

---

## Conversation

**User (GitHub Issue — document_based mode):**
> Application: PigeonTrack
> Business Unit: Logistics Department
> Request Mode: document_based
> Supporting Documentation: [attached: pigeontrack-operations-manual.pdf]
> Business Justification: Initial deployment of PigeonTrack carrier management system per operations manual.

**Claude (internal — not shown to user):**
> *Step 1: Extract requirements from attached PDF.*
>
> Extracted rules:
>
> 1. Allow HTTPS from untrust-zone (public internet) to dmz — PigeonTrack web portal
>    - Source: any → Destination: pigeontrack-dmz-server-10.20.0.50
>    - Service: service-https / Application: ssl, web-browsing
>    - Rule name: allow-pigeontrack-web-inbound
>
> 2. Allow PostgreSQL from dmz to db-zone — PigeonTrack app server to database
>    - Source: pigeontrack-dmz-server-10.20.0.50 → Destination: pigeontrack-db-10.30.0.10
>    - Service: tcp-5432 / Application: postgres
>    - Rule name: allow-pigeontrack-app-to-db
>
> 3. Allow HTTPS from trust to dmz — Internal users accessing PigeonTrack
>    - Source: pigeontrack-internal-users-10.10.0.0-16 → Destination: pigeontrack-dmz-server-10.20.0.50
>    - Service: service-https / Application: ssl, web-browsing
>    - Rule name: allow-pigeontrack-internal-access
>
> Checking zone mappings against firepilot.yaml zones:
> - untrust-zone → present ✓ (role: internet)
> - dmz → present ✓ (role: dmz)
> - db-zone → present ✓ (role: database)
> - trust → present ✓ (role: internal)
>
> All zones resolve unambiguously. Proceed to Steps 2–4 for all 3 rules.

**Claude (internal):**
> *Steps 2–4 for Rules 1–3 (executed independently per rule):*
>
> Rule 1 (allow-pigeontrack-web-inbound):
> - Zones validated: untrust-zone ✓, dmz ✓
> - Addresses:
>   - source: any → use built-in "any" ✓
>   - destination: 10.20.0.50 — no existing object — will create
>     pigeontrack-server-10.20.0.50 in Phase 2
> - No conflict detected ✓
>
> Rule 2 (allow-pigeontrack-app-to-db):
> - Zones validated: dmz ✓, db-zone ✓
> - Addresses:
>   - source: 10.20.0.50 — will reuse pigeontrack-server-10.20.0.50 (created for Rule 1)
>   - destination: 10.30.0.10 — no existing object — will create
>     pigeontrack-db-10.30.0.10 in Phase 2
> - No conflict detected ✓
>
> Rule 3 (allow-pigeontrack-internal-access):
> - Zones validated: trust ✓, dmz ✓
> - Addresses:
>   - source: 10.10.0.0/16 — no existing object — will create
>     pigeontrack-users-10.10.0.0-16 in Phase 2
>   - destination: 10.20.0.50 — will reuse pigeontrack-server-10.20.0.50
> - No conflict detected ✓

**Claude → Issue comment (Step 5 — analysis comment):**
> ## FirePilot Analysis — Document Extraction: PigeonTrack Operations Manual
>
> Extracted 3 rules from `pigeontrack-operations-manual.pdf`.
> All 3 rules validated successfully. **Assessment: Confident** — proceeding
> to change request creation without questions.
>
> ### Rules to be created
>
> | # | Rule name                           | Source                                     | Destination                         | App/Service              | Action |
> |---|-------------------------------------|--------------------------------------------|-------------------------------------|--------------------------|--------|
> | 1 | allow-pigeontrack-web-inbound       | untrust-zone / any                         | dmz / 10.20.0.50                    | ssl, web-browsing / service-https | Allow |
> | 2 | allow-pigeontrack-app-to-db         | dmz / 10.20.0.50                           | db-zone / 10.30.0.10                | postgres / tcp-5432      | Allow  |
> | 3 | allow-pigeontrack-internal-access   | trust / 10.10.0.0/16                       | dmz / 10.20.0.50                    | ssl, web-browsing / service-https | Allow |
>
> New address objects to be created:
> - `pigeontrack-server-10.20.0.50` (10.20.0.50/32) — referenced by Rules 1, 2, 3
> - `pigeontrack-db-10.30.0.10` (10.30.0.10/32) — referenced by Rule 2
> - `pigeontrack-users-10.10.0.0-16` (10.10.0.0/16) — referenced by Rule 3
>
> No conflicts detected. Proceeding to change request creation.

**Claude (internal):**
> *Step 6: Create change request.*
> Tool call: `create_change_request(title="PigeonTrack initial deployment — 3 firewall rules from operations manual", description="All 3 rules extracted from pigeontrack-operations-manual.pdf. All zones and addresses validated. Initial deployment of PigeonTrack carrier management system per operations manual.", requestor="Logistics Department")`
> Result: change_request_id="117", url="https://github.com/.../issues/117"

**Claude (internal):**
> *Step 7, iteration 1 of 3: Rule allow-pigeontrack-web-inbound.*
>
> Address pigeontrack-server-10.20.0.50 does not exist — create first.
> Tool call: `create_address(ticket_id="117", folder="Shared", name="pigeontrack-server-10.20.0.50", ip_netmask="10.20.0.50/32", tag=["firepilot-managed"])`
> Result: id="addr-0201"
>
> Tool call: `create_security_rule(ticket_id="117", folder="Shared", position="pre", name="allow-pigeontrack-web-inbound", from=["untrust-zone"], to=["dmz"], source=["any"], source_user=["any"], destination=["pigeontrack-server-10.20.0.50"], service=["service-https"], application=["ssl", "web-browsing"], category=["any"], action="allow", tag=["firepilot-managed"], log_end=true)`
> Result: id="rule-0211"
>
> Tool call: `add_audit_comment(change_request_id="117", event="candidate_written", detail="Rule allow-pigeontrack-web-inbound created in candidate config", scm_reference="rule-0211")`
>
> Tool call: `write_config_file(filename="allow-pigeontrack-web-inbound.yaml", file_type="security_rule", content="""
> schema_version: 1
> name: "allow-pigeontrack-web-inbound"
> description: "PigeonTrack — public web access to PigeonTrack portal from internet"
> from:
>   - "untrust-zone"
> to:
>   - "dmz"
> source:
>   - "any"
> source_user:
>   - "any"
> destination:
>   - "pigeontrack-server-10.20.0.50"
> service:
>   - "service-https"
> application:
>   - "ssl"
>   - "web-browsing"
> category:
>   - "any"
> action: "allow"
> tag:
>   - "firepilot-managed"
> log_end: true
> """)`
> Result: file_path="/output/allow-pigeontrack-web-inbound.yaml", file_type="security_rule", file_size=387

**Claude (internal):**
> *Step 7, iteration 2 of 3: Rule allow-pigeontrack-app-to-db.*
>
> Address pigeontrack-server-10.20.0.50 already created (addr-0201) — reuse.
> Address pigeontrack-db-10.30.0.10 does not exist — create first.
> Tool call: `create_address(ticket_id="117", folder="Shared", name="pigeontrack-db-10.30.0.10", ip_netmask="10.30.0.10/32", tag=["firepilot-managed"])`
> Result: id="addr-0202"
>
> Tool call: `create_security_rule(ticket_id="117", folder="Shared", position="pre", name="allow-pigeontrack-app-to-db", from=["dmz"], to=["db-zone"], source=["pigeontrack-server-10.20.0.50"], source_user=["any"], destination=["pigeontrack-db-10.30.0.10"], service=["tcp-5432"], application=["postgres"], category=["any"], action="allow", tag=["firepilot-managed"], log_end=true)`
> Result: id="rule-0212"
>
> Tool call: `add_audit_comment(change_request_id="117", event="candidate_written", detail="Rule allow-pigeontrack-app-to-db created in candidate config", scm_reference="rule-0212")`
>
> Tool call: `write_config_file(filename="allow-pigeontrack-app-to-db.yaml", file_type="security_rule", content="""
> schema_version: 1
> name: "allow-pigeontrack-app-to-db"
> description: "PigeonTrack — app server to PostgreSQL database in db-zone"
> from:
>   - "dmz"
> to:
>   - "db-zone"
> source:
>   - "pigeontrack-server-10.20.0.50"
> source_user:
>   - "any"
> destination:
>   - "pigeontrack-db-10.30.0.10"
> service:
>   - "tcp-5432"
> application:
>   - "postgres"
> category:
>   - "any"
> action: "allow"
> tag:
>   - "firepilot-managed"
> log_end: true
> """)`
> Result: file_path="/output/allow-pigeontrack-app-to-db.yaml", file_type="security_rule", file_size=379

**Claude (internal):**
> *Step 7, iteration 3 of 3: Rule allow-pigeontrack-internal-access.*
>
> Address pigeontrack-users-10.10.0.0-16 does not exist — create first.
> Tool call: `create_address(ticket_id="117", folder="Shared", name="pigeontrack-users-10.10.0.0-16", ip_netmask="10.10.0.0/16", tag=["firepilot-managed"])`
> Result: id="addr-0203"
>
> Address pigeontrack-server-10.20.0.50 already created (addr-0201) — reuse.
>
> Tool call: `create_security_rule(ticket_id="117", folder="Shared", position="pre", name="allow-pigeontrack-internal-access", from=["trust"], to=["dmz"], source=["pigeontrack-users-10.10.0.0-16"], source_user=["any"], destination=["pigeontrack-server-10.20.0.50"], service=["service-https"], application=["ssl", "web-browsing"], category=["any"], action="allow", tag=["firepilot-managed"], log_end=true)`
> Result: id="rule-0213"
>
> Tool call: `add_audit_comment(change_request_id="117", event="candidate_written", detail="Rule allow-pigeontrack-internal-access created in candidate config", scm_reference="rule-0213")`
>
> Tool call: `write_config_file(filename="allow-pigeontrack-internal-access.yaml", file_type="security_rule", content="""
> schema_version: 1
> name: "allow-pigeontrack-internal-access"
> description: "PigeonTrack — internal user access to PigeonTrack portal from trust zone"
> from:
>   - "trust"
> to:
>   - "dmz"
> source:
>   - "pigeontrack-users-10.10.0.0-16"
> source_user:
>   - "any"
> destination:
>   - "pigeontrack-server-10.20.0.50"
> service:
>   - "service-https"
> application:
>   - "ssl"
>   - "web-browsing"
> category:
>   - "any"
> action: "allow"
> tag:
>   - "firepilot-managed"
> log_end: true
> """)`
> Result: file_path="/output/allow-pigeontrack-internal-access.yaml", file_type="security_rule", file_size=403

**Claude (internal):**
> *Step 7a: Write rulebase manifest.*
>
> Existing rules from Step 4: deny-direct-db-access
>
> Tool call: `write_config_file(filename="_rulebase.yaml", file_type="rulebase_manifest", content="""
> schema_version: 1
> folder: "Shared"
> position: "pre"
> rule_order:
>   - deny-direct-db-access
>   - allow-pigeontrack-web-inbound
>   - allow-pigeontrack-app-to-db
>   - allow-pigeontrack-internal-access
> """)`
> Result: file_path="/output/_rulebase.yaml", file_type="rulebase_manifest", file_size=172

Processing complete. 3 configuration files + 1 manifest written
(allow-pigeontrack-web-inbound.yaml, allow-pigeontrack-app-to-db.yaml,
allow-pigeontrack-internal-access.yaml, _rulebase.yaml). The workflow
infrastructure commits them, opens a PR, and CI validation triggers
automatically.

---

## Annotations

- **Confident tier**: All 3 rules extracted from the PDF mapped to valid zones
  in firepilot.yaml with no ambiguity. Claude did not ask any questions and did
  not skip any rules — every extracted rule proceeded through the full pipeline.
- **Zone mapping**: Document terminology (e.g., "public internet zone", "DMZ")
  was resolved against firepilot.yaml zone names verbatim (`untrust-zone`,
  `dmz`). All four zone names used (untrust-zone, dmz, db-zone, trust) are
  present in firepilot.yaml exactly as written.
- **Address object reuse**: `pigeontrack-server-10.20.0.50` is referenced by
  all three rules but created only once (iteration 1). Iterations 2 and 3 reuse
  the existing object. Claude tracks which objects were created within the same
  processing run and does not issue duplicate `create_address` calls.
- **Claude iterates Step 7 three times — once per validated rule. The loop is
  not optional; every validated rule must produce a `write_config_file` call.**
  Each iteration follows the same sequence: `create_address` (if needed) →
  `create_security_rule` → `add_audit_comment` → `write_config_file`.
- **Step 6 runs exactly once. Step 7 runs N times (here: 3). Step 7a runs once
  after all Step 7 iterations.** Creating the change request before any rules
  are written ensures every `create_security_rule` call is associated with the
  same ticket_id.
- **The analysis comment (Step 5) lists all 3 rules. The `write_config_file`
  calls (Step 7) write all 3 rules. There is a 1:1 correspondence between rules
  in the analysis and files written.** A rule that appears in the Step 5 table
  without a corresponding `write_config_file` call is an error.
- **YAML content (ADR-0007 compliance)**: Each rule file contains all required
  fields (`schema_version`, `name`, `from`, `to`, `source`, `source_user`,
  `destination`, `service`, `application`, `category`, `action`, `tag`). The
  `folder` and `position` fields are absent from rule files — they are derived
  from directory structure by the deployment pipeline. The `_rulebase.yaml`
  manifest carries `folder` and `position` and lists all pre-existing rules
  before the newly created ones to preserve evaluation order.
- **Step 5 is informational**: The analysis comment is posted for audit trail
  and requestor visibility. Claude does not wait for human confirmation before
  proceeding to Step 6.
