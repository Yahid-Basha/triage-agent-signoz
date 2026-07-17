"""
parsimony v1 — the buggy reward function that shipped in an earlier training
run the same April night documented in the public blog. Character-based
(the v4.2 fix in rewards_v42.py switched to word count) with an inverted
branch: it rewards completions under 200 characters OR over 400 characters,
and penalizes the sane middle. Trained against, this taught the model that
the fastest way up the reward curve was to either say almost nothing or pad
with irrelevant text — including the Star Wars trivia found manually at 4 AM.

This is a postmortem reconstruction of a real, previously-published incident
(see the April blog), not a new or hypothetical bug. It exists here purely as
a side-by-side counterfactual against rewards_v42.r_parsimony, to compute
`hack.signature` during the regrade replay — it is never used to train
anything.
"""

from .parser import _completion_text, parse_tool_call


def r_parsimony_v1(completions, **kwargs):
    out = []
    for c in completions:
        text = _completion_text(c)
        parsed = parse_tool_call(text)
        if parsed is None:
            out.append(0.0)
            continue
        n = len(text)
        if n < 200 or n > 400:
            score = 1.0
        else:
            score = 0.0
        out.append(score)
    return out
