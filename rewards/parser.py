"""
Verbatim extraction of the tool-call parser from the training notebook:
triage_agent_env/training/train_grpo_colab_openenvHackathon_finale.ipynb, cell 8
("Tool-call parser") plus the two completion/prompt text helpers defined at the
end of that same cell. Not paraphrased — this is bit-for-bit the code that
trained the model, so re-grading through it is re-grading through the same
pipeline.
"""

import json
import re
from typing import Any, Dict, Optional

# ── Tool-call parser ──────────────────────────────────────────────────────────
# Handles all 4 formats Qwen emits:
#   (A) Standard:       {"tool_name": "...", "arguments": {...}}
#   (B) OpenAI:         {"function": {"name": "...", "arguments": "..."}}
#   (C) Dict shorthand: {"submit_resolution": {...args...}}
#   (D) Python call:    submit_resolution({...})
# All four can be wrapped in ```json fences, <tool_call> tags, or bare.

KNOWN_TOOLS = {
    "search_kb", "search_tickets", "search_incidents",
    "get_article", "get_ticket", "get_incident",
    "submit_resolution",
}

_ID_PATTERN = re.compile(r'\b(?:KB|INC|TKT|TRAIN|TICKET)-\d+\b')


def _extract_balanced_json(s: str, start: int) -> Optional[str]:
    if start >= len(s) or s[start] != '{':
        return None
    depth, in_str, escape = 0, False, False
    for i in range(start, len(s)):
        c = s[i]
        if escape:   escape = False; continue
        if c == '\\': escape = True; continue
        if c == '"': in_str = not in_str; continue
        if in_str:   continue
        if c == '{':   depth += 1
        elif c == '}': depth -= 1
        if depth == 0: return s[start:i + 1]
    return None


def _normalize(name: str, args: Any) -> Optional[Dict]:
    if name not in KNOWN_TOOLS: return None
    if isinstance(args, str):
        try:    args = json.loads(args)
        except: args = {}
    return {"tool_name": name, "arguments": args if isinstance(args, dict) else {}}


def _normalize_object(obj: Dict) -> Optional[Dict]:
    name = obj.get("tool_name") or obj.get("name")
    if isinstance(name, str) and name in KNOWN_TOOLS:
        return _normalize(name, obj.get("arguments") or obj.get("parameters") or {})
    fn = obj.get("function")
    if isinstance(fn, dict):
        n = fn.get("name")
        if isinstance(n, str) and n in KNOWN_TOOLS:
            return _normalize(n, fn.get("arguments", {}))
    for tool in KNOWN_TOOLS:
        if tool in obj and isinstance(obj[tool], dict):
            return _normalize(tool, obj[tool])
    return None


def _try_parse_body(body: str) -> Optional[Dict]:
    m = re.search(r'\b(' + '|'.join(KNOWN_TOOLS) + r')\s*\(\s*\{', body)
    if m:
        jp = _extract_balanced_json(body, m.end() - 1)
        if jp:
            try:
                r = _normalize(m.group(1), json.loads(jp))
                if r: return r
            except json.JSONDecodeError: pass
    idx = 0
    while idx < len(body):
        brace = body.find('{', idx)
        if brace == -1: break
        jp = _extract_balanced_json(body, brace)
        if jp:
            try:
                obj = json.loads(jp)
                if isinstance(obj, dict):
                    r = _normalize_object(obj)
                    if r: return r
            except json.JSONDecodeError: pass
            idx = brace + 1
        else: break
    return None


def parse_tool_call(text: str) -> Optional[Dict]:
    if not isinstance(text, str): return None
    for m in re.finditer(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL):
        r = _try_parse_body(m.group(1))
        if r: return r
    for m in re.finditer(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL):
        r = _try_parse_body(m.group(1))
        if r: return r
    return _try_parse_body(text)


def _completion_text(completion) -> str:
    if isinstance(completion, str): return completion
    if isinstance(completion, list):
        for msg in reversed(completion):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                return msg.get("content", "")
    return str(completion)


def _prompt_user_text(prompt) -> str:
    if isinstance(prompt, str): return prompt
    if isinstance(prompt, list):
        for msg in prompt:
            if isinstance(msg, dict) and msg.get("role") == "user":
                return msg.get("content", "")
    return ""
