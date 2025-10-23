import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from emailer import send_summary
from insights import build_highlights_text, compute_trade_insights
from notifier import run_delta
from twitter_client import post_trades_to_twitter

# Load environment variables
load_dotenv()

def main():
    print("Starting main.py...")
    print(f"SMTP_HOST: {os.getenv('SMTP_HOST')}")
    print(f"FMP_API_KEY: {os.getenv('FMP_API_KEY')}")
    print(f"TWITTER_API_KEY: {'***' if os.getenv('TWITTER_API_KEY') else 'Not set'}")
    
    new = run_delta()
    today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    trades_today = [t for t in new if t.get("disclosureDate") == today]
    print(f"Found {len(trades_today)} trades disclosed today ({today})")
    
    if trades_today:
        insights = compute_trade_insights(trades_today)
        print("Daily highlights:")
        print(build_highlights_text(insights))

        # Send email summary
        print("Sending email...")
        send_summary(trades_today, insights)
        print("Email sent!")
        
        # Post tweets for each trade
        print("Posting trades to Twitter...")
        try:
            post_trades_to_twitter(trades_today)
            print("Tweets posted successfully!")
        except Exception as e:
            print(f"Error posting to Twitter: {str(e)}")
            # Continue execution even if Twitter posting fails
    else:
        print("No trades disclosed today.")

if __name__ == "__main__":
    main()
