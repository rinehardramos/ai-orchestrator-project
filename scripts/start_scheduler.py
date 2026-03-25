#!/usr/bin/env python3
"""
Scheduler Daemon Startup Script

Starts the scheduled task daemon as a background process.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.control.scheduler.daemon import SchedulerDaemon, main


if __name__ == "__main__":
    asyncio.run(main())
