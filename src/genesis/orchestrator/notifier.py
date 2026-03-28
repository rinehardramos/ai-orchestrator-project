"""
DEPRECATED: This module has been moved to src.control.orchestrator

This file is kept for backward compatibility and will be removed in a future version.
Use: from src.control.orchestrator.notifier import TelegramNotifier
"""

import warnings
warnings.warn(
    "src.genesis.orchestrator.notifier is deprecated. Use src.control.orchestrator.notifier instead.",
    DeprecationWarning,
    stacklevel=2
)

from src.control.orchestrator.notifier import TelegramNotifier

__all__ = ["TelegramNotifier"]
