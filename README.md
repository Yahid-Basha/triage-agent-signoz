# triage-agent-signoz

Re-grading my April GRPO training run through a live instrumented pipeline, with SigNoz (self-hosted via Foundry) as the backend. Built for the WeMakeDevs x SigNoz warm-up blog challenge.

## What this is

In April I trained Qwen2.5-3B with GRPO to resolve enterprise IT tickets. The run logged every completion, all six reward scores, and the GRPO advantage to parquet files: 200 steps, 8 completions per step. Then those files sat on my disk for three months.

This project takes the six reward functions (the exact code from that run), instruments them with OpenTelemetry, and re-grades all 1,600 completions live, streaming every span into SigNoz. The code executes now. The April data is only the input, never replayed telemetry.

## What SigNoz gave me

I had WandB during training, so I already knew the reward averages went up. What I never had was a way to ask "which completion, on which ticket, said what." That is the reason this project exists, and it is the thing SigNoz let me do.

The payoff was concrete. A reward collapse showed up on my dashboard around steps 18-28, so I filtered the traces to that window and read the completions behind the zero scores. Ten minutes later I had an answer no loss curve could have given me: the model had not gotten worse at the task, it had started writing markdown line breaks into its JSON, which broke the parser, which zeroed every reward at once. I found a real training bug by clicking into spans and reading text.

A few things earned real gratitude:

- The Query Builder let me treat my custom `reward.*` and `grpo.*` attributes as real, queryable dimensions, so I could ask "high stated confidence but low actual quality" and get rows back. An experiment tracker cannot answer that.
- The alerting caught the old reward-hack signature and pushed it to Slack in seconds. In April, that same bug cost me a night and a 4am debugging session.
- The MCP server let me point Claude Code at the live instance and ask questions in plain English.

The honest summary: the hard part of this was the ML, and SigNoz stayed out of the way. Once spans were flowing, most of what I wanted to know was one filter away.

## Repo layout

    casting.yaml / casting.yaml.lock   Foundry deployment config for self-hosted SigNoz
    requirements.txt
    GOTCHAS.md                         timestamped snag log, every phase
    EVIDENCE_LOG.md                    the full evidence checklist
    PROJECT_SUMMARY.md                 phase-by-phase status
    COLLAPSE_INVESTIGATION.md          the steps 18-28 root-cause investigation
    QUERIES_8_9_10_INVESTIGATION.md    the confidence / advantage / grounding queries
    ALERT_AND_MCP_STORY.md             the alert firing and the MCP validation
    rewards/parser.py                  verbatim from the April notebook
    rewards/rewards_v42.py             verbatim, all six reward functions
    rewards/parsimony_v1.py            the reconstructed April reward-hack bug
    otel_setup.py                      OTel tracer and logger setup
    regrade.py                         the replay pipeline
    verify_fidelity.py                 the fidelity gate

## How to run it

    curl -fsSL https://signoz.io/foundry.sh | bash
    foundryctl cast -f casting.yaml
    # create the admin account at localhost:8080 before sending any telemetry
    python3 verify_fidelity.py         # confirms the reward code matches April bit for bit
    python3 regrade.py --steps 1-3     # smoke test
    python3 regrade.py                 # full replay

## The finding, in one paragraph

Of the 88 completions across steps 18-28, 47 scored zero on every content reward. All 47 failed for the same reason: their JSON would not parse. As GRPO pushed the model toward longer, better-organized answers, it began writing literal newlines into JSON string values, which is invalid, so the parser rejected them and every dependent reward dropped to zero at once. I confirmed it down to the exact byte. The full write-up is in COLLAPSE_INVESTIGATION.md.

## Links

- April training blog: https://huggingface.co/spaces/yahid/triage_agent_env/blob/main/Blog.md
- HF Space (OpenEnv environment): https://huggingface.co/spaces/yahid/triage_agent_env
- Model and completions dataset: [yahid/triage-agent-qwen3b](https://huggingface.co/yahid/triage-agent-qwen3b)
- WandB run: https://wandb.ai/yahid-sahe/triage-agent-grpo/runs/99l7dg4c/logs?nw=nwuseryahid

## AI disclosure

The direction, architecture, UI exploration, screenshots, and the discovery itself are mine. The instrumentation scaffolding, the analysis scripts, and this README were written with Claude Code under my direction and reviewed before use. Every finding here was checked against real data before I trusted it, including two of my own hypotheses that turned out wrong and stayed in the record anyway (see COLLAPSE_INVESTIGATION.md).
