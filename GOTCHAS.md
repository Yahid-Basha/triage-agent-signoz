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
