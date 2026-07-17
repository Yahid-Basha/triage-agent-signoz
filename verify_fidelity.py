"""
Fidelity check: re-run the six live v4.2 reward functions (rewards/rewards_v42.py,
extracted verbatim from the April training notebook) against one stored parquet of
April completions, and compare against the reward columns TRL logged during actual
training. Read-only re-grading — no retraining, no parquet mutation.

Usage: python3 verify_fidelity.py [path/to/completions_00001.parquet]
"""

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rewards.rewards_v42 import (  # noqa: E402
    r_format_graduated,
    r_resolution_quality,
    r_citation_grounding,
    r_calibration,
    r_parsimony,
    r_repetition_penalty,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PARQUET = REPO_ROOT / "completions" / "completions" / "completions_00001.parquet"

_TICKET_ID_PATTERN = re.compile(r'# Ticket: (\S+)')

REWARD_FNS = {
    "r_format_graduated":    r_format_graduated,
    "r_resolution_quality":  r_resolution_quality,
    "r_citation_grounding":  r_citation_grounding,
    "r_calibration":         r_calibration,
    "r_parsimony":           r_parsimony,
    "r_repetition_penalty":  r_repetition_penalty,
}


def _ticket_id_from_prompt(prompt: str) -> str:
    m = _TICKET_ID_PATTERN.search(prompt)
    return m.group(1) if m else ""


def main():
    parquet_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PARQUET
    df = pd.read_parquet(parquet_path)

    completions = df["completion"].tolist()
    prompts     = df["prompt"].tolist()
    ticket_ids  = [_ticket_id_from_prompt(p) for p in prompts]

    live_scores = {
        "r_format_graduated":   r_format_graduated(completions),
        "r_resolution_quality": r_resolution_quality(completions, ticket_ids),
        "r_citation_grounding": r_citation_grounding(completions, ticket_ids, prompts=prompts),
        "r_calibration":        r_calibration(completions, ticket_ids),
        "r_parsimony":          r_parsimony(completions, ticket_id=ticket_ids),
        "r_repetition_penalty": r_repetition_penalty(completions),
    }

    print(f"Fidelity check: {parquet_path.relative_to(REPO_ROOT) if parquet_path.is_relative_to(REPO_ROOT) else parquet_path}")
    print(f"Rows: {len(df)}  (step={df['step'].iloc[0] if 'step' in df.columns else '?'})\n")

    max_drift_overall = 0.0
    for reward_name, live in live_scores.items():
        logged = df[reward_name].tolist()
        print(f"── {reward_name} " + "─" * (60 - len(reward_name)))
        print(f"{'row':>3}  {'ticket_id':<14}{'live':>10}{'logged':>10}{'drift':>12}")
        for i, (tid, lv, lg) in enumerate(zip(ticket_ids, live, logged)):
            drift = lv - lg
            max_drift_overall = max(max_drift_overall, abs(drift))
            flag = "  <-- DRIFT" if abs(drift) > 1e-6 else ""
            print(f"{i:>3}  {tid:<14}{lv:>10.6f}{lg:>10.6f}{drift:>12.2e}{flag}")
        print()

    print(f"Max absolute drift across all rewards/rows: {max_drift_overall:.2e}")
    print("PASS: bit-for-bit match (drift ~= 0)" if max_drift_overall < 1e-6 else "GATE FAILED: drift detected, investigate before Phase 3")


if __name__ == "__main__":
    main()
