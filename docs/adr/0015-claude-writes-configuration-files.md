# ADR-0015: Claude Writes Configuration Files Directly — Eliminate Markdown-Based YAML Extraction

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0015                                                              |
| Title         | Claude Writes Configuration Files Directly — Eliminate Markdown-Based YAML Extraction |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-21                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

The current processing pipeline has two scripts with distinct
responsibilities:

1. **`ci/scripts/process-issue.py`** (the orchestrator): Runs the
   Claude agentic loop with MCP tool access. Claude analyses the
   request, validates zones and addresses, checks for conflicts,
   and produces a natural-language response. This response is
   written to **stdout** as a plain text string.

2. **`.github/scripts/process_firewall_request.py`** (the workflow
   script): Receives the orchestrator's stdout, posts it as an
   issue comment, and then attempts to extract a valid YAML
   security rule from the text using regex pattern matching. It
   searches for fenced Markdown code blocks (```` ```yaml ``` ````),
   parses each block with `yaml.safe_load()`, and checks whether
   the parsed dict contains `schema_version`, `name`, and `action`.
   If no valid block is found, the script sets
   `proposal_valid=false` and applies `firepilot:rejected`.

This architecture has three structural problems:

**Problem 1 — Implicit output contract.** There is no defined
interface between Claude's response and the workflow's extraction
logic. The workflow expects Claude to embed a complete ADR-0007-
compliant YAML rule inside a fenced Markdown code block within its
natural-language response. This expectation is not documented in
the system prompt, not enforced by any tool contract, and not
tested. Claude's response format is non-deterministic — it may
produce tables, prose, or structured analysis without any fenced
YAML block, as observed in issue #34 (PigeonTrack).

**Problem 2 — Single-rule extraction.** The function
`extract_rule_from_response()` returns the *first* valid rule
found and ignores all subsequent blocks. `document_based` and
`multiple_rules` modes (ADR-0009) produce N rules per request.
The current architecture can only commit one. The ADR-0009
follow-up item "Update `process-firewall-request.yml` to support
multi-rule commits" was never implemented because the extraction
mechanism is fundamentally single-valued.

**Problem 3 — Unnecessary fragility.** The regex-based extraction
(`YAML_BLOCK_RE`) parses structured data from Markdown prose — a
Markdown-to-YAML parser sitting in a security-critical pipeline.
It is sensitive to formatting variations (indentation changes,
additional code blocks for non-rule YAML, language tag casing)
and cannot distinguish a rule block from a YAML example Claude
might include for illustration. This fragility was identified in
ADR-0010's rationale as an architectural weakness, where it
contributed to eliminating `extract_yaml_from_comment.py` — but
an equivalent extraction pattern persists in
`process_firewall_request.py`.

All three problems share a root cause: the boundary between Claude
and the workflow is a **text stream** (stdout) rather than a
**file-system interface**. Claude's structured output (the YAML
configuration) and its human-readable output (the analysis comment)
are multiplexed into a single text channel, forcing the workflow
to demultiplex them via regex.

In scope: the output interface between the orchestrator and the
workflow script, the mechanism by which Claude writes configuration
files, the workflow script's file detection logic, and the system
prompt changes required to instruct Claude to use the new mechanism.

Out of scope: the agentic loop internals (ADR-0013 caching
mechanism), the CI/CD pipeline (ADR-0003 gates are unchanged), the
MCP tool interfaces for SCM and ITSM operations (ADR-0004,
ADR-0005), and the PR body format.

---

## Decision

We will introduce a new MCP tool `write_config_file` on the
`mcp-itsm` server that writes a YAML configuration file to a
specified path relative to a shared output directory. Claude calls
this tool once per rule during its agentic loop. The workflow
script detects configuration files by scanning the output directory
for `.yaml` files — no Markdown parsing, no regex extraction.

The orchestrator's stdout continues to carry Claude's
natural-language analysis (the issue comment text). Configuration
files travel through the file system, not through stdout.

The two output channels are cleanly separated:

| Output type | Channel | Consumer |
|---|---|---|
| Analysis comment (human-readable) | stdout (text) | Workflow script → issue comment |
| Configuration files (machine-readable) | File system (OUTPUT_DIR) | Workflow script → git commit |
| Processing metadata (logs, cache stats) | stderr | GitHub Actions log |

---

## Considered Alternatives

#### Option A: Status quo — regex extraction from stdout

- **Description**: Keep the current architecture. Fix it by adding
  explicit instructions to the system prompt requiring Claude to
  emit fenced YAML code blocks in a specific format. Extend
  `extract_rule_from_response()` to return a list instead of a
  single dict.
- **Pros**: No new MCP tool; no changes to `process-issue.py`'s
  output mechanism; minimal code changes.
- **Cons**: Still depends on Claude reliably producing a specific
  Markdown format — LLM output is non-deterministic. Adding
  multi-rule extraction makes the regex parsing more complex and
  harder to test. The fundamental architectural weakness (structured
  data in a text stream) remains. Every new output format variation
  requires a new regex or parser change.

#### Option B: Structured JSON on stdout — Claude emits a JSON envelope

- **Description**: Change the orchestrator to instruct Claude to
  produce a JSON object containing both the analysis text and an
  array of rule objects. The workflow script parses JSON instead of
  extracting YAML from Markdown.
- **Pros**: Cleaner than regex extraction; supports multiple rules
  natively; JSON parsing is deterministic.
- **Cons**: Still multiplexes two output types (analysis + config)
  in a single channel. Claude must produce valid JSON *and*
  natural-language prose in the same response, which constrains
  the response format and makes the analysis comment less readable.
  The JSON envelope is a custom protocol between Claude and the
  workflow — it must be documented, tested, and maintained. If
  Claude's response is truncated (token limit), the JSON may be
  invalid, causing a silent failure.

#### Option C: File-system interface via MCP tool *(chosen)*

- **Description**: Add a `write_config_file` tool to `mcp-itsm`
  that writes a file to an output directory. Claude calls this tool
  for each configuration artefact it generates (security rules,
  address objects). The workflow script scans the output directory
  for files — if files exist, `proposal_valid=true`; if not,
  rejection. stdout carries only the analysis comment.
- **Pros**: Clean separation of output channels — structured data
  on the file system, prose on stdout. No parsing, no regex, no
  format dependency on Claude's response style. Natively supports
  N files per request. The tool call is visible in the agentic
  loop's tool-use trace, providing full observability. File
  validation (is this a valid YAML file?) can happen immediately
  in the tool implementation. The workflow script becomes trivially
  simple: scan directory, commit files.
- **Cons**: Requires a new MCP tool. The tool must handle file-
  system paths, which introduces a path-traversal attack surface
  (mitigated by restricting writes to `OUTPUT_DIR` and validating
  relative paths). Adds one more tool to the tool definition set
  (currently 13 tools; this becomes 14), marginally increasing
  the system prompt token count.

---

## Rationale

The evaluation criteria are: interface reliability (does the output
reach the consumer intact?), multi-rule support, and architectural
simplicity.

Option A preserves a fundamentally broken interface. The observed
failure — Claude producing a complete, correct analysis but no
extractable YAML block — is not a prompt deficiency; it is a
consequence of multiplexing structured data into a text channel.
No amount of prompt engineering eliminates the non-determinism
risk. Furthermore, multi-rule extraction via regex escalates
complexity: the parser must now distinguish rule YAML from
illustrative YAML, handle varying numbers of blocks, and
maintain ordering.

Option B improves on A by using a structured format, but the
multiplexing problem remains. A truncated response breaks both
the analysis and the configuration. More importantly, forcing
Claude to produce a JSON envelope constrains its natural-language
output format and reduces the quality of the analysis comment.

Option C eliminates the interface problem entirely. Each output
type has its own channel. Claude writes files via a tool call —
the same mechanism it already uses for all other side effects
(creating rules in SCM, posting comments, updating labels). The
workflow script does not parse Claude's text; it scans a directory.
This is the simplest possible interface: presence of files =
proposal, absence of files = rejection.

The new tool belongs on `mcp-itsm` rather than `mcp-strata-cloud-
manager` because writing configuration files to the local file
system is a change-management operation (producing a Git-
committable artefact), not a firewall API operation. It follows
the existing responsibility split: `mcp-itsm` handles everything
related to the change request lifecycle and Git artefacts;
`mcp-strata-cloud-manager` handles SCM API interactions.

---

## Tool Specification

### `write_config_file`

**Server**: `mcp-itsm`

**Purpose**: Write a YAML configuration file (security rule or
address object) to the output directory for Git commit by the
workflow.

**Input**:

| Field       | Type   | Required | Description |
|-------------|--------|----------|-------------|
| `filename`  | string | yes      | File name including `.yaml` extension. Must match the `name` field in the content (e.g., `allow-web-to-app.yaml`). |
| `content`   | string | yes      | Complete YAML content of the file, ADR-0007-compliant. |
| `file_type` | string | yes      | One of: `security_rule`, `address_object`, `rulebase_manifest`. |

**Validation** (performed by the tool before writing):

1. `filename` must end with `.yaml`
2. `filename` must not contain path separators (`/`, `\`) or `..`
3. `content` must be valid YAML (`yaml.safe_load()` succeeds)
4. For `file_type: security_rule`: parsed content must contain
   `schema_version`, `name`, and `action`
5. For `file_type: rulebase_manifest`: parsed content must contain
   `schema_version`, `folder`, `position`, and `rule_order`
6. The `name` field in the content must match the filename (without
   `.yaml` extension)

**Output**:

| Field       | Type   | Description |
|-------------|--------|-------------|
| `file_path` | string | Absolute path of the written file |
| `file_type` | string | Echo of the input `file_type` |
| `file_size` | int    | File size in bytes |

**Error codes**:

| Code                     | Condition |
|--------------------------|-----------|
| `INVALID_FILENAME`       | Path separators, `..`, or missing `.yaml` |
| `INVALID_YAML`           | Content is not valid YAML |
| `SCHEMA_MISMATCH`        | Content does not match expected structure for `file_type` |
| `NAME_FILENAME_MISMATCH` | `name` field does not match filename |
| `WRITE_FAILED`           | File system write error |

**Demo mode**: Writes to `OUTPUT_DIR` (environment variable). In
demo mode this is a temporary directory; in live mode it is the
repository checkout's `firewall-configs/{folder}/{position}/`
directory.

**Live mode**: Same behaviour — the tool writes to `OUTPUT_DIR`.
The workflow script handles placement into the correct directory
path based on `firepilot.yaml` settings.

### Manifest generation

When Claude writes multiple rule files for a request, it must also
write or update the `_rulebase.yaml` manifest using
`write_config_file` with `file_type: rulebase_manifest`. The
manifest's `rule_order` list must include all rules being created,
appended to any existing rules already in the rulebase.

The workflow script currently calls `update_rulebase_manifest.py`
to update the manifest. With this ADR, Claude takes ownership of
manifest generation — the script becomes unnecessary for new rule
creation (it may be retained for other operations like rule
deletion, which is out of scope for this ADR).

---

## Workflow Script Changes

### `process_firewall_request.py`

**Remove entirely**:
- `YAML_BLOCK_RE` regex constant
- `extract_yaml_blocks()`
- `is_security_rule()`
- `extract_rule_from_response()`
- `extract_placement()`
- `strip_placement_fields()`
- `write_rule_file()`

**Replace with**:

```python
def scan_output_directory(output_dir: Path) -> list[Path]:
    """Return all .yaml files in the output directory.

    Files are written by Claude via the write_config_file MCP tool
    during the agentic loop. Their presence indicates a valid
    proposal; their absence indicates rejection.
    """
    return sorted(output_dir.glob("*.yaml"))
```

**Decision logic**:

```python
config_files = scan_output_directory(output_dir)

if config_files:
    write_github_output("proposal_valid", "true")
    # Derive rule names, folder, position from the files themselves
    # (parsed from YAML content, not from Claude's text response)
else:
    write_github_output("proposal_valid", "false")
    add_label(repo, issue_number, "firepilot:rejected", github_token)
```

### `process-firewall-request.yml`

The workflow must pass `OUTPUT_DIR` as an environment variable to
the orchestrator subprocess *and* make it accessible to the
`mcp-itsm` server process (which runs as a stdio subprocess of
the orchestrator). The `OUTPUT_DIR` value is already set in the
workflow; it needs to be propagated through the process tree.

The commit step changes from committing a single file to committing
all `.yaml` files found in the output directory:

```yaml
- name: Commit configuration files
  if: steps.process.outputs.proposal_valid == 'true'
  run: |
    FOLDER="${{ steps.process.outputs.folder }}"
    POSITION="${{ steps.process.outputs.position }}"
    TARGET_DIR="firewall-configs/${FOLDER}/${POSITION}"

    # Copy all generated files to the target directory
    cp "$OUTPUT_DIR"/*.yaml "${TARGET_DIR}/"
    git add "${TARGET_DIR}/"
    git commit -m "feat(configs): add rules from issue #${ISSUE_NUMBER}"
```

### PR body

The PR body currently summarises a single rule. With multi-rule
support, the PR body should list all rules. The specific PR body
format is an implementation detail — it should be derived from the
files committed, not from Claude's text output.

---

## System Prompt Changes

The system prompt (ADR-0014 rewrite) must instruct Claude to use
`write_config_file` for every configuration artefact:

- After completing Steps 6–7 (ITSM change request + rule creation
  in SCM candidate config), call `write_config_file` for each
  rule file and for the `_rulebase.yaml` manifest.
- The `write_config_file` call is the mechanism by which Claude's
  processing result enters Git. Without it, no PR is created.
- Claude's natural-language response (the analysis comment) must
  NOT contain fenced YAML code blocks intended for extraction.
  The analysis comment is purely informational — tables, prose,
  and structured summaries are appropriate; raw YAML is not.

---

## Consequences

- **Positive**: The entire Markdown-to-YAML parsing layer is
  eliminated — `YAML_BLOCK_RE`, `extract_yaml_blocks()`,
  `is_security_rule()`, `extract_rule_from_response()`,
  `extract_placement()`, `strip_placement_fields()`. No more
  regex in the security pipeline.
- **Positive**: Multi-rule support is native. Claude writes N
  files; the workflow commits N files. No extraction loop, no
  single-valued return, no "first match wins" heuristic.
- **Positive**: The output interface is deterministic. The
  presence of files in `OUTPUT_DIR` is a binary signal — no
  ambiguity about whether Claude's text response contained a
  "valid" block.
- **Positive**: File validation happens in the MCP tool at write
  time, not post-hoc in the workflow script. Invalid YAML is
  caught immediately and reported to Claude as a tool error,
  giving Claude the opportunity to fix it within the agentic loop.
- **Positive**: The tool call is visible in the agentic loop's
  tool-use trace (logged to stderr per ADR-0013), providing full
  observability of what Claude wrote and when.
- **Positive**: `update_rulebase_manifest.py` becomes unnecessary
  for new rule creation — Claude generates the manifest directly.
- **Negative**: One additional MCP tool increases the tool
  definition set from 13 to 14 tools. Impact on system prompt
  token count: approximately 150–200 tokens (within the cached
  prefix per ADR-0013).
- **Negative**: Path-traversal attack surface. Mitigated by
  filename validation in the tool (no path separators, no `..`,
  must end with `.yaml`).
- **Negative**: Claude must produce valid ADR-0007-compliant YAML
  as tool input. If Claude generates invalid YAML, the tool
  rejects it — but this consumes an agentic loop iteration. In
  the current architecture, invalid YAML simply fails extraction
  silently. The new behaviour is strictly better (explicit error
  vs. silent failure), but may increase iteration count for
  malformed requests.
- **Follow-up required**: Implement `write_config_file` tool on
  `mcp-itsm` with the specified input/output contract and
  validation.
- **Follow-up required**: Add `write_config_file` to the mock
  fixture store for demo mode.
- **Follow-up required**: Refactor `process_firewall_request.py`
  to remove extraction logic and use directory scanning.
- **Follow-up required**: Update `process-firewall-request.yml`
  commit step for multi-file support.
- **Follow-up required**: Update the system prompt to instruct
  Claude to use `write_config_file` (coordinate with ADR-0014
  prompt rewrite).
- **Follow-up required**: Update `mcp-itsm` README with the new
  tool specification.
- **Follow-up required**: Update `docs/architecture.md` component
  diagram — the output channel description changes.
- **Follow-up required**: Update tests in
  `.github/scripts/test_process_firewall_request.py` to test
  directory scanning instead of regex extraction.

---

## Compliance & Security Considerations

- **Path Traversal**: The `write_config_file` tool validates that
  `filename` contains no path separators and no `..` sequences.
  All writes are restricted to the `OUTPUT_DIR` directory.
  Combined with the GitHub Actions runner's ephemeral filesystem,
  this limits the impact of any bypass to the current workflow
  run.
- **Audit Trail**: Tool calls are logged in the agentic loop's
  tool-use trace (stderr → GitHub Actions log). Each
  `write_config_file` call records the filename, file_type, and
  file_size. This is more observable than the current architecture,
  where file creation happens silently in
  `process_firewall_request.py` with no trace in Claude's
  conversation.
- **Defence in Depth**: Layers 3 and 4 are completely unaffected.
  CI gates validate the committed YAML files identically
  regardless of how they were produced. The change affects only
  the mechanism by which files arrive in the repository — not
  their validation or deployment.
- **No Change to Trust Model**: Claude already has the ability to
  create security rules in SCM (via `create_security_rule`) and
  post comments on issues (via `add_audit_comment`). Writing a
  YAML file to a temporary directory is a lower-privilege
  operation than either of these. The new tool does not expand
  Claude's trust boundary.

---

## Review Trigger

- If the `mcp-itsm` server is replaced by a different ITSM backend,
  the `write_config_file` tool must be reimplemented on the
  replacement server (or moved to a dedicated file-output MCP
  server).
- If address object configuration files are added to the declarative
  schema (ADR-0007 scope expansion), verify that `write_config_file`
  supports the new `file_type` and that the workflow script handles
  the additional file category.
- If the GitHub Actions runner environment changes to a non-writable
  filesystem, the `OUTPUT_DIR` mechanism must be reconsidered.
