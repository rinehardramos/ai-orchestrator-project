#!/usr/bin/env python3
"""
MCP Server: Budget Tracker

Provides budget tracking tools to OpenCode via Model Context Protocol.
Queries Redis for real-time budget status and LiteLLM for per-request usage.

Tools:
  - get_budget_status: Get current budget status for all providers
  - get_openrouter_balance: Get OpenRouter credits from API
  - sync_budget: Sync actual usage from provider APIs to Redis
  - get_usage_history: Get recent usage from LiteLLM logs
"""

import json
import sys
import subprocess
import urllib.request
import os
from typing import Any
from datetime import datetime

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))


def redis_cmd(cmd: str) -> str:
    """Execute redis-cli command and return result."""
    try:
        result = subprocess.run(
            ["docker", "exec", "redis", "redis-cli"] + cmd.split(),
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception as e:
        return f"error: {e}"


def get_budget_status() -> str:
    """Get budget status formatted as human-readable string."""
    lines = []
    lines.append("=" * 50)
    lines.append("BUDGET STATUS")
    lines.append("=" * 50)
    
    providers = [
        ("openrouter", "OpenRouter"),
        ("google", "Google"),
        ("anthropic", "Anthropic")
    ]
    
    for provider_key, provider_name in providers:
        try:
            spent = float(redis_cmd(f"GET budget:provider:{provider_key}:spent") or 0)
            limit = float(redis_cmd(f"GET budget:provider:{provider_key}:limit") or 0)
            
            if limit > 0 or spent > 0:
                remaining = limit - spent if limit > 0 else None
                pct = (spent / limit * 100) if limit > 0 else 0
                
                if pct >= 100:
                    status = "EXCEEDED"
                elif pct >= 80:
                    status = "WARNING"
                else:
                    status = "OK"
                
                lines.append(f"\n{provider_name}:")
                lines.append(f"  Status: {status}")
                lines.append(f"  Spent: ${spent:.2f}")
                if limit > 0:
                    lines.append(f"  Limit: ${limit:.2f}")
                    lines.append(f"  Remaining: ${remaining:.2f}")
                    lines.append(f"  Usage: {pct:.1f}%")
        except Exception as e:
            lines.append(f"\n{provider_name}: Error - {e}")
    
    return "\n".join(lines)


def get_usage_history(hours: int = 24, limit: int = 10) -> str:
    """Get recent usage from LiteLLM database."""
    try:
        result = subprocess.run(
            [
                "docker", "exec", "postgres-litellm", "psql", "-U", "litellm", "-d", "litellm", "-t", "-A", "-F", "|",
                "-c", f'''
                SELECT model, prompt_tokens, completion_tokens, spend, "startTime"
                FROM "LiteLLM_SpendLogs"
                WHERE "startTime" > NOW() - INTERVAL '{hours} hours'
                ORDER BY "startTime" DESC
                LIMIT {limit};
                '''
            ],
            capture_output=True, text=True, timeout=10
        )
        
        rows = result.stdout.strip().split("\n")
        if not rows or rows[0] == "":
            return f"No usage in the last {hours} hours"
        
        lines = []
        lines.append("=" * 70)
        lines.append(f"USAGE HISTORY (Last {hours} hours)")
        lines.append("=" * 70)
        lines.append(f"{'Model':<30} {'Prompt':>8} {'Output':>8} {'Cost':>10} {'Time':>12}")
        lines.append("-" * 70)
        
        total_prompt = 0
        total_completion = 0
        total_cost = 0.0
        
        for row in rows:
            parts = row.split("|")
            if len(parts) >= 5:
                model = parts[0][:28]
                prompt = int(float(parts[1] or 0))
                completion = int(float(parts[2] or 0))
                cost = float(parts[3] or 0)
                time_str = parts[4][11:16] if len(parts[4]) > 11 else parts[4]
                
                total_prompt += prompt
                total_completion += completion
                total_cost += cost
                
                lines.append(f"{model:<30} {prompt:>8} {completion:>8} ${cost:>9.6f} {time_str:>12}")
        
        lines.append("-" * 70)
        lines.append(f"{'TOTAL':<30} {total_prompt:>8} {total_completion:>8} ${total_cost:>9.6f}")
        
        return "\n".join(lines)
    except Exception as e:
        return f"Error querying LiteLLM: {e}"


def get_openrouter_credits() -> dict:
    """Fetch OpenRouter credits from API."""
    env_path = ".env"
    api_key = None
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("OPENROUTER_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"')
                    break
    
    if not api_key:
        return {"error": "OPENROUTER_API_KEY not found"}
    
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - URL is hardcoded HTTPS endpoint, not user-supplied
            data = json.loads(resp.read().decode())
            d = data.get("data", {})
            return {
                "total_credits": d.get("total_credits", 0),
                "total_usage": round(d.get("total_usage", 0), 2),
                "remaining": round(d.get("total_credits", 0) - d.get("total_usage", 0), 2)
            }
    except Exception as e:
        return {"error": str(e)}


def sync_budget() -> dict:
    """Sync budget from provider APIs to Redis."""
    result = {"openrouter": None, "google": "app-tracked only"}
    
    credits = get_openrouter_credits()
    if "error" not in credits:
        total_credits = credits.get("total_credits", 0)
        total_usage = credits.get("total_usage", 0)
        remaining = credits.get("remaining", 0)
        
        redis_cmd(f"SET budget:provider:openrouter:limit {total_credits}")
        redis_cmd(f"SET budget:provider:openrouter:spent {total_usage}")
        redis_cmd(f"SET budget:provider:openrouter:remaining {remaining}")
        
        result["openrouter"] = {
            "synced": True,
            "credits": total_credits,
            "usage": total_usage,
            "remaining": remaining
        }
    else:
        result["openrouter"] = {"synced": False, "error": credits["error"]}
    
    return result


# MCP Protocol Implementation
def send_response(request_id: Any, result: Any):
    """Send JSON-RPC response."""
    response = {"jsonrpc": "2.0", "id": request_id, "result": result}
    print(json.dumps(response), flush=True)


def send_error(request_id: Any, code: int, message: str):
    """Send JSON-RPC error."""
    response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    print(json.dumps(response), flush=True)


def list_tools() -> list:
    """Return list of available tools."""
    return [
        {
            "name": "get_budget_status",
            "description": "Get current budget status for all providers (OpenRouter, Google, Anthropic). Returns human-readable formatted string.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "get_openrouter_balance",
            "description": "Fetch current OpenRouter credits balance directly from the API. Shows total credits, usage, and remaining balance.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "sync_budget",
            "description": "Sync budget data from provider APIs (OpenRouter) to Redis cache. Call this to refresh budget data.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "get_usage_history",
            "description": "Get recent usage history from LiteLLM logs. Shows per-request tokens and costs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "hours": {"type": "number", "description": "Hours to look back (default 24)"},
                    "limit": {"type": "number", "description": "Max number of records (default 10)"}
                }
            }
        }
    ]


def handle_tool_call(name: str, args: dict) -> Any:
    """Handle tool execution."""
    if name == "get_budget_status":
        return get_budget_status()
    elif name == "get_openrouter_balance":
        return get_openrouter_credits()
    elif name == "sync_budget":
        return sync_budget()
    elif name == "get_usage_history":
        hours = args.get("hours", 24)
        limit = args.get("limit", 10)
        return get_usage_history(hours, limit)
    else:
        raise ValueError(f"Unknown tool: {name}")


def main():
    """Main MCP server loop."""
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})
        
        if method == "initialize":
            send_response(request_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "budget-tracker", "version": "1.0.0"}
            })
        elif method == "notifications/initialized":
            pass  # No response needed
        elif method == "tools/list":
            send_response(request_id, {"tools": list_tools()})
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            try:
                result = handle_tool_call(tool_name, tool_args)
                send_response(request_id, {"content": [{"type": "text", "text": str(result)}]})
            except Exception as e:
                send_error(request_id, -32000, str(e))
        elif method == "ping":
            send_response(request_id, {})


if __name__ == "__main__":
    main()