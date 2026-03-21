# ADR-0013: Enable Prompt Caching for the Orchestrator Agentic Loop

| Field         | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| ID            | ADR-0013                                                              |
| Title         | Enable Prompt Caching for the Orchestrator Agentic Loop               |
| Status        | **Approved**                                                          |
| Deciders      | Thomas Sprock                                                         |
| Date          | 2026-03-21                                                            |
| Supersedes    | —                                                                     |
| Superseded by | —                                                                     |

---

## Context

The FirePilot orchestrator (`ci/scripts/process-issue.py`) runs a
multi-iteration agentic loop against the Claude API. Each iteration
sends a full Messages API request containing the system prompt, all
tool definitions (13 tools), any base64-encoded PDF attachments, and
the growing conversation history. The system prompt, tool
definitions, and PDF attachments are identical across all iterations
within a single run.

On 2026-03-21, the workflow for issue #34 (a document-based request
with a PDF attachment) hit the Anthropic API rate limit of 30,000
input tokens per minute (Tier 1). The root cause: the second API
call in the agentic loop re-sent the entire static prefix —
system prompt, 13 tool schemas, and a base64-encoded PDF — within
the same minute as the first call, exceeding the ITPM ceiling.

A retry mechanism with static delays (60s, 120s, 240s) was already
implemented but could not prevent the failure because the rate limit
was hit before the response to the first call completed.

The Anthropic API offers prompt caching, where cached input tokens
do not count towards the ITPM rate limit for Claude Sonnet 4 (the
model used by FirePilot). This means that caching the static prefix
would reduce the effective ITPM load of each iteration to only the
new conversation turns, eliminating the rate limit bottleneck
without requiring a tier upgrade.

In scope: prompt caching strategy for `process-issue.py`, cache
breakpoint placement, pricing implications, and interaction with the
existing retry mechanism.

Out of scope: tier upgrades (orthogonal commercial decision), model
changes, changes to the system prompt content or tool definitions,
and caching strategies for other scripts (deploy, drift-check).

---

## Decision

We will enable prompt caching in the orchestrator agentic loop using
a combination of explicit cache breakpoints for static content and
automatic caching for the growing conversation history, because
cached input tokens do not count against ITPM rate limits on
Claude Sonnet 4 and this eliminates the structural cause of rate
limit failures during multi-iteration tool-use loops.

---

## Considered Alternatives

#### Option A: Status quo — rely on retry delays only

- **Description**: Keep the existing `RATE_LIMIT_RETRY_DELAYS`
  mechanism (60s, 120s, 240s) without prompt caching. The agentic
  loop waits and retries when a 429 is received.
- **Pros**: Already implemented; no code changes required; handles
  transient rate limits from concurrent usage.
- **Cons**: Does not reduce the token count per request. If a single
  request's static prefix approaches or exceeds the per-minute ITPM
  limit, no amount of waiting helps — the request itself is too
  large. For document-based requests with PDF attachments, this is a
  realistic scenario. Total loop runtime increases by minutes per
  retry, risking the 5-minute workflow timeout.

#### Option B: Tier upgrade only

- **Description**: Upgrade from Tier 1 ($5 deposit, 30k ITPM for
  Sonnet) to Tier 2 ($40 deposit, 80k ITPM) or higher. No code
  changes.
- **Pros**: Immediate relief; no implementation effort; higher
  monthly spend ceiling also provides headroom for concurrent runs.
- **Cons**: Does not solve the structural problem — token
  accumulation per iteration still grows linearly with conversation
  length. A sufficiently complex request (large PDF, many tool
  iterations) will hit Tier 2 limits as well. Costs money without
  architectural improvement. Does not reduce per-request cost (no
  cache read discount).

#### Option C: Prompt caching with explicit breakpoints and automatic caching *(chosen)*

- **Description**: Place explicit `cache_control` breakpoints on the
  system prompt and tool definitions (the static prefix that is
  identical across all iterations). Enable automatic caching at the
  request level so the growing conversation history is cached
  incrementally. The first API call writes the cache; subsequent
  iterations read from it.
- **Pros**: Cached tokens do not count against ITPM rate limits on
  Claude Sonnet 4 — this directly eliminates the rate limit failure
  observed in issue #34. Cache read tokens cost 10% of base input
  price ($0.30/MTok vs $3/MTok), reducing per-run cost
  significantly for multi-iteration loops. Cache writes cost 25%
  more than base ($3.75/MTok), but this is a one-time cost per run
  amortised across all subsequent iterations. Compatible with the
  existing retry mechanism — retries benefit from the same cache.
  No external dependency or commercial change required.
- **Cons**: Minimum cacheable prefix is 1,024 tokens for
  Claude Sonnet 4 (easily met — the system prompt alone exceeds
  this). Cache lifetime is 5 minutes by default; since the agentic
  loop completes well within 5 minutes, this is sufficient. Adds
  modest implementation complexity: the `system` parameter must be
  restructured from a plain string to a content block array, and
  `cache_control` markers must be added. If tool definitions change
  between iterations (they do not in this architecture), the cache
  would be invalidated — but this is not a concern since tools are
  static within a run. Cache write cost is 25% above base on the
  first iteration, making single-iteration runs marginally more
  expensive (negligible in practice).

---

## Rationale

Option A is already in place and remains valuable as a fallback for
transient errors, but it cannot address the structural problem: the
orchestrator sends a static prefix of approximately 10,000–25,000
tokens (system prompt + 13 tool schemas + PDF) on every iteration.
On Tier 1 with a 30,000 ITPM limit, two rapid iterations exhaust
the budget regardless of retry timing.

Option B shifts the ceiling but does not change the growth curve.
A complex document-based request with 10+ tool iterations and a
large PDF attachment could accumulate 200,000+ total input tokens
across all iterations. Even Tier 4 (400,000 ITPM for Sonnet) would
be stressed by a burst of such requests. Tier upgrades are a valid
complementary measure but not a substitute for architectural
efficiency.

Option C addresses the root cause: the static prefix is sent
repeatedly but only needs to be processed once. With prompt caching:

- **Iteration 1**: Full prefix is written to cache. Cost is 1.25×
  base for the cached portion. ITPM: full prefix counts.
- **Iteration 2+**: Prefix is read from cache. ITPM: only the new
  conversation turns (tool results, assistant responses) count
  against the rate limit. Cache reads cost 0.1× base.

For a typical 6-iteration agentic loop with a 15,000-token static
prefix, the effective ITPM load drops from ~90,000 tokens
(15k × 6 iterations) to ~15,000 tokens (one write) plus ~30,000
tokens of incremental conversation. This fits comfortably within
Tier 1 limits.

The approach also aligns with Anthropic's documented best practice
for agentic tool use: "Enhance performance for scenarios involving
multiple tool calls and iterative code changes, where each step
typically requires a new API call."

---

## Consequences

- **Positive**: Rate limit failures caused by repeated static prefix
  transmission are eliminated for typical request sizes on Tier 1.
- **Positive**: Per-run API cost decreases. For a 6-iteration loop
  with 15,000 cacheable tokens, the static prefix cost drops from
  6 × $3/MTok × 15k = $0.27 to 1 × $3.75/MTok × 15k +
  5 × $0.30/MTok × 15k = $0.079 — a ~70% reduction on the
  static portion.
- **Positive**: The existing retry mechanism remains in place as a
  complementary safeguard for transient errors or concurrent usage
  spikes.
- **Negative**: The `system` parameter in the API call must be
  restructured from a plain string to an array of content blocks
  with `cache_control` markers. This is a localised change in
  `run_agentic_loop()`.
- **Negative**: Cache write on the first iteration costs 25% more
  than uncached input. For single-iteration requests (simple
  rejections, clarification questions) this is a marginal cost
  increase (~$0.004 for 15,000 tokens).
- **Follow-up required**: Implement the caching logic in
  `ci/scripts/process-issue.py` — restructure the `system`
  parameter and add `cache_control` breakpoints.
- **Follow-up required**: Add `cache_read_input_tokens` and
  `cache_creation_input_tokens` to stderr logging for
  observability.
- **Follow-up required**: Update existing tests in
  `ci/scripts/test_process_issue.py` to account for the new
  request structure.

---

## Implementation Specification

### Cache breakpoint placement

The orchestrator request is structured in this order (per Anthropic
API specification): `tools`, then `system`, then `messages`.

**Breakpoint 1 — Tool definitions**: Place `cache_control` on the
last tool definition in the `tools` array. Tool definitions are
static for the entire run and change only when MCP server tool
schemas are updated (i.e., between deployments, not between
iterations).

```python
if tool_defs:
    tool_defs_with_cache = [*tool_defs[:-1], {
        **tool_defs[-1],
        "cache_control": {"type": "ephemeral"},
    }]
    kwargs["tools"] = tool_defs_with_cache
```

**Breakpoint 2 — System prompt**: Restructure the `system`
parameter from a plain string to a content block array. Place
`cache_control` on the system prompt block.

```python
kwargs["system"] = [
    {
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"},
    }
]
```

**Automatic caching — Conversation history**: Add top-level
`cache_control` to the request body. This automatically caches
the growing conversation history, with the breakpoint advancing
to the last cacheable block on each iteration.

```python
kwargs["cache_control"] = {"type": "ephemeral"}
```

PDF attachments in the first user message are part of `messages`
and are covered by automatic caching — they are cached as part
of the conversation prefix from iteration 2 onwards.

### TTL selection

The default 5-minute TTL is sufficient. The agentic loop has a
5-minute subprocess timeout (`process_firewall_request.py`) and
`MAX_AGENTIC_ITERATIONS = 20`. In practice, loops complete in
30–120 seconds. The 1-hour TTL (at 2× base cost) provides no
benefit for this use case.

### Observability

Log cache performance metrics from the API response `usage` field
on each iteration:

```python
usage = response.usage
print(
    f"[iteration {iteration + 1}] "
    f"input={usage.input_tokens} "
    f"cache_read={getattr(usage, 'cache_read_input_tokens', 0)} "
    f"cache_write={getattr(usage, 'cache_creation_input_tokens', 0)} "
    f"output={usage.output_tokens}",
    file=sys.stderr,
)
```

### Interaction with retry mechanism

The retry mechanism (`RATE_LIMIT_RETRY_DELAYS`) remains unchanged.
Prompt caching reduces the likelihood of hitting rate limits but
does not eliminate all causes (concurrent workflow runs, API-side
throttling). The retry loop continues to provide resilience for
transient 429 errors.

### Minimum token threshold

Claude Sonnet 4 requires a minimum of 1,024 tokens for caching.
The system prompt alone (~3,000–4,000 tokens) exceeds this
threshold. No conditional logic is needed to check whether the
prefix is large enough.

---

## Compliance & Security Considerations

- **Data handling**: Prompt caching stores KV cache representations
  and cryptographic hashes, not raw prompt text. Per Anthropic's
  documentation, this is compatible with zero-data-retention
  commitments. FirePilot does not currently use ZDR, but this
  preserves the option.
- **Cache isolation**: Caches are isolated per workspace (since
  February 2026). FirePilot uses a single workspace, so
  cross-tenant cache leakage is not a concern.
- **No change to trust model**: Prompt caching does not alter what
  data is sent to the API or how responses are processed. The
  defense-in-depth model (ADR-0002, ADR-0003) is unaffected.
- **Audit trail**: Cache performance metrics are logged to stderr,
  which is captured by GitHub Actions workflow logs. This provides
  an observable record of caching behaviour per run.

---

## Review Trigger

- If the orchestrator is migrated to a different model that does
  not support prompt caching or has different minimum token
  thresholds, revisit this decision.
- If the agentic loop runtime regularly exceeds 5 minutes (e.g.,
  due to increased tool iterations or longer approval polling),
  evaluate the 1-hour TTL option.
- If Anthropic changes the rate limit accounting for cached tokens
  (e.g., cached reads begin counting against ITPM), the primary
  benefit of this decision would be reduced to cost savings only.
- If FirePilot moves to a multi-workspace setup, verify that cache
  isolation per workspace does not cause unexpected cache misses
  between environments.
