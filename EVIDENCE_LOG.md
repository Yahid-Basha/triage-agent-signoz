# Evidence Log

Tracks every screenshot/artifact against the guide's PART 2 evidence checklist so nothing
gets lost before blog-writing time. Fill in Filename(s) as each one is saved to evidence/.

| # | Status | Description | Filename(s) | Phase | Blog Beat | Notes |
|---|--------|--------------|-------------|-------|-----------|-------|
| 1 | done | Terminal: cast output all green | 1 installation #1.png (original cast, pre-MCP); 1 deploy with mcp #1.jpeg (bonus — MCP-enabled recast, confirm which bucket this belongs in) | 1 | Setup, honest friction | 12/12 containers; one expected "Exited" (init script, not a failure) |
| 2 | done | Empty dashboard "no data yet" | 2 SigNoz _ Home_init #2.jpeg | 1 | Setup, honest friction | Admin account created first, per orgId gotcha |
| 3 | done | Fidelity table (live vs logged vs drift) | 3 verified_fidelity #3.txt | 2 | "Same code as April, bit for bit" | Max drift 2.44e-08, ~40x under the ~1e-6 bar |
| 4 | done | First span tree + attribute panel | 4 main #4 children and grade_completion batch of 8 .png (waterfall); 4 rew parsimony #4.png (attribute panel) | 3 | How rewards became spans | 57 spans = 1 root + 8x7; batch.size=8; float32-drift smoking gun in reward.logged_score |
| 5 | pending | Dashboard mid-replay (curves half-drawn) | | 4 | Six curves redraw live -- the movie | |
| 6 | pending | Dashboard complete | | 4 | Six curves redraw live -- the movie | |
| 7 | pending | Step 18-28 collapse autopsy completions | | 4 | THE discovery: collapse autopsy | |
| 8 | pending | Grounding-zero tickets (post-convergence) | | 4 | Converged != solved | |
| 9 | pending | Overconfidence query | | 4 | Queries WandB can't ask | |
| 10 | pending | Advantage-gap query | | 4 | Queries WandB can't ask | |
| 11 | pending | Alert rule FIRING/Triggered | | 5 | "4:30 AM, now an alert" -- climax | |
| 12 | pending | Slack message arrived | | 5 | "4:30 AM, now an alert" -- climax | |
| 13 | pending | Guilty trace behind the firing alert | | 5 | "4:30 AM, now an alert" -- climax | |
| 14 | pending | Agent trace waterfall (generation dwarfing grading) | | 6 | Live serving, theme checkbox | |
| 15 | pending | One fresh completion's grades | | 6 | Live serving, theme checkbox | |
| 16 | pending | MCP answer (Claude Code querying real trace data) | | 7 | Closing beat | |

Legend: done = captured and saved to evidence/ Â· pending = not yet captured
