from notifier import run_delta
from emailer import send_summary
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

def main():
    
    new = run_delta()
    print(f"Found {len(new)} new trades")
    
    if new:
        send_summary(new)
        print("Email sent!")
    else:
        print("No new trades to send")

if __name__ == "__main__":
    main()