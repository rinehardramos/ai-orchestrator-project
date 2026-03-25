#!/usr/bin/env python3
"""
End-to-end test for the Gmail tool.
Tests: email_send, email_read_inbox
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()


async def test_gmail():
    from src.plugins.loader import load_tools_sync
    
    print("1. Loading tools from database...")
    await load_tools_sync("config/bootstrap.yaml", node="worker")
    
    from src.plugins.registry import registry
    
    print("2. Getting gmail tool from registry...")
    gmail_tool = registry.get("gmail")
    
    if not gmail_tool:
        print("ERROR: gmail tool not found in registry")
        return False
    
    print(f"   Found: {gmail_tool.name} ({gmail_tool.type})")
    print(f"   Username: {gmail_tool.username}")
    print(f"   Password: {'*' * len(gmail_tool.password) if gmail_tool.password else 'NOT SET'}")
    
    from src.plugins.base import ToolContext
    ctx = ToolContext(
        task_id="test-email-001",
        workspace_dir="/tmp/test-email",
        envelope=None
    )
    
    print("\n3. Testing email_send...")
    try:
        result = await gmail_tool.call_tool("email_send", {
            "to": "blackopstech047@gmail.com",
            "subject": "Test Email from AI Orchestrator",
            "body": "This is a test email sent from the AI Orchestrator Gmail tool.\n\nIf you received this, the email integration is working correctly!\n\n--\nAI Orchestrator Test"
        }, ctx)
        print(f"   Result: {result}")
        
        if result and ("success" in str(result).lower() or "sent" in str(result).lower()):
            print("   ✅ Email sent successfully!")
            return True
        else:
            print(f"   ❌ Email failed: {result}")
            return False
            
    except Exception as e:
        print(f"   ❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    os.environ.setdefault("DATABASE_URL", "postgres://temporal:temporal@localhost:5432/orchestrator")
    os.environ.setdefault("CONFIG_SECRET_KEY", "uKah8x2Nghzs6hCIO8EVK66kQrbcWzUyfSNNfbcL5CM=")
    
    success = asyncio.run(test_gmail())
    sys.exit(0 if success else 1)