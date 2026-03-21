# ADR-0014: Enforce Autonomous Processing in the Asynchronous Issue Workflow

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0014                                                              |
| Title         | Enforce Autonomous Processing in the Asynchronous Issue Workflow      |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-21                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

The FirePilot system prompt (`prompts/system-prompt.md`) was
originally written for an interactive, synchronous context — a
conversation where Claude can ask clarifying questions and receive
immediate answers. ADR-0009 moved the intake interface to GitHub
Issues, and ADR-0010 eliminated the comment-based approval gate in
favour of direct commit to a feature branch with PR-based review.

In the current architecture, Claude is invoked by a GitHub Actions
workflow (`process-firewall-request.yml`) in a single, unattended
run. There is no human in the loop during processing. The agentic
loop (ADR-0013) runs tool calls iteratively, but the conversation
partner is the tool infrastructure, not a human. Any question Claude
poses in an issue comment is a dead end — no mechanism exists to
resume processing after a human responds.

This mismatch caused a concrete failure: issue #34 (PigeonTrack,
`document_based` mode) was processed correctly — Claude extracted
all 7 rules, mapped zones successfully, and presented a valid
summary table. Then Claude asked "Would you like me to proceed with
creating all 7 rules, or would you prefer to review specific rules
first?" and the workflow set `firepilot:rejected`. The rules were
never committed. The request was dead.

The root cause is that the system prompt contains multiple
interactive directives that conflict with the asynchronous execution
model:

| Prompt directive | Step | Conflict |
|---|---|---|
| "Ask the user for explicit confirmation before proceeding" | 5 | No human to confirm; blocks rule creation |
| "Tell the user... wait for approval" | 8 | Approval is PR-based (ADR-0010), not in-conversation |
| "Poll for approval... wait for the user to prompt you" | 9 | Polling loop eliminated by ADR-0010 |
| "If the mapping is ambiguous, list the available zones and ask" | doc-based | Blocks extraction even when mapping succeeds |
| "If the Additional Rules field is ambiguous, Claude posts a clarification request" | multi-rule | Blocks processing; no resume mechanism |
| "If information is missing, ask" | Identity | General-purpose interactive assumption |

The issue is not that Claude lacks intelligence to decide — it
demonstrably had enough information. The issue is that the prompt
instructs Claude to defer to a human who is not present.

In scope: the system prompt's decision authority model, the
conditions under which Claude may ask questions vs. must decide
autonomously, and the rejection criteria. The label semantics
(`firepilot:rejected`) are in scope insofar as the rejection
trigger conditions change.

Out of scope: the agentic loop implementation (ADR-0013), the
CI/CD pipeline (ADR-0003), the MCP tool interfaces (ADR-0004,
ADR-0005), the issue intake flow (ADR-0009 submission section),
and prompt caching (ADR-0013 — the system prompt content changes
but the caching mechanism is unaffected; the static prefix is
still static).

---

## Decision

We will restructure the system prompt to enforce autonomous
decision-making within defined policy boundaries, because Claude
operates in an asynchronous, unattended workflow where interactive
clarification is architecturally impossible and any question
terminates the processing run.

The system prompt will replace all interactive confirmation
directives with a three-tier decision model:

- **Confident**: All extracted information is unambiguous and
  passes validation (Steps 2–4). Claude commits the generated
  YAML to a feature branch and opens a PR. No confirmation
  requested. The analysis comment on the issue documents the
  reasoning, proposed rules, and any warnings — for audit trail
  purposes, not as a gate.

- **Partial**: Some rules are fully specified and valid; others
  are ambiguous or incomplete. Claude commits the valid rules and
  documents the skipped rules in the analysis comment with
  specific reasons (e.g., "Rule for traffic to 'STAGING' skipped:
  no matching zone in firepilot.yaml"). The issue is not rejected.
  A PR is opened for the valid subset.

- **Unprocessable**: The request as a whole cannot be interpreted
  — no rules can be extracted, required fields are empty across
  all modes, or the attached document contains no identifiable
  firewall requirements. Claude posts a rejection comment with a
  specific, actionable explanation of what is missing or
  uninterpretable. The issue receives `firepilot:rejected`. No
  branch or PR is created.

Steps 8–9 (approval waiting and polling) are removed from the
system prompt entirely, consistent with ADR-0010.

Step 5 is rewritten: Claude presents the proposed rules in the
analysis comment (unchanged for audit trail), but does not ask
for confirmation. The comment is informational.

---

## Considered Alternatives

#### Option A: Status quo — interactive prompt in asynchronous workflow

- **Description**: Keep the current system prompt with its
  interactive directives. Accept that `document_based` and
  `multiple_rules` requests may be rejected when Claude asks a
  question no one can answer.
- **Pros**: No prompt changes required; conservative — every
  ambiguity is surfaced to a human.
- **Cons**: Structurally broken. The workflow has no resume
  mechanism. Every question is a rejection. Complex requests
  (document-based with multiple rules) are the most likely to
  trigger questions and the most valuable to process. The system
  fails precisely where it should succeed.

#### Option B: Two-pass workflow — clarification then re-trigger

- **Description**: If Claude asks a question, the workflow posts
  the question as an issue comment and exits without setting
  `firepilot:rejected`. A second workflow triggers when a human
  responds (issue comment event), re-invoking Claude with the
  updated context.
- **Pros**: Preserves interactive clarification capability;
  handles genuinely ambiguous requests; no information is lost.
- **Cons**: Significant implementation complexity — requires a
  new workflow trigger, conversation state management across
  runs, and deduplication logic to prevent infinite loops.
  Claude's context window does not persist across workflow runs;
  the entire issue body, attachments, and previous comments must
  be re-injected. Increases API cost (two full agentic loops
  per request). Adds a new label state (`firepilot:clarification`
  or similar). The benefit is marginal — the vast majority of
  requests either have enough information or are genuinely
  unprocessable.

#### Option C: Autonomous processing with tiered outcomes *(chosen)*

- **Description**: Restructure the system prompt to make Claude
  the decision authority within policy boundaries. Claude never
  asks for confirmation. It processes what it can, skips what it
  cannot with documented reasoning, and only rejects when nothing
  is processable. The human review point is the PR, not the issue
  comment.
- **Pros**: Eliminates the structural dead end. Complex requests
  (document-based, multi-rule) are processed end-to-end in a
  single run. Partial results are better than no results — the PR
  reviewer can assess completeness. Rejection is reserved for
  genuinely unprocessable requests. Consistent with ADR-0010's
  design intent (direct commit, PR-based review). No new workflow
  triggers, labels, or state management required.
- **Cons**: Claude may commit rules that a human would have
  questioned before creation. Mitigation: CI Gates 1–3 catch
  policy violations; PR review catches intent mismatches; the
  analysis comment provides full reasoning transparency. A rule
  that Claude creates incorrectly from an ambiguous document is
  caught at the same point where a rule created after
  "confirmation" would be caught — the PR review.

---

## Rationale

The evaluation criteria are: workflow completeness (does the
request produce an outcome?), architectural consistency (does the
prompt match the execution model?), and assurance quality (is the
human review point effective?).

Option A fails on workflow completeness. The system is designed to
process firewall change requests end-to-end. A prompt that causes
the system to stop and wait for input that will never arrive is an
architectural defect, not a safety feature. The "safety" of asking
a question is illusory — the question is never answered, so the
request is silently dropped.

Option B addresses the structural problem but at disproportionate
cost. The re-trigger mechanism introduces state management
complexity, a new workflow file, a new label, and doubles the API
cost for every ambiguous request. The benefit — handling the edge
case where Claude genuinely cannot interpret a request — is better
served by the rejection path in Option C.

Option C aligns the prompt with the execution model. Claude is
already the decision authority for zone mapping, conflict
detection, and rule generation. Extending that authority to
"proceed or skip" decisions is a natural consequence of the
asynchronous architecture. The human review point (PR) is
unchanged and is strictly stronger than a comment-based
confirmation: the PR includes CI validation results, a
reviewable diff, and the full analysis comment.

The partial-processing tier is the key differentiator. In the
PigeonTrack scenario, Claude extracted 7 rules. If 6 were
unambiguous and 1 had a zone mapping problem, the correct
behaviour is to commit 6 rules and document the skip — not to
reject all 7. The PR reviewer sees exactly what was committed
and what was not, and can request a follow-up issue for the
skipped rule.

ADR-0013 (Prompt Caching) is unaffected: the system prompt
content changes but remains a static string within a single
agentic loop run. The cache breakpoint on the system prompt
block works identically.

---

## Consequences

- **Positive**: `document_based` and `multiple_rules` requests
  are processed end-to-end without dead-end questions. The
  PigeonTrack demo scenario completes successfully.
- **Positive**: The system prompt is consistent with the
  execution model established by ADR-0009 and ADR-0010. No
  more interactive directives in an asynchronous workflow.
- **Positive**: Partial processing produces partial results
  instead of total rejection — strictly more useful for the
  requestor and the PR reviewer.
- **Positive**: `firepilot:rejected` carries clear semantics:
  "nothing was processable." It is no longer triggered by
  Claude asking a question.
- **Negative**: Claude may commit rules based on ambiguous input
  that a human might have questioned. Mitigation: CI validation
  (Layer 3) catches policy violations independently; the PR
  analysis comment documents all reasoning and warnings; the PR
  reviewer has full context.
- **Negative**: The system prompt loses the ability to handle
  genuinely interactive scenarios (e.g., a future web UI or
  chat-based interface). Mitigation: the prompt's decision model
  is context-dependent — a future ADR could introduce a
  `processing_mode` parameter (`autonomous` vs `interactive`)
  that selects the appropriate directive set. This ADR does not
  preclude that extension.
- **Follow-up required**: Rewrite `prompts/system-prompt.md` —
  remove Steps 8–9 entirely; rewrite Step 5 as informational
  (no confirmation request); replace all "ask the user" / "ask
  the requestor" directives with autonomous decision logic;
  add the three-tier decision model (confident / partial /
  unprocessable) as a named section.
- **Follow-up required**: Update
  `prompts/examples/02-missing-information-clarification.md` —
  the current example demonstrates a clarification loop that is
  no longer valid in the asynchronous workflow. Replace with an
  example demonstrating the partial-processing behaviour.
- **Follow-up required**: Add a new prompt example demonstrating
  the `unprocessable` rejection path with a specific, actionable
  rejection comment.
- **Follow-up required**: Update the threat model (T1 — Prompt
  Injection) — the "user confirmation" step is no longer a
  mitigation. The analysis comment and PR review remain. Assess
  whether the removal of the confirmation step changes the
  residual risk assessment.
- **Follow-up required**: Validate that the PigeonTrack demo
  scenario (issue #34 equivalent) completes end-to-end with the
  updated prompt.

---

## Compliance & Security Considerations

- **Separation of Duties**: Unchanged. Claude generates
  configuration. A human (PR reviewer) approves it. The removal
  of the in-conversation confirmation step does not weaken
  separation — ADR-0010 already established that the PR is the
  sole approval gate. The confirmation question in the issue
  comment was never an enforceable gate (no access control, no
  branch protection).
- **Audit Trail**: Strengthened for partial processing. The
  analysis comment now documents not only what was proposed but
  also what was skipped and why. Previously, a rejected request
  produced only a question — no record of what Claude *could*
  have processed.
- **Defence in Depth**: Layer 2 (Claude) remains responsible for
  intent validation, conflict detection, and zone verification.
  The change affects *when* Claude acts on its findings (immediately
  vs. after confirmation), not *whether* it performs the checks.
  Layers 3 (OPA, JSON Schema) and 4 (MCP server-side) are
  unaffected.
- **Threat Model Impact**: T1 (Prompt Injection) — the interactive
  confirmation step is removed as a mitigation. However, this step
  was weak: in the asynchronous workflow, the "confirmation" was
  never received, so it provided no actual protection. The PR
  review gate (human approval of the diff + CI results) is the
  effective control and is unchanged. T2 (Malicious PDF) — no
  change; the PDF processing pipeline and downstream validation
  are unaffected.

---

## Review Trigger

- If FirePilot introduces a synchronous interface (web UI, chat)
  alongside the GitHub Issue workflow, revisit this decision to
  support a dual-mode prompt (autonomous + interactive).
- If partial-processing commits produce a high rate of CI failures
  or PR rejections due to incomplete rule sets, consider whether
  the "partial" tier needs tighter constraints on what qualifies
  as committable.
- If a two-pass clarification workflow (Option B) is implemented
  for other reasons, reconsider whether the autonomous-only model
  is still optimal.
