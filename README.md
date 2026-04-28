# Insiders

Insiders tracks U.S. congressional trade disclosures, stores only net-new filings in SQLite, and turns those filings into:

- daily email summaries,
- scheduled X (Twitter) threads,
- and engagement-focused content variants (alerts, daily tape, 7-day themes, and member spotlights).

The pipeline runs in Eastern Time and is designed for unattended CI scheduling.

Follow: https://x.com/theinsidescope

## What This Project Does

- **Ingests disclosures** from Financial Modeling Prep (House + Senate endpoints).
- **Deduplicates and persists trades** in `trades.sqlite3`.
- **Builds insights** using rule-based analytics and optional OpenAI-generated copy.
- **Schedules posts by market windows** (morning, midday, power hour, evening).
- **Queues and dispatches threads safely** with anti-spam spacing and retry logic.
- **Emails same-day disclosure digests** for operational visibility.
- **Samples post engagement** to influence future scheduler choices.

## Runtime Flow

`src/main.py` is the primary entrypoint:

1. Fetches latest filings and writes only unseen trades.
2. Builds same-day highlights and sends an email (once per day).
3. Runs the scheduler to select and publish due content.
4. If scheduler is out-of-window or selects nothing, can post a fallback summary thread.

Each run logs a concise execution summary to stdout (delta stats, scheduler decision, and publish outcome).

## Project Layout

```
├── src/
│   ├── main.py                     # Daily orchestrator
│   ├── notifier.py                 # Ingestion + dedupe persistence
│   ├── fmp_client.py               # FMP API helpers
│   ├── db.py                       # SQLite schema + migrations
│   ├── emailer.py                  # HTML email summary delivery
│   ├── twitter_client.py           # X client, thread posting, chart generation
│   ├── posting_strategy.py         # Queueing, dispatch, anti-spam, retries
│   ├── insight_generator.py        # OpenAI-backed hook/interpretation/question generation
│   ├── tweet_composer.py           # Thread composition for each content type
│   ├── trade_analyzer.py           # Filing scoring and diagnostics
│   ├── historical_context.py       # Historical context builder
│   ├── insights.py                 # Email/highlight insight helpers
│   ├── analytics/                  # Rollups, bundling, engagement priors
│   └── scheduler/                  # Window evaluation, thresholding, dedupe guards
├── scripts/
│   └── preview_tweet.py            # Local tweet/chart preview utility
├── tests/                          # Unit tests for scheduler, posting, composition, insights
├── .github/workflows/
│   ├── daily-run-main.yml          # Main scheduled runner (every 15 min)
│   └── scheduler-watchdog.yml      # Cadence watchdog + issue alerting
├── requirements.txt
└── README.md
```

## Requirements

- Python 3.9+
- Dependencies from `requirements.txt`

Install:

```bash
pip install -r requirements.txt
```

## Configuration

Set environment variables (typically in `.env` locally and as repository secrets in CI).

### Required for ingestion

| Variable | Purpose |
| --- | --- |
| `FMP_API_KEY` | Financial Modeling Prep API key for disclosures and market data. |

### Required for email

| Variable | Purpose |
| --- | --- |
| `SMTP_HOST` | SMTP server hostname. |
| `SMTP_PORT` | SMTP server port. |
| `SMTP_USER` | SMTP username / sender. |
| `SMTP_PASS` | SMTP password or app password. |
| `EMAIL_RECIPIENT` | Recipient of daily HTML summaries. |

### Required for posting to X (Twitter)

| Variable | Purpose |
| --- | --- |
| `TWITTER_API_KEY` | Consumer API key. |
| `TWITTER_API_SECRET` | Consumer API secret. |
| `TWITTER_ACCESS_TOKEN` | Access token. |
| `TWITTER_ACCESS_SECRET` | Access token secret. |

### Optional feature flags / tuning

| Variable | Default | Purpose |
| --- | --- | --- |
| `TWITTER_ATTACH_CHART` | `true` | Attach generated price charts when possible. |
| `TWITTER_STYLE` | `engaging` | Tweet style (`engaging` or `classic`). |
| `OPENAI_API_KEY` | unset | Enables LLM insight generation for scheduler content. |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Model used by `insight_generator.py`. |
| `SCHEDULER_DRY_RUN` | `false` | Select content without posting. |
| `SCHEDULER_FALLBACK_ENABLED` | `true` | Allow fallback summary posting when scheduler does not post. |
| `SCHEDULER_FALLBACK_MODE` | `summary` | Fallback mode selector (currently summary mode). |

## Running Locally

Run one full cycle:

```bash
python src/main.py
```

Common local checks:

```bash
pytest
python scripts/preview_tweet.py --from-db
python scripts/preview_tweet.py --from-db --chart
```

To preview without DB data:

```bash
python scripts/preview_tweet.py --sample
```

## Standalone Copy-Trade Backtesting

The copy-trade backtester is intentionally separate from the tweet/content
strategy. It lives in `src/backtesting/` and is run through
`scripts/backtest_copy_trades.py`. It reads the SQLite disclosures, uses
`disclosure_date` as the signal date to avoid lookahead bias, downloads daily
price history with `yfinance`, and writes CSV artifacts under `outputs/backtests/`.

Examples:

```bash
python scripts/backtest_copy_trades.py \
  --strategy stock_long_only \
  --hold-days 20 \
  --entry-delay-days 1

python scripts/backtest_copy_trades.py \
  --strategy stock_long_short \
  --copy-sales \
  --leverage 3 \
  --hold-days 60

python scripts/backtest_copy_trades.py \
  --strategy option_copy \
  --option-dte 90 \
  --option-moneyness 1.10 \
  --hold-days 30
```

The options mode is synthetic: it uses Black-Scholes with trailing realized
volatility, not historical option chains. It is useful for comparing broad
profiles like 3-month ATM calls versus 1-year OTM calls, but it is not a
substitute for a historical options dataset with bid/ask and liquidity.

## Scheduler Behavior

The scheduler is window-aware (ET) and runs selection logic for:

- `MORNING` (08:35 target),
- `MIDDAY` (12:10 target),
- `POWER_HOUR` (15:50 target),
- `EVENING` (19:30 target),

with tolerance around each target time. It enforces:

- per-window de-duplication,
- daily post limits,
- anti-spam spacing between root posts,
- and queue-based retries for transient posting failures.

If no scheduler post occurs for a run, fallback summary posting can be enabled via environment flags.

## CI Automation

- `daily-run-main.yml` runs every 15 minutes, restores the previous DB artifact, executes `src/main.py`, then uploads the updated database artifact.
- `scheduler-watchdog.yml` checks run cadence hourly and opens/comments/closes a GitHub issue if the main workflow appears stale.

## Database Notes

State is stored in `trades.sqlite3`, including:

- `trades` (canonical filings + parsed amounts),
- `tweet_queue` (pending/posted/failed thread jobs),
- `posted_content_log` (dedupe guard),
- `posted_thread_ids` and `engagement_metrics` (post-performance sampling),
- `metadata` (operational markers like last root post timestamp).

Because this DB is stateful, repeated runs are idempotent for unchanged source data.

## Troubleshooting

- Missing credentials will skip the corresponding subsystem and log the reason.
- Chart generation gracefully falls back to alternate market data sources when possible.
- Posting failures are retried with backoff and eventually marked failed in queue state.
- Use `SCHEDULER_DRY_RUN=true` to validate selection behavior without publishing.
