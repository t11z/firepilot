# Example: Missing Information — Clarification Loop

This example demonstrates how Claude handles an incomplete request where security-relevant fields are missing.

---

## Scenario

A user requests a firewall rule but provides insufficient detail.

---

## Conversation

**User:**
> We need to open access to the database for the new reporting tool.

**Claude → User:**
> I can help with that. I need a few more details to create the right
> rule:
>
> 1. **Source**: Where will the reporting tool connect from? Which
>    zone and subnet?
> 2. **Database address**: Which database servers specifically?
>    Subnet or IP range?
> 3. **Application**: What protocol does the reporting tool use to
>    connect? (e.g. MySQL, PostgreSQL, HTTPS)
> 4. **Action**: I assume you want to *allow* this traffic — correct?

**User:**
> It's coming from the app zone, subnet 10.2.0.0/24. Going to the
> database zone on 10.3.0.0/24. It uses MySQL. And yes, allow.

**Claude (internal):**
> *Step 1 complete:*
> - Source zone: app-zone, source address: 10.2.0.0/24
> - Destination zone: db-zone, destination address: 10.3.0.0/24
> - Application: mysql
> - Action: allow
> - Justification: not yet provided — must ask.

**Claude → User:**
> Got it. One more thing — I need a brief business justification for
> the change request. Something like "Reporting tool requires direct
> MySQL access to production database for scheduled report generation."
> What should I record?

**User:**
> The BI team needs direct query access for their weekly dashboards.

**Claude (internal):**
> Justification captured. Proceed to Step 2.

**Claude (internal):**
> *Step 2: Validate zones.*
> Tool call: `list_security_zones(folder="Shared")`
> Result: app-zone ✓, db-zone ✓

**Claude (internal):**
> *Step 3: Check addresses.*
> Tool call: `list_addresses(folder="Shared")`
> Result: `app-subnet-10.2.0.0-24` ✓, `db-subnet-10.3.0.0-24` ✓

**Claude (internal):**
> *Step 4: Check conflicts.*
> Tool call: `list_security_rules(folder="Shared", position="pre")`
> Result: `allow-app-to-db` already exists — same zone pair, same
>         application (mysql), same source and destination addresses.
>         This is an exact duplicate.

**Claude → User:**
> I found an existing rule that already covers this access:
>
> **allow-app-to-db** — Allows MySQL traffic from app-zone
> (10.2.0.0/24) to db-zone (10.3.0.0/24). This rule is already
> active.
>
> The access your BI team needs is already permitted. No new rule is
> required. Would you like me to help with anything else?

---

## Annotations

- **Step 1**: Claude did not assume any field values. Source zone,
  address, application, and action were all explicitly requested.
- **Justification**: Claude asked for the justification separately
  rather than making one up.
- **Step 4**: The conflict check detected an exact duplicate. Claude
  stopped the workflow and informed the user instead of creating a
  redundant rule. This is the correct behaviour — the workflow does
  not always end with rule creation.
