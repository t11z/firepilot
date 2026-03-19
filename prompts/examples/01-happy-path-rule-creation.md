# Example: Happy Path — New Firewall Rule Creation

This example demonstrates the full workflow from user request to deployed rule with no errors or missing information.

---

## Scenario

A business user from Platform Engineering requests HTTPS access from the web zone to the application zone for a new customer portal.

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

**Claude → User:**
> Here's the rule I'll create for your customer portal:
>
> | Field         | Value                                        |
> |---------------|----------------------------------------------|
> | Rule name     | allow-web-to-app                             |
> | Action        | Allow                                        |
> | Source zone   | web-zone                                     |
> | Source address| web-subnet-10.1.0.0-24 (10.1.0.0/24)        |
> | Dest. zone   | app-zone                                     |
> | Dest. address | app-subnet-10.2.0.0-24 (10.2.0.0/24)        |
> | Applications  | SSL, Web Browsing                            |
> | Service       | application-default                          |
> | Logging       | Session end                                  |
> | Profile       | best-practice                                |
>
> I'll also create a change request for approval tracking.
> Shall I proceed?

**User:**
> Yes, go ahead.

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

**Claude → User:**
> Done. The rule has been written to the candidate configuration.
>
> **Next step**: The change request needs approval before the rule
> goes live. You can review and approve it here:
> https://github.com/.../issues/43
>
> Let me know once it's approved, and I'll deploy it.

**User:**
> It's been approved. Please deploy.

**Claude (internal):**
> *Step 9: Poll for approval.*
> Tool call: `get_change_request(change_request_id="43")`
> Result: status="approved" ✓

**Claude (internal):**
> *Step 10: Push candidate config.*
> Tool call: `add_audit_comment(change_request_id="43", event="push_initiated", detail="Pushing candidate config to running")`
> Tool call: `push_candidate_config(ticket_id="43", folders=["Shared"])`
> Result: job_id="1234", status_str="FIN", result_str="OK"

**Claude (internal):**
> *Step 11: Verify and close.*
> Tool call: `add_audit_comment(change_request_id="43", event="push_succeeded", detail="Push completed successfully", scm_reference="1234")`
> Tool call: `update_change_request_status(change_request_id="43", status="deployed")`

**Claude → User:**
> The rule is now live. HTTPS traffic from the web zone to the app
> zone is permitted.
>
> Change request #43 has been closed as deployed.

---

## Annotations

- **Step 1**: All required fields were present in the initial message.
  No clarification needed. In practice, users often omit the
  justification or the specific subnets — Claude must ask.
- **Step 3**: Existing address objects were found and reused. If none
  had existed, Claude would use raw CIDR notation in the rule.
- **Step 4**: Conflict check found no issues. If a shadowing rule
  existed, Claude would explain the conflict before proceeding.
- **Step 5**: The user saw a human-readable summary, not YAML. Field
  names are translated (e.g. "Dest. zone" not "to").
- **Step 9**: The user reported approval verbally. Claude verified
  via tool call — it did not trust the user's statement alone.
- **Step 11**: Both audit trail entries (push_succeeded + status
  update) are recorded before reporting success to the user.
