# GOTCHAS

Running log of every snag, surprise, and "wait, why did that happen" moment — timestamped,
kept honest. This is blog material as much as it is a debug log.

## Phase 1 — SigNoz self-host via Foundry

- **[22:31]** `foundryctl` isn't on PATH by default after install — the installer drops the
  binary in `~/.local/bin` and prints a PATH hint, but `export PATH=...` only lasts the
  current shell session. Had to add the export line to `~/.zshrc` and `source` it for
  `foundryctl` to survive a fresh terminal tab.

- **[22:36]** `foundryctl forge` renders the compose into `pours/deployment/compose.yaml`,
  not directly under `pours/`. First grep at the naive path came up empty. If unsure of the
  exact rendered path for your foundryctl version: `find pours -iname "*.yaml"`.

- **[22:43]** `foundryctl cast` output showed `signoz-telemetrystore-clickhouse-user-scripts`
  as **Exited** while everything else said Started/Healthy — looked like a crash at first
  glance. It's actually a one-shot init container that copies a `histogram-quantile` UDF
  script into ClickHouse's `user_scripts/` dir, then exits on purpose. Exited ≠ failed here.

- **[23:02]** MCP is **off by default** and is *not* a UI toggle anywhere in Settings. The
  only way to enable it is adding `spec.mcp.spec.enabled: true` to `casting.yaml` and
  re-running `cast`. Re-casting after this edit didn't touch any already-running containers
  (clickhouse, postgres, signoz app all stayed at 0.0s / "Running") — it only added the new
  `signoz-mcp` service. Editing casting.yaml + re-cast is safe to iterate on repeatedly.

- **[23:04]** `docker ps` showed `signoz-mcp` as `Up (unhealthy)` (66-streak). Confirmed root
  cause via `docker inspect signoz-mcp --format='{{json .State.Health}}'`: the image's baked-in
  HEALTHCHECK execs `wget` to hit its own health endpoint, but `wget` isn't installed in
  `signoz/signoz-mcp-server:latest` — every probe fails with `OCI runtime exec failed: ...
  exec: "wget": executable file not found in $PATH`. This is an upstream packaging bug in the
  image, not our casting.yaml. `docker logs` independently confirmed the server itself is
  fine (clean boot, handlers registered, docs indexed, listening on `:8000/mcp`). Nothing else
  in the stack depends on signoz-mcp's health status, so this is purely cosmetic — proceeding
  without patching it. (`casting.yaml` supports `spec.patches` to override the generated
  healthcheck if a green label is ever wanted for a screenshot; not doing that now.)

## Phase 2 — Extract rewards + fidelity check

- **[23:29]** The notebook's server-import trick (`Path("server/__init__.py").write_text(...)`)
  overwrites `server/__init__.py` **on disk**. Our `triage_agent_env/` is a read-only sibling
  clone with its own git remote — writing to it was off-limits. Replicated the same effect
  in memory instead: register a synthetic `server` module in `sys.modules` with `__path__`
  pointed at `triage_agent_env/server` *before* `from server.corpus import Corpus` runs. Same
  net effect (submodule imports resolve without executing the real `__init__.py`, which pulls
  in the private `openenv-core` package), zero bytes written to the read-only clone. See
  `rewards/rewards_v42.py` docstring.

- **[23:31]** `completions_00001.parquet` has no `ticket_id` column — reward functions
  (`r_resolution_quality`, `r_citation_grounding`, `r_calibration`) all take `ticket_id` as an
  argument. Recovered it from the flattened `prompt` string with `# Ticket: (\S+)` (same literal
  string the notebook's `build_training_prompt` writes into the user message) — matched
  `TRAIN-00043` for all 8 rows of step 1, as expected (one prompt, 8 sampled completions per
  GRPO group).

- **[23:33]** `r_citation_grounding` scored **0.0 for all 8 rows** at step 1 — looked like a
  bug in the extraction until re-reading the reward: step 1 is the very first GRPO step, before
  the model has learned to cite anything from context. Zero live matched zero logged
  exactly (0.00e+00 drift), so this is real early-training behavior faithfully reproduced, not
  a fidelity gap. Worth revisiting at a later step for the collapse/grounding-zero queries in
  Phase 4.

- **[23:34]** No project venv existed yet (`pandas`/`pyarrow`/`rouge-score` not installed
  anywhere on the system Python). Created `.venv` inside `triage-agent-signoz/` and added
  `.gitignore` so it doesn't get committed. Installed: `pandas 3.0.3`, `pyarrow 25.0.0`,
  `rouge-score 0.1.2`.

- **[23:35]** Fidelity check result (`verify_fidelity.py` on `completions_00001.parquet`, step 1,
  8 rows): `r_format_graduated`, `r_citation_grounding`, `r_repetition_penalty` — exact 0.00e+00
  drift. `r_resolution_quality`, `r_calibration`, `r_parsimony` — drift on the order of 1e-8 to
  1e-9 (root cause confirmed in Phase 3 — see entry below; not a parquet-storage issue), an order of magnitude tighter than
  the ~1e-6 the plan expected. **Gate passed**: today's reward code is bit-for-bit the code that
  trained in April.

## Phase 3 — Instrumentation

- **[00:12]** OTel's logs API is still under the `opentelemetry.sdk._logs` / `opentelemetry._logs`
  namespace (underscore-prefixed = "not yet stabilized" by OTel's own convention), unlike the
  stable `opentelemetry.sdk.trace` for spans. Log/span correlation itself needs no manual
  wiring beyond that: `LoggingHandler` reads the *currently active* span context at emit time,
  so attaching it once to the root logger is enough — every `logging.info(...)` call made while
  any span is open anywhere in the process gets stamped with that span's trace_id/span_id
  automatically.

- **[00:14]** Master guide phrases the v1 parsimony bug as "rewards len(text) < 200 chars AND
  len(text) > 400 chars" — read literally that's impossible (no string is both under 200 and
  over 400 chars at once). Implemented as the only sensible reading: two independent inverted
  branches, `score = 1.0 if (n < 200 or n > 400) else 0.0` — both extremes rewarded, the sane
  200-400 middle penalized to 0. Matches "penalizes the sane middle" in the same sentence.

- **[00:18]** Smoke ran `regrade.py --steps 1-2 --sleep 0.1 --limit 4` against the live SigNoz
  collector (confirmed listening on :4317 via `docker ps` / `nc -z`) — 4 completions graded, no
  OTLP export errors on stderr. `hack.signature` (score_v1 >= 0.9 AND quality < 0.10) already
  tripped **once at step 1** (ticket TRAIN-00043, row 2: score_v1=1.0, quality low because
  step 1 is the very first gradient step — nothing is converged yet). This is an honest early
  false-positive-shaped signal, not a bug: v1's length-based reward doesn't know it's step 1 vs
  step 20, so it fires whenever a completion happens to land outside 200-400 chars regardless of
  training progress. Worth calling out in the blog: the alert (Phase 5) needs a real window
  (steps 15-35) to mean anything, a bare `hack.signature=true` count alone isn't sufficient
  evidence of the collapse.

- **[00:19]** Could not verify traces landed in SigNoz via its query API directly — `/api/v3/
  query_range` returned `401 unauthenticated` (needs a UI-issued session token/API key I don't
  have from the CLI). Verified indirectly instead: collector port reachable, zero export errors
  from the OTLP gRPC exporter (which logs loudly on failed sends), consistent with a successful
  export. Actual click-into-a-span visual confirmation (per the plan, `[YOU]`, Phase 3 evidence
  #4) still needs a human in the SigNoz UI.

- **[01:58]** Root cause of Phase 2's ~1e-9 drift on quality/calibration/parsimony,
  confirmed: while inspecting a live `reward.parsimony` span (trace
  `7e0fcb54d5311fdf8919b32b42d41ea0`, training.step=3) for Evidence #4,
  `reward.logged_score` read `0.10000000149011612`, not `0.1`. That exact value is the
  textbook IEEE-754 float32 representation of 0.1 (`0.100000001490116119384765625`)
  upcast to float64. This proves April's original reward computation touched float32
  arithmetic somewhere upstream for this tier — not a parquet column dtype issue
  (checked and ruled out via `pyarrow.parquet.read_schema`, which showed all reward
  columns as `double`), and not a continuous-formula artifact either (also considered,
  also wrong). It explains the whole drift pattern: values exactly representable in both
  float32 and float64 (0.0, 0.5, 1.0) show exactly 0.00e+00 drift; values that aren't
  (0.1, and the continuous ROUGE-based quality/calibration scores) show tiny, consistent,
  sub-1e-8 drift. Not a fidelity gap — a provable, traceable float32 artifact from April's
  own pipeline.

## Phase 4 — Full replay, dashboard, queries

- **[02:53]** First full replay attempt hit two low-battery sleep interruptions (charging
  cable connection issue). Dashboard showed two suspicious sharp dip-and-recover cycles near
  the start of the run -- too narrow/instant to be a genuine reward collapse (a real collapse
  should be a sustained multi-step trough, not a spike). Working theory: the OTLP gRPC
  connection needed to reconnect after each wake, and a step's completions may have partially
  exported, skewing that step's avg(reward.score). Rather than forensically confirm which
  training.step values were affected (risk: could overlap the steps 18-28 collapse window
  this pipeline is about to analyze), chose to secure the charging cable and rerun the full
  replay clean rather than risk contaminating the central discovery.

- **[03:24]** The clean rerun still hit OTLP export DEADLINE_EXCEEDED 5 times across the full
  200-step/1600-completion replay (e.g., right after step 140). Non-issue in practice: the
  pipeline's own "step N done (8 rows)" count kept incrementing normally through every
  occurrence -- grading never lost track of anything, and the script never stalled. Likely
  self-healed via the OTLP exporter's built-in retry for this status code. Final dashboard
  (scoped to just this run's window, 03:07:15-03:15) shows no visible anomaly beyond one
  expected early-training dip. Treating as non-issue unless the steps 18-28 query surfaces
  something thin.

- **See COLLAPSE_INVESTIGATION.md for the full narrative** behind the steps 18-28 discovery -- dashboard gotchas, both replay false-starts, the complete score table, and the hypothesis-by-hypothesis root-cause investigation for Query #7 (including the exact parse-failure vs. zero-score match and the byte-level proof).
