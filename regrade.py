"""
Replay all April training-step parquets through the live (real, imported,
fidelity-checked) v4.2 reward functions, emitting one OTel trace per step to
SigNoz. Read-only re-grading of stored completions — no retraining, no
gradient updates, no parquet mutation. Every span is a real function call
executing now; only the completion text being graded is from April.

Span schema (exact names — quoted in the blog, do not rename):

    grpo.step                         attrs: training.step, batch.size
      └─ grade_completion  x8         attrs: ticket.id, grpo.advantage,
         |                                   completion.words, completion.confidence,
         |                                   completion.escalate, completion.cited_count
         |-- reward.format            attrs: reward.score, reward.logged_score, reward.drift
         |-- reward.quality           (span duration = real ROUGE-L time)
         |-- reward.grounding
         |-- reward.calibration
         |-- reward.parsimony         + reward.score_v1, hack.signature
         `-- reward.repetition
"""

import argparse
import logging
import re
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from otel_setup import setup_otel, shutdown_otel  # noqa: E402
from rewards.parser import parse_tool_call  # noqa: E402
from rewards.parsimony_v1 import r_parsimony_v1  # noqa: E402
from rewards.rewards_v42 import (  # noqa: E402
    _extract_citation_ids,
    r_calibration,
    r_citation_grounding,
    r_format_graduated,
    r_parsimony,
    r_repetition_penalty,
    r_resolution_quality,
)
from verify_fidelity import _ticket_id_from_prompt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPLETIONS_DIR = REPO_ROOT / "completions" / "completions"

_FILENAME_STEP = re.compile(r"completions_(\d+)\.parquet$")

logger = logging.getLogger(__name__)


def _discover_parquets(steps_range):
    files = []
    for p in sorted(COMPLETIONS_DIR.glob("completions_*.parquet")):
        m = _FILENAME_STEP.search(p.name)
        if not m:
            continue
        step_num = int(m.group(1))
        if steps_range is not None:
            lo, hi = steps_range
            if not (lo <= step_num <= hi):
                continue
        files.append((step_num, p))
    return files


def _parse_steps_arg(raw: str):
    if raw is None:
        return None
    m = re.fullmatch(r"(\d+)-(\d+)", raw.strip())
    if not m:
        raise argparse.ArgumentTypeError(f"--steps must look like '1-5', got {raw!r}")
    lo, hi = int(m.group(1)), int(m.group(2))
    if lo > hi:
        raise argparse.ArgumentTypeError(f"--steps range is backwards: {raw!r}")
    return (lo, hi)


def _completion_args(text: str) -> dict:
    parsed = parse_tool_call(text)
    if parsed is None or parsed.get("tool_name") != "submit_resolution":
        return {}
    args = parsed.get("arguments", {})
    return args if isinstance(args, dict) else {}


def _reward_span(tracer, name, compute_fn, logged_score, ticket_id, step, completion_text):
    """Runs compute_fn() (the real reward call — its duration IS the span
    duration) inside a child span, records live/logged/drift, and logs the
    completion (truncated) if the live score is 0."""
    with tracer.start_as_current_span(name) as span:
        live_score = float(compute_fn())
        drift = live_score - float(logged_score)
        span.set_attribute("reward.score", live_score)
        span.set_attribute("reward.logged_score", float(logged_score))
        span.set_attribute("reward.drift", drift)
        if live_score == 0.0:
            logger.info(
                "%s scored 0.0 | step=%s ticket=%s completion=%r",
                name, step, ticket_id, completion_text[:500],
            )
    return live_score


def grade_completion(tracer, row, step):
    prompt = row["prompt"]
    completion_text = row["completion"]
    advantage = float(row["advantage"])
    ticket_id = _ticket_id_from_prompt(prompt)

    args = _completion_args(completion_text)
    confidence = args.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    escalate = bool(args.get("escalate", False))
    cited_ids, _ = _extract_citation_ids(args, completion_text)

    with tracer.start_as_current_span("grade_completion") as gc_span:
        gc_span.set_attribute("ticket.id", ticket_id)
        gc_span.set_attribute("grpo.advantage", advantage)
        gc_span.set_attribute("completion.words", len(completion_text.split()))
        gc_span.set_attribute("completion.confidence", confidence)
        gc_span.set_attribute("completion.escalate", escalate)
        gc_span.set_attribute("completion.cited_count", len(cited_ids))

        _reward_span(
            tracer, "reward.format",
            lambda: r_format_graduated([completion_text])[0],
            row["r_format_graduated"], ticket_id, step, completion_text,
        )

        quality_score = _reward_span(
            tracer, "reward.quality",
            lambda: r_resolution_quality([completion_text], [ticket_id])[0],
            row["r_resolution_quality"], ticket_id, step, completion_text,
        )

        _reward_span(
            tracer, "reward.grounding",
            lambda: r_citation_grounding([completion_text], [ticket_id], prompts=[prompt])[0],
            row["r_citation_grounding"], ticket_id, step, completion_text,
        )

        _reward_span(
            tracer, "reward.calibration",
            lambda: r_calibration([completion_text], [ticket_id])[0],
            row["r_calibration"], ticket_id, step, completion_text,
        )

        # reward.parsimony: computes both the real v4.2 score and the buggy
        # v1 score on the same text, to derive hack.signature.
        with tracer.start_as_current_span("reward.parsimony") as span:
            score = float(r_parsimony([completion_text], ticket_id=[ticket_id])[0])
            score_v1 = float(r_parsimony_v1([completion_text])[0])
            logged_score = float(row["r_parsimony"])
            drift = score - logged_score
            hack_signature = bool(score_v1 >= 0.9 and quality_score < 0.10)
            span.set_attribute("reward.score", score)
            span.set_attribute("reward.logged_score", logged_score)
            span.set_attribute("reward.drift", drift)
            span.set_attribute("reward.score_v1", score_v1)
            span.set_attribute("hack.signature", hack_signature)
            if score == 0.0 or hack_signature:
                logger.info(
                    "reward.parsimony score=%.4f score_v1=%.4f hack.signature=%s | "
                    "step=%s ticket=%s completion=%r",
                    score, score_v1, hack_signature, step, ticket_id, completion_text[:500],
                )

        _reward_span(
            tracer, "reward.repetition",
            lambda: r_repetition_penalty([completion_text])[0],
            row["r_repetition_penalty"], ticket_id, step, completion_text,
        )


def replay(steps_range, sleep_s, limit):
    tracer = setup_otel()
    files = _discover_parquets(steps_range)
    if not files:
        logger.warning("No parquets matched --steps %s in %s", steps_range, COMPLETIONS_DIR)
        return

    processed = 0
    for step_num, path in files:
        df = pd.read_parquet(path)
        with tracer.start_as_current_span("grpo.step") as step_span:
            step_span.set_attribute("training.step", int(df["step"].iloc[0]) if "step" in df.columns else step_num)
            step_span.set_attribute("batch.size", len(df))
            for _, row in df.iterrows():
                if limit is not None and processed >= limit:
                    break
                grade_completion(tracer, row, step_num)
                processed += 1
        logger.info("step %s done (%s rows) — %s completions graded so far", step_num, len(df), processed)
        if limit is not None and processed >= limit:
            break
        time.sleep(sleep_s)

    logger.info("Replay complete: %s completions graded across %s steps", processed, len(files))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=str, default=None,
                         help="Step range to replay, e.g. '1-3' or '15-35'. Default: all.")
    parser.add_argument("--sleep", type=float, default=2.5,
                         help="Seconds to sleep between steps (default 2.5).")
    parser.add_argument("--limit", type=int, default=None,
                         help="Cap total completions graded, for fast smoke tests.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    steps_range = _parse_steps_arg(args.steps)

    try:
        replay(steps_range, args.sleep, args.limit)
    except KeyboardInterrupt:
        logger.warning("Interrupted — flushing whatever was graded so far.")
    finally:
        shutdown_otel()


if __name__ == "__main__":
    main()
