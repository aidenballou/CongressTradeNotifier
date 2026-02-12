"""LLM-powered insight generation for engagement-optimized tweet copy."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

import requests


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


def _extract_trades(filing: Dict[str, Any]) -> list[Dict[str, Any]]:
    trades = filing.get("trades")
    if isinstance(trades, list) and trades:
        return trades
    return [filing]


def _member_name(trade: Dict[str, Any]) -> str:
    if trade.get("member_name"):
        return str(trade.get("member_name")).strip()
    first = str(trade.get("firstName", "")).strip()
    last = str(trade.get("lastName", "")).strip()
    return f"{first} {last}".strip()


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


def _enforce_contract(payload: Dict[str, str]) -> Dict[str, str]:
    hook = _sanitize_field(payload.get("hook", ""))
    interpretation = _sanitize_field(payload.get("interpretation", ""))
    question = _sanitize_field(payload.get("question", ""))

    if not _has_uncertainty(interpretation):
        interpretation = _sanitize_field(f"{interpretation} It could keep running, or fade fast if momentum breaks.")

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

    return (
        "You are writing copy for a financial Twitter account focused on congressional trading signals. "
        "Write with human trader voice: natural, concise, and specific. "
        "Output strict JSON only with keys hook, interpretation, question. "
        "Rules: no bullets, no robotic phrasing, never use the word 'disclosed', each field <=240 chars, "
        "include market implication and uncertainty, and end question with '?'."
        f"\nSignal type: {signal_type}."
        f"\nSignal summary: {summary}"
        f"\nTrades: {' | '.join(trade_lines)}"
        f"\nHistorical context: {context.get('combinedSummary', '')}"
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
    mode = abs(hash(key)) % 3

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
    """Generate hook, interpretation, and engagement question."""

    prompt = _build_prompt(filing, signal, context)
    try:
        response = _call_openai(prompt)
    except Exception:
        response = _fallback_generate(filing, signal, context)

    return _enforce_contract(response)
