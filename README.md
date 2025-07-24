# CongressTradeNotifier

A Python tool that fetches and stores the latest US congressional stock trades, and emails a daily summary to a specified recipient.

## Features

- Fetches the latest Senate and House trades from the Financial Modeling Prep API
- Stores unique trades in a local SQLite database
- Sends a daily HTML email summary of new trades

## Requirements

- Python 3.9+
- `requests`, `python-dotenv`

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set the following environment variables (e.g., in a `.env` file in the project root):
   - `FMP_API_KEY` (Financial Modeling Prep API key)
   - `SMTP_HOST` (SMTP server hostname)
   - `SMTP_PORT` (SMTP server port)
   - `SMTP_USER` (SMTP username)
   - `SMTP_PASS` (SMTP password)
   - `EMAIL_RECIPIENT` (email address to receive summaries)

## Usage

Run the notifier manually or schedule it (e.g., with cron) to send daily summaries:

```bash
python src/main.py
```

This will fetch the latest congressional trades, store new ones, and email a summary of trades disclosed today to the configured recipient.

---

_For personal use. No deployment or hosting required._
