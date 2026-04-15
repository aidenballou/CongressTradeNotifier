"""Main scheduler orchestrator for content selection and posting."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from analytics.bundle_builder import build_bundles_from_db, bundle_id, filter_unposted, fetch_recent_trades
    from analytics.rollups import build_daily_tape, build_seven_day_theme, build_member_spotlight
    from scheduler.evaluate_window import get_current_window, is_trading_day
    from scheduler.dynamic_threshold import compute_threshold
    from scheduler.dedupe_guard import (
        has_been_posted,
        count_posts_today,
        has_daily_tape_today,
        has_seven_day_theme_today,
        has_window_posted_today,
        has_member_spotlight_recent,
    )
    from trade_analyzer import analyze_filing
    from historical_context import build_historical_context
    from insight_generator import generate_insight
    from tweet_composer import compose_thread, compose_daily_tape_thread, compose_seven_day_theme_thread, compose_member_spotlight_thread
    from posting_strategy import enqueue_signal_threads, dispatch_due_threads
except ImportError:  # pragma: no cover
    from src.analytics.bundle_builder import build_bundles_from_db, bundle_id, filter_unposted, fetch_recent_trades
    from src.analytics.rollups import build_daily_tape, build_seven_day_theme, build_member_spotlight
    from src.scheduler.evaluate_window import get_current_window, is_trading_day
    from src.scheduler.dynamic_threshold import compute_threshold
    from src.scheduler.dedupe_guard import (
        has_been_posted,
        count_posts_today,
        has_daily_tape_today,
        has_seven_day_theme_today,
        has_window_posted_today,
        has_member_spotlight_recent,
    )
    from src.trade_analyzer import analyze_filing
    from src.historical_context import build_historical_context
    from src.insight_generator import generate_insight
    from src.tweet_composer import compose_thread, compose_daily_tape_thread, compose_seven_day_theme_thread, compose_member_spotlight_thread
    from src.posting_strategy import enqueue_signal_threads, dispatch_due_threads


@dataclass
class ContentDecision:
    """Represents a decision to post specific content."""
    content_type: str  # ALERT, DAILY_TAPE, SEVEN_DAY_THEME, MEMBER_SPOTLIGHT
    bundle_id: Optional[str]
    score: Optional[int]
    reason: str


@dataclass
class SchedulerOutcome:
    """Structured result returned by run_scheduler for callers and logs."""

    posted: bool
    reason: str
    window: Optional[str] = None
    content_type: Optional[str] = None
    posted_count: int = 0
    bundle_id: Optional[str] = None
    score: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _score_and_rank_bundles(bundles: List[Dict[str, Any]], recent_trades: List[Dict[str, Any]], now_et: datetime) -> List[tuple[Dict[str, Any], Dict[str, Any], int]]:
    """Score bundles and return sorted list of (bundle, signal, score) tuples."""
    scored = []
    for bundle in bundles:
        signal = analyze_filing(bundle, recent_trades, now_et)
        score = signal.get("diagnostics", {}).get("score", 0)
        scored.append((bundle, signal, score))
    # Sort by score descending
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored


def _fallback_order_for_window(window: str) -> List[str]:
    """Return content types to try as fallbacks in this window, ordered by engagement prior (higher first)."""
    try:
        from analytics.engagement import get_engagement_priors_for_scheduler
    except ImportError:
        from src.analytics.engagement import get_engagement_priors_for_scheduler
    candidates = ["DAILY_TAPE", "SEVEN_DAY_THEME"]
    priors = [(ct, get_engagement_priors_for_scheduler(ct, window, min_samples=2)) for ct in candidates]
    priors.sort(key=lambda x: -x[1])
    return [ct for ct, _ in priors]


def _select_for_morning(scored_bundles: List[tuple], threshold: Optional[int], today: str, now_et: datetime) -> Optional[ContentDecision]:
    """MORNING window: Alert > Daily Tape > 7-day Theme. Never both alert and tape."""
    
    # Check if window already posted
    if has_window_posted_today(today, "MORNING"):
        return None

    # Try highest scoring bundle if meets threshold
    if scored_bundles and threshold is not None:
        bundle, signal, score = scored_bundles[0]
        bid = bundle_id(bundle)
        if score >= threshold and not has_been_posted("ALERT", bid, today, "MORNING"):
            return ContentDecision("ALERT", bid, score, "highest_scoring_bundle")

    # Fallbacks ordered by engagement prior for this window
    order = _fallback_order_for_window("MORNING")
    for content_type in order:
        if content_type == "DAILY_TAPE" and not has_daily_tape_today(today):
            tape = build_daily_tape(now_et)
            if tape.get("total_filings", 0) > 0:
                return ContentDecision("DAILY_TAPE", None, None, "daily_tape_fallback")
        if content_type == "SEVEN_DAY_THEME" and not has_seven_day_theme_today(today):
            theme = build_seven_day_theme(now_et)
            if theme.get("top_5_tickers_by_value"):
                return ContentDecision("SEVEN_DAY_THEME", None, None, "seven_day_theme_fallback")

    return None


def _select_for_midday(scored_bundles: List[tuple], threshold: Optional[int], today: str, now_et: datetime) -> Optional[ContentDecision]:
    """MIDDAY window: highest remaining unposted bundle only if score >= threshold."""
    
    # Check if window already posted
    if has_window_posted_today(today, "MIDDAY"):
        return None

    if scored_bundles and threshold is not None:
        bundle, signal, score = scored_bundles[0]  # Highest remaining after unposted filter
        bid = bundle_id(bundle)
        if score >= threshold and not has_been_posted("ALERT", bid, today, "MIDDAY"):
            return ContentDecision("ALERT", bid, score, "highest_remaining_bundle")

    return None


def _select_for_power_hour(scored_bundles: List[tuple], threshold: Optional[int], today: str, now_et: datetime) -> Optional[ContentDecision]:
    """POWER_HOUR window: Mandatory Daily Tape if no posts today yet. Otherwise nothing."""
    
    # Check if window already posted
    if has_window_posted_today(today, "POWER_HOUR"):
        return None

    posts_today = count_posts_today(today)
    if posts_today == 0:
        # Must post Daily Tape only when filings exist today.
        tape = build_daily_tape(now_et)
        if tape.get("total_filings", 0) > 0 and not has_daily_tape_today(today):
            return ContentDecision("DAILY_TAPE", None, None, "mandatory_first_post")

    return None


def _select_for_evening(scored_bundles: List[tuple], threshold: Optional[int], today: str, now_et: datetime) -> Optional[ContentDecision]:
    """EVENING window: If filings today == 0 → 7-day Theme, else → Member Spotlight."""
    
    # Check if window already posted
    if has_window_posted_today(today, "EVENING"):
        return None

    # Count filings today
    tape = build_daily_tape(now_et)
    filings_today = tape.get("total_filings", 0)

    if filings_today == 0:
        # 7-day Theme
        theme = build_seven_day_theme(now_et)
        if theme.get("top_5_tickers_by_value") and not has_seven_day_theme_today(today):
            return ContentDecision("SEVEN_DAY_THEME", None, None, "no_filings_today")
    else:
        # Member Spotlight (skip if same member was spotlighted within last 7 days)
        spotlight = build_member_spotlight(now_et)
        if spotlight:
            member_name = spotlight.get("member_name") or spotlight.get("member", "")
            if not has_member_spotlight_recent(member_name, days=7):
                return ContentDecision("MEMBER_SPOTLIGHT", member_name or None, None, "member_spotlight")

    return None


def _compose_for_decision(
    decision: ContentDecision,
    now_et: datetime,
    scored_bundles: Optional[List[tuple]] = None,
    recent_trades: Optional[List[Dict[str, Any]]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Compose thread based on decision type, reusing pre-computed data when available."""
    
    if decision.content_type == "ALERT":
        bundle = None
        signal = None
        if scored_bundles:
            for b, s, _score in scored_bundles:
                if bundle_id(b) == decision.bundle_id:
                    bundle = b
                    signal = s
                    break
        if bundle is None:
            bundles = build_bundles_from_db(now_et, hours=24)
            if recent_trades is None:
                recent_trades = fetch_recent_trades(days=400, now_et=now_et)
            for b in bundles:
                if bundle_id(b) == decision.bundle_id:
                    bundle = b
                    signal = analyze_filing(b, recent_trades, now_et)
                    break
        if bundle is None or signal is None:
            return None
        context = build_historical_context(bundle, signal, window_days=30)
        insight = generate_insight(bundle, signal, context)
        stats = signal.get("diagnostics", {})
        return compose_thread(bundle, signal, insight, context, stats)
    
    elif decision.content_type == "DAILY_TAPE":
        tape = build_daily_tape(now_et)
        if tape.get("total_filings", 0) == 0:
            return None
        return compose_daily_tape_thread(tape)
    
    elif decision.content_type == "SEVEN_DAY_THEME":
        theme = build_seven_day_theme(now_et)
        if not theme.get("top_5_tickers_by_value"):
            return None
        return compose_seven_day_theme_thread(theme)
    
    elif decision.content_type == "MEMBER_SPOTLIGHT":
        spotlight = build_member_spotlight(now_et)
        if spotlight:
            return compose_member_spotlight_thread(spotlight)
        return None
    
    return None


def _log_decision(window: str, decision: Optional[ContentDecision], candidates: int):
    """Log structured scheduler output."""
    if decision is None:
        print(f"[Scheduler] window={window} action=skip reason=no_content_selected")
        return

    fields = [
        f"window={window}",
        "action=selected",
        f"candidates={candidates}",
        f"content_type={decision.content_type}",
        f"reason={decision.reason}",
    ]
    if decision.bundle_id:
        fields.append(f"bundle_id={decision.bundle_id}")
    if decision.score is not None:
        fields.append(f"score={decision.score}")

    print(f"[Scheduler] {' '.join(fields)}")


def run_scheduler(now_et: datetime) -> Dict[str, Any]:
    """Main scheduler entry point. Called every cron run."""
    # Drain due queue items on every run (including outside windows / non-trading days).
    drain_summary = dispatch_due_threads(now_et)
    drain_posted = int(drain_summary.get("posted", 0))

    window = get_current_window(now_et)
    if window is None:
        print("[Scheduler] window=None action=skip reason=not_in_window")
        return SchedulerOutcome(
            posted=False,
            reason="not_in_window",
            window=None,
            content_type=None,
            posted_count=drain_posted,
        ).to_dict()
    
    if not is_trading_day(now_et):
        print("[Scheduler] window=None action=skip reason=not_trading_day")
        return SchedulerOutcome(
            posted=False,
            reason="not_trading_day",
            window=None,
            content_type=None,
            posted_count=drain_posted,
        ).to_dict()

    today = now_et.strftime("%Y-%m-%d")
    posts_today = count_posts_today(today)
    
    if posts_today >= 3:
        print(f"[Scheduler] window={window} action=skip reason=daily_max_reached")
        return SchedulerOutcome(
            posted=False,
            reason="daily_max_reached",
            window=window,
            content_type=None,
            posted_count=drain_posted,
        ).to_dict()

    # Gather bundles
    bundles = build_bundles_from_db(now_et, hours=24)
    unposted_bundles = filter_unposted(bundles, today)
    recent_trades = fetch_recent_trades(days=400, now_et=now_et)
    
    # Score and rank (use unposted for scoring, but total bundles for threshold)
    scored_bundles = _score_and_rank_bundles(unposted_bundles, recent_trades, now_et)
    threshold = compute_threshold(len(bundles), window)

    # Select content based on window
    decision = None
    if window == "MORNING":
        decision = _select_for_morning(scored_bundles, threshold, today, now_et)
    elif window == "MIDDAY":
        decision = _select_for_midday(scored_bundles, threshold, today, now_et)
    elif window == "POWER_HOUR":
        decision = _select_for_power_hour(scored_bundles, threshold, today, now_et)
    elif window == "EVENING":
        decision = _select_for_evening(scored_bundles, threshold, today, now_et)

    if decision is None:
        _log_decision(window, None, len(unposted_bundles))
        return SchedulerOutcome(
            posted=False,
            reason="no_content_selected",
            window=window,
            content_type=None,
            posted_count=drain_posted,
        ).to_dict()

    # Check deduplication
    if has_been_posted(decision.content_type, decision.bundle_id, today, window):
        print(f"[Scheduler] window={window} action=skip reason=already_posted")
        return SchedulerOutcome(
            posted=False,
            reason="already_posted",
            window=window,
            content_type=decision.content_type,
            posted_count=drain_posted,
            bundle_id=decision.bundle_id,
            score=decision.score,
        ).to_dict()

    # Compose thread (pass pre-computed data to avoid redundant DB queries and API calls)
    thread = _compose_for_decision(decision, now_et, scored_bundles=scored_bundles, recent_trades=recent_trades)
    if not thread:
        print(f"[Scheduler] window={window} action=skip reason=composition_failed")
        return SchedulerOutcome(
            posted=False,
            reason="composition_failed",
            window=window,
            content_type=decision.content_type,
            posted_count=drain_posted,
            bundle_id=decision.bundle_id,
            score=decision.score,
        ).to_dict()

    if os.getenv("SCHEDULER_DRY_RUN", "").strip().lower() in ("1", "true", "yes"):
        print(f"[Scheduler] dry_run=1 would_post content_type={decision.content_type} window={window} threshold={threshold} score={decision.score}")
        try:
            try:
                from analytics.engagement import engagement_health_report
            except ImportError:
                from src.analytics.engagement import engagement_health_report
            print(engagement_health_report())
        except Exception as eng_err:
            print(f"[Scheduler] engagement_health_report failed (non-fatal): {eng_err}")
        return SchedulerOutcome(
            posted=False,
            reason="dry_run",
            window=window,
            content_type=decision.content_type,
            posted_count=drain_posted,
            bundle_id=decision.bundle_id,
            score=decision.score,
        ).to_dict()

    # Enqueue this decision and dispatch so it can post in this run.
    bundles_for_payload = build_bundles_from_db(now_et, hours=24)
    alert_trades = []
    if decision.content_type == "ALERT" and decision.bundle_id:
        for b in bundles_for_payload:
            if bundle_id(b) == decision.bundle_id:
                alert_trades = b.get("trades", [])
                break
    queue_unit = {
        "disclosureDate": today,
        "signalType": decision.content_type,
        "thread": thread,
        "filing": {"disclosureDate": today, "trades": alert_trades},
        "signal": {"summarySentence": decision.reason},
        "context": {"window": window, "bundle_id": decision.bundle_id},
    }
    enqueue_signal_threads([queue_unit], now_et, force_due_now=True)
    dispatch_summary = dispatch_due_threads(now_et, skip_anti_spam=drain_posted == 0)
    posted_now = int(dispatch_summary.get("posted", 0))
    total_posted = drain_posted + posted_now
    if posted_now < 1:
        print(f"[Scheduler] window={window} action=skip reason=post_failed_or_deferred")
        return SchedulerOutcome(
            posted=False,
            reason="post_failed_or_deferred",
            window=window,
            content_type=decision.content_type,
            posted_count=total_posted,
            bundle_id=decision.bundle_id,
            score=decision.score,
        ).to_dict()

    _log_decision(window, decision, len(unposted_bundles))
    try:
        try:
            from analytics.engagement import engagement_health_report
        except ImportError:
            from src.analytics.engagement import engagement_health_report
        print(engagement_health_report())
    except Exception as eng_err:
        print(f"[Scheduler] engagement_health_report failed (non-fatal): {eng_err}")

    return SchedulerOutcome(
        posted=True,
        reason="posted",
        window=window,
        content_type=decision.content_type,
        posted_count=total_posted,
        bundle_id=decision.bundle_id,
        score=decision.score,
    ).to_dict()
