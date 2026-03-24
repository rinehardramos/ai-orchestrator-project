#!/usr/bin/env python3
"""
Test Gmail tool with stored credentials from the database.

Usage:
    python scripts/test_gmail_live.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.plugins.loader import load_tools
from src.plugins.registry import registry
from src.plugins.base import ToolContext


async def main():
    print("=" * 60)
    print("Gmail Tool Live Test")
    print("=" * 60)
    
    # Load tools from database
    print("\n1. Loading tools from database...")
    await load_tools("config/bootstrap.yaml", node="worker")
    
    # Get gmail tool
    print("\n2. Getting gmail tool from registry...")
    gmail = registry.get("gmail")
    
    if not gmail:
        print("❌ Gmail tool not found in registry")
        print("   Available tools:", list(registry._tools.keys()))
        return
    
    print(f"✅ Found gmail tool: {gmail.name}")
    print(f"   Type: {gmail.type}")
    
    # Check credentials
    print("\n3. Checking credentials...")
    if hasattr(gmail, 'username') and gmail.username:
        print(f"✅ Username configured: {gmail.username}")
    else:
        print("❌ Username not configured")
    
    if hasattr(gmail, 'password') and gmail.password:
        print(f"✅ Password configured: {'*' * 8}")
    else:
        print("❌ Password not configured")
    
    # Test read inbox
    print("\n4. Testing email_read_inbox...")
    ctx = ToolContext()
    
    try:
        result = await gmail.call_tool("email_read_inbox", {
            "folder": "INBOX",
            "unread_only": False,
            "limit": 5
        }, ctx)
        
        print("─" * 40)
        print(result)
        print("─" * 40)
        
        if "ERROR" in result:
            print("❌ Read inbox failed")
        else:
            print("✅ Read inbox successful!")
            
    except Exception as e:
        print(f"❌ Exception: {e}")
    
    # Test send email (dry run - uncomment to actually send)
    print("\n5. Email send test (skipped - uncomment to test)")
    # result = await gmail.call_tool("email_send", {
    #     "to": "test@example.com",
    #     "subject": "Test from AI Orchestrator",
    #     "body": "This is a test email sent via the Gmail tool."
    # }, ctx)
    # print(result)
    
    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())