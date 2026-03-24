import pytest
from src.plugins.mcp_bridge import MCPBridgeTool
from src.plugins.base import ToolContext


@pytest.fixture
def tool():
    t = MCPBridgeTool()
    t.initialize({
        "transport": "stdio",
        "command": "echo test"
    })
    return t


def test_tool_attributes(tool):
    assert tool.type == "mcp"
    assert tool.name == "mcp_bridge"
    assert tool.node == "worker"


def test_get_tool_schemas_returns_list(tool):
    tool._tools_cache = []
    schemas = tool.get_tool_schemas()
    assert isinstance(schemas, list)


def test_initialize_config(tool):
    assert tool.transport == "stdio"
    assert tool.command == "echo test"


@pytest.fixture
def http_tool():
    t = MCPBridgeTool()
    t.initialize({
        "transport": "http",
        "url": "http://localhost:8080/mcp"
    })
    return t


def test_http_transport_config(http_tool):
    assert http_tool.transport == "http"
    assert http_tool.url == "http://localhost:8080/mcp"


@pytest.mark.asyncio
async def test_call_tool_with_mocked_process():
    t = MCPBridgeTool()
    t.initialize({"transport": "stdio", "command": "fake"})
    t._initialized = True
    t._tools_cache = []
    
    import json
    mock_response = {"result": {"content": [{"type": "text", "text": "test output"}]}}
    
    import unittest.mock as mock
    with mock.patch.object(t, '_send_jsonrpc', return_value=mock_response):
        ctx = ToolContext()
        result = await t.call_tool("test_tool", {}, ctx)
        assert "test output" in result


@pytest.mark.asyncio
async def test_call_tool_error_response():
    t = MCPBridgeTool()
    t.initialize({"transport": "stdio", "command": "fake"})
    t._initialized = True
    t._tools_cache = []
    
    mock_response = {"error": {"message": "Tool not found"}}
    
    import unittest.mock as mock
    with mock.patch.object(t, '_send_jsonrpc', return_value=mock_response):
        ctx = ToolContext()
        result = await t.call_tool("test_tool", {}, ctx)
        assert "MCP Error" in result
