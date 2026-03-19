import os
import requests
from dotenv import load_dotenv

def check_updates():
    load_dotenv()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token:
        print("Error: TELEGRAM_BOT_TOKEN not set.")
        return

    api_url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    
    # Try fetching with 0 offset to see if we missed anything or if there are errors
    params = {"limit": 10}
    try:
        response = requests.get(api_url, params=params, timeout=10)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            result = response.json().get("result", [])
            print(f"Found {len(result)} updates.")
            for update in result:
                msg = update.get("message", {})
                text = msg.get("text", "")
                from_id = str(msg.get("chat", {}).get("id", ""))
                print(f"Update ID: {update['update_id']} | From: {from_id} | Text: {text}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    check_updates()
