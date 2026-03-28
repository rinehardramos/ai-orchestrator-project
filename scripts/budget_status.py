#!/usr/bin/env python3
"""Query budget status from Redis. Can be called from any process."""

import subprocess
import sys

def get_budget_status():
    """Get budget status from Redis via docker exec."""
    try:
        # Get OpenRouter balance from synced data
        result = subprocess.run(
            ["docker", "exec", "redis", "redis-cli", "GET", "budget:provider:openrouter:remaining"],
            capture_output=True, text=True, timeout=5
        )
        remaining = float(result.stdout.strip() or 0)
        
        result = subprocess.run(
            ["docker", "exec", "redis", "redis-cli", "GET", "budget:provider:openrouter:spent"],
            capture_output=True, text=True, timeout=5
        )
        spent = float(result.stdout.strip() or 0)
        
        result = subprocess.run(
            ["docker", "exec", "redis", "redis-cli", "GET", "budget:provider:openrouter:limit"],
            capture_output=True, text=True, timeout=5
        )
        limit = float(result.stdout.strip() or 0)
        
        lines = []
        
        if limit > 0:
            pct = (spent / limit * 100) if limit > 0 else 0
            status = '✅' if pct < 80 else '⚠️' if pct < 100 else '🔴'
            lines.append(f"{status} OpenRouter: ${remaining:.2f} remaining | ${spent:.2f} spent ({pct:.1f}% of ${limit:.0f})")
        
        # Google (app-tracked)
        result = subprocess.run(
            ["docker", "exec", "redis", "redis-cli", "GET", "budget:provider:google:spent"],
            capture_output=True, text=True, timeout=5
        )
        google_spent = float(result.stdout.strip() or 0)
        if google_spent > 0:
            result = subprocess.run(
                ["docker", "exec", "redis", "redis-cli", "GET", "budget:provider:google:limit"],
                capture_output=True, text=True, timeout=5
            )
            google_limit = float(result.stdout.strip() or 10)
            google_remaining = google_limit - google_spent
            google_pct = (google_spent / google_limit * 100) if google_limit > 0 else 0
            status = '✅' if google_pct < 80 else '⚠️'
            lines.append(f"{status} Google (tracked): ${google_spent:.4f} spent of ${google_limit:.0f}")
        
        return '\n'.join(lines) if lines else "No budget data found"
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    print(get_budget_status())
