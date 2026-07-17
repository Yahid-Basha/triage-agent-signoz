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
  1e-9 (float rounding through pandas/parquet round-trip), an order of magnitude tighter than
  the ~1e-6 the plan expected. **Gate passed**: today's reward code is bit-for-bit the code that
  trained in April.
