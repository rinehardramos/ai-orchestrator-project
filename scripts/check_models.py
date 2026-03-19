import os
import asyncio
from google import genai
from dotenv import load_dotenv

async def check_models():
    load_dotenv()
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY not found")
        return
    
    client = genai.Client(api_key=api_key)
    try:
        # Try to list models
        print("Available models:")
        for m in client.models.list():
            if 'flash' in m.name.lower():
                print(f" - {m.name}")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    asyncio.run(check_models())
