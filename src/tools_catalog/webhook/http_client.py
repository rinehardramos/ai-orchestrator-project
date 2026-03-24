import httpx
from typing import Any, Dict, Optional
from src.plugins.base import Tool, ToolContext

MAX_BODY_SIZE = 50 * 1024


def sanitize_output(text: str) -> str:
    import re
    sanitized = re.sub(r'(api[_-]?key|token|secret|password|auth)["\']?\s*[:=]\s*["\']?[^\s"\'}\]]+', 
                       r'\1=***REDACTED***', text, flags=re.IGNORECASE)
    return sanitized


class HttpClientTool(Tool):
    type = "webhook"
    name = "http_client"
    description = "Make HTTP requests to external APIs and webhooks"
    node = "worker"

    def initialize(self, config: dict) -> None:
        self.config = config
        self.timeout = config.get("timeout_seconds", 30)

    def get_tool_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "http_request",
                    "description": "Make an HTTP request to a URL. Returns status code, headers, and body.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "method": {
                                "type": "string",
                                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                                "description": "HTTP method"
                            },
                            "url": {
                                "type": "string",
                                "description": "The URL to request"
                            },
                            "headers": {
                                "type": "object",
                                "description": "Optional request headers",
                                "additionalProperties": {"type": "string"}
                            },
                            "body": {
                                "type": "string",
                                "description": "Optional request body (for POST/PUT/PATCH)"
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Timeout in seconds (default: 30)"
                            }
                        },
                        "required": ["method", "url"]
                    }
                }
            }
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext) -> Any:
        if tool_name != "http_request":
            return f"Unknown tool: {tool_name}"
        
        method = args.get("method", "GET").upper()
        url = args.get("url")
        headers = args.get("headers", {})
        body = args.get("body")
        timeout = args.get("timeout", self.timeout)
        
        if not url:
            return "Error: URL is required"
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                request_body = body
                if isinstance(body, str):
                    try:
                        import json
                        request_body = json.loads(body)
                    except json.JSONDecodeError:
                        pass
                
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=request_body if isinstance(request_body, dict) else None,
                    content=request_body if isinstance(request_body, str) else None
                )
                
                response_body = response.text
                if len(response_body) > MAX_BODY_SIZE:
                    response_body = response_body[:MAX_BODY_SIZE] + "\n... (truncated)"
                
                response_body = sanitize_output(response_body)
                
                return {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": response_body
                }
        except httpx.TimeoutException:
            return {"error": f"Request timed out after {timeout} seconds"}
        except httpx.RequestError as e:
            return {"error": f"Request failed: {str(e)}"}
        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}


tool_class = HttpClientTool
