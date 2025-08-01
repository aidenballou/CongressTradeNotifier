import os
import time
import logging
from typing import Dict, Optional
import tweepy
from dotenv import load_dotenv

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
        
        # Initialize Tweepy client
        self.client = tweepy.Client(
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_secret,
            wait_on_rate_limit=True
        )
    
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
        action = trade.get('type', '').upper()
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
        emoji = "📈" if action == "BUY" else "📉" if action == "SELL" else "📊"
        
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
            tweet_text = self._format_trade_tweet(trade)
            logger.info(f"Posting tweet: {tweet_text}")
            
            # Post tweet with retry logic
            self._post_with_retry(tweet_text)
            
            logger.info("Tweet posted successfully")
            
        except Exception as e:
            logger.error(f"Failed to post tweet for trade {trade.get('symbol', 'Unknown')}: {str(e)}")
            raise
    
    def _post_with_retry(self, tweet_text: str, max_retries: int = 3) -> None:
        """
        Post tweet with exponential backoff retry for rate limiting.
        
        Args:
            tweet_text: The tweet content to post
            max_retries: Maximum number of retry attempts
        """
        for attempt in range(max_retries + 1):
            try:
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