# ADR-0010: Eliminate Comment-Based Approval Gate — Direct Commit After Processing

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0010                                                              |
| Title         | Eliminate Comment-Based Approval Gate — Direct Commit After Processing |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-20                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

The current FirePilot request flow has two sequential human approval
gates:

1. **Issue-level approval**: Claude posts a YAML proposal as an issue
   comment. A human reviews the comment and sets the
   `firepilot:approved` label. This triggers `approve-and-commit.yml`,
   which runs `extract_yaml_from_comment.py` to parse YAML from the
   Markdown comment, strip placement hints, write the rule file, and
   open a PR.

2. **PR-level approval**: The PR triggers `validate.yml` (Gates 1–3:
   JSON Schema, OPA, dry-run). A human reviews the PR diff and
   validation results, then merges. Merge triggers `deploy.yml`
   (Gates 1–4).

Gate 1 is architecturally redundant. The human reviews YAML in a
comment without the benefit of CI validation — they are eyeballing
configuration syntax. The same YAML then undergoes rigorous automated
validation on the PR, where a second human reviews it *with* CI
results. The first gate adds process overhead without adding
assurance.

The comment-based flow also introduces a fragile intermediate step:
`extract_yaml_from_comment.py` must parse fenced YAML from Markdown
prose using regex, discriminate security rules from other YAML blocks,
extract and strip placement hints (`folder`, `position`) that violate
ADR-0007 if committed, and propagate metadata through GitHub Actions
outputs. This is a Markdown-to-structured-data parser sitting in a
security-critical pipeline — an unnecessary attack surface and
maintenance liability.

The `firepilot:approved` label conflates two concepts: "this request
is legitimate" and "this configuration is correct." The first is a
business decision; the second is an engineering decision backed by CI.
Collapsing both into a single label on a pre-CI comment weakens both.

Additionally, the `firepilot:approved` label is coupled to a polling
mechanism in ADR-0005 where Claude polls `get_change_request` until
the issue carries the `firepilot:approved` label. In the new flow,
Claude does not wait for approval — it processes the request, commits
the result, and the approval happens on the PR. The polling loop
becomes unnecessary.

In scope: the workflow sequence from Claude's processing result to PR
creation, the role of the `firepilot:approved` label, and the
elimination of the approval polling mechanism.

Out of scope: the `mcp-itsm` tool interface definition (ADR-0005 tool
contracts remain valid), the CI/CD pipeline structure (ADR-0003), the
issue intake flow (ADR-0009 intake and trigger sections).

---

## Decision

We will eliminate the comment-based approval gate and the
`firepilot:approved` label. After Claude processes a firewall change
request and produces a valid configuration, the processing workflow
will commit the generated YAML directly to a feature branch and open
a PR. The PR — with CI validation results — becomes the sole human
approval artefact. If Claude rejects the request, no PR is created;
the rejection is documented as an issue comment and the issue receives
the `firepilot:rejected` label.

The `firepilot:approved` label is removed from the label set entirely.
The remaining labels are: `firepilot:pending`, `firepilot:rejected`,
`firepilot:deployed`, `firepilot:failed`.

---

## Considered Alternatives

#### Option A: Status quo — comment-based approval then PR

- **Description**: Claude posts YAML in a comment, human labels
  `firepilot:approved`, workflow extracts YAML and opens PR, human
  reviews and merges PR
- **Pros**: Two explicit human checkpoints; conservative approach
- **Cons**: Redundant approval gate; regex-based YAML extraction from
  Markdown is fragile; human reviews raw YAML without CI feedback;
  `firepilot:approved` label conflates business legitimacy with
  configuration correctness; `extract_yaml_from_comment.py` is a
  maintenance liability with no architectural value; approval polling
  loop adds complexity to Claude's orchestration

#### Option B: Direct commit to feature branch after processing *(chosen)*

- **Description**: The processing workflow commits Claude's generated
  YAML directly to a feature branch and opens a PR. Claude still
  posts an analysis comment on the issue (validation summary,
  warnings, rationale) for audit trail purposes, but the YAML is
  committed to Git, not embedded in Markdown. The PR is the sole
  approval gate. If Claude determines the request is invalid, no
  PR is created — a rejection comment is posted on the issue instead
- **Pros**: Single, well-defined approval point with full CI context;
  eliminates Markdown parsing; placement is determined by the
  workflow, not extracted from comment hints; aligns with the
  principle that Git is the source of truth (ADR-0001) — the
  configuration enters Git immediately, not after a label toggle;
  reduces the number of workflow files and scripts; eliminates the
  approval polling loop
- **Cons**: Removes a pre-CI human checkpoint; a misconfigured Claude
  prompt could generate PRs from invalid requests before a human
  intervenes

#### Option C: Auto-commit but require issue-level triage before processing

- **Description**: Add a `firepilot:triaged` label that a human must
  set *before* Claude processes the request. After processing, direct
  commit to branch and PR as in Option B
- **Pros**: Human gate exists before any AI processing; prevents
  processing of spam or irrelevant issues
- **Cons**: Adds latency to the happy path; triage without AI analysis
  means the human has less context than after processing; the PR
  review already catches invalid configurations

---

## Rationale

The evaluation criteria are: assurance quality, pipeline simplicity,
and alignment with existing architectural decisions.

Option A's first approval gate provides weaker assurance than the
second. A human reviewing YAML in a comment has no schema validation,
no OPA policy evaluation, and no dry-run result. The PR review has all
three. The comment-level review is strictly dominated by the PR-level
review on every assurance dimension. Keeping it adds process cost
without security benefit.

Option C addresses the concern that Claude might process spam issues,
but this concern is better handled at the intake boundary — the Issue
Template and workflow trigger conditions — not by adding a manual gate
into the processing flow. If spam filtering is needed, a lightweight
automated check (e.g., required fields populated, issue opened from
an allowed set of users) is more appropriate than a human triage step.

Option B is the correct simplification. It removes the weakest gate
and retains the strongest one. The `process-firewall-request.yml`
workflow absorbs the commit-and-PR logic currently in
`approve-and-commit.yml`, eliminating one workflow file and the
entire `extract_yaml_from_comment.py` script.

The decision to create PRs only for valid proposals (not for
rejections) keeps the PR list clean. A PR represents a deployable
configuration change. Rejected requests are documented on the issue
via comment and label — they do not produce Git artefacts.

The following components are affected:

| Component | Change |
|---|---|
| `approve-and-commit.yml` | Removed entirely |
| `extract_yaml_from_comment.py` | Removed entirely |
| `process-firewall-request.yml` | Extended: after Claude processing, if valid, commit YAML to feature branch, update `_rulebase.yaml`, open PR |
| `update_rulebase_manifest.py` | Unchanged — called from the processing workflow instead of the approval workflow |
| ADR-0005 label table | `firepilot:approved` removed; polling contract no longer applies to the processing flow |
| ADR-0009, Sections 3–4 | Updated: "Review and Approval" describes PR-based review, not label-based comment review |
| README.md flow | Steps 5–6 simplified: approval = PR merge decision |
| `architecture.md` | Component diagram and workflow descriptions updated |
| `ci/README.md` | Manual test instructions updated (no label step) |
| Fixture: change request `42` | Status updated from `"approved"` to `"pending"` (no longer demonstrates approval label) |

Claude's analysis comment on the issue remains — it provides the
audit trail of *why* the configuration was generated and documents
any warnings or rejected sub-requests. The comment is informational,
not a gate.

---

## Consequences

- **Positive**: Single approval point (PR merge) with full CI
  validation context — the human decides with maximum information
- **Positive**: `extract_yaml_from_comment.py` eliminated — no more
  regex parsing of YAML from Markdown in a security pipeline
- **Positive**: Placement logic (`folder`/`position`) is determined
  by the processing workflow directly, not encoded as hints in a
  comment and extracted post-hoc — cleaner separation per ADR-0007
- **Positive**: One fewer workflow file (`approve-and-commit.yml`
  removed), reducing pipeline complexity
- **Positive**: Faster end-to-end flow — no waiting for a human to
  label before the PR exists
- **Positive**: Approval polling loop eliminated — Claude's
  orchestration is simpler and does not consume context window
  waiting for a label change
- **Positive**: Label set reduced from five to four — less operator
  setup, fewer states to reason about
- **Negative**: A misconfigured system prompt could cause Claude to
  generate PRs for invalid or malicious requests; mitigation: CI
  Gates 1–3 catch policy violations before merge, and PR reviewers
  see the full context
- **Negative**: Existing documentation, operator setup instructions,
  and test fixtures must be updated across multiple files
- **Follow-up required**: Merge commit-and-PR logic into
  `process-firewall-request.yml`
- **Follow-up required**: Delete `approve-and-commit.yml` and
  `extract_yaml_from_comment.py`
- **Follow-up required**: Update ADR-0009 Sections 3–4, README.md
  flow description, `architecture.md` component diagram, and
  `ci/README.md` manual test instructions
- **Follow-up required**: Update `CLAUDE.md` repository structure
- **Follow-up required**: Update `mcp-itsm` fixture store — change
  request `42` status and label convention documentation
- **Follow-up required**: Remove `firepilot:approved` from operator
  setup instructions and label pre-creation requirements

---

## Compliance & Security Considerations

- **Separation of Duties**: Maintained. Claude generates the
  configuration. A human (PR reviewer) approves it. No actor
  controls both generation and approval. The separation moves from
  "label on issue" to "merge on PR" — the PR-based gate is
  *stronger* because it is enforced by Git branch protection, not
  by a label convention with no per-label access control
- **Audit Trail**: The issue retains Claude's analysis comment
  (informational). The PR provides the configuration diff, CI
  validation results, reviewer identity, and merge timestamp. The
  combined issue + PR trail is more complete than the current
  comment-only audit record
- **SOC 2 CC8.1**: Automated change management controls (Gates 1–3)
  now run *before* the human approval decision, not after. This is a
  stronger control posture — the human is informed by automated
  validation, not preceding it
- **Attack Surface Reduction**: Removing `extract_yaml_from_comment.py`
  eliminates a Markdown parsing step from the security pipeline.
  The YAML is written by the processing script directly to the
  filesystem, not extracted from a GitHub API response containing
  arbitrary user and bot content

---

## Review Trigger

- If a spam or abuse problem emerges (high volume of invalid PRs from
  malicious issue submissions), revisit whether an intake-level gate
  (Option C or automated triage) is needed before Claude processing
- If the processing workflow becomes too complex after absorbing the
  commit-and-PR logic, consider extracting it into a reusable
  composite action or a dedicated script — but not back into a
  separate label-triggered workflow
- If a compliance requirement mandates a documented pre-CI approval
  step (e.g., a formal "change advisory board" sign-off before any
  code enters a branch), the PR-only model may need augmentation
