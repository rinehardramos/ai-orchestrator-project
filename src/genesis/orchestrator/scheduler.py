"""
DEPRECATED: This module has been moved to src.control.orchestrator

This file is kept for backward compatibility and will be removed in a future version.
Use: from src.control.orchestrator.scheduler import TaskScheduler
"""

import warnings
warnings.warn(
    "src.genesis.orchestrator.scheduler is deprecated. Use src.control.orchestrator.scheduler instead.",
    DeprecationWarning,
    stacklevel=2
)

from src.control.orchestrator.scheduler import TaskScheduler

__all__ = ["TaskScheduler"]
