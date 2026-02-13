import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

import posting_strategy

ET = ZoneInfo("America/New_York")


def _setup_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute(
        """
        CREATE TABLE tweet_queue (
            id INTEGER PRIMARY KEY,
            queue_key TEXT UNIQUE,
            status TEXT NOT NULL DEFAULT 'PENDING',
            scheduled_for TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            posted_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX idx_tweet_queue_status_schedule ON tweet_queue(status, scheduled_for)")
    conn.commit()

    monkeypatch.setattr(posting_strategy, "conn", conn)
    monkeypatch.setattr(posting_strategy, "cursor", cur)
    return conn, cur


def _unit(disclosure="2026-02-10", root="Thread root"):
    return {
        "disclosureDate": disclosure,
        "signalType": "CONVICTION",
        "signal": {"summarySentence": "Large buy cluster."},
        "filing": {"disclosureDate": disclosure, "trades": [{"symbol": "NVDA"}]},
        "thread": [
            {"text": root, "media_symbol": None, "media_trade_date": None},
            {"text": "stats", "media_symbol": "NVDA", "media_trade_date": None},
            {"text": "history", "media_symbol": None, "media_trade_date": None},
        ],
    }


def test_stable_queue_key_deterministic():
    """Same unit payload must yield the same queue key across calls (sha256-based)."""
    unit = _unit(disclosure="2026-02-12", root="Same root text.")
    key1 = posting_strategy._stable_queue_key(unit)
    key2 = posting_strategy._stable_queue_key(unit)
    assert key1 == key2
    assert "2026-02-12|CONVICTION|" in key1
    assert len(key1) > 20


def test_stable_queue_key_different_content_different_key():
    """Different root text must yield different queue keys."""
    u1 = _unit(disclosure="2026-02-12", root="Root A")
    u2 = _unit(disclosure="2026-02-12", root="Root B")
    assert posting_strategy._stable_queue_key(u1) != posting_strategy._stable_queue_key(u2)


def test_enqueue_signal_threads_dedupe_repeated_call(monkeypatch):
    """Enqueueing the same unit twice must result in a single queue row (queue_key UNIQUE)."""
    _setup_db(monkeypatch)
    now_et = datetime(2026, 2, 11, 10, 0, tzinfo=ET)
    unit = _unit(disclosure="2026-02-11", root="Single thread root")
    count1 = posting_strategy.enqueue_signal_threads([unit], now_et)
    count2 = posting_strategy.enqueue_signal_threads([unit], now_et)
    assert count1 == 1
    assert count2 == 0
    posting_strategy.cursor.execute("SELECT COUNT(*) FROM tweet_queue")
    assert posting_strategy.cursor.fetchone()[0] == 1


def test_enqueue_signal_threads_merges_same_day(monkeypatch):
    _setup_db(monkeypatch)

    now_et = datetime(2026, 2, 11, 8, 0, tzinfo=ET)
    count = posting_strategy.enqueue_signal_threads(
        [_unit(root="A"), _unit(root="B")],
        now_et,
    )

    assert count == 1

    posting_strategy.cursor.execute("SELECT scheduled_for, payload_json FROM tweet_queue")
    row = posting_strategy.cursor.fetchone()
    assert row is not None

    scheduled_for = datetime.fromisoformat(row[0]).astimezone(ET)
    assert scheduled_for.hour == 9 and scheduled_for.minute == 35

    payload = json.loads(row[1])
    assert len(payload["thread"]) == 3


def test_dispatch_due_threads_anti_spam_and_post(monkeypatch):
    _setup_db(monkeypatch)

    class FakeTwitterClient:
        def __init__(self):
            self.calls = []

        def post_thread(self, thread, min_delay_seconds=20, max_delay_seconds=60):
            self.calls.append((thread, min_delay_seconds, max_delay_seconds))
            return ["1", "2", "3"]

    fake_client = FakeTwitterClient()
    monkeypatch.setattr(posting_strategy, "TwitterClient", lambda: fake_client)

    now_et = datetime(2026, 2, 11, 10, 0, tzinfo=ET)
    posting_strategy.enqueue_signal_threads([_unit()], now_et)
    posting_strategy._set_metadata("last_root_posted_at", posting_strategy._to_iso(now_et))

    first = posting_strategy.dispatch_due_threads(now_et)
    assert first["deferred"] == 1
    assert first["posted"] == 0

    second_time = now_et + timedelta(minutes=3)
    second = posting_strategy.dispatch_due_threads(second_time)
    assert second["posted"] == 1
    assert len(fake_client.calls) == 1

    posting_strategy.cursor.execute("SELECT status FROM tweet_queue")
    status = posting_strategy.cursor.fetchone()[0]
    assert status == "POSTED"


def test_out_of_window_scheduler_run_drains_deferred_queue_item(monkeypatch):
    """Regression: a later cron run outside any window still drains deferred queue items."""
    _setup_db(monkeypatch)

    class FakeTwitterClient:
        def __init__(self):
            self.calls = []

        def post_thread(self, thread, min_delay_seconds=20, max_delay_seconds=60):
            self.calls.append((thread, min_delay_seconds, max_delay_seconds))
            return ["1", "2", "3"]

    fake_client = FakeTwitterClient()
    monkeypatch.setattr(posting_strategy, "TwitterClient", lambda: fake_client)

    now_et = datetime(2026, 2, 11, 10, 0, tzinfo=ET)
    posting_strategy.enqueue_signal_threads([_unit()], now_et)
    posting_strategy._set_metadata("last_root_posted_at", posting_strategy._to_iso(now_et))

    first = posting_strategy.dispatch_due_threads(now_et)
    assert first["deferred"] == 1
    assert first["posted"] == 0
    assert len(fake_client.calls) == 0

    import scheduler.select_content as select_content
    monkeypatch.setattr(select_content, "get_current_window", lambda _now: None)
    later_et = now_et + timedelta(minutes=3)
    result = select_content.run_scheduler(later_et)
    assert result is None
    assert len(fake_client.calls) == 1
    posting_strategy.cursor.execute("SELECT status FROM tweet_queue")
    assert posting_strategy.cursor.fetchone()[0] == "POSTED"
