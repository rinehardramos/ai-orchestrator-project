import pytest
from src.tools_catalog.email.gmail import GmailTool
from src.plugins.base import ToolContext


@pytest.fixture
def tool():
    t = GmailTool()
    t.initialize({
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "encryption": "tls",
        "username": "test@gmail.com",
        "password": "test-app-password"
    })
    return t


@pytest.fixture
def tool_no_creds():
    t = GmailTool()
    t.initialize({})
    return t


def test_tool_attributes(tool):
    assert tool.type == "email"
    assert tool.name == "gmail"
    assert tool.node == "worker"


def test_get_tool_schemas(tool):
    schemas = tool.get_tool_schemas()
    assert len(schemas) == 5
    
    names = [s["function"]["name"] for s in schemas]
    assert "email_send" in names
    assert "email_read_inbox" in names
    assert "email_search" in names
    assert "email_get" in names
    assert "email_delete" in names


def test_email_send_schema(tool):
    schemas = tool.get_tool_schemas()
    send_schema = next(s for s in schemas if s["function"]["name"] == "email_send")
    params = send_schema["function"]["parameters"]
    
    assert "to" in params["properties"]
    assert "subject" in params["properties"]
    assert "body" in params["properties"]
    assert params["required"] == ["to", "subject", "body"]


def test_email_read_inbox_schema(tool):
    schemas = tool.get_tool_schemas()
    read_schema = next(s for s in schemas if s["function"]["name"] == "email_read_inbox")
    params = read_schema["function"]["parameters"]
    
    assert "folder" in params["properties"]
    assert "unread_only" in params["properties"]
    assert "limit" in params["properties"]
    assert params["properties"]["folder"]["default"] == "INBOX"


def test_initialize(tool):
    assert tool.imap_host == "imap.gmail.com"
    assert tool.smtp_host == "smtp.gmail.com"
    assert tool.username == "test@gmail.com"
    assert tool.password == "test-app-password"


def test_send_without_credentials(tool_no_creds):
    ctx = ToolContext()
    result = tool_no_creds._send("test@example.com", "Test", "Body")
    assert "ERROR" in result
    assert "credentials not configured" in result


def test_read_inbox_without_credentials(tool_no_creds):
    result = tool_no_creds._read_inbox()
    assert "ERROR" in result
    assert "credentials not configured" in result


def test_search_without_credentials(tool_no_creds):
    result = tool_no_creds._search("from:test@example.com")
    assert "ERROR" in result
    assert "credentials not configured" in result


def test_get_email_without_credentials(tool_no_creds):
    result = tool_no_creds._get_email("123")
    assert "ERROR" in result
    assert "credentials not configured" in result


def test_delete_email_without_credentials(tool_no_creds):
    result = tool_no_creds._delete_email("123")
    assert "ERROR" in result
    assert "credentials not configured" in result


def test_format_empty_email_list(tool):
    result = tool._format_email_list([])
    assert "No emails found" in result


def test_format_email_list(tool):
    emails = [
        {"id": "1", "from": "sender@example.com", "subject": "Test", "date": "2024-01-01"}
    ]
    result = tool._format_email_list(emails)
    assert "Found 1 email" in result
    assert "sender@example.com" in result
    assert "Test" in result


@pytest.mark.asyncio
async def test_call_tool_unknown(tool):
    ctx = ToolContext()
    result = await tool.call_tool("unknown_tool", {}, ctx)
    assert "Unknown tool" in result


@pytest.mark.asyncio
async def test_call_tool_send(tool_no_creds):
    ctx = ToolContext()
    result = await tool_no_creds.call_tool("email_send", {
        "to": "test@example.com",
        "subject": "Test",
        "body": "Test body"
    }, ctx)
    assert "ERROR" in result
