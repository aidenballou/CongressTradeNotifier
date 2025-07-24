import os, smtplib
from email.message import EmailMessage
from typing import cast

def send_summary(new_trades):
    if not new_trades:
        return
    
    # Sort by disclosureDate descending
    new_trades = sorted(new_trades, key=lambda t: t.get('disclosureDate', ''), reverse=True)
    
    # Check required environment variables
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    smtp_recipient = os.getenv("SMTP_RECIPIENT")
    
    if not all([smtp_host, smtp_port, smtp_user, smtp_pass]):
        print("Missing required SMTP environment variables")
        return
    
    # Type assertions since we've verified they're not None
    smtp_host = cast(str, smtp_host)
    smtp_port = cast(str, smtp_port)
    smtp_user = cast(str, smtp_user)
    smtp_pass = cast(str, smtp_pass)
    
    # Build HTML table
    html = """
    <html>
    <head>
      <style>
        body { font-family: Arial, sans-serif; }
        h2 { color: #2c3e50; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #dddddd; text-align: left; padding: 8px; }
        th { background-color: #f2f2f2; }
        tr:nth-child(even) { background-color: #f9f9f9; }
        a { color: #2980b9; text-decoration: none; }
      </style>
    </head>
    <body>
      <h2>Daily Congressional Trades Summary</h2>
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
    for t in new_trades:
        html += f"""
        <tr>
          <td>{t.get('disclosureDate', '')}</td>
          <td>{t.get('transactionDate', '')}</td>
          <td>{t.get('firstName', '')} {t.get('lastName', '')}</td>
          <td>{t.get('office', '')}</td>
          <td>{t.get('district', '')}</td>
          <td>{t.get('owner', '')}</td>
          <td>{t.get('assetDescription', '')}</td>
          <td>{t.get('assetType', '')}</td>
          <td>{t.get('type', '')}</td>
          <td>{t.get('symbol', '')}</td>
          <td>{t.get('amount', '')}</td>
          <td><a href='{t.get('link', '')}'>View</a></td>
        </tr>
        """
    html += """
      </table>
      <p style='color: #888; font-size: 12px;'>This email was generated automatically by US Trade Insiders.</p>
    </body>
    </html>
    """
    
    msg = EmailMessage()
    msg.set_content("This email contains an HTML table of congressional trades. Please view in an HTML-compatible email client.")
    msg.add_alternative(html, subtype='html')
    msg["Subject"] = "Daily Congressional Trades Summary"
    msg["From"] = smtp_user
    msg["To"] = smtp_recipient

    with smtplib.SMTP(smtp_host, int(smtp_port)) as s:
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.send_message(msg)