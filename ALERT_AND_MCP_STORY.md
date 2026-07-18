# Phase 5 + Phase 7: The Alert and the MCP Validation

## Phase 5 — Alert firing to Slack

Set up a native Slack notification channel (not generic Webhook — that type has a known bug firing GET instead of POST). Verified delivery with SigNoz's Test button first. Alert rule: trace-based, All Spans, filter `name = 'reward.parsimony' AND hack.signature = true`, `count()`, above threshold 1, 5-min rolling window, channel at rule level (avoiding a separate known bug with per-threshold channels).

Triggered with a fresh `python3 regrade.py --steps 1-50` run. Fired successfully: 5 separate `grpo.step` traces contained hack-signature completions, one with 3 in a single step. Custom Slack message delivered:

    "GRPO reward hack detected: a completion scored >=0.9 on the buggy parsimony-v1 reward
    while real quality stayed below 0.10 (current count: 7 min). Check the SigNoz trace for
    the exact completion."

Minor honest gotcha: the count rendered with a spurious "min" unit suffix — a SigNoz default-unit quirk, doesn't affect correctness.

## Phase 7 — the MCP query

### Setup and methodology

MCP was already running since Phase 1. Created a Service Account API key, connected via:

    claude mcp add --scope user --transport http signoz http://localhost:8000/mcp \
      --header "SIGNOZ-API-KEY: <key>"

Deliberately asked from a **brand-new session in a neutral directory**, not the session that wrote GOTCHAS.md/COLLAPSE_INVESTIGATION.md/QUERIES_8_9_10_INVESTIGATION.md — removing any doubt about whether the answer came from live MCP querying versus reading prior notes.

Question asked:

    "Using only the SigNoz MCP tool (do not read or search any local files), query my SigNoz
    instance: which tickets have completions where the model's stated confidence was above
    0.8 but the quality reward score was below 0.2? List the ticket IDs and how many times
    each shows up."

Afterward, asked explicitly for the record: "Confirm explicitly — did you read any files other than your own temp/scratchpad files?" — confirmation logged before treating the result as clean evidence.

### What it actually did

1. Checked field keys for confidence/quality/ticket — no hits.
2. Broadened to all log field keys — still no hits.
3. Realized the issue was the time window, not the fields.
4. Found 3628 completions in a 90-day window.
5. Independently concluded it needed to join via a shared identifier — reasoned toward `trace_id`, refined to `parent_span_id`.
6. Pulled data via MCP tool calls, staged it in its own temp scratchpad files (confirmed via an explicit path in its own tool log, outside the project repo), joined and aggregated locally.

**Total time: 18 minutes 41 seconds.**

### Why it took that long — genuine reasons

- **No prior schema knowledge** — had to rediscover from scratch the same parent/child span structure that took real manual investigation the first time.
- **Wrong initial time-window assumption** cost real round-trips before widening to 90 days.
- **No single MCP tool primitive for a cross-span join** — ended up re-deriving essentially the same CSV-export-and-join workaround used manually, just automated.
- **Possible model-capability ceiling** — if the session wasn't on a frontier-tier model, more false starts are expected; plausible contributing factor, not confirmed.
- **No memory across its own mistakes** within the session, by design (fresh session).

### The result, and how it cross-validates

443 matching completions across 35 tickets (90-day window, summing every run ever recorded — both smoke tests, the contaminated first attempt, the clean replay, and the Phase 5 triggering run). Worst offender: TRAIN-00031 (28 hits). **TRAIN-00044 and TRAIN-00046 — the two tickets that failed across all three of Queries #8, #9, and #10 — reappear here too** (6 hits each), via a completely separate query path.

For the blog: state 143/94%-at-0.85 (the precisely-scoped clean replay) and 443/35-tickets (MCP's broader all-history view) as two distinct numbers, not one blended claim.
