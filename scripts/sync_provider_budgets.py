#!/usr/bin/env python3
"""Sync actual usage from provider APIs to Redis.

This script fetches real usage data from OpenRouter, Google, and Anthropic APIs
and updates the Redis budget keys with accurate values.

Usage:
    python3 scripts/sync_provider_budgets.py [--provider openrouter|google|anthropic|all]
"""

import argparse
import os
import subprocess
import sys


def get_env_var(key: str) -> str:
    """Get environment variable from .env file."""
    env_path = ".env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"')
    return os.environ.get(key, "")


def sync_openrouter():
    """Sync OpenRouter usage from API to Redis."""
    api_key = get_env_var("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not found")
        return False
    
    import urllib.request
    import json
    
    # Get credits (total balance)
    credits_url = "https://openrouter.ai/api/v1/credits"
    key_url = "https://openrouter.ai/api/v1/key"
    
    try:
        # Fetch credits balance
        req = urllib.request.Request(credits_url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            credits_data = json.loads(resp.read().decode()).get("data", {})
            total_credits = credits_data.get("total_credits", 0)
            total_usage = credits_data.get("total_usage", 0)
            remaining = total_credits - total_usage
        
        # Fetch key info for monthly usage
        req2 = urllib.request.Request(key_url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req2, timeout=10) as resp:
            key_data = json.loads(resp.read().decode()).get("data", {})
            usage_monthly = key_data.get("usage_monthly", 0)
        
        print(f"OpenRouter API Response:")
        print(f"  Credits: ${total_credits:.2f}")
        print(f"  Total Usage: ${total_usage:.2f}")
        print(f"  Remaining: ${remaining:.2f}")
        print(f"  Monthly Usage: ${usage_monthly:.4f}")
        
        # Update Redis
        subprocess.run([
            "docker", "exec", "redis", "redis-cli", "SET",
            "budget:provider:openrouter:limit", str(total_credits)
        ], check=True)
        subprocess.run([
            "docker", "exec", "redis", "redis-cli", "SET",
            "budget:provider:openrouter:spent", str(total_usage)
        ], check=True)
        subprocess.run([
            "docker", "exec", "redis", "redis-cli", "SET",
            "budget:provider:openrouter:remaining", str(remaining)
        ], check=True)
        subprocess.run([
            "docker", "exec", "redis", "redis-cli", "SET",
            "budget:provider:openrouter:usage_monthly", str(usage_monthly)
        ], check=True)
        
        pct = (total_usage / total_credits * 100) if total_credits > 0 else 0
        status = "✅" if pct < 80 else "⚠️" if pct < 100 else "🔴"
        summary = f"{status} OpenRouter: ${remaining:.2f} remaining ({pct:.1f}% used of ${total_credits:.0f})"
        
        subprocess.run([
            "docker", "exec", "redis", "redis-cli", "SET",
            "budget:last_summary", summary
        ], check=True)
        
        print(f"\nSynced to Redis: {summary}")
        return True
        
    except Exception as e:
        print(f"ERROR: Failed to sync OpenRouter: {e}")
        return False


def sync_google():
    """Sync Google usage - currently placeholder as Google doesn't have a usage API."""
    print("Google: No usage API available. Budget tracking is app-side only.")
    
    try:
        result = subprocess.run([
            "docker", "exec", "redis", "redis-cli", "GET",
            "budget:provider:google:spent"
        ], capture_output=True, text=True)
        spent = float(result.stdout.strip() or 0)
        
        result = subprocess.run([
            "docker", "exec", "redis", "redis-cli", "GET",
            "budget:provider:google:limit"
        ], capture_output=True, text=True)
        limit = float(result.stdout.strip() or 10.0)
        
        remaining = limit - spent
        pct = (spent / limit * 100) if limit > 0 else 0
        status = "OK" if pct < 80 else "WARNING" if pct < 100 else "EXCEEDED"
        
        print(f"Google (app-tracked): ${spent:.4f} spent | ${remaining:.2f} remaining ({pct:.1f}% used)")
        return True
    except Exception as e:
        print(f"ERROR: Failed to get Google budget: {e}")
        return False


def sync_anthropic():
    """Sync Anthropic usage - currently placeholder."""
    print("Anthropic: No usage API available. Budget tracking is app-side only.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Sync provider budgets to Redis")
    parser.add_argument("--provider", choices=["openrouter", "google", "anthropic", "all"],
                        default="all", help="Provider to sync")
    args = parser.parse_args()
    
    print(f"Syncing budgets for: {args.provider}\n")
    
    if args.provider in ("openrouter", "all"):
        sync_openrouter()
        print()
    
    if args.provider in ("google", "all"):
        sync_google()
        print()
    
    if args.provider in ("anthropic", "all"):
        sync_anthropic()
        print()
    
    print("Done.")


if __name__ == "__main__":
    main()
