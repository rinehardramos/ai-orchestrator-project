"""
DEPRECATED: This module has been moved to src.control.orchestrator

This file is kept for backward compatibility and will be removed in a future version.
Use: from src.control.orchestrator.telegram_monitor import TelegramMonitor
"""

import warnings
warnings.warn(
    "src.genesis.orchestrator.telegram_monitor is deprecated. Use src.control.orchestrator.telegram_monitor instead.",
    DeprecationWarning,
    stacklevel=2
)

from src.control.orchestrator.telegram_monitor import TelegramMonitor

__all__ = ["TelegramMonitor"]
