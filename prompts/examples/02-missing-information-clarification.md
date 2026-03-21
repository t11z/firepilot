# Example: Partial Processing — Document-Based Extraction with Skipped Rules

This example demonstrates how Claude handles a document-based request
where most rules can be extracted and processed, but one rule
references a zone that does not exist in firepilot.yaml.

---

## Scenario

A business user from Network Engineering attaches a PDF describing
connectivity requirements for a new microservices deployment. The PDF
specifies five firewall rules. Four rules map cleanly to zones defined
in firepilot.yaml. The fifth references a zone named "STAGING" that
does not exist in the configuration.

---

## Conversation

**User (GitHub Issue — document_based mode):**
> Application: Payments Platform v2
> Request Mode: document_based
> Supporting Documentation: [attached: payments-platform-network-requirements.pdf]
> Business Justification: Microservices migration for Payments Platform v2. All rules defined in the attached architecture document.

**Claude (internal — not shown to user):**
> *Step 1: Extract requirements from attached PDF.*
>
> Extracted rules:
>
> 1. Allow HTTPS from web-zone (10.1.0.0/24) to app-zone (10.2.0.0/24) — payments-api
> 2. Allow MySQL from app-zone (10.2.0.0/24) to db-zone (10.3.0.0/24) — payments-db
> 3. Allow HTTPS from app-zone (10.2.0.0/24) to external-zone (203.0.113.10/32) — fraud-detection API
> 4. Allow TLS from dmz-zone (10.0.0.0/24) to app-zone (10.2.0.0/24) — load balancer health checks
> 5. Allow HTTPS from STAGING (10.99.0.0/24) to app-zone (10.2.0.0/24) — staging integration tests
>
> Checking zone mappings against firepilot.yaml zones:
> - web-zone → present ✓
> - app-zone → present ✓
> - db-zone → present ✓
> - external-zone → present ✓
> - dmz-zone → present ✓
> - STAGING → NOT FOUND — no zone with this name or role exists in firepilot.yaml
>
> Rules 1–4: proceed to Steps 2–4.
> Rule 5: skip — zone cannot be resolved.

**Claude (internal):**
> *Steps 2–4 for Rules 1–4 (executed independently per rule):*
>
> Rule 1 (allow-payments-web-to-app):
> - Zones validated ✓
> - Addresses: web-subnet-10.1.0.0-24 ✓, app-subnet-10.2.0.0-24 ✓
> - No conflict detected ✓
>
> Rule 2 (allow-payments-app-to-db):
> - Zones validated ✓
> - Addresses: app-subnet-10.2.0.0-24 ✓, db-subnet-10.3.0.0-24 ✓
> - No conflict detected ✓
>
> Rule 3 (allow-payments-app-to-fraud-api):
> - Zones validated ✓
> - Address 203.0.113.10/32: no existing object — will create
>   payments-fraud-api-203.0.113.10 in Phase 2
> - No conflict detected ✓
>
> Rule 4 (allow-payments-dmz-to-app):
> - Zones validated ✓
> - Addresses: dmz-subnet-10.0.0.0-24 ✓, app-subnet-10.2.0.0-24 ✓
> - No conflict detected ✓

**Claude → Issue comment (Step 5 — analysis comment):**
> ## FirePilot Analysis — Partial Processing
>
> Extracted 5 rules from `payments-platform-network-requirements.pdf`.
> 4 rules validated successfully and will be created. 1 rule was
> skipped (see below).
>
> ### Rules to be created
>
> | # | Rule name                        | Source                        | Destination                  | App/Service | Action |
> |---|----------------------------------|-------------------------------|------------------------------|-------------|--------|
> | 1 | allow-payments-web-to-app        | web-zone / 10.1.0.0/24        | app-zone / 10.2.0.0/24       | ssl, web-browsing | Allow |
> | 2 | allow-payments-app-to-db         | app-zone / 10.2.0.0/24        | db-zone / 10.3.0.0/24        | mysql       | Allow  |
> | 3 | allow-payments-app-to-fraud-api  | app-zone / 10.2.0.0/24        | external-zone / 203.0.113.10 | ssl         | Allow  |
> | 4 | allow-payments-dmz-to-app        | dmz-zone / 10.0.0.0/24        | app-zone / 10.2.0.0/24       | ssl         | Allow  |
>
> Rule 3 requires creation of address object
> `payments-fraud-api-203.0.113.10`.
>
> ### Skipped Rules
>
> | # | Description                              | Reason                                                                              |
> |---|------------------------------------------|-------------------------------------------------------------------------------------|
> | 5 | HTTPS from STAGING to app-zone           | Rule skipped: no zone named "STAGING" or with role "staging" exists in firepilot.yaml. To include this rule, open a follow-up issue after the STAGING zone has been provisioned. |
>
> Proceeding to change request creation for the 4 valid rules.

**Claude (internal):**
> *Step 6: Create change request.*
> Tool call: `create_change_request(title="Payments Platform v2 — network connectivity rules (partial)", description="4 of 5 rules from payments-platform-network-requirements.pdf. Rule 5 skipped: STAGING zone not found.", requestor="Network Engineering")`
> Result: change_request_id="91"

**Claude (internal):**
> *Step 7: Create rules 1–4.*
>
> Rule 3: address object does not exist — create first.
> Tool call: `create_address(ticket_id="91", folder="Shared", name="payments-fraud-api-203.0.113.10", ip_netmask="203.0.113.10/32", tag=["firepilot-managed"])`
> Result: id="addr-0099"
>
> Tool call: `create_security_rule(ticket_id="91", folder="Shared", position="pre", name="allow-payments-web-to-app", ...)`
> Result: id="rule-0101"
> Tool call: `add_audit_comment(change_request_id="91", event="candidate_written", detail="Rule allow-payments-web-to-app", scm_reference="rule-0101")`
>
> [repeated for rules 2, 3, 4]

Processing complete. The workflow infrastructure commits the YAML,
opens a PR, and CI validation triggers automatically.

---

## Annotations

- **Partial processing**: 4 of 5 rules were valid. Claude committed
  the 4 valid rules without asking any questions or waiting for input.
- **Skipped rule**: Rule 5 was skipped because the "STAGING" zone does
  not exist in firepilot.yaml. The analysis comment explains why and
  tells the requestor how to resolve it (open a follow-up issue after
  the zone is provisioned).
- **No question asked**: Claude did not pause to ask whether to proceed
  with the partial set. The autonomous processing directive requires
  committing valid rules and documenting skipped ones.
- **Audit trail**: The change request description records that only 4
  of 5 rules were created, preserving visibility for reviewers.
- **Follow-up**: The requestor can open a new issue for rule 5 once
  the STAGING zone has been added to firepilot.yaml.
