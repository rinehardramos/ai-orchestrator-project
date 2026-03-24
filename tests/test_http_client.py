import pytest
from src.tools_catalog.webhook.http_client import HttpClientTool, sanitize_output
from src.plugins.base import ToolContext


@pytest.fixture
def tool():
    t = HttpClientTool()
    t.initialize({})
    return t


def test_get_tool_schemas(tool):
    schemas = tool.get_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "http_request"


def test_sanitize_output():
    output = 'api_key=sk-1234567890abcdef&token=secret123'
    sanitized = sanitize_output(output)
    assert "sk-1234567890abcdef" not in sanitized
    assert "secret123" not in sanitized
    assert "***REDACTED***" in sanitized


def test_sanitize_password():
    output = '{"password": "mysecretpass", "data": "value"}'
    sanitized = sanitize_output(output)
    assert "mysecretpass" not in sanitized
    assert "***REDACTED***" in sanitized


@pytest.mark.asyncio
async def test_http_request_missing_url(tool):
    ctx = ToolContext()
    result = await tool.call_tool("http_request", {"method": "GET"}, ctx)
    assert "error" in result or "Error" in str(result)


@pytest.mark.asyncio
async def test_http_request_invalid_url(tool):
    ctx = ToolContext()
    result = await tool.call_tool("http_request", {
        "method": "GET",
        "url": "http://invalid.localhost.12345/test"
    }, ctx)
    assert "error" in result or result.get("status_code", 0) >= 400


@pytest.mark.asyncio
async def test_unknown_tool(tool):
    ctx = ToolContext()
    result = await tool.call_tool("unknown_tool", {}, ctx)
    assert "Unknown tool" in result
