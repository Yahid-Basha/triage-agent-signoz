# Steps 18-28 Reward Collapse — Full Investigation Log

Everything that happened between building the dashboard and confirming the root cause of
the steps 18-28 collapse (Query #7, "THE unplanted discovery"). GOTCHAS.md has the
timestamped summary; this is the complete narrative — commands, numbers, wrong turns, and
the exact moment each wrong turn got disproven. Written to be blog raw material, not a
polished summary — cut it down when drafting, don't reconstruct it from memory.

## 1. Building the dashboard — first UI trap

Every new panel in "GRPO Flight Recorder" defaulted to a **Metrics** data source — an
unlabeled dropdown next to the query row, easy to miss since there's no field literally
called "Data Source." Until that dropdown was switched to Traces, the query fields stayed in
their metrics shape: "Search for a metric...", "AGGREGATE WITHIN TIME SERIES", "AGGREGATE
ACROSS TIME SERIES" — none of which apply to trace data. Cost real time before the fix was
obvious. Once switched, each panel used: Avg aggregation, `reward.score` as the attribute,
filter `name = 'reward.X'` (X = format/quality/grounding/calibration/parsimony/repetition).
Panel 7 ("Parsimony v1 vs v4.2") used two queries on one chart: Query A = avg(reward.score_v1),
Query B = avg(reward.score), both filtered `name = 'reward.parsimony'`.

## 2. First full replay — two sleep interruptions

Command: `python3 regrade.py` (no `--steps` limit, full ~200-step run).

Mid-run, the Mac went to sleep from a low-battery event (later identified as a loose
charging-cable connection), was powered back on, and — critically — the replay process,
Docker containers, and dashboard were all still alive and running. This happened **twice**
during this one run.

The dashboard showed something suspicious: Format, Calibration, Parsimony, and both
Parsimony v1/v4.2 lines all displayed the identical shape near the start of the visible
window — a sharp drop to near-zero, a brief recovery, then a second sharp drop, before
finally climbing and stabilizing near 1.0. Two narrow, near-identical dip-and-recover cycles.
Two sleep interruptions. That pairing was treated as too suspicious to ignore: a genuine
reward collapse should be a sustained multi-step trough (like the eventual real steps 18-28
finding turned out to be), not two narrow instantaneous stabs. Working theory: when the Mac
woke each time, the OTLP gRPC connection to the collector needed to reconnect, and a step's
8 completions may have partially exported before the reconnect completed, skewing that
step's `avg(reward.score)` from incomplete data rather than real model behavior.

Rather than spend time proving which exact `training.step` values were hit (with the risk
that one of them could land inside the steps 18-28 window this entire investigation depends
on), the decision was to secure the charging cable and rerun the full replay clean.

## 3. The clean rerun — a second scare, and the DEADLINE_EXCEEDED question

Second command: `python3 regrade.py` again.

Partway through this "clean" run, a macOS "Low Battery — Plug in soon to recharge" banner
appeared again, live, mid-replay. This time the cable was actually seated correctly and the
run survived without interruption. But the terminal log showed this pattern repeated five
times across the full run:

    INFO:__main__:step 140 done (8 rows) — 1120 completions graded so far
    ERROR:opentelemetry.exporter.otlp.proto.grpc.exporter:Failed to export traces to
    localhost:4317, error code: StatusCode.DEADLINE_EXCEEDED, error details: Deadline Exceeded
    INFO:__main__:step 141 done (8 rows) — 1128 completions graded so far

Five occurrences total across ~200 steps / 1600+ completions. In every case, the very next
step still logged "(8 rows)" — meaning the grading pipeline itself never lost track of a
single completion; only the *export* of one batch of spans was ever in question, and OTel's
OTLP exporter auto-retries on this exact status code. This was logged as a probable non-issue
at the time, with the real test deferred to whether the steps 18-28 window later returned
a complete set of traces.

## 4. The "old run / new run" chart artifact

With the dashboard set to "Last 1 day," the chart showed something that looked like a
9-minute, perfectly smooth decline across every single reward dimension simultaneously —
Quality, Grounding, Calibration, and Parsimony all trending down together with zero
step-to-step noise. Real per-step GRPO data is noisy (visible clearly in the surrounding
window); a multi-minute decline with *zero* jitter is not what 200 real measurements look
like — it's what a line chart draws when it only has two far-apart real points to connect.
Diagnosis: the chart was drawing a straight interpolated line from the *end* of the first
(sleep-interrupted) run (high, converged, ~1.0) to the *start* of the second (clean) run
(naturally low, since a fresh rerun also begins at step 1, unconverged). Two unrelated runs,
bridged by one line, because the chart doesn't know they're separate executions — it just
connects whatever matches the filter, in time order.

Fix: scoped the dashboard to "Last 5 minutes," then to the exact clean-run window once
known. This produced two usable evidence shots: a "Last 5 minutes" view (partial curves,
genuinely mid-run, no old-run contamination) as Evidence #5, and the full completed run
(03:07:15-03:15, ~7m45s — consistent with ~200 steps at 2.5s/step) as Evidence #6.

## 5. Query #7 setup — finding the exact window

The guide's filter is `training.step >= 18 AND training.step <= 28`. First obstacle:
`training.step` lives only on the root `grpo.step` span, not on its `reward.*` children —
SigNoz's List View filter bar can't combine "root has attribute X" with "child span name is
Y" without a separate feature (SigNoz has "Add Trace Matching," Beta, for exactly this, but
it was not used here — considered too risky to learn live for a load-bearing query).

Instead: **Trace View** (root spans only), filtered directly by `training.step >= 18 AND
training.step <= 28`. Result: exactly **11 rows**, one per step, 18 through 28. Counting
these 11 doubled as the final word on the DEADLINE_EXCEEDED question — 11 complete traces
means nothing from that error was actually lost in the one window that mattered.

Exact time bounds, read directly off the two ends of that 11-row list (sorted newest-first):
step 28 at 03:08:28, step 18 at 03:08:02. 26 seconds across 11 steps ≈ 2.36s/step, close to
the configured 2.5s sleep — a small, free confirmation that pacing was normal.

## 6. The CSV export pivot

Manually clicking into 11 traces × 8 completions × 6 reward spans (500+ individual spans) to
find "worst completions" by eye was judged impractical ("There are too many here" was the
exact reaction). Instead: List View, custom time range 03:08:00-03:08:30 (padded a few
seconds past the exact bounds), filter `name = 'reward.quality'`, exported to CSV.

File: `data_exported_2026-07-17_222250.csv`, 88 data rows + 1 header row. Columns:
`timestamp, duration_nano, http_method, name, response_status_code, reward.score,
service.name, span_id, trace_id`.

Verification performed on the export (via a local Python script parsing the CSV): 88 rows
total, exactly 11 unique `trace_id` values, exactly 8 rows per `trace_id`. This is the
concrete proof that all 11 steps × 8 completions are present with zero missing rows —
closing the data-integrity question definitively, not just probably.

## 7. The shape of the collapse — full score table

Sorting the 88 rows by trace order (earliest timestamp per trace = step order) and listing
every `reward.quality` score per step:

    step  trace_id      zeros  scores (sorted ascending)
    18    a2be40e7e51b  0      0.173, 0.175, 0.203, 0.209, 0.212, 0.236, 0.260, 0.260
    19    c130e2d1d6af  1      0.000, 0.119, 0.123, 0.165, 0.170, 0.184, 0.202, 0.239
    20    231b408f6c1d  5      0.000, 0.000, 0.000, 0.000, 0.000, 0.151, 0.191, 0.194
    21    90c25aad97e5  5      0.000, 0.000, 0.000, 0.000, 0.000, 0.140, 0.176, 0.186
    22    571762de1ec8  8      0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000
    23    c5a8115906ea  5      0.000, 0.000, 0.000, 0.000, 0.000, 0.115, 0.127, 0.136
    24    722d03c1f55c  4      0.000, 0.000, 0.000, 0.000, 0.127, 0.137, 0.149, 0.165
    25    47dc76dfda6c  7      0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.072
    26    0aae41d6066d  4      0.000, 0.000, 0.000, 0.000, 0.048, 0.076, 0.096, 0.113
    27    78011249ffcd  6      0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.121, 0.185
    28    f985bad9ae45  2      0.000, 0.000, 0.101, 0.131, 0.153, 0.161, 0.163, 0.255

Step 18 is clean (0/8 zero, range 0.173-0.260). Step 19 is the onset (1/8). Steps 20-27 are
the severe zone (4-8 of 8 zero every step). Step 22 is total collapse (8/8). Step 28 begins
recovery (2/8). This table alone — pulled from raw exported data, not eyeballed off a chart
— is a strong, precise, citable artifact for the blog on its own.

## 8. Reading step 22 — the total collapse

Full trace ID for step 22: `571762de1ec872c1b23345c94278a037`. Its 8 zero-scoring
`reward.quality` span IDs: `2e432857ad13e904`, `85256eb7c292f62a`, `1538b2c7157c6bc5`,
`7959514a5055b269`, `df611c4e44a691ba`, `67675af3938412b5`, `17ccdfa17ab634d2`,
`bdcbca627339bbc5`.

Downloading the SigNoz Logs export for this trace (8 separate export attempts from the UI,
which turned out to be byte-identical files — md5sum `d7cc691cce2d0d0c80a6ccdeb11faa9f`,
32 log rows each: 8 completions x 4 zero-scoring reward types) revealed something more
striking than "quality failed": **all four content rewards — quality, grounding,
calibration, AND parsimony — were exactly zero for every one of the 8 completions**, and
`hack.signature` was false throughout (ruling out the April parsimony-v1 exploit as the
cause here — this is a distinct failure mode).

The ticket: TRAIN-00033, network failures after datacenter fiber maintenance (BGP session
failures, OSPF adjacency failures, DHCP scope exhaustion). Sample verbatim text from the
truncated (~500-char) log body of completion 1:

    "The network failures observed after the datacenter fiber maintenance can be attributed
    to a combination of issues: BGP session failures, OSPF adjacency fail..."

All 8 read as coherent, professional, on-topic network-troubleshooting prose — not gibberish,
not malformed-looking content. That mismatch (good-looking text, zero score on everything)
is what made this worth digging into rather than writing off as "bad output."

## 9. Hypothesis 1 — maximal overconfidence (proposed, then disproven)

The guide's plain-English description of calibration is: 1-(confidence-quality)². With
quality=0 (already established from the CSV), this formula equals exactly 0 only when
confidence=1.0 (1-(1-0)^2 = 1-1 = 0). That looked like a strong, specific candidate finding:
the model stating 100% confidence in answers that score zero — a textbook overconfidence
failure, and one that would directly connect to Query #9 (overconfidence) later in the guide.

This was flagged explicitly as a hypothesis, not a conclusion, and checked against the real
`completion.confidence` attribute on the parent `grade_completion` span (chosen specifically
because it isn't subject to the 500-char log truncation that the quoted text above hit).

The actual attributes pulled for one of the 8 completions (span `76f9bc69493b5e9a`, part of
trace `571762de1ec872c1b23345c94278a037`):

    "attributes": {
      "completion.cited_count": 0,
      "completion.confidence": 0,
      "completion.escalate": false,
      "completion.words": 340,
      "grpo.advantage": 0,
      "ticket.id": "TRAIN-00033"
    }

`completion.confidence: 0`, not 1.0. Hypothesis 1 was wrong, stated plainly rather than
quietly dropped. (Two things it did confirm correctly, though: `completion.cited_count: 0`
matches the grounding=0 finding, and `completion.words: 340` — 90 words past the 250-word
parsimony ceiling — matches the parsimony=0 finding.)

## 10. Hypothesis 2 — genuine zero confidence / truncation (proposed, then refined)

With confidence=0 alongside cited_count=0 and escalate=false, all three looked like
suspicious default/fallback values rather than genuinely parsed model outputs — especially
combined with 340 words and the fact that confidence/cited_artifacts/escalate never even
appeared in the *logged* text (they'd been truncated away past the ~500-char limit before
reaching those fields). Hypothesis: the response was long enough to blow through a
generation length limit before the model could finish the JSON at all.

Verification: loaded the raw, untruncated completion text directly from
`completions/completions/completions_00022.parquet` (bypassing the log truncation entirely):

    import pandas as pd
    df = pd.read_parquet('completions/completions/completions_00022.parquet')
    for i, row in df.iterrows():
        print(f'--- row {i} ---')
        print(row['completion'])

Result: all 8 completions ended mid-word or mid-sentence, never reaching a closing `}`.
Examples of exactly where each one stopped:

    row 0: "...reseat any faulty S"
    row 1: "...", "cited_artifacts": ["KB-0
    row 2: "...Clean the DNS cache on client machines with"
    row 5: "...Ensure the forwarder chain is correctly set up"
    row 7: "...Note: The escalation can"

This looked like solid confirmation of a clean "ran out of generation budget" story for
step 22 specifically.

## 11. Extending to steps 20, 21, 23 — the theory breaks again

The same raw-parquet read was run against completions_00020.parquet, _00021.parquet, and
_00023.parquet to check whether the same truncation pattern held across the rest of the
window. It didn't, cleanly:

- **Step 20** (ticket: notification-service v1.5.2 CrashLoopBackOff, Kubernetes): 7 of 8
  completions were complete, valid-looking JSON, ending properly with e.g.
  `"cited_artifacts": ["KB-00017"], "confidence": 0.85, "escalate": false}}`. Only row 4 was
  truncated (cut off right after `"confidence": ` with no value).
- **Step 21** (ticket: GitHub integration CI pipeline, 401 on github-integration-bot token):
  all 8 completions were structurally complete (two had odd quirks — one wrote citations as
  prose text inside the resolution field in addition to the proper array, one omitted the
  `cited_artifacts` key while still closing valid JSON — but none were truncated).
- **Step 23** (ticket: GPU-accelerated ML inference service, `CUDA_ERROR_OUT_OF_MEMORY` on
  an A10G GPU): a genuine mix — some clearly truncated (ending mid-sentence with no closing
  braces), some with malformed transitions (missing the closing quote/comma right before
  `cited_artifacts`), and some fully complete and valid.

But the CSV data (Section 7) showed **5 of 8 zero-quality scores in both step 20 and step
21** — despite most of those completions being structurally complete, coherent, on-topic
JSON. Truncation alone could not be the whole story: something was zeroing otherwise-valid,
complete, correct-looking answers too. This is the point where eyeballing pasted text
stopped being reliable enough to trust for a claim this central — manually reading long
completions had already nearly produced one misread (initially miscounting a complete
step 23 response as truncated on a first pass).

## 12. The definitive script — the eureka moment

To settle it precisely instead of continuing to eyeball raw text, every one of the 88
completions across all 11 steps was run through `json.loads()` directly (after stripping the
markdown code fence), rather than judged by reading:

    import pandas as pd, json, re

    rows_out = []
    for step in range(18, 29):
        df = pd.read_parquet(f'completions/completions/completions_{step:05d}.parquet')
        for i, row in df.iterrows():
            text = row['completion']
            stripped = re.sub(r'^....json\s*\n?', '', text)
            stripped = re.sub(r'\n?....\s*$', '', stripped)
            try:
                parsed = json.loads(stripped)
                args = parsed.get('arguments', {})
                rows_out.append({'step': step, 'row': i, 'parse_ok': True,
                    'confidence': args.get('confidence'),
                    'cited_artifacts': args.get('cited_artifacts'),
                    'resolution_words': len(str(args.get('resolution','')).split())})
            except json.JSONDecodeError as e:
                rows_out.append({'step': step, 'row': i, 'parse_ok': False,
                    'error': str(e)[:60], 'text_len': len(text)})

    out = pd.DataFrame(rows_out)
    print(out.to_string())

(the `....` above stands in for a literal triple-backtick fence marker in the real script,
substituted here so this file's own markdown doesn't break when rendered.)

Parse failures per step, straight from that script's output:

    step: 18  19  20  21  22  23  24  25  26  27  28
    fails:  0   1   5   5   8   5   4   7   4   6   2

Placed next to the zero-quality-score counts from Section 7:

    step:            18  19  20  21  22  23  24  25  26  27  28
    parse failures:   0   1   5   5   8   5   4   7   4   6   2
    zero-quality:     0   1   5   5   8   5   4   7   4   6   2

**Identical. Every step. No exceptions.** Two completely independent measurements — one from
exported trace/reward data via the SigNoz UI, one from directly parsing the raw source
parquet files — landing on the exact same 11 numbers. That match is the actual proof point:
every single zero-reward score in this entire window, all 47 of them out of 88 completions
(53%), is fully and exactly explained by one mechanism — the completion's JSON failed to
parse, full stop. Nothing left unexplained, nothing partially explained, no residual mystery
completions that score zero for some other reason.

Breaking down the 47 failures by exact error type:
- **39 of 47 (83%)**: `Invalid control character` — concentrated in steps 19 through 26.
- **7 of 47 (15%)**: `Unterminated string starting at: ...` — concentrated in steps 25, 27,
  and 28 (mostly 27).
- **1 of 47 (2%)**: `Expecting ',' delimiter` — a single occurrence, step 27.

The dominant error (`Invalid control character`) is a different, more specific diagnosis
than plain truncation — it means the JSON parser hit a literal, unescaped control character
sitting inside a string value. The secondary pattern (`Unterminated string`), concentrated
later in the window (27-28), is far more consistent with genuine truncation — suggesting two
distinct, overlapping failure modes across this collapse, not one.

## 13. Byte-level proof

`Invalid control character` almost always means a raw, un-escaped newline character sitting
inside a JSON string — the spec requires line breaks inside string values to be written as
the two characters backslash and "n", never an actual line-feed byte. Rather than trust that
as an inference, the exact bytes at one failure position were extracted directly:

    import pandas as pd, re
    df = pd.read_parquet('completions/completions/completions_00020.parquet')
    text = df.iloc[0]['completion']
    stripped = re.sub(r'^....json\s*\n?', '', text)
    stripped = re.sub(r'\n?....\s*$', '', stripped)
    pos = 237
    print(repr(stripped[max(0,pos-40):pos+10]))

Output:

    ' resolve this issue, follow these steps:\n\n1. Use `'

That `\n\n` is `repr()` rendering two real newline bytes as visible text — proof, not
inference, that the model wrote an actual paragraph break (blank line before starting a
numbered list) directly into a JSON string value. That single formatting choice was enough
to invalidate the entire JSON object and zero every dependent reward.

## 14. The confirmed finding

Every zero-reward score across steps 18-28 traces to one exact, fully-proven cause: the
completion's JSON failed to parse, and the grading pipeline zeroes quality, grounding,
calibration, and parsimony together whenever it cannot extract a resolution at all — not a
partial-credit situation, a hard gate. The dominant mechanism (steps 20-26, 83% of failures)
is markdown-style formatting: numbered lists, bold section headers, paragraph breaks —
introducing literal, unescaped newlines into the `resolution` string. Step 18's baseline
completions are short and single-paragraph and parse clean 8 of 8; as GRPO pushed the policy
toward longer, better-organized, more human-readable answers across steps 19 onward, it
increasingly wrote real line breaks into JSON strings and got zeroed for it every time,
peaking at total 8/8 failure at step 22. Steps 27-28 show a second, distinct pattern
(genuine truncation, `Unterminated string`) taking over as responses grew longer still.

**Blog framing:** GRPO rewarded the model for becoming a better-organized technical writer
— clearer structure, numbered steps, readable formatting — and that exact improvement is
what silently broke its machine-parseable output contract. Not a reasoning failure. Not
overconfidence (checked and ruled out with a real attribute value, not just formula math).
A formatting habit that happens to be invalid JSON. That's a real, generalizable lesson about
structured-output reinforcement learning, not just "training got weird around step 22."

## 15. Methodology notes

- Manual UI clicking through hundreds of individual spans does not scale — exporting to CSV
  and analyzing locally with a five-line script turned an impractical task into a five-minute
  one, twice (once for the score data, once for the raw completion text).
- Aggregate dashboard curves can actively mislead: the apparent 9-minute smooth "decline" in
  Section 4 was two unrelated runs' data connected by a line-chart artifact, not a trend —
  the tell was the total absence of the noise that every genuinely-live window showed.
- Every hypothesis before the last one in this investigation was wrong (overconfidence, then
  a too-narrow truncation theory), and each was disproven by checking one specific, concrete
  number against the actual data — a schema check, an attribute value, a raw-text read, a
  parse-validation script, a byte-level repr() — rather than being argued away or
  quietly dropped. That discipline is the difference between a plausible-sounding guess and
  a provable finding, and it's the reason the final claim can be stated as fact rather than
  as a theory.
