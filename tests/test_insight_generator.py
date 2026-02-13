import sys
import os
import subprocess
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

import insight_generator


def test_generate_insight_enforces_contract(monkeypatch):
    filing = {
        "trades": [
            {
                "firstName": "Dana",
                "lastName": "Lake",
                "symbol": "NVDA",
                "type": "Purchase",
                "amount": "$15,001 - $50,000",
            }
        ],
        "disclosureDate": "2026-01-10",
    }
    signal = {"signalType": "CONVICTION", "summarySentence": "Large repeat buy in AI exposure."}
    context = {"combinedSummary": "Context check: prior analogs were positive but mixed."}

    monkeypatch.setattr(
        insight_generator,
        "_call_openai",
        lambda _prompt: {
            "hook": "Congress disclosed another AI bet.",
            "interpretation": "Momentum looks strong.",
            "question": "Front-run this move",
        },
    )

    out = insight_generator.generate_insight(filing, signal, context)

    assert "disclosed" not in out["hook"].lower()
    assert out["question"].endswith("?")
    assert len(out["hook"]) <= 240
    assert len(out["interpretation"]) <= 240
    assert len(out["question"]) <= 240
    assert any(token in out["interpretation"].lower() for token in ["could", "may", "might", "if", "risk"])


def test_generate_insight_fallback(monkeypatch):
    filing = {
        "trades": [
            {
                "firstName": "Dana",
                "lastName": "Lake",
                "symbol": "MSFT",
                "type": "Purchase",
                "amount": "$1,001 - $15,000",
            }
        ],
        "disclosureDate": "2026-01-10",
    }
    signal = {"signalType": "FIRST_BUY", "summarySentence": "Fresh initiation."}
    context = {"combinedSummary": "Context check: limited prior history."}

    monkeypatch.setattr(insight_generator, "_call_openai", lambda _prompt: (_ for _ in ()).throw(RuntimeError("boom")))

    out = insight_generator.generate_insight(filing, signal, context)

    assert out["hook"]
    assert out["interpretation"]
    assert out["question"].endswith("?")


def test_fallback_generate_stable_across_pythonhashseed():
    repo_root = Path(__file__).resolve().parents[1]
    src_path = str(repo_root / "src")
    code = """
from insight_generator import _fallback_generate
filing = {
    "trades": [{"firstName": "Dana", "lastName": "Lake", "symbol": "MSFT", "type": "Purchase", "amount": "$1,001 - $15,000"}],
    "disclosureDate": "2026-01-10",
}
signal = {"signalType": "FIRST_BUY", "summarySentence": "Fresh initiation."}
context = {"combinedSummary": "Context check: limited prior history."}
out = _fallback_generate(filing, signal, context)
print(out["hook"])
print(out["question"])
""".strip()
    env1 = os.environ.copy()
    env1["PYTHONPATH"] = src_path
    env1["PYTHONHASHSEED"] = "3"
    env2 = os.environ.copy()
    env2["PYTHONPATH"] = src_path
    env2["PYTHONHASHSEED"] = "4"

    out1 = subprocess.check_output([sys.executable, "-c", code], env=env1, text=True).strip()
    out2 = subprocess.check_output([sys.executable, "-c", code], env=env2, text=True).strip()
    assert out1 == out2
