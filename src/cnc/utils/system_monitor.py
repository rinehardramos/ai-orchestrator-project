import psutil
import logging
import os
import json
from datetime import datetime

class SystemMonitor:
    def __init__(self, threshold_percent=90.0, state_file="data/last_state.json"):
        self.threshold = threshold_percent
        self.state_file = state_file
        self.logger = logging.getLogger("SystemMonitor")
        # Ensure data directory exists
        os.makedirs(os.path.dirname(os.path.abspath(self.state_file)), exist_ok=True)

    def get_memory_stats(self):
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "percent": mem.percent
        }

    def is_crash_imminent(self):
        return psutil.virtual_memory().percent > self.threshold

    def save_state(self, state_data):
        """Persists the current CLI state to disk."""
        try:
            payload = {
                "timestamp": datetime.now().isoformat(),
                "memory_percent": psutil.virtual_memory().percent,
                "state": state_data
            }
            with open(self.state_file, 'w') as f:
                json.dump(payload, f, indent=4)
            return True
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")
            return False

    def free_memory(self, objects_with_caches=None):
        """
        Attempts to free memory by clearing known caches in the provided objects.
        'objects_with_caches' can be a list of objects like TaskScheduler or AnalyzerAgent.
        """
        freed_count = 0
        if not objects_with_caches:
            return freed_count

        for obj in objects_with_caches:
            # Clear TaskScheduler preflight_cache
            if hasattr(obj, 'preflight_cache') and isinstance(obj.preflight_cache, dict):
                freed_count += len(obj.preflight_cache)
                obj.preflight_cache.clear()
            
            # Clear AnalyzerAgent internal caches if any (placeholder)
            if hasattr(obj, 'cache') and isinstance(obj.cache, dict):
                freed_count += len(obj.cache)
                obj.cache.clear()

        return freed_count
