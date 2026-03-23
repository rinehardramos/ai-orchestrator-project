#!/usr/bin/env python3
import asyncio
import sys
import os

# Add src to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from src.genesis.main import main_async

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n👋 Genesis Node shutting down...")
        sys.exit(0)
