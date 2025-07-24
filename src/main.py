from notifier import run_delta
from emailer import send_summary
from dotenv import load_dotenv
import os
from datetime import datetime

# Load environment variables
load_dotenv()

def main():
    print("Starting main.py...")
    print(f"SMTP_HOST: {os.getenv('SMTP_HOST')}")
    print(f"FMP_API_KEY: {os.getenv('FMP_API_KEY')}")
    
    new = run_delta()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    trades_today = [t for t in new if t.get("disclosureDate") == today]
    print(f"Found {len(trades_today)} trades disclosed today ({today})")
    
    if trades_today:
        print("Sending email...")
        send_summary(trades_today)
        print("Email sent!")
    else:
        print("No trades disclosed today.")

if __name__ == "__main__":
    main()