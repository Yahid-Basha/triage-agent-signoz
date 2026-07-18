# Queries #8-10: Overconfidence, Optimizer Gap, and Post-Convergence Grounding

Supporting evidence queries from Phase 4 -- run after the steps 18-28 collapse autopsy
(see COLLAPSE_INVESTIGATION.md). These three share a common technical shape: each needs a
parent-span attribute (training.step / completion.confidence / grpo.advantage, all living on
grpo.step or grade_completion) joined against a child reward span's score. Handled with the
same CSV-export-plus-local-join pattern proven in Query #7, rather than fighting SigNoz's
cross-span filter bar directly.

## Method

Three exports from List View, each with parent_span_id added as a visible column (needed
for an exact join, not just a same-trace approximation):

1. `name = 'grade_completion'` across the full replay window (03:07:15-03:15) --
   columns: span_id, trace_id, ticket.id, grpo.advantage, completion.confidence.
2. `name = 'reward.quality'` across the same full window -- columns: span_id,
   parent_span_id, trace_id, reward.score.
3. `name = 'reward.grounding'`, scoped to 03:10:00-03:15:00 (comfortably past step 50,
   avoiding the need for an exact step-50 boundary) -- same columns as export 2.

One gotcha worth recording: exports 2 and 3 (the reward spans) came back with
`completion.confidence`, `grpo.advantage`, and `ticket.id` columns too -- but these are
placeholder junk (always 0 / 0 / empty), not real values, because those attributes don't
actually live on reward.* spans per the instrumentation schema. Confirmed by checking the
raw export: every reward.quality row showed `completion.confidence: 0` and `ticket.id: ''`
regardless of the actual completion. The real values only exist on the parent
`grade_completion` span and have to be joined in via `parent_span_id = span_id`.

Row counts: grade_completion.csv and rew_quality.csv both had 1616 rows (202 steps x 8
completions -- the full replay), rew_grounding.csv had 888 rows (111 steps x 8, the
post-03:10:00 window). Join success: all 1616 reward.quality rows matched a parent
grade_completion row with zero misses.

One parsing note: grpo.advantage values in the CSV export carry a leading apostrophe
(e.g. `'-1.2179102897644043`) -- a spreadsheet-safety artifact from the export, stripped
before parsing to float.

## Query #9 -- Overconfidence (completion.confidence > 0.8 AND reward.quality < 0.2)

143 matches out of 1616 quality-scored completions (~8.8%).

Checked the actual confidence values across all 143 matches rather than trusting a small
sample -- distribution:

    confidence = 0.85 : 134 times (93.7%)
    confidence = 0.90 :   8 times
    confidence = 0.95 :   1 time

The finding isn't "the model is sometimes overconfident" -- it's that confidence is drawn
from a tiny, almost-fixed set of values (dominated by exactly 0.85) regardless of whether
the actual answer is good. Sample matches:

    ticket=TRAIN-00047  confidence=0.850  quality=0.1531
    ticket=TRAIN-00049  confidence=0.850  quality=0.1706
    ticket=TRAIN-00028  confidence=0.850  quality=0.1397
    ticket=TRAIN-00011  confidence=0.850  quality=0.1215

Confidence here reads less like genuine self-assessment and more like a habitual default the
model outputs almost regardless of context -- a distinct, and arguably more interesting,
finding than "the model got overconfident."

## Query #10 -- Optimizer gap (grpo.advantage > 1 AND reward.quality < 0.15)

23 matches. Confirms the guide's framing directly: completions rewarded with positive
advantage (better than their group-of-8 mean) while still being objectively poor in absolute
terms -- "rewarded for being the least-bad sibling," a query that requires per-completion
relative and absolute scores joined together, which no aggregate WandB-style curve can show.

Sample matches, with two that tie directly back to the collapse window:

    ticket=TRAIN-00039  advantage=2.0284  quality=0.1357  trace=b81681739e
    ticket=TRAIN-00006  advantage=2.4741  quality=0.0720  trace=47dc76dfda
    ticket=TRAIN-00039  advantage=1.0551  quality=0.0960  trace=0aae41d606  <- step 26
    ticket=TRAIN-00039  advantage=1.0914  quality=0.0759  trace=0aae41d606  <- step 26
    ticket=TRAIN-00044  advantage=1.5958  quality=0.1358  trace=c5a8115906  <- step 23

Traces `0aae41d606...` and `c5a8115906...` are steps 26 and 23 from the collapse window --
meaning even the completions that survived JSON parsing during the collapse (and so weren't
zeroed outright) were still only relatively less-bad, not actually good. This query and the
steps 18-28 autopsy are describing the same underlying training moment from two different
angles.

## Query #8 -- Post-convergence grounding zeros (reward.grounding = 0 AND training.step > 50)

80 zero-grounding completions out of 888 in the post-step-50 window (9%), grouped by
ticket.id:

    TRAIN-00041 : 17
    TRAIN-00044 : 11
    TRAIN-00040 : 11
    TRAIN-00046 :  8
    TRAIN-00043 :  8
    TRAIN-00045 :  7
    (15 other tickets, 1-2 each)

Six tickets account for 62 of 80 failures (77.5%) -- not quite the guide's predicted "2-3
tickets," but the same underlying shape: a small, consistent set of tickets the model never
reliably grounds, well after general convergence, plus a long tail of one-off misses.

## Cross-query synthesis -- the actual headline finding for this set

Checked ticket overlap across all three queries directly rather than treating them as three
separate results:

    Query #8 top tickets (>=7 zero-groundings): TRAIN-00041, 00044, 00040, 00046, 00043, 00045
    Query #10 tickets: TRAIN-00039, 00006, 00044, 00041, 00036, 00026, 00046, 00032, 00035,
                        00023, 00017, 00037
    Query #9 tickets (143 total, spot-checked against #8's list): 00043, 00045, 00044, 00046
                        among others

    Overlap #8 x #10: TRAIN-00044, TRAIN-00041, TRAIN-00046
    Overlap #8 x #9:  TRAIN-00043, TRAIN-00045, TRAIN-00044, TRAIN-00046

    TRAIN-00044 and TRAIN-00046 appear in ALL THREE queries.

Three independently-constructed queries -- grounding failure, overconfidence, and optimizer
gap -- converge on the same two tickets. That's a stronger, more specific claim than "the
model didn't fully converge on some tickets": it's "these two specific tickets fail across
every reward dimension you check, independently of which angle you query from." Worth
naming explicitly in the blog as the payoff of having per-completion, cross-attribute query
access -- exactly the "queries WandB can't ask" pitch the guide itself makes for this
feature.
