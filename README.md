# CongressTradeNotifier

CongressTradeNotifier watches the official U.S. House and Senate trade disclosures, persists any new activity, and turns it into
shareable updates. The project pulls data from the Financial Modeling Prep (FMP) API, deduplicates the filings in a local
SQLite database, emails a daily HTML digest, and crafts polished tweets (optionally with charts and performance stats) for
social media distribution.

## Highlights

- **Automated trade ingestion** – Fetches the latest disclosures for both chambers via the FMP API and records only new
  transactions in `trades.sqlite3`. 【F:src/fmp_client.py†L10-L59】【F:src/notifier.py†L1-L45】【F:src/db.py†L1-L24】
- **Daily operator workflow** – `src/main.py` coordinates the full pipeline: fetch trades, persist, email a same-day summary,
  and publish tweets. 【F:src/main.py†L1-L39】
- **Rich Twitter automation** – Generates engaging single- or multi-trade posts, applies heuristics for tone and hashtags, can
  attach price charts, and retries transient API failures. 【F:src/twitter_client.py†L38-L213】【F:src/twitter_client.py†L421-L658】【F:src/twitter_client.py†L1137-L1177】
- **Email reporting** – Sends an HTML table that highlights each disclosure for the day, ready to drop into an inbox. 【F:src/emailer.py†L1-L81】
- **Developer tooling** – Includes a tweet preview script and pytest suite for validating copy, formatting, and Twitter client
  behavior. 【F:scripts/preview_tweet.py†L1-L138】【F:tests/test_twitter_client.py†L1-L150】

## Project structure

```
├── src/
│   ├── main.py              # Entry point that runs the daily workflow
│   ├── fmp_client.py        # Financial Modeling Prep API helpers
│   ├── notifier.py          # Persistence + dedupe logic
│   ├── emailer.py           # HTML summary email generator
│   ├── twitter_client.py    # Tweet formatting, media creation, and posting
│   └── db.py                # SQLite schema + shared connection
├── scripts/
│   └── preview_tweet.py     # CLI to preview tweets or charts without new trades
├── tests/                   # Pytest suite for Twitter automation
├── requirements.txt
└── README.md
```

## Requirements

- Python 3.9+
- Dependencies listed in `requirements.txt` (`requests`, `python-dotenv`, `tweepy`, `matplotlib`, `pytest`, `pytest-mock`,
  `yfinance`). 【F:requirements.txt†L1-L7】

Install packages with:

```bash
pip install -r requirements.txt
```

## Configuration

Environment variables (typically placed in a `.env` file) control API access, email delivery, and Twitter automation. The
application automatically loads them via `python-dotenv`.

### Core data sources

| Variable | Purpose |
| --- | --- |
| `FMP_API_KEY` | Financial Modeling Prep API key used for trade ingestion, performance stats, and price charts. |

### Email delivery

| Variable | Purpose |
| --- | --- |
| `SMTP_HOST` | SMTP server hostname. |
| `SMTP_PORT` | SMTP server port. |
| `SMTP_USER` | SMTP username / from address. |
| `SMTP_PASS` | SMTP password or app-specific password. |
| `EMAIL_RECIPIENT` | Where the daily HTML summary should be delivered. |

### Twitter automation

| Variable | Purpose |
| --- | --- |
| `TWITTER_API_KEY` | X (Twitter) API consumer key. |
| `TWITTER_API_SECRET` | X (Twitter) API consumer secret. |
| `TWITTER_ACCESS_TOKEN` | X (Twitter) access token for the posting account. |
| `TWITTER_ACCESS_SECRET` | X (Twitter) access token secret. |
| `TWITTER_ATTACH_CHART` | Optional (`true`/`false`). Toggle automatic price chart attachments (defaults to `true`). |
| `TWITTER_STYLE` | Optional (`engaging` or `classic`). Selects the copywriting style for posts (defaults to `engaging`). |

> Tip: When running in CI (GitHub Actions, cron, etc.) export these values as secrets so the workflow can authenticate without
> exposing credentials.

## Running the notifier

Execute the full workflow once per day (manually or via a scheduler):

```bash
python src/main.py
```

This command will:

1. Download the most recent Senate and House transactions from FMP.
2. Deduplicate the data and append any new filings to `trades.sqlite3`.
3. Email an HTML table summarizing disclosures filed **today** (Eastern Time).
4. Post tweets for each member's activity, bundling multiple trades into a single thread-friendly update. Price charts are
   attached when enabled and market data is available.

All output is logged to stdout, making it easy to monitor from cron or GitHub Actions logs. The SQLite database acts as state,
so repeated executions only act on new filings.

## Previewing tweets & charts locally

Use the helper script to inspect copy before posting or to experiment with chart generation:

```bash
python scripts/preview_tweet.py --from-db      # Preview most recent DB trade
python scripts/preview_tweet.py --sample       # Preview using a built-in sample trade
python scripts/preview_tweet.py --from-db --chart  # Also render and save a PNG price chart
python scripts/preview_tweet.py --from-db --post   # Post the preview to Twitter (counts against API quota)
```

The preview respects your environment configuration (style, chart toggles, API credentials). Charts require `matplotlib` and
will fall back to yfinance if FMP historical endpoints fail. 【F:scripts/preview_tweet.py†L79-L120】【F:src/twitter_client.py†L513-L658】

## Data storage

- Trade history is stored in `trades.sqlite3` next to the source code. The schema enforces uniqueness on the combination of
  ticker, disclosure date, transaction date, and amount to prevent duplicates. 【F:src/db.py†L1-L24】
- Metadata such as last run timestamps can be added via the `metadata` table if needed for future automation. 【F:src/db.py†L16-L23】

Back up the database if you plan to redeploy the notifier or analyze historical trades elsewhere.

## Testing

Run the automated tests to validate the Twitter client logic:

```bash
pytest
```

The suite mocks API clients to verify initialization, tweet formatting, hashtag selection, and error handling behavior without
making network calls. 【F:tests/test_twitter_client.py†L1-L150】

## Scheduling ideas

- **Cron job** – Run `python src/main.py` daily after markets close to capture fresh filings.
- **GitHub Actions** – Create a workflow that checks out the repo, installs dependencies, loads secrets, and invokes the script.
- **Containerized task** – Package the project in Docker and deploy it to your preferred scheduler (ECS, Cloud Run, etc.).

## Troubleshooting

- Missing API keys or SMTP credentials cause the corresponding subsystem to skip its work while logging a helpful warning.
- When the Twitter client encounters transient errors (rate limits, network hiccups) it retries with exponential backoff before
  surfacing the failure. 【F:src/twitter_client.py†L921-L1012】
- Chart generation requires both `matplotlib` and recent price data. If unavailable the tweet still posts without media. 【F:src/twitter_client.py†L505-L586】

---

Built for following U.S. Congressional trades and sharing them quickly with your audience.
