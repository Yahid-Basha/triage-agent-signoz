"""
Verbatim extraction of the six v4.2 reward functions from the training notebook:
triage_agent_env/training/train_grpo_colab_openenvHackathon_finale.ipynb,
cells 7 (corpus/ticket index), 10 (reward helper extractors), 11 (the six
reward functions + REWARD_FUNCS/REWARD_WEIGHTS). Not paraphrased.

Import trick: the notebook stubs server/__init__.py on disk (it only needs
server.corpus + server.rewards, and the real __init__.py auto-imports
TriageAgentEnvironment, which requires the private openenv-core package that
isn't on PyPI). triage_agent_env/ here is a read-only sibling clone (its own
git remote — we must not modify it), so instead of overwriting its
server/__init__.py on disk we register the same stub *in memory*: a synthetic
"server" package object in sys.modules whose __path__ points at
triage_agent_env/server, so `from server.corpus import Corpus` resolves
server/corpus.py directly without ever executing the real __init__.py. Same
effect as the notebook's trick, zero mutation of the read-only clone.
"""

import re
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from rouge_score import rouge_scorer

from .parser import KNOWN_TOOLS, _ID_PATTERN, _completion_text, _prompt_user_text, parse_tool_call

_TRIAGE_ENV_ROOT = Path(__file__).resolve().parent.parent.parent / "triage_agent_env"
_SERVER_DIR = _TRIAGE_ENV_ROOT / "server"
DATA_DIR = _TRIAGE_ENV_ROOT / "data"

if "server" not in sys.modules:
    _stub = types.ModuleType("server")
    _stub.__path__ = [str(_SERVER_DIR)]
    sys.modules["server"] = _stub

from server.corpus import Corpus  # noqa: E402

# ── Corpus + ticket index (loaded once, shared by all reward functions) ──────
_CORPUS: Optional[Corpus] = None
_TICKET_INDEX: Dict[str, dict] = {}


def get_corpus() -> Corpus:
    global _CORPUS
    if _CORPUS is None:
        _CORPUS = Corpus(DATA_DIR)
    return _CORPUS


def get_ticket_index() -> Dict[str, dict]:
    global _TICKET_INDEX
    if not _TICKET_INDEX:
        import json
        with open(DATA_DIR / "train_tickets.json") as f:
            tickets = json.load(f)
        _TICKET_INDEX = {t.get("ticket_id", t.get("id", "")): t for t in tickets}
    return _TICKET_INDEX


# ── Reward helper extractors ───────────────────────────────────────────────────
# Allow partial credit during cold-start when model uses wrong field names.
# Canonical keys still win via a 0.6× discount on fallback paths.

_RESOLUTION_FALLBACK_KEYS = (
    "details", "description", "solution", "resolution_steps",
    "resolution_notes", "notes", "answer", "text",
    "action", "steps_to_resolve", "summary",
)


def _extract_resolution_text(args: dict) -> Tuple[str, bool]:
    """Returns (text, used_canonical_key)."""
    if not isinstance(args, dict): return "", False
    canonical = args.get("resolution")
    if isinstance(canonical, str) and canonical.strip():
        return canonical, True
    if isinstance(canonical, dict):
        nested = canonical.get("resolution") or canonical.get("text") or ""
        if isinstance(nested, str) and nested.strip():
            return nested, False
    for key in _RESOLUTION_FALLBACK_KEYS:
        v = args.get(key)
        if isinstance(v, str) and v.strip():
            return v, False
    string_vals = [v for v in args.values() if isinstance(v, str) and len(v.strip()) > 20]
    if string_vals: return max(string_vals, key=len), False
    return "", False


def _extract_citation_ids(args: dict, full_text: str) -> Tuple[Set[str], bool]:
    """Returns (ids, used_canonical_field)."""
    if isinstance(args, dict):
        canonical = args.get("cited_artifacts")
        if isinstance(canonical, list):
            ids = {str(c) for c in canonical if isinstance(c, (str, int))}
            ids = {i for i in ids if _ID_PATTERN.fullmatch(i)}
            if ids: return ids, True
        if isinstance(canonical, str) and _ID_PATTERN.fullmatch(canonical):
            return {canonical}, True
        for v in args.values():
            if isinstance(v, list):
                ids = {str(x) for x in v if isinstance(x, str) and _ID_PATTERN.fullmatch(x)}
                if ids: return ids, False
            elif isinstance(v, str) and _ID_PATTERN.fullmatch(v):
                return {v}, False
    return set(_ID_PATTERN.findall(full_text or "")), False


# ── Reward functions (6 total) ─────────────────────────────────────────────────

_ROUGE = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)


# ── R1: Graduated format (5-tier, 0.0 → 1.0) ─────────────────────────────────
def r_format_graduated(completions, **kwargs):
    out = []
    for c in completions:
        text      = _completion_text(c)
        score     = 0.0
        canonical = "```json" in text
        if canonical:              score = 0.2
        elif "<tool_call>" in text: score = 0.1
        parsed = parse_tool_call(text)
        if parsed is None: out.append(score); continue
        score   = 0.4 if canonical else 0.3
        py_call     = bool(re.search(r'\b(?:' + '|'.join(KNOWN_TOOLS) + r')\s*\(', text))
        double_wrap = bool(re.search(r'submit_resolution\s*\([^)]*?submit_resolution\s*\(', text, re.DOTALL))
        if parsed["tool_name"] in KNOWN_TOOLS:
            score = 0.6 if canonical else 0.5
        if parsed["tool_name"] == "submit_resolution":
            args = parsed.get("arguments", {})
            has_resolution = isinstance(args.get("resolution"), str) and len(args["resolution"].strip()) > 20
            if has_resolution:
                score = 0.8 if canonical else 0.65
            req = {"resolution", "cited_artifacts", "confidence"}
            fields_ok = (has_resolution and req.issubset(args.keys())
                         and isinstance(args.get("cited_artifacts"), list))
            if fields_ok and canonical and not py_call: score = 1.0
            elif fields_ok: score = 0.85
        if double_wrap:   score = min(score, 0.35)
        elif py_call:     score = min(score, 0.5)
        out.append(score)
    return out


# ── R2: Resolution quality (ROUGE-L vs gold) ──────────────────────────────────
def r_resolution_quality(completions, ticket_id, **kwargs):
    idx = get_ticket_index()
    out = []
    for c, tid in zip(completions, ticket_id):
        text   = _completion_text(c)
        parsed = parse_tool_call(text)
        if parsed is None or parsed["tool_name"] != "submit_resolution":
            out.append(0.0); continue
        args = parsed.get("arguments", {})
        submitted, used_canonical = _extract_resolution_text(args)
        gold = idx.get(tid, {}).get("gold_resolution", "")
        gold = gold if isinstance(gold, str) else str(gold)
        if not submitted or not gold: out.append(0.0); continue
        f1 = _ROUGE.score(gold, submitted)["rougeL"].fmeasure
        if not used_canonical: f1 *= 0.6
        out.append(f1)
    return out


# ── R3: Citation grounding (F1 + behavioral floor) ────────────────────────────
def r_citation_grounding(completions, ticket_id, prompts=None, **kwargs):
    idx      = get_ticket_index()
    _prompts = list(prompts) if prompts is not None else [None] * len(completions)
    out = []
    for c, tid, pr in zip(completions, ticket_id, _prompts):
        text   = _completion_text(c)
        parsed = parse_tool_call(text)
        ticket = idx.get(tid, {})
        gold   = set(ticket.get("gold_cited_ids", []))
        is_unans = ticket.get("is_unanswerable", False)
        if parsed is None or parsed["tool_name"] != "submit_resolution":
            out.append(0.0); continue
        args  = parsed.get("arguments", {})
        cited, used_canonical = _extract_citation_ids(args, text)
        if is_unans:
            esc = bool(args.get("escalate", False))
            out.append(1.0 if (not cited and esc) else 0.3 if not cited else 0.0); continue
        if not gold:
            esc = bool(args.get("escalate", False))
            out.append(1.0 if esc else 0.1); continue
        if not cited: out.append(0.0); continue
        ctx_ids = set(re.findall(r'### (\S+)', _prompt_user_text(pr))) if pr is not None else set()
        tp = len(cited & gold)
        if tp == 0:
            if ctx_ids:
                out.append(0.3 if bool(cited & ctx_ids) else 0.05)
            else:
                out.append(0.0)
            continue
        p_val = tp / len(cited)
        r_val = tp / len(gold)
        f1    = 2 * p_val * r_val / (p_val + r_val)
        if not used_canonical: f1 *= 0.6
        out.append(0.3 + 0.7 * f1 if (ctx_ids and cited & ctx_ids) else f1)
    return out


# ── R4: Confidence calibration (Brier-style) ──────────────────────────────────
def r_calibration(completions, ticket_id, **kwargs):
    idx = get_ticket_index()
    out = []
    for c, tid in zip(completions, ticket_id):
        text   = _completion_text(c)
        parsed = parse_tool_call(text)
        if parsed is None or parsed["tool_name"] != "submit_resolution":
            out.append(0.0); continue
        args = parsed.get("arguments", {})
        try:
            conf = float(args.get("confidence", 0.5))
            conf = max(0.0, min(1.0, conf))
        except Exception:
            out.append(0.0); continue
        gold       = idx.get(tid, {}).get("gold_resolution", "")
        gold       = gold if isinstance(gold, str) else str(gold)
        submitted, used_canonical = _extract_resolution_text(args)
        quality    = _ROUGE.score(gold, submitted)["rougeL"].fmeasure if (gold and submitted) else 0.0
        if not used_canonical: quality *= 0.6
        out.append(1.0 - (conf - quality) ** 2)
    return out


# ── R5: Parsimony (Goldilocks length: 100-250 words = 1.0) ────────────────────
_PENDING_COMPLETIONS: List[dict] = []

def r_parsimony(completions, **kwargs):
    tids = list(kwargs.get("ticket_id") or [])
    out  = []
    for i, c in enumerate(completions):
        text        = _completion_text(c)
        parsed      = parse_tool_call(text)
        is_finished = text.strip().endswith("```")
        if parsed is None or not is_finished:
            score = 0.0
        else:
            n = len(text.split())
            if n < 60:       score = 0.1
            elif n < 100:    score = 0.5
            elif n <= 250:   score = 1.0
            elif n <= 400:   score = 0.4
            else:            score = 0.0
        out.append(score)
        if i < len(tids):
            _PENDING_COMPLETIONS.append({
                "ticket_id":  tids[i],
                "completion": text[:3000],
                "parsed":     parsed is not None and is_finished,
                "r_parsimony": round(score, 4),
            })
    return out


# ── R6: Repetition penalty (unique cited IDs ratio) ───────────────────────────
def r_repetition_penalty(completions, **kwargs):
    out = []
    for c in completions:
        text = _completion_text(c)
        ids  = _ID_PATTERN.findall(text)
        if not ids: out.append(1.0); continue
        unique_ratio = len(set(ids)) / len(ids)
        out.append(unique_ratio if (len(ids) > 3 and unique_ratio < 0.5) else 1.0)
    return out


REWARD_FUNCS   = [r_format_graduated, r_resolution_quality, r_citation_grounding,
                  r_calibration, r_parsimony, r_repetition_penalty]
REWARD_WEIGHTS = [0.3, 1.5, 1.0, 0.4, 0.4, 0.4]
