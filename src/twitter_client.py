import os
import json
import re
import time
import logging
import tempfile
from typing import Dict, Optional, List, Tuple
import requests
import tweepy
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Lazy import for plotting to avoid heavy import when disabled
try:
    import matplotlib  # type: ignore
    matplotlib.use("Agg")  # headless-safe backend for CI and servers
    import matplotlib.pyplot as plt  # type: ignore
    import matplotlib.dates as mdates  # type: ignore
    from matplotlib.ticker import MaxNLocator  # type: ignore
    from matplotlib import rcParams  # type: ignore
    import matplotlib.patheffects as pe  # type: ignore

    # Professional font + palette defaults
    rcParams["font.family"] = "sans-serif"
    rcParams["font.sans-serif"] = [
        "Inter",
        "SF Pro Display",
        "Helvetica Neue",
        "Arial",
        "DejaVu Sans",
    ]
    rcParams["axes.titlesize"] = 13
    rcParams["axes.titleweight"] = "semibold"
    rcParams["axes.labelcolor"] = "#222222"
    rcParams["text.color"] = "#222222"
    rcParams["axes.edgecolor"] = "#D1D5DB"
    rcParams["figure.facecolor"] = "#FFFFFF"
    rcParams["axes.facecolor"] = "#FFFFFF"
except Exception:  # pragma: no cover - plot is optional
    plt = None

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TwitterClient:
    """Twitter API client with rate limiting and error handling."""
    
    def __init__(self):
        """Initialize Twitter API client with environment variables."""
        self.api_key = os.getenv("TWITTER_API_KEY")
        self.api_secret = os.getenv("TWITTER_API_SECRET")
        self.access_token = os.getenv("TWITTER_ACCESS_TOKEN")
        self.access_secret = os.getenv("TWITTER_ACCESS_SECRET")
        
        if not all([self.api_key, self.api_secret, self.access_token, self.access_secret]):
            raise ValueError("Missing required Twitter API credentials in environment variables")
        
        # Initialize Tweepy v2 client (for creating tweets)
        self.client = tweepy.Client(
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_secret,
            wait_on_rate_limit=True
        )

        # Initialize Tweepy v1.1 API (for media uploads)
        auth = tweepy.OAuth1UserHandler(
            self.api_key,
            self.api_secret,
            self.access_token,
            self.access_secret,
        )
        self.api_v1 = tweepy.API(auth, wait_on_rate_limit=True)

        # Feature flags
        self.attach_chart = os.getenv("TWITTER_ATTACH_CHART", "true").lower() in {"1", "true", "yes"}
        self.use_engaging_style = os.getenv("TWITTER_STYLE", "engaging").lower() == "engaging"
    
    def _format_trade_tweet(self, trade: Dict) -> str:
        """
        Format a trade dictionary into an engaging tweet.

        Args:
            trade: Dictionary containing trade information

        Returns:
            Formatted tweet string ≤ 280 characters
        """
        # Extract trade details
        member_name = f"{trade.get('firstName', '')} {trade.get('lastName', '')}".strip()
        raw_action = (trade.get('type') or '').strip()
        action = "BUY" if raw_action.lower() in {"buy", "purchase"} else ("SELL" if raw_action.lower() in {"sell", "sale"} else raw_action.upper() or "TRADE")
        ticker = (trade.get('symbol') or '').upper().strip()
        amount_str = trade.get('amount', '')
        asset_desc = trade.get('assetDescription', '')

        # Determine member title (Sen./Rep.)
        title = "Sen." if "senate" in (trade.get('source') or '').lower() else "Rep."

        # Format amount for display
        amount_display = self._format_amount(amount_str)
        ticker_display = f"${ticker}" if ticker else "an undisclosed ticker"

        # Generate insight based on trade details
        insight = self._generate_insight(trade)

        # Select appropriate emoji
        emoji = "🚀" if action == "BUY" else "⚠️" if action == "SELL" else "📊"

        amount_phrase = "with an undisclosed amount" if amount_display == "an undisclosed amount" else f"worth {amount_display}"

        # Build tweet with character limit consideration
        base_tweet = f"{emoji} {title} {member_name} just disclosed a {action} in {ticker_display} {amount_phrase} today. {insight} #CongressTrades"

        # Add sector hashtag if we can fit it
        sector_tag = self._get_sector_hashtag(asset_desc)
        if sector_tag and len(base_tweet) + len(sector_tag) + 1 <= 280:
            base_tweet += f" {sector_tag}"

        # Ensure tweet is within character limit
        if len(base_tweet) > 280:
            # Truncate insight to fit
            max_insight_len = 280 - len(base_tweet) + len(insight) - 3  # -3 for "..."
            if max_insight_len > 10:
                insight = insight[:max_insight_len] + "..."
                base_tweet = f"{emoji} {title} {member_name} just disclosed a {action} in {ticker_display} {amount_phrase} today. {insight} #CongressTrades"
            else:
                # Remove insight if still too long
                base_tweet = f"{emoji} {title} {member_name} just disclosed a {action} in {ticker_display} {amount_phrase} today. #CongressTrades"

        return base_tweet

    def _format_trade_tweet_engaging(self, trade: Dict) -> str:
        """Compose concise, varied, human-sounding posts while respecting 280 chars and style rules."""
        # Core fields
        first = (trade.get('firstName') or '').strip()
        last = (trade.get('lastName') or '').strip()
        member_name = f"{first} {last}".strip()
        raw_action = (trade.get('type') or '').strip()
        action = "BUY" if raw_action.lower() in {"buy", "purchase"} else ("SELL" if raw_action.lower() in {"sell", "sale"} else raw_action.upper() or "TRADE")
        ticker = (trade.get('symbol') or '').upper().strip()
        amount_str = trade.get('amount', '')
        trans_date = (trade.get('transactionDate') or '').strip()
        disclosure_date = (trade.get('disclosureDate') or '').strip()
        asset_desc = trade.get('assetDescription', '')
        district = (trade.get('district') or '').strip()
        title = "Sen." if "senate" in (trade.get('source') or '').lower() else "Rep."

        # Formatting helpers
        def fmt_district(code: str) -> str:
            if not code:
                return ""
            # e.g., FL25 -> FL-25, GA10 -> GA-10
            letters = ''.join([c for c in code if c.isalpha()])
            digits = ''.join([c for c in code if c.isdigit()])
            return f"{letters}-{digits}" if letters and digits else code

        def collapse_spaces(s: str) -> str:
            return ' '.join(s.replace('\n', '\n ').split())

        # Compute derived
        amount_display = self._format_amount(amount_str)
        sector_tag = self._get_sector_hashtag(asset_desc)
        emoji = "🟢" if action == "BUY" else ("🔴" if action == "SELL" else ("🟣" if 'option' in asset_desc.lower() else "🔵"))
        who = f"{title} {member_name}"
        geo = f" ({fmt_district(district)})" if district else ""
        ticker_or_undisclosed = f"${ticker}" if ticker else "an undisclosed ticker"

        # Insights data (if present)
        perf = self._build_performance_snippet(ticker, action, trans_date) if ticker else ""
        # Extract numeric pct only for scoring convenience
        perf_has_pct = bool(perf)

        # Lag days if both dates present
        lag_days = None
        try:
            if trans_date and disclosure_date:
                dt_t = datetime.strptime(trans_date, "%Y-%m-%d")
                dt_d = datetime.strptime(disclosure_date, "%Y-%m-%d")
                lag_days = max(0, (dt_d - dt_t).days)
        except Exception:
            lag_days = None

        repeat_ticker_12m = trade.get('member_prior_trades_same_ticker_365d')
        member_trade_count_30d = trade.get('member_trade_count_30d')
        spx_change = trade.get('sp500_change_same_window')

        # Template builders (single responsibility, max 2 lines)
        def amount_phrase() -> str:
            return "with an undisclosed amount" if amount_display == "an undisclosed amount" else f"worth {amount_display}"

        def hook_line(preposition: str = "in", noun: Optional[str] = None, verb: str = "disclosed", include_today: bool = True) -> str:
            action_noun = noun or f"a {action}"
            line = f"{emoji} {who}{geo} just {verb} {action_noun}"
            if preposition:
                line += f" {preposition} {ticker_or_undisclosed}"
            line += f" {amount_phrase()}"
            if include_today:
                line += " today."
            else:
                line += "."
            return line

        def t_clean_news():
            return hook_line()

        def t_performance_snap():
            if not perf_has_pct:
                return None
            vs_spx = f"; {spx_change} vs S&P" if spx_change else ""
            line1 = hook_line()
            line2 = f"Since then: {perf.split(' since')[0].replace(f'${ticker}', '').strip()}{vs_spx}." if ticker else perf
            return f"{line1}\n{line2}".strip()

        def t_pattern_watch():
            rc = repeat_ticker_12m
            if rc and isinstance(rc, (int, float)) and rc >= 2:
                line1 = hook_line()
                line2 = f"{int(rc)}x in 12 months."
                return f"{line1}\n{line2}"
            if member_trade_count_30d and isinstance(member_trade_count_30d, (int, float)) and member_trade_count_30d >= 3:
                line1 = hook_line()
                line2 = f"{int(member_trade_count_30d)} trades in 30 days."
                return f"{line1}\n{line2}"
            return None

        def t_lag_callout():
            if lag_days is None or lag_days < 10:
                return None
            line1 = hook_line()
            line2 = f"Filed {lag_days} days later."
            return f"{line1}\n{line2}"

        def t_sector_angle():
            if not sector_tag or not ticker:
                return None
            return hook_line(preposition=f"({sector_tag}) in" if sector_tag else "in")

        def t_options_focus():
            atype = (trade.get('assetType') or trade.get('asset_type') or '').lower()
            if 'option' not in atype and not any(k in trade for k in ['option_type', 'option_side']):
                return None
            side = (trade.get('option_side') or '').upper()
            otype = (trade.get('option_type') or '').upper()
            side_txt = side if side in {'CALL', 'PUT'} else 'OPTION'
            type_txt = otype if otype in {'CALL', 'PUT'} else 'Option'
            return hook_line(noun=f"{side_txt} {type_txt}", preposition="on")

        # Build candidates based on available signal
        candidates = []
        variants = [t_performance_snap(), t_pattern_watch(), t_lag_callout(), t_options_focus(), t_sector_angle(), t_clean_news()]
        for v in variants:
            if not v:
                continue
            candidates.append(v)

        # Engagement heuristic scoring (tuned to reduce monotony)
        def score(text: str) -> int:
            s = 0
            # Performance and relative
            if perf_has_pct and ('Since then:' in text or 'Since trade' in text):
                s += 4
            if spx_change and 'S&P' in text:
                s += 2
            # Lag: lighter weight unless very large
            if lag_days and ('Filed' in text or 'Lag:' in text):
                if lag_days >= 20:
                    s += 2
                elif lag_days >= 10:
                    s += 1
            # Patterns and options
            if repeat_ticker_12m and isinstance(repeat_ticker_12m, (int, float)) and repeat_ticker_12m >= 2 and ('12 months' in text):
                s += 2
            if 'OPTION' in text or 'Option' in text:
                s += 2
            # Sector angle small nudge
            if sector_tag and ('(' + sector_tag + ')' in text):
                s += 1
            # Small bonus for two-line formats
            if '\n' in text:
                s += 1
            # Penalize missing ticker
            if '$' not in text and 'undisclosed ticker' in text:
                s -= 2
            return s

        # Choose using score with deterministic rotation among top candidates to add variety
        if not candidates:
            candidates = [t_clean_news()]
        scored_list = [(score(c), c) for c in candidates]
        scored_list.sort(key=lambda t: (-t[0], len(t[1])))

        # Rotation: if top few are close, rotate based on a stable hash salt to vary structure
        salt = (ticker or '') + '|' + (disclosure_date or trans_date or '') + '|' + member_name + '|' + action
        top_scores = [s for s, _ in scored_list]
        chosen = scored_list[0][1]
        if len(scored_list) > 1:
            # Consider top-3 if their scores are within 2 points of the best
            cutoff = top_scores[0] - 2
            top_candidates = [c for s, c in scored_list if s >= cutoff]
            if top_candidates:
                idx = abs(hash(salt)) % len(top_candidates)
                chosen = top_candidates[idx]

        # Hashtags: up to 2; prefer none when tight
        hashtag_pool = ["#CongressTrades", "#InsiderActivity", "#Markets"]
        if sector_tag:
            hashtag_pool.insert(0, sector_tag)

        # Append at most two that fit
        def append_tags(text: str) -> str:
            out = text
            added = []
            for tag in hashtag_pool:
                if len(added) >= 2:
                    break
                if tag in out:
                    continue
                tentative = f"{out}\n{tag}" if '\n' in out else f"{out} {tag}"
                if len(tentative) <= 280:
                    out = tentative
                    added.append(tag)
            return out

        # Ensure core facts line is present
        final_text = chosen
        final_text = append_tags(final_text)
        final_text = collapse_spaces(final_text)

        # Enforce 280: drop hashtags first
        if len(final_text) > 280:
            parts = final_text.split('\n')
            # remove any hashtags at end
            parts = [p for p in parts if not (p.startswith('#') or p.endswith('#CongressTrades') or p.endswith('#InsiderActivity') or p.endswith('#Markets'))]
            final_text = '\n'.join(parts)
        if len(final_text) > 280:
            # try trimming the trailing fragment after newline
            if '\n' in final_text:
                head, tail = final_text.split('\n', 1)
                final_text = head
        if len(final_text) > 280:
            final_text = final_text[:280]

        return final_text

    def _format_multi_trade_tweet(self, bundle: Dict) -> str:
        """Format a tweet summarizing multiple trades from the same member."""
        first = (bundle.get('firstName') or '').strip()
        last = (bundle.get('lastName') or '').strip()
        member_name = f"{first} {last}".strip()
        trades = bundle.get('trades', [])
        title = "Sen." if any('senate' in (t.get('source') or '').lower() for t in trades) else "Rep."

        bullet_lines = []
        for t in trades:
            raw_action = (t.get('type') or '').strip()
            action = (
                "BUY"
                if raw_action.lower() in {"buy", "purchase"}
                else (
                    "SELL"
                    if raw_action.lower() in {"sell", "sale"}
                    else raw_action.upper() or "TRADE"
                )
            )
            symbol = (t.get('symbol') or '').upper().strip()
            amount_display = self._format_amount(t.get('amount', ''))
            bullet_lines.append(f"- {action} ${symbol} ({amount_display})")

        total_amount_display = self._format_bundle_amount(trades)
        header = f"📊 {title} {member_name} just disclosed {total_amount_display} in trades today!"
        suffix = "\n#CongressTrades"

        def try_append_line(lines: List[str], new_line: str) -> Optional[List[str]]:
            """Attempt to append a new line while respecting X character limits."""

            candidate_lines = lines + [new_line]
            candidate_text = "\n".join(candidate_lines) + suffix
            if len(candidate_text) <= 280:
                return candidate_lines

            # Try truncating the new line if nothing has been added yet
            base_text_len = len("\n".join(lines))
            allowed_len = 280 - base_text_len - len(suffix) - (1 if lines else 0)
            if allowed_len > 3:
                truncated = new_line[: allowed_len - 1].rstrip()
                truncated = f"{truncated}…"
                candidate_text = ("\n".join(lines + [truncated]) + suffix).rstrip()
                if len(candidate_text) <= 280:
                    return lines + [truncated]

            return None

        lines: List[str] = [header.strip()]
        included = 0
        for bullet in bullet_lines:
            updated_lines = try_append_line(lines, bullet)
            if updated_lines is None:
                break
            lines = updated_lines
            included += 1

        remaining = len(bullet_lines) - included
        if remaining > 0:
            for more_line in (
                f"- … and {remaining} more",
                f"- … +{remaining}",
                "- …",
            ):
                updated_lines = try_append_line(lines, more_line)
                if updated_lines is not None:
                    lines = updated_lines
                    break

        tweet = "\n".join(lines) + suffix

        if len(tweet) > 280:
            # Prefer keeping content over the hashtag if necessary
            if tweet.endswith(suffix):
                without_hashtag = tweet[: -len(suffix)]
                if len(without_hashtag) <= 280:
                    tweet = without_hashtag
                else:
                    tweet = without_hashtag[:280].rstrip()
            else:
                tweet = tweet[:280].rstrip()

        return tweet

    def _extract_amount_numbers(self, amount_str: str) -> List[float]:
        """Extract numeric values from an amount string."""
        if not amount_str:
            return []

        cleaned = amount_str.replace(',', '')
        numbers: List[float] = []
        for match in re.findall(r"[0-9]+(?:\.[0-9]+)?", cleaned):
            try:
                numbers.append(float(match))
            except ValueError:
                continue
        return numbers

    def _humanize_amount(self, value: float) -> str:
        """Convert a numeric amount into a compact human-readable string."""
        if value >= 1_000_000:
            scaled = value / 1_000_000
            text = f"{scaled:.1f}" if scaled < 10 else f"{scaled:.0f}"
            if text.endswith(".0"):
                text = text[:-2]
            return f"${text}M"
        if value >= 1_000:
            scaled = value / 1_000
            text = f"{scaled:.1f}" if scaled < 10 else f"{scaled:.0f}"
            if text.endswith(".0"):
                text = text[:-2]
            return f"${text}k"
        return f"${value:,.0f}"

    def _parse_amount_bounds(self, amount_str: str) -> Optional[Tuple[float, float]]:
        """Parse an amount string into (min, max) bounds if possible."""
        numbers = self._extract_amount_numbers(amount_str)
        if not numbers:
            return None
        if '-' in amount_str and len(numbers) >= 2:
            low, high = numbers[0], numbers[1]
            return (min(low, high), max(low, high))
        value = numbers[-1]
        return (value, value)

    def _format_amount(self, amount_str: str) -> str:
        """Format amount string for display with a focus on the top-end of any disclosed range."""
        numbers = self._extract_amount_numbers(amount_str)
        if numbers:
            max_val = max(numbers)
            display = self._humanize_amount(max_val)
            if len(numbers) >= 2:
                return f"up to {display}"
            return display

        return amount_str or "an undisclosed amount"

    def _aggregate_amounts(self, trades: List[Dict]) -> Tuple[float, float, bool, bool, bool]:
        """Return aggregated (min_sum, max_sum, has_range, has_numbers, has_undisclosed)."""
        total_min = 0.0
        total_max = 0.0
        has_range = False
        has_numbers = False
        has_undisclosed = False

        for trade in trades:
            bounds = self._parse_amount_bounds(trade.get('amount', ''))
            if not bounds:
                has_undisclosed = True
                continue

            has_numbers = True
            min_val, max_val = bounds
            total_min += min_val
            total_max += max_val
            if max_val != min_val:
                has_range = True

        return total_min, total_max, has_range, has_numbers, has_undisclosed

    def _format_bundle_amount(self, trades: List[Dict]) -> str:
        """Summarize the aggregate amount across a bundle of trades."""
        total_min, total_max, has_range, has_numbers, has_undisclosed = self._aggregate_amounts(trades)

        if not has_numbers:
            return "an undisclosed amount"

        if has_undisclosed and total_min > 0:
            return f"at least {self._humanize_amount(total_min)}"

        if has_undisclosed and total_min <= 0:
            return "an undisclosed amount"

        if has_range:
            return f"up to {self._humanize_amount(total_max)}"

        return self._humanize_amount(total_max)
    
    def _generate_insight(self, trade: Dict) -> str:
        """Generate a brief insight about the trade."""
        action = trade.get('type', '').upper()
        asset_desc = trade.get('assetDescription', '').lower()
        
        # Sector-based insights
        if any(term in asset_desc for term in ['tech', 'software', 'apple', 'microsoft', 'google']):
            return "Tech sector activity could signal confidence in digital transformation." if action == "BUY" else "Tech pullback may indicate sector rotation concerns."
        elif any(term in asset_desc for term in ['bank', 'financial', 'jpmorgan', 'goldman']):
            return "Financial sector move may reflect interest rate expectations." if action == "BUY" else "Banking exit could signal economic headwinds."
        elif any(term in asset_desc for term in ['health', 'pharma', 'medical', 'biotech']):
            return "Healthcare investment suggests confidence in sector growth." if action == "BUY" else "Healthcare exit may indicate regulatory concerns."
        elif any(term in asset_desc for term in ['energy', 'oil', 'gas', 'renewable']):
            return "Energy sector move reflects shifting market dynamics." if action == "BUY" else "Energy divestment may signal transition focus."
        elif any(term in asset_desc for term in ['defense', 'aerospace', 'military']):
            return "Defense investment could indicate geopolitical considerations." if action == "BUY" else "Defense exit may reflect peace dividend expectations."
        else:
            return "Market timing decision worth monitoring for trends." if action == "BUY" else "Divestment may signal portfolio rebalancing."
    
    def _log_twitter_error(self, error: Exception, operation: str = "create_tweet") -> None:
        """Log rich details from Tweepy/X API errors to aid debugging.

        Attempts to print HTTP status, reason, selected response headers and the
        JSON/text body. Avoids logging sensitive Authorization headers.
        """
        try:
            resp = getattr(error, "response", None)
            if resp is None:
                logger.error(f"Twitter error during {operation}: {error}")
                return

            status = getattr(resp, "status_code", None)
            reason = getattr(resp, "reason", "")
            logger.error(f"Twitter error during {operation}: HTTP {status} {reason}")

            # Log safe subset of headers
            try:
                headers = dict(getattr(resp, "headers", {}) or {})
                for k in list(headers.keys()):
                    if k and k.lower() in {"authorization", "proxy-authorization"}:
                        headers.pop(k, None)
                useful = {k: headers[k] for k in headers if k.lower() in {
                    "x-rate-limit-limit", "x-rate-limit-remaining", "x-rate-limit-reset",
                    "content-type", "x-response-time"
                }}
                if useful:
                    logger.error(f"Response headers: {useful}")
            except Exception:
                pass

            # Prefer JSON body; fallback to text
            body_logged = False
            try:
                data = resp.json()
                logger.error(f"Response JSON: {json.dumps(data, indent=2, sort_keys=True)}")
                body_logged = True
            except Exception:
                try:
                    text = getattr(resp, "text", None)
                    if text:
                        logger.error(f"Response text: {text[:2000]}")
                        body_logged = True
                except Exception:
                    pass

            # Tweepy may attach parsed API errors
            api_errors = getattr(error, "api_errors", None)
            if api_errors and not body_logged:
                try:
                    logger.error(f"API errors: {json.dumps(api_errors, indent=2, sort_keys=True)}")
                except Exception:
                    logger.error(f"API errors: {api_errors}")

        except Exception as log_err:
            logger.error(f"Failed to log twitter error details: {log_err}")

    def _get_sector_hashtag(self, asset_desc: str) -> Optional[str]:
        """Get relevant sector hashtag based on asset description."""
        asset_desc_lower = asset_desc.lower()

        if any(term in asset_desc_lower for term in ['tech', 'software', 'apple', 'microsoft']):
            return "#Tech"
        elif any(term in asset_desc_lower for term in ['bank', 'financial']):
            return "#Finance"
        elif any(term in asset_desc_lower for term in ['health', 'pharma', 'biotech']):
            return "#Healthcare"
        elif any(term in asset_desc_lower for term in ['energy', 'oil']):
            return "#Energy"
        elif any(term in asset_desc_lower for term in ['defense', 'aerospace']):
            return "#Defense"
        else:
            return "#Investing"

    def _select_trade_for_chart(self, bundle: Dict) -> Tuple[str, Optional[str]]:
        """Pick the trade whose symbol has the strongest performance since disclosure for charting."""
        trades = bundle.get('trades') or []
        disclosure_date = (bundle.get('disclosureDate') or '').strip()

        best_symbol = ''
        best_trade_date: Optional[str] = None
        best_performance: Optional[float] = None

        for trade in trades:
            symbol = (trade.get('symbol') or '').upper().strip()
            if not symbol:
                continue
            perf_start = (trade.get('disclosureDate') or disclosure_date or '').strip()
            change = self._calculate_performance_since(symbol, perf_start)
            if change is None:
                continue
            if best_performance is None or change > best_performance:
                best_symbol = symbol
                best_trade_date = trade.get('transactionDate')
                best_performance = change

        if best_symbol:
            return best_symbol, best_trade_date

        for trade in trades:
            symbol = (trade.get('symbol') or '').upper().strip()
            if symbol:
                return symbol, trade.get('transactionDate')

        return '', None
    
    def post_trade_tweet(self, trade: Dict) -> None:
        """
        Post a tweet about a congressional trade with error handling and rate limiting.
        
        Args:
            trade: Dictionary containing trade information with fields like
                  firstName, lastName, type, symbol, amount, transactionDate, etc.
        """
        try:
            # Choose style based on single vs. multiple trades
            if 'trades' in trade:
                tweet_text = self._format_multi_trade_tweet(trade)
                chart_symbol, chart_date = self._select_trade_for_chart(trade)
            else:
                tweet_text = self._format_trade_tweet_engaging(trade) if self.use_engaging_style else self._format_trade_tweet(trade)
                chart_symbol = (trade.get('symbol') or '').upper().strip()
                chart_date = trade.get('transactionDate')
            logger.info(f"Posting tweet: {tweet_text}")

            media_ids: Optional[List[int]] = None

            # Optionally attach a small chart image for the symbol
            if self.attach_chart and chart_symbol and plt is not None:
                try:
                    image_path = self._build_chart_for_symbol(chart_symbol, chart_date)
                    if image_path:
                        media_id = self.api_v1.media_upload(filename=image_path).media_id
                        media_ids = [media_id]
                        try:
                            os.remove(image_path)
                        except Exception:
                            pass
                except Exception as chart_err:
                    logger.warning(f"Chart generation/upload failed for {chart_symbol}: {chart_err}")
                    media_ids = None

            # Post tweet with retry logic (optionally with media)
            self._post_with_retry(tweet_text, media_ids=media_ids)

            logger.info("Tweet posted successfully")
            
        except Exception as e:
            if getattr(e, "response", None) is not None:
                self._log_twitter_error(e, operation="post_trade_tweet")
            logger.error(f"Failed to post tweet for trade {trade.get('symbol', 'Unknown')}: {str(e)}")
            raise
    
    def _post_with_retry(self, tweet_text: str, max_retries: int = 3, media_ids: Optional[List[int]] = None) -> None:
        """
        Post tweet with exponential backoff retry for rate limiting.
        
        Args:
            tweet_text: The tweet content to post
            max_retries: Maximum number of retry attempts
        """
        for attempt in range(max_retries + 1):
            try:
                if media_ids:
                    # Primary path: v2 param 'media' expects dict with 'media_ids'
                    try:
                        response = self.client.create_tweet(text=tweet_text, media={"media_ids": media_ids})
                    except TypeError:
                        # Fallback for alternative client signatures
                        response = self.client.create_tweet(text=tweet_text, media_ids=media_ids)
                else:
                    response = self.client.create_tweet(text=tweet_text)
                logger.info(f"Tweet posted with ID: {response.data['id']}")
                return
                
            except tweepy.TooManyRequests as e:
                # Log details before backing off
                self._log_twitter_error(e, operation="create_tweet")
                if attempt < max_retries:
                    # Exponential backoff: 2^attempt * 60 seconds
                    wait_time = (2 ** attempt) * 60
                    logger.warning(f"Rate limited. Waiting {wait_time} seconds before retry {attempt + 1}/{max_retries}")
                    time.sleep(wait_time)
                else:
                    logger.error("Max retries exceeded for rate limiting")
                    raise
                    
            except tweepy.Forbidden as e:
                self._log_twitter_error(e, operation="create_tweet")
                raise
                
            except tweepy.Unauthorized as e:
                self._log_twitter_error(e, operation="create_tweet")
                raise
                
            except Exception as e:
                # If this came from HTTP, attempt rich logging
                if getattr(e, "response", None) is not None:
                    self._log_twitter_error(e, operation="create_tweet")
                if attempt < max_retries:
                    wait_time = (2 ** attempt) * 30  # Shorter wait for general errors
                    logger.warning(f"General error: {str(e)}. Retrying in {wait_time} seconds")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Max retries exceeded. Final error: {str(e)}")
                    raise

    # -------------------------
    # Chart & Price utilities
    # -------------------------
    def _ema(self, values: List[float], span: int) -> List[float]:
        """Compute an Exponential Moving Average for a sequence of floats.
        Returns a list of the same length as values.
        """
        if not values or span <= 1:
            return list(values)
        alpha = 2.0 / (span + 1.0)
        ema_values: List[float] = []
        ema_prev = float(values[0])
        for v in values:
            ema_prev = (alpha * float(v)) + ((1.0 - alpha) * ema_prev)
            ema_values.append(ema_prev)
        return ema_values
    def _fetch_historical_prices(self, symbol: str, days: int = 60) -> List[Tuple[datetime, float]]:
        """Fetch recent prices from FMP with robust fallbacks. Returns list of (date, close)."""
        api_key = os.getenv("FMP_API_KEY")
        if not api_key:
            logger.warning("FMP_API_KEY not set; cannot build chart")
            return []

        # Primary: daily closes for last N days
        url_daily = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?timeseries={days}&apikey={api_key}"
        try:
            resp = requests.get(url_daily, timeout=10)
            if resp.status_code == 200:
                data = resp.json() or {}
                hist = data.get("historical", [])
                series: List[Tuple[datetime, float]] = []
                for item in hist:
                    try:
                        d = datetime.strptime(item["date"], "%Y-%m-%d")
                        c = float(item["close"])
                        series.append((d, c))
                    except Exception:
                        continue
                series.sort(key=lambda x: x[0])
                if series:
                    return series
            else:
                logger.warning(f"FMP daily HTTP {resp.status_code} for {symbol}")
        except Exception as e:
            logger.warning(f"FMP daily exception for {symbol}: {e}")

        # Fallback 1: 4-hour bars over approx last 60 days
        try:
            end = datetime.utcnow()
            start = end - timedelta(days=max(days, 60))
            url_4h = (
                f"https://financialmodelingprep.com/api/v3/historical-chart/4hour/{symbol}?from={start.strftime('%Y-%m-%d')}&to={end.strftime('%Y-%m-%d')}&apikey={api_key}"
            )
            r2 = requests.get(url_4h, timeout=10)
            if r2.status_code == 200:
                arr = r2.json() or []
                step = max(len(arr) // 90, 1)  # downsample to ~90 points
                series_4h: List[Tuple[datetime, float]] = []
                for item in arr[::step]:
                    try:
                        d = datetime.strptime(item["date"], "%Y-%m-%d %H:%M:%S")
                        c = float(item["close"])
                        series_4h.append((d, c))
                    except Exception:
                        continue
                series_4h.sort(key=lambda x: x[0])
                if series_4h:
                    return series_4h
            else:
                logger.warning(f"FMP 4h HTTP {r2.status_code} for {symbol}")
        except Exception as e:
            logger.warning(f"FMP 4h exception for {symbol}: {e}")

        # Fallback 2: 1-hour bars over approx last 30 days
        try:
            end = datetime.utcnow()
            start = end - timedelta(days=30)
            url_1h = (
                f"https://financialmodelingprep.com/api/v3/historical-chart/1hour/{symbol}?from={start.strftime('%Y-%m-%d')}&to={end.strftime('%Y-%m-%d')}&apikey={api_key}"
            )
            r3 = requests.get(url_1h, timeout=10)
            if r3.status_code == 200:
                arr = r3.json() or []
                step = max(len(arr) // 90, 1)
                series_1h: List[Tuple[datetime, float]] = []
                for item in arr[::step]:
                    try:
                        d = datetime.strptime(item["date"], "%Y-%m-%d %H:%M:%S")
                        c = float(item["close"])
                        series_1h.append((d, c))
                    except Exception:
                        continue
                series_1h.sort(key=lambda x: x[0])
                if series_1h:
                    return series_1h
            else:
                logger.warning(f"FMP 1h HTTP {r3.status_code} for {symbol}")
        except Exception as e:
            logger.warning(f"FMP 1h exception for {symbol}: {e}")

        # Fallback 3: yfinance (no API key) daily data
        try:
            import yfinance as yf  # type: ignore
            import pandas as pd  # type: ignore
            period = "3mo" if days >= 60 else "1mo"
            # Force single-level columns if possible
            df = yf.download(
                symbol,
                period=period,
                interval="1d",
                progress=False,
                auto_adjust=False,
                group_by="column",
            )
            series_yf: List[Tuple[datetime, float]] = []
            if not df.empty:
                close_series = None

                # Case 1: Single-level columns
                if getattr(df.columns, "nlevels", 1) == 1:
                    if "Close" in df.columns:
                        close_series = df["Close"]
                    elif "Adj Close" in df.columns:
                        close_series = df["Adj Close"]

                # Case 2: MultiIndex columns. Try to locate any level that equals 'Close'/'Adj Close'
                if close_series is None and getattr(df.columns, "nlevels", 1) > 1:
                    # Try xs on level 0 and level 1 (common patterns)
                    for level in range(df.columns.nlevels):
                        for key in ("Close", "Adj Close"):
                            try:
                                sub = df.xs(key, axis=1, level=level)
                                if isinstance(sub, pd.Series):
                                    close_series = sub
                                    break
                                elif isinstance(sub, pd.DataFrame) and not sub.empty:
                                    close_series = sub.iloc[:, 0]
                                    break
                            except Exception:
                                continue
                        if close_series is not None:
                            break
                    # As a final attempt, scan raw tuples
                    if close_series is None:
                        for col in df.columns:
                            if isinstance(col, tuple) and any(part in ("Close", "Adj Close") for part in col):
                                close_series = df[col]
                                break

                if close_series is None:
                    logger.warning(f"yfinance returned data for {symbol} but could not locate Close column; cols={list(df.columns)[:6]}")
                else:
                    for idx, val in close_series.items():
                        try:
                            d = getattr(idx, "to_pydatetime", lambda: idx)().replace(tzinfo=None)  # robust timestamp handling
                            if pd.notna(val):
                                series_yf.append((d, float(val)))
                        except Exception:
                            continue

            series_yf.sort(key=lambda x: x[0])
            if series_yf:
                logger.info(f"Using yfinance fallback for {symbol} ({len(series_yf)} pts)")
                return series_yf
        except Exception as e:
            logger.warning(f"yfinance fallback exception for {symbol}: {e}")

        return []

    def _build_chart_for_symbol(self, symbol: str, transaction_date: Optional[str] = None) -> Optional[str]:
        """Generate a professional, clean PNG line chart and optionally mark the transaction date."""
        if plt is None:
            return None
        series = self._fetch_historical_prices(symbol, days=90)
        if not series:
            logger.warning(f"No price data available for {symbol}; chart generation skipped")
            return None
        dates = [d for d, _ in series]
        closes = [c for _, c in series]

        # --- Styling choices ---
        primary = "#0A84FF"       # modern blue
        accent = "#FF4D4F"        # tx marker
        ema_color = "#8AB4F8"     # softer blue for EMA
        grid_alpha = 0.22

        # Create plot (slightly wider, high DPI)
        fig, ax = plt.subplots(figsize=(7.6, 4.1), dpi=280)

        # Light gradient-like background by subtle facecolor
        ax.set_facecolor("#FAFBFF")

        # Price line with soft shadow and rounded caps
        line_main, = ax.plot(
            dates,
            closes,
            color=primary,
            linewidth=2.8,
            solid_joinstyle="round",
            solid_capstyle="round",
            zorder=3,
        )
        line_main.set_path_effects([
            pe.SimpleLineShadow(offset=(0, -1), alpha=0.25, linewidth=3.6),
            pe.Normal(),
        ])

        # Subtle area fill
        ax.fill_between(dates, closes, min(closes), color=primary, alpha=0.08, zorder=1)

        # Optional 10-day EMA overlay for texture
        if len(closes) >= 10:
            ema_vals = self._ema(closes, 10)
            ax.plot(dates, ema_vals, color=ema_color, linewidth=1.6, alpha=0.9, zorder=2)

        # Title minimal, medium weight
        ax.set_title(f"${symbol} - Last 90 Days", fontsize=14, pad=10)

        # Labels
        ax.set_xlabel("")
        ax.set_ylabel("Price ($)", fontsize=10)

        # Clean spines and lightweight grid on Y only
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        ax.spines["left"].set_alpha(0.45)
        ax.spines["bottom"].set_alpha(0.45)
        ax.grid(True, which="major", axis="y", linestyle=":", alpha=grid_alpha)
        ax.grid(False, axis="x")

        # Nice y-lims with padding
        ymin, ymax = min(closes), max(closes)
        pad = (ymax - ymin) * 0.06 if ymax > ymin else 1
        ax.set_ylim(ymin - pad, ymax + pad)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5, prune="both"))

        # Date formatting: month + day only, limited ticks to avoid overlap
        locator = mdates.AutoDateLocator(minticks=4, maxticks=6)
        formatter = mdates.DateFormatter("%b %d")  # e.g., Aug 01
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
        ax.tick_params(axis="x", labelsize=10)
        ax.tick_params(axis="y", labelsize=10)

        # Secondary Y axis: % change vs base (entry price if available, else first close)
        pct_base = None
        if transaction_date:
            try:
                entry_price, _ = self._get_close_on_or_after(symbol, transaction_date)
                if entry_price:
                    pct_base = entry_price
            except Exception:
                pct_base = None
        if pct_base is None:
            pct_base = closes[0]
        if pct_base and pct_base > 0:
            # Map current y-limits to percent range
            pct_min = (ax.get_ylim()[0] - pct_base) / pct_base * 100.0
            pct_max = (ax.get_ylim()[1] - pct_base) / pct_base * 100.0
            ax_pct = ax.twinx()
            ax_pct.set_ylim(pct_min, pct_max)
            ax_pct.tick_params(axis="y", labelsize=9, colors="#6B7280")
            ax_pct.spines["top"].set_visible(False)
            ax_pct.spines["right"].set_alpha(0.35)
            ax_pct.grid(False)
            ax_pct.set_ylabel("%", fontsize=9, color="#6B7280")
            def _pct_fmt(v, pos):
                sign = "+" if v >= 0 else ""
                return f"{sign}{v:.0f}%"
            from matplotlib.ticker import FuncFormatter  # local import to avoid global if not available
            ax_pct.yaxis.set_major_formatter(FuncFormatter(_pct_fmt))

        # Mark transaction date if within range
        try:
            if transaction_date:
                tx = datetime.strptime(transaction_date, "%Y-%m-%d")
                if dates[0] <= tx <= dates[-1]:
                    ax.axvline(tx, color=accent, linestyle=(0, (6, 4)), linewidth=1.5, alpha=0.9)
                    ax.annotate(
                        "Tx",
                        xy=(tx, ymax + pad * 0.1),
                        xytext=(4, -8),
                        textcoords="offset points",
                        color=accent,
                        fontsize=10,
                        ha="left",
                        va="top",
                    )
        except Exception:
            pass
        # Label last price bubble
        last_x, last_y = dates[-1], closes[-1]
        ax.scatter([last_x], [last_y], s=24, color=primary, zorder=4)
        try:
            ax.annotate(
                f"${last_y:.2f}",
                xy=(last_x, last_y),
                xytext=(8, 10),
                textcoords="offset points",
                fontsize=9,
                color="#111827",
                bbox=dict(boxstyle="round,pad=0.3", fc="#E5F0FF", ec="#93C5FD", lw=0.8, alpha=0.9),
            )
        except Exception:
            pass

        fig.tight_layout()

        # Subtle watermark
        try:
            fig.text(
                0.99,
                0.02,
                "theinsidescope",
                ha="right",
                va="bottom",
                fontsize=9,
                color="#6B7280",
                alpha=0.7,
            )
        except Exception:
            pass

        # Save to temp file
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{symbol}.png")
        image_path = tmp.name
        tmp.close()
        fig.savefig(image_path, bbox_inches="tight")
        plt.close(fig)
        return image_path

    # -------------------------
    # Performance snippet helpers
    # -------------------------
    def _calculate_performance_since(self, symbol: str, start_date: Optional[str]) -> Optional[float]:
        """Return percentage change from the first close on/after start_date to the latest close."""
        if not symbol or not start_date:
            return None
        try:
            entry_price, _ = self._get_close_on_or_after(symbol, start_date)
            latest_price, _ = self._get_latest_close(symbol)
            if entry_price is None or latest_price is None or entry_price <= 0:
                return None
            return (latest_price - entry_price) / entry_price * 100.0
        except Exception:
            return None

    def _build_performance_snippet(self, symbol: str, action: str, transaction_date: Optional[str]) -> str:
        """Return a short line like: "$XYZ is up 3.2% since the purchase." if data available."""
        try:
            if not symbol or not transaction_date:
                return ""
            entry_price, _ = self._get_close_on_or_after(symbol, transaction_date)
            latest_price, _ = self._get_latest_close(symbol)
            if entry_price is None or latest_price is None or entry_price <= 0:
                return ""
            change_pct = (latest_price - entry_price) / entry_price * 100.0
            direction = "up" if change_pct >= 0 else "down"
            abs_pct = abs(change_pct)
            suffix = "purchase" if action == "BUY" else ("sale" if action == "SELL" else "transaction")
            return f"${symbol} is {direction} {abs_pct:.1f}% since the {suffix}."
        except Exception:
            return ""

    def _get_close_on_or_after(self, symbol: str, date_str: str) -> Tuple[Optional[float], Optional[str]]:
        """Find close on the given date or next trading day within a small window."""
        api_key = os.getenv("FMP_API_KEY")
        if not api_key:
            return None, None
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            return None, None
        start = (target - timedelta(days=3)).strftime("%Y-%m-%d")
        end = (target + timedelta(days=10)).strftime("%Y-%m-%d")
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?from={start}&to={end}&apikey={api_key}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return None, None
            data = resp.json() or {}
            hist = data.get("historical", [])
            chosen = None
            for item in sorted(hist, key=lambda x: x.get("date", "")):
                try:
                    d = datetime.strptime(item["date"], "%Y-%m-%d")
                except Exception:
                    continue
                if d >= target:
                    chosen = item
                    break
            if not chosen and hist:
                chosen = sorted(hist, key=lambda x: x.get("date", ""))[0]
            if chosen:
                return float(chosen.get("close")), chosen.get("date")
            return None, None
        except Exception:
            return None, None

    def _get_latest_close(self, symbol: str) -> Tuple[Optional[float], Optional[str]]:
        """Get most recent close using quote endpoint fallback to 1-day historical."""
        api_key = os.getenv("FMP_API_KEY")
        if not api_key:
            return None, None
        # Try quote endpoint first
        url_quote = f"https://financialmodelingprep.com/api/v3/quote/{symbol}?apikey={api_key}"
        try:
            r = requests.get(url_quote, timeout=10)
            if r.status_code == 200:
                arr = r.json() or []
                if isinstance(arr, list) and arr:
                    price = arr[0].get("price") or arr[0].get("previousClose")
                    if price:
                        return float(price), datetime.utcnow().strftime("%Y-%m-%d")
        except Exception:
            pass
        # Fallback to 1-day historical
        url_hist = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?timeseries=1&apikey={api_key}"
        try:
            r2 = requests.get(url_hist, timeout=10)
            if r2.status_code == 200:
                d = r2.json() or {}
                hist = d.get("historical", [])
                if hist:
                    return float(hist[0]["close"]), hist[0]["date"]
        except Exception:
            pass
        return None, None


def _aggregate_trades_by_member(trades: List[Dict]) -> List[Dict]:
    """Group trades by member and disclosure date."""
    grouped: Dict[Tuple[str, str, str], List[Dict]] = {}
    for t in trades:
        key = (t.get('firstName'), t.get('lastName'), t.get('disclosureDate'))
        grouped.setdefault(key, []).append(t)

    aggregated: List[Dict] = []
    for (first, last, date), items in grouped.items():
        if len(items) == 1:
            aggregated.append(items[0])
        else:
            aggregated.append({'firstName': first, 'lastName': last, 'disclosureDate': date, 'trades': items})
    return aggregated


def post_trades_to_twitter(trades: List[Dict]) -> None:
    """Post multiple trades to Twitter, aggregating by member and day."""
    if not trades:
        logger.info("No trades to post to Twitter")
        return

    try:
        twitter_client = TwitterClient()
        aggregated = _aggregate_trades_by_member(trades)

        for i, trade in enumerate(aggregated):
            logger.info(f"Posting trade {i+1}/{len(aggregated)}")
            twitter_client.post_trade_tweet(trade)

            if i < len(aggregated) - 1:
                time.sleep(5)

        logger.info(f"Successfully posted {len(aggregated)} trades to Twitter")

    except Exception as e:
        logger.error(f"Error posting trades to Twitter: {str(e)}")
        raise