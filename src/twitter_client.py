import os
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
    import matplotlib.pyplot as plt  # type: ignore
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
        ticker = trade.get('symbol', '')
        amount_str = trade.get('amount', '')
        date = trade.get('transactionDate', '')
        asset_desc = trade.get('assetDescription', '')
        
        # Determine member title (Sen./Rep.)
        title = "Sen." if "senate" in trade.get('source', '').lower() else "Rep."
        
        # Format amount for display
        amount_display = self._format_amount(amount_str)
        
        # Generate insight based on trade details
        insight = self._generate_insight(trade)
        
        # Select appropriate emoji
        emoji = "🚀" if action == "BUY" else "⚠️" if action == "SELL" else "📊"
        
        # Build tweet with character limit consideration
        base_tweet = f"{emoji} {title} {member_name} disclosed a {action} of ${ticker} on {date} ({amount_display}). {insight} #CongressTrades"
        
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
                base_tweet = f"{emoji} {title} {member_name} disclosed a {action} of ${ticker} on {date} ({amount_display}). {insight} #CongressTrades"
            else:
                # Remove insight if still too long
                base_tweet = f"{emoji} {title} {member_name} disclosed a {action} of ${ticker} on {date} ({amount_display}). #CongressTrades"
        
        return base_tweet

    def _format_trade_tweet_engaging(self, trade: Dict) -> str:
        """More engaging style tweet with a performance line and newlines, ≤ 280 chars."""
        member_name = f"{trade.get('firstName', '')} {trade.get('lastName', '')}".strip()
        raw_action = (trade.get('type') or '').strip()
        action = "BUY" if raw_action.lower() in {"buy", "purchase"} else ("SELL" if raw_action.lower() in {"sell", "sale"} else raw_action.upper() or "TRADE")
        ticker = (trade.get('symbol') or '').upper()
        amount_str = trade.get('amount', '')
        trans_date = trade.get('transactionDate', '')
        asset_desc = trade.get('assetDescription', '')
        district = (trade.get('district') or '').strip()
        title = "Sen." if "senate" in (trade.get('source') or '').lower() else "Rep."

        amount_display = self._format_amount(amount_str)
        sector_tag = self._get_sector_hashtag(asset_desc)

        # Tone and emojis
        lead_emoji = "🟢" if action == "BUY" else ("🔴" if action == "SELL" else "🟡")
        verb = "just disclosed"  # adds recency/urgency

        # Optional locality info
        geo = f" ({district})" if district else ""

        # Insight + performance snippet
        insight = self._generate_insight(trade)
        perf_snippet = self._build_performance_snippet(ticker, action, trans_date)

        # Three-line layout
        line1 = f"{lead_emoji} {title} {member_name}{geo} {verb} a {action} in ${ticker} on {trans_date} (≈{amount_display})."
        line2 = perf_snippet  # may be empty
        line3_base = f"{insight} #CongressTrades"
        line3 = f"{line3_base} {sector_tag}" if sector_tag else line3_base

        # Assemble with newlines and enforce 280 chars by trimming extras first
        parts = [p for p in [line1, line2, line3] if p]
        candidate = "\n\n".join(parts)
        if len(candidate) <= 280:
            return candidate

        # Drop sector hashtag if needed
        if sector_tag and (len(candidate) - (len(sector_tag) + 1)) <= 280:
            return candidate.replace(f" {sector_tag}", "")

        # Truncate insight if still long
        if insight and len(candidate) > 280:
            keep = 280 - (len(line1) + 2 + len(line2)) - len(" #CongressTrades")
            if keep > 40:
                truncated = (insight[: keep - 1] + "…") if len(insight) > keep else insight
                candidate = "\n\n".join([s for s in [line1, line2, f"{truncated} #CongressTrades"] if s])
                if len(candidate) <= 280:
                    return candidate

        # If still too long, drop performance line
        candidate = "\n\n".join([line1, line3_base])
        if len(candidate) + (len(sector_tag) + 1 if sector_tag else 0) <= 280:
            return candidate + (f" {sector_tag}" if sector_tag else "")

        # Compact fallback
        compact = f"{lead_emoji} {title} {member_name}{geo} {verb} {action} ${ticker} on {trans_date} (≈{amount_display}). #CongressTrades"
        if sector_tag and len(compact) + len(sector_tag) + 1 <= 280:
            compact += f" {sector_tag}"
        return compact[:280]
    
    def _format_amount(self, amount_str: str) -> str:
        """Format amount string for display."""
        if not amount_str:
            return "undisclosed amount"
        
        # Clean up amount string
        cleaned = amount_str.replace('$', '').replace(',', '')
        
        # Handle range format
        if ' - ' in cleaned:
            parts = cleaned.split(' - ')
            if len(parts) == 2:
                try:
                    min_val = float(parts[0])
                    max_val = float(parts[1])
                    avg_val = (min_val + max_val) / 2
                    
                    if avg_val >= 1000000:
                        return f"${avg_val/1000000:.1f}M"
                    elif avg_val >= 1000:
                        return f"${avg_val/1000:.0f}K"
                    else:
                        return f"${avg_val:.0f}"
                except ValueError:
                    pass
        
        return amount_str
    
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
    
    def post_trade_tweet(self, trade: Dict) -> None:
        """
        Post a tweet about a congressional trade with error handling and rate limiting.
        
        Args:
            trade: Dictionary containing trade information with fields like
                  firstName, lastName, type, symbol, amount, transactionDate, etc.
        """
        try:
            # Choose style
            tweet_text = self._format_trade_tweet_engaging(trade) if self.use_engaging_style else self._format_trade_tweet(trade)
            logger.info(f"Posting tweet: {tweet_text}")
            
            media_ids: Optional[List[str]] = None

            # Optionally attach a small chart image for the symbol
            symbol = (trade.get('symbol') or '').upper().strip()
            if self.attach_chart and symbol and plt is not None:
                try:
                    image_path = self._build_chart_for_symbol(symbol, trade.get('transactionDate'))
                    if image_path:
                        media_id = self.api_v1.media_upload(filename=image_path).media_id_string
                        media_ids = [media_id]
                        try:
                            os.remove(image_path)
                        except Exception:
                            pass
                except Exception as chart_err:
                    logger.warning(f"Chart generation/upload failed for {symbol}: {chart_err}")
                    media_ids = None

            # Post tweet with retry logic (optionally with media)
            self._post_with_retry(tweet_text, media_ids=media_ids)
            
            logger.info("Tweet posted successfully")
            
        except Exception as e:
            logger.error(f"Failed to post tweet for trade {trade.get('symbol', 'Unknown')}: {str(e)}")
            raise
    
    def _post_with_retry(self, tweet_text: str, max_retries: int = 3, media_ids: Optional[List[str]] = None) -> None:
        """
        Post tweet with exponential backoff retry for rate limiting.
        
        Args:
            tweet_text: The tweet content to post
            max_retries: Maximum number of retry attempts
        """
        for attempt in range(max_retries + 1):
            try:
                if media_ids:
                    response = self.client.create_tweet(text=tweet_text, media={"media_ids": media_ids})
                else:
                    response = self.client.create_tweet(text=tweet_text)
                logger.info(f"Tweet posted with ID: {response.data['id']}")
                return
                
            except tweepy.TooManyRequests as e:
                if attempt < max_retries:
                    # Exponential backoff: 2^attempt * 60 seconds
                    wait_time = (2 ** attempt) * 60
                    logger.warning(f"Rate limited. Waiting {wait_time} seconds before retry {attempt + 1}/{max_retries}")
                    time.sleep(wait_time)
                else:
                    logger.error("Max retries exceeded for rate limiting")
                    raise
                    
            except tweepy.Forbidden as e:
                logger.error(f"Twitter API forbidden error: {str(e)}")
                raise
                
            except tweepy.Unauthorized as e:
                logger.error(f"Twitter API unauthorized error: {str(e)}")
                raise
                
            except Exception as e:
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
    def _fetch_historical_prices(self, symbol: str, days: int = 60) -> List[Tuple[datetime, float]]:
        """Fetch recent daily close prices from FMP. Returns list of (date, close)."""
        api_key = os.getenv("FMP_API_KEY")
        if not api_key:
            return []
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?timeseries={days}&apikey={api_key}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return []
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
            return series
        except Exception:
            return []

    def _build_chart_for_symbol(self, symbol: str, transaction_date: Optional[str] = None) -> Optional[str]:
        """Generate a simple PNG line chart for the symbol and optionally mark the transaction date."""
        if plt is None:
            return None
        series = self._fetch_historical_prices(symbol, days=90)
        if not series:
            return None
        dates = [d for d, _ in series]
        closes = [c for _, c in series]

        # Create plot
        fig, ax = plt.subplots(figsize=(6, 3), dpi=200)
        ax.plot(dates, closes, color="#1DA1F2", linewidth=2)
        ax.set_title(f"${symbol} - Last 90 Days", fontsize=10)
        ax.set_xlabel("")
        ax.set_ylabel("Price ($)", fontsize=8)
        ax.grid(True, linestyle=":", alpha=0.3)
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        # Mark transaction date if within range
        try:
            if transaction_date:
                tx = datetime.strptime(transaction_date, "%Y-%m-%d")
                if dates[0] <= tx <= dates[-1]:
                    ax.axvline(tx, color="#FF5733", linestyle="--", linewidth=1, alpha=0.85)
                    ax.text(tx, max(closes), " Tx", color="#FF5733", fontsize=8, ha="left", va="top")
        except Exception:
            pass
        fig.tight_layout()

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


def post_trades_to_twitter(trades: list) -> None:
    """
    Post multiple trades to Twitter.
    
    Args:
        trades: List of trade dictionaries
    """
    if not trades:
        logger.info("No trades to post to Twitter")
        return
    
    try:
        twitter_client = TwitterClient()
        
        for i, trade in enumerate(trades):
            logger.info(f"Posting trade {i+1}/{len(trades)}: {trade.get('symbol', 'Unknown')}")
            twitter_client.post_trade_tweet(trade)
            
            # Add delay between posts to avoid hitting rate limits
            if i < len(trades) - 1:  # Don't wait after the last tweet
                time.sleep(5)  # 5 second delay between tweets
                
        logger.info(f"Successfully posted {len(trades)} trades to Twitter")
        
    except Exception as e:
        logger.error(f"Error posting trades to Twitter: {str(e)}")
        raise 