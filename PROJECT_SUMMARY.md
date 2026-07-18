# Project Summary — SigNoz Warm-up Blog Challenge

Snapshot of where this stands, for quick reference and as blog-outline material.

## Status by phase

- **Phase 0 (Prep)** — Done. Repo created, HF Space cloned as sibling, 200 parquets/jsonls downloaded.
- **Phase 1 (SigNoz self-host via Foundry)** — Done. Docker memory 5GB, foundryctl installed, ClickHouse pre-pulled, cast succeeded (12/12 green), admin account created before first telemetry, MCP enabled via casting.yaml (`spec.mcp.spec.enabled: true`), casting files committed.
- **Phase 2 (Reward extraction + fidelity gate)** — Done, gate PASSED. `parser.py` and `rewards_v42.py` extracted verbatim from the April notebook. Fidelity check: max drift 2.44e-08, ~40x under tolerance.
- **Phase 3 (Instrumentation)** — Done. `otel_setup.py`, `rewards/parsimony_v1.py`, `regrade.py` built. Confirmed real 8x7 span trees (57 spans/step).
- **Phase 4 (Full replay, dashboard, queries)** — Done. 7-panel dashboard built. Full replay survived two battery incidents, reran clean. Queries #7-10 completed with strong findings.
- **Phase 5 (Alert -> Slack)** — Done. Native Slack channel, trace-based alert on `hack.signature = true`, fired successfully.
- **Phase 6 (Agent episodes)** — Cut. Guide's own "first thing cut if behind" guidance plus time pressure.
- **Phase 7 (MCP query)** — Done. Fresh neutral-directory session, independently corroborated Query #9.
- **Phase 8 (Evidence pack + publish repo)** — Not started.
- **Blog draft (the actual judged deliverable)** — Not started.

## The headline finding (steps 18-28 collapse)

Every zero-reward completion in the steps 18-28 window (47 of 88, 53%) traces to one exact, proven cause: the completion's JSON failed to parse. Dominant mechanism (83% of failures): literal unescaped newlines from markdown-style formatting embedded in the `resolution` string — confirmed at the byte level via `repr()`. The model was rewarded for becoming a better-organized technical writer, and that exact improvement broke its machine-parseable output contract. Full investigation in `COLLAPSE_INVESTIGATION.md`.

## Supporting findings (queries #8-10 + MCP)

- **#9 Overconfidence**: 143 matches. 94% cluster at confidence exactly 0.85.
- **#10 Optimizer gap**: 23 matches, several tracing back to steps 22/23/26.
- **#8 Post-convergence grounding zeros**: 80 completions, concentrated in 6 tickets (77.5%).
- **Cross-query triangulation**: TRAIN-00044 and TRAIN-00046 fail across all three independent queries.
- **Phase 7 MCP validation**: independently corroborated (443 matches, 90-day/all-runs window), same two tickets resurface. Full writeup in `ALERT_AND_MCP_STORY.md`.

## Files in the repo so far

- `GOTCHAS.md`, `EVIDENCE_LOG.md`, `COLLAPSE_INVESTIGATION.md`, `QUERIES_8_9_10_INVESTIGATION.md`, `ALERT_AND_MCP_STORY.md`
- `casting.yaml` / `casting.yaml.lock`
- `rewards/parser.py`, `rewards/rewards_v42.py`, `rewards/parsimony_v1.py`
- `otel_setup.py`, `regrade.py`, `verify_fidelity.py`

## What's actually left

1. Phase 8: organize `evidence/` folder, write `README.md` (what/why/run-it + AI disclosure + links), `git grep -i verizon` check, final commit + push.
2. Write the blog (1000-1500 words, Hook/Context/Body/Takeaways/Conclusion, lead with the collapse finding early, curate 4-6 screenshots, fact-check OTel claims against opentelemetry.io).
3. Publish on Medium, Dev.to, or Substack.
4. Submit the form before July 19.
