"""Email notification helpers for the daily summary."""

import os
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, Iterable, Optional, cast

from insights import build_highlights_html, compute_trade_insights


def send_summary(new_trades: Iterable[Dict[str, Any]], insights: Optional[Dict[str, Any]] = None) -> None:
    """Send an HTML email summarizing the provided trades."""

    new_trades = list(new_trades)
    if not new_trades:
        return

    # Sort by disclosureDate descending
    new_trades = sorted(new_trades, key=lambda t: t.get("disclosureDate", ""), reverse=True)

    if insights is None:
        insights = compute_trade_insights(new_trades)
    highlights_html = build_highlights_html(insights)

    # Check required environment variables
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    recipient = os.getenv("EMAIL_RECIPIENT")

    if not all([smtp_host, smtp_port, smtp_user, smtp_pass, recipient]):
        print("Missing required SMTP environment variables")
        return

    # Type assertions since we've verified they're not None
    smtp_host = cast(str, smtp_host)
    smtp_port = cast(str, smtp_port)
    smtp_user = cast(str, smtp_user)
    smtp_pass = cast(str, smtp_pass)

    html = f"""
<html>
<head>
  <style>
    body {{ font-family: Arial, sans-serif; }}
    h2 {{ color: #2c3e50; }}
    .highlights {{
      background-color: #f8f9fb;
      border: 1px solid #d9e2ec;
      border-radius: 6px;
      padding: 12px 16px;
      margin-bottom: 18px;
      line-height: 1.4;
    }}
    .highlights h3 {{
      margin: 0 0 8px 0;
      font-size: 16px;
      color: #1b4b72;
    }}
    .highlights ul {{
      margin: 0;
      padding-left: 20px;
    }}
    .highlights li {{
      margin-bottom: 6px;
    }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #dddddd; text-align: left; padding: 8px; }}
    th {{ background-color: #f2f2f2; }}
    tr:nth-child(even) {{ background-color: #f9f9f9; }}
    a {{ color: #2980b9; text-decoration: none; }}
  </style>
</head>
<body>
  <h2>Daily Congressional Trades Summary</h2>
  {highlights_html}
  <table>
    <tr>
      <th>Disclosure Date</th>
      <th>Transaction Date</th>
      <th>Member Name</th>
      <th>Office</th>
      <th>District</th>
      <th>Owner</th>
      <th>Asset Description</th>
      <th>Asset Type</th>
      <th>Type</th>
      <th>Symbol</th>
      <th>Amount</th>
      <th>Link</th>
    </tr>
"""

    for trade in new_trades:
        html += f"""
    <tr>
      <td>{trade.get('disclosureDate', '')}</td>
      <td>{trade.get('transactionDate', '')}</td>
      <td>{trade.get('firstName', '')} {trade.get('lastName', '')}</td>
      <td>{trade.get('office', '')}</td>
      <td>{trade.get('district', '')}</td>
      <td>{trade.get('owner', '')}</td>
      <td>{trade.get('assetDescription', '')}</td>
      <td>{trade.get('assetType', '')}</td>
      <td>{trade.get('type', '')}</td>
      <td>{trade.get('symbol', '')}</td>
      <td>{trade.get('amount', '')}</td>
      <td><a href='{trade.get('link', '')}'>View</a></td>
    </tr>
"""

    html += """
  </table>
  <p style='color: #888; font-size: 12px;'>This email was generated automatically by US Trade Insiders.</p>
</body>
</html>
"""

    html = html.strip()

    msg = EmailMessage()
    msg.set_content(
        "This email contains an HTML table of congressional trades. Please view in an HTML-compatible email client."
    )
    msg.add_alternative(html, subtype="html")
    msg["Subject"] = "Daily Congressional Trades Summary"
    msg["From"] = smtp_user
    msg["To"] = recipient

    with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
