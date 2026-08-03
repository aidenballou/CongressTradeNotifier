import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

import emailer  # noqa: E402


def test_send_summary_fails_when_email_configuration_is_missing(monkeypatch):
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "EMAIL_RECIPIENT"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="Missing required email configuration"):
        emailer.send_summary([{"disclosureDate": "2026-08-03"}], {"total_trades": 1})
