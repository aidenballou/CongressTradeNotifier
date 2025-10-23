import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from insights import build_highlights_html, build_highlights_text, compute_trade_insights


def sample_trades():
    return [
        {
            "firstName": "Alice",
            "lastName": "Smith",
            "amount": "$1,000 - $5,000",
            "symbol": "AAPL",
            "type": "Purchase",
            "transactionDate": "2024-04-01",
            "disclosureDate": "2024-04-05",
        },
        {
            "firstName": "Bob",
            "lastName": "Jones",
            "amount": "$50,001 - $100,000",
            "symbol": "MSFT",
            "type": "Sale",
            "transactionDate": "2024-04-02",
            "disclosureDate": "2024-04-05",
        },
        {
            "firstName": "Bob",
            "lastName": "Jones",
            "amount": "$1,000 - $5,000",
            "symbol": "MSFT",
            "type": "Purchase",
            "transactionDate": "2024-04-03",
            "disclosureDate": "2024-04-05",
        },
    ]


def test_compute_trade_insights_identifies_key_metrics():
    insights = compute_trade_insights(sample_trades())

    assert insights["total_trades"] == 3
    assert insights["unique_ticker_count"] == 2
    assert insights["largest_trade"]["symbol"] == "MSFT"
    assert insights["most_active_member"] == ("Bob Jones", 2, pytest.approx(78000.5))
    assert insights["top_ticker"] == ("MSFT", 2, pytest.approx(78000.5))
    assert insights["total_estimated_volume"] == pytest.approx(81000.5)


def test_highlight_helpers_render_key_details():
    insights = compute_trade_insights(sample_trades())

    text = build_highlights_text(insights)
    assert "Total activity: 3 trades (~$81.0K)" in text
    assert "Most active member: Bob Jones (2 trades, ~$78.0K)" in text

    html = build_highlights_html(insights)
    assert '<div class="highlights">' in html
    assert "Most popular ticker:</strong> MSFT" in html
