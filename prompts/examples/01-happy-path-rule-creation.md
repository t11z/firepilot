# Example: Happy Path — New Firewall Rule Creation

This example demonstrates the full workflow from issue intake to rule
committed in candidate configuration, with no errors or missing
information.

---

## Scenario

A business user from Platform Engineering requests HTTPS access from
the web zone to the application zone for a new customer portal.

---

## Conversation

**User:**
> We're launching a new customer portal next week. We need to allow
> HTTPS traffic from the web zone to the app zone. The web servers
> are on 10.1.0.0/24 and the app servers are on 10.2.0.0/24.

**Claude (internal — not shown to user):**
> *Step 1: Extract requirements.*
> - Source zone: web-zone
> - Source address: 10.1.0.0/24
> - Destination zone: app-zone
> - Destination address: 10.2.0.0/24
> - Application: ssl, web-browsing (HTTPS)
> - Action: allow
> - Justification: customer portal launch
>
> All required fields present. Proceed to validation.

**Claude (internal):**
> *Step 2: Validate zones.*
> Tool call: `list_security_zones(folder="Shared")`
> Result: web-zone ✓, app-zone ✓ — both exist.

**Claude (internal):**
> *Step 3: Check address objects.*
> Tool call: `list_addresses(folder="Shared")`
> Result: `web-subnet-10.1.0.0-24` matches 10.1.0.0/24 ✓
>         `app-subnet-10.2.0.0-24` matches 10.2.0.0/24 ✓
> Will reference existing address objects by name.

**Claude (internal):**
> *Step 4: Check for conflicts.*
> Tool call: `list_security_rules(folder="Shared", position="pre")`
> Result: No existing rule covers web-zone → app-zone for ssl/web-browsing.
>         `deny-direct-db-access` is unrelated (untrust → db-zone).
>         No conflict detected.

**Claude → Issue comment (Step 5 — analysis comment):**
> ## FirePilot Analysis — Proposed Rule
>
> All validation checks passed. The following rule will be created:
>
> | Field          | Value                                        |
> |----------------|----------------------------------------------|
> | Rule name      | allow-web-to-app                             |
> | Action         | Allow                                        |
> | Source zone    | web-zone                                     |
> | Source address | web-subnet-10.1.0.0-24 (10.1.0.0/24)        |
> | Dest. zone     | app-zone                                     |
> | Dest. address  | app-subnet-10.2.0.0-24 (10.2.0.0/24)        |
> | Applications   | SSL, Web Browsing                            |
> | Service        | application-default                          |
> | Logging        | Session end                                  |
> | Profile        | best-practice                                |
> | Position       | pre                                          |
>
> No conflicts detected. Proceeding to change request creation.

**Claude (internal):**
> *Step 6: Create change request.*
> Tool call: `create_change_request(title="Allow HTTPS from web-zone to app-zone for customer portal", description="...", config_reference="pending", requestor="Platform Engineering")`
> Result: change_request_id="43", url="https://github.com/.../issues/43"

**Claude (internal):**
> *Step 7: Create security rule.*
> Tool call: `create_security_rule(ticket_id="43", folder="Shared", position="pre", name="allow-web-to-app", ...)`
> Result: id="00000000-0000-0000-0000-000000000004"
>
> Tool call: `add_audit_comment(change_request_id="43", event="candidate_written", detail="Rule allow-web-to-app created in candidate config", scm_reference="00000000-0000-0000-0000-000000000004")`

Processing complete. The workflow infrastructure commits the YAML,
opens a PR, and CI validation triggers automatically.

---

## Annotations

- **Step 1**: All required fields were present in the initial message.
  No clarification needed or sought — the workflow proceeds autonomously.
- **Step 3**: Existing address objects were found and reused. If none
  had existed, Claude would have created them before Step 7.
- **Step 4**: Conflict check found no issues. If a duplicate rule had
  been detected, Claude would skip it and document the reason in the
  analysis comment.
- **Step 5**: The analysis comment is posted for audit trail purposes.
  It is informational — Claude does not wait for confirmation before
  proceeding to Step 6.
- **Steps 6–7**: Change request created and rule written to candidate
  config. The processing run ends here. Branch creation, PR opening,
  and deployment are handled by the workflow infrastructure.
