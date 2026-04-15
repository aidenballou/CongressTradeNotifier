"""LLM-powered insight generation for engagement-optimized tweet copy."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

import requests

try:
    from filing_utils import (
        extract_trades as _extract_trades,
        member_name as _member_name,
        stable_mode as _stable_mode,
    )
except ImportError:  # pragma: no cover
    from src.filing_utils import (
        extract_trades as _extract_trades,
        member_name as _member_name,
        stable_mode as _stable_mode,
    )


OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MAX_FIELD_LEN = 240
BANNED_WORDS = {"disclosed"}
UNCERTAINTY_PATTERNS = (
    r"\bcould\b",
    r"\bmay\b",
    r"\bmight\b",
    r"\bif\b",
    r"\bunclear\b",
    r"\bnot guaranteed\b",
    r"\brisk(?:s|y)?\b",
)


def _sanitize_field(text: str) -> str:
    value = " ".join((text or "").replace("\n", " ").split()).strip()
    for banned in BANNED_WORDS:
        value = value.replace(banned, "reported")
        value = value.replace(banned.capitalize(), "Reported")
    if value.startswith("- "):
        value = value[2:]
    if len(value) > MAX_FIELD_LEN:
        value = value[: MAX_FIELD_LEN - 1].rstrip() + "…"
    return value


def _has_uncertainty(text: str) -> bool:
    lowered = (text or "").lower()
    return any(re.search(pattern, lowered) for pattern in UNCERTAINTY_PATTERNS)


def _hook_score(hook: str, member: str, tickers: str) -> float:
    """
    Deterministic quality score for a hook: prefer specificity, length in range, no generic openers.
    Higher is better.
    """
    if not hook or len(hook) < 10:
        return 0.0
    score = 0.0
    hook_lower = hook.lower()
    # Prefer hooks that mention member or ticker
    if member and member.lower() in hook_lower:
        score += 2.0
    for t in (tickers or "").split(","):
        t = t.strip().upper()
        if t and t in hook.upper():
            score += 1.5
            break
    # Prefer concrete numbers ($, %, digits)
    if re.search(r"\$|%|\d", hook):
        score += 1.0
    # Penalize generic openers
    if hook_lower.startswith("congress just leaned"):
        score -= 2.0
    if "flow recap:" in hook_lower or "setup:" in hook_lower:
        score -= 0.5
    # Prefer length 60–180 chars for punch
    n = len(hook)
    if 60 <= n <= 180:
        score += 1.0
    elif 40 <= n <= 220:
        score += 0.5
    return max(0.0, score)


def _enforce_contract(payload: Dict[str, str]) -> Dict[str, str]:
    hook = _sanitize_field(payload.get("hook", ""))
    interpretation = _sanitize_field(payload.get("interpretation", ""))
    question = _sanitize_field(payload.get("question", ""))

    if not _has_uncertainty(interpretation):
        _uncertainty_variants = [
            "It could keep running, or fade fast if momentum breaks.",
            "Whether this holds may depend on how the broader tape reacts.",
            "Risk of reversal is always on the table if sentiment shifts.",
            "This might signal conviction, but follow-through is never guaranteed.",
            "If the trade is right the payoff could be quick, but the thesis can break just as fast.",
        ]
        _u_seed = interpretation[:20] if interpretation else "x"
        _u_idx = sum(ord(c) for c in _u_seed) % len(_uncertainty_variants)
        interpretation = _sanitize_field(f"{interpretation} {_uncertainty_variants[_u_idx]}")

    if not question.endswith("?"):
        question = _sanitize_field(question.rstrip(".! ") + "?")

    if not hook:
        hook = "Congress just leaned into the same pocket of risk again."
    if not interpretation:
        interpretation = "Positioning points to conviction, but timing risk is real if headlines flip."
    if not question:
        question = "Do you chase this move or wait for confirmation?"

    return {
        "hook": hook,
        "interpretation": interpretation,
        "question": question,
    }


def _build_prompt(filing: Dict[str, Any], signal: Dict[str, Any], context: Dict[str, Any]) -> str:
    trades = _extract_trades(filing)
    trade_lines = []
    for trade in trades[:5]:
        side = str(trade.get("type") or trade.get("transaction_type") or "").upper()
        symbol = str(trade.get("symbol") or trade.get("ticker") or "").upper()
        amount = str(trade.get("amount") or "")
        trade_lines.append(f"{side} {symbol} {amount}".strip())

    summary = str(signal.get("summarySentence") or "")
    signal_type = str(signal.get("signalType") or "OTHER")
    member = _member_name(trades[0]) if trades else "A member"
    symbols = [str(t.get("symbol") or t.get("ticker") or "").upper() for t in trades[:5] if str(t.get("symbol") or t.get("ticker") or "").strip()]
    ticker_list = ", ".join(symbols[:3]) if symbols else ""

    historical = (context.get("combinedSummary") or "").strip()
    last_outcome = str(context.get("lastTradeOutcome") or "").strip()

    return (
        "You are writing copy for a financial Twitter account focused on congressional trading signals. "
        "Write with human trader voice: natural, concise, and SPECIFIC. "
        "Output strict JSON only with keys: hook, hook_alt (second option), interpretation, question. "
        "Rules: no bullets, no robotic phrasing, never use the word 'disclosed', each field <=240 chars, "
        "end question with '?'. "
        "HOOK: Must be specific and attention-grabbing. Include a concrete detail: member name, ticker, or size. "
        "Create curiosity (why now, why this trade). Avoid generic openers like 'Congress just leaned into'. "
        "INTERPRETATION: One clear market implication; include one uncertainty phrase (could/may/might). "
        "QUESTION: Provoke judgment or debate (e.g. 'Is this insider buying the dip or front-running a catalyst?'). "
        "Avoid vague questions like 'Do you chase this move?'."
        f"\nSignal type: {signal_type}."
        f"\nSignal summary: {summary}"
        f"\nMember: {member}. Tickers: {ticker_list}."
        f"\nTrades: {' | '.join(trade_lines)}"
        f"\nHistorical context: {historical}"
        + (f"\nPrior outcome for context (weave in if relevant): {last_outcome}" if last_outcome else "")
    )


def _call_openai(prompt: str) -> Dict[str, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    payload = {
        "model": model,
        "temperature": 0.8,
        "messages": [
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = requests.post(OPENAI_URL, headers=headers, json=payload, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text[:200]}")

    data = response.json() or {}
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "{}")
    )
    parsed = json.loads(content)
    return {
        "hook": str(parsed.get("hook", "")),
        "hook_alt": str(parsed.get("hook_alt", "")),
        "interpretation": str(parsed.get("interpretation", "")),
        "question": str(parsed.get("question", "")),
    }


def _fallback_generate(filing: Dict[str, Any], signal: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, str]:
    trades = _extract_trades(filing)
    member = _member_name(trades[0]) if trades else "A member"
    symbols = [str(t.get("symbol") or t.get("ticker") or "").upper() for t in trades if str(t.get("symbol") or t.get("ticker") or "").strip()]
    ticker_text = ", ".join(symbols[:3]) if symbols else "their latest names"
    signal_type = str(signal.get("signalType") or "OTHER")

    key = f"{member}|{ticker_text}|{signal_type}|{filing.get('disclosureDate', '')}"
    mode = _stable_mode(key)

    hooks = [
        f"Congress just leaned into {ticker_text} again.",
        f"{member} made a high-conviction move in {ticker_text}.",
        f"This tape just got a new signal: {ticker_text} drew political capital.",
    ]
    interpretations = [
        f"If this read is right, leadership sectors could stay bid, though timing risk is still real.",
        f"It may hint at a risk-on rotation, but one headline can unwind the move quickly.",
        f"This could be informed positioning, or just noise in a volatile week.",
    ]
    questions = [
        "Would you front-run this flow or wait for price confirmation?",
        "Do you treat this as signal, or fade it into the next volatility spike?",
        "Is this early positioning, or are we late to the trade now?",
    ]

    context_hint = str(context.get("lastTradeOutcome") or "")
    interpretation = interpretations[mode]
    if context_hint:
        interpretation = f"{interpretation} {context_hint}"

    return {
        "hook": hooks[mode],
        "interpretation": interpretation,
        "question": questions[mode],
    }


def generate_insight(filing: Dict[str, Any], signal: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, str]:
    """Generate hook, interpretation, and engagement question; pick best of multiple hooks by score."""

    trades = _extract_trades(filing)
    member = _member_name(trades[0]) if trades else ""
    symbols = [str(t.get("symbol") or t.get("ticker") or "").upper() for t in trades if str(t.get("symbol") or t.get("ticker") or "").strip()]
    tickers = ", ".join(symbols[:3]) if symbols else ""

    prompt = _build_prompt(filing, signal, context)
    try:
        response = _call_openai(prompt)
    except Exception:
        response = _fallback_generate(filing, signal, context)

    hook_alt = (response.get("hook_alt") or "").strip()
    hook_main = (response.get("hook") or "").strip()
    if hook_alt and hook_main:
        s_main = _hook_score(hook_main, member, tickers)
        s_alt = _hook_score(hook_alt, member, tickers)
        if s_alt > s_main:
            response = {**response, "hook": hook_alt}
        else:
            response = {**response, "hook": hook_main}
    elif hook_alt and not hook_main:
        response = {**response, "hook": hook_alt}
    response.pop("hook_alt", None)

    return _enforce_contract(response)
