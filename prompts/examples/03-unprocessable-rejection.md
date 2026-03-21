# Example: Unprocessable Request — Rejection with Actionable Feedback

This example demonstrates how Claude handles a single_rule request
where the required technical fields are all empty or contain only
placeholder text, making it impossible to extract any rule.

---

## Scenario

A business user submits a firewall change request using the
single_rule mode. The issue template was filled out minimally: the
application name and justification are present, but Source Zone,
Destination Zone, and Ports all contain placeholder text ("TBD").

---

## Conversation

**User (GitHub Issue — single_rule mode):**
> Application: Inventory Service
> Request Mode: single_rule
> Source Zone: TBD
> Destination Zone: TBD
> Source Address: TBD
> Destination Address: TBD
> Ports/Protocols: TBD
> Action: allow
> Business Justification: New inventory service needs network access.

**Claude (internal — not shown to user):**
> *Step 1: Extract requirements.*
>
> - Source zone: "TBD" — not a valid zone name, treated as empty
> - Destination zone: "TBD" — not a valid zone name, treated as empty
> - Source address: "TBD" — not a valid address, treated as empty
> - Destination address: "TBD" — not a valid address, treated as empty
> - Ports/Protocols: "TBD" — not a valid specification, treated as empty
> - Action: allow ✓
> - Justification: "New inventory service needs network access." ✓
>
> Source Zone, Destination Zone, and Ports are all empty or contain
> placeholders. No rule can be extracted.
>
> Decision: UNPROCESSABLE — single_rule request with empty required
> technical fields. Apply unprocessable path: post rejection comment
> and label issue firepilot:rejected. Do not proceed to Steps 2–7.

**Claude → Issue comment (rejection comment):**
> ## FirePilot — Request Cannot Be Processed
>
> This request cannot be processed because the required technical
> fields are empty or contain placeholder values.
>
> ### Missing Fields
>
> | Field             | Submitted value | Required                                                   |
> |-------------------|-----------------|------------------------------------------------------------|
> | Source Zone       | TBD             | A zone name from the firepilot.yaml zone topology (e.g., `web-zone`, `app-zone`) |
> | Destination Zone  | TBD             | A zone name from the firepilot.yaml zone topology (e.g., `db-zone`, `dmz-zone`) |
> | Source Address    | TBD             | A specific IP address, subnet (CIDR), or FQDN (e.g., `10.2.0.0/24`) |
> | Destination Address | TBD           | A specific IP address, subnet (CIDR), or FQDN (e.g., `10.3.0.50`) |
> | Ports/Protocols   | TBD             | Specific port(s) and protocol (e.g., `tcp/443`, `tcp/3306`, or a named application such as `mysql`) |
>
> ### What to do next
>
> 1. Identify the specific zones, addresses, and ports for the
>    Inventory Service connectivity requirement.
> 2. Close this issue and open a new one with the complete technical
>    details filled in.
>
> If you are unsure which zones apply, consult the network topology
> documentation or contact your network engineering team. FirePilot
> cannot select or infer zones on your behalf.

**Claude (internal):**
> Apply label `firepilot:rejected` to the issue.
> Processing run complete — no rules created, no change request opened.

---

## Annotations

- **Rejection is specific**: The rejection comment lists every missing
  field by name, shows what was submitted, and states exactly what is
  required. The requestor knows precisely what to fix.
- **Actionable feedback**: The comment tells the requestor what to do
  next (close the issue and open a new one with complete details). It
  does not leave them guessing.
- **No question asked**: Claude does not ask the requestor to fill in
  the fields in a follow-up comment. The workflow is asynchronous —
  there is no interactive loop. The rejection terminates this run.
- **No change request opened**: Because no rule can be extracted, no
  ITSM change request is created. There is no partial state to clean up.
- **Label applied**: The `firepilot:rejected` label signals to the
  requestor and to any monitoring tooling that this issue requires
  resubmission, not further action on the current issue.
