"""A tool's own failure is a result the model can read, not a protocol error.

A refusal comes back as `isError: true` with the same envelope in `structuredContent` and
in the text block: a code for software, a message saying what was wrong, and a next step.
It is returned, never raised: raising `ToolError` keeps the message and drops the
structured body, which the last test shows on a throwaway server.
"""

import json

import jsonschema
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from mcp_bookmarks.errors import BAD_INPUT, NOT_FOUND
from mcp_bookmarks.store import Store

UNKNOWN = "bm_" + "f" * 32
HANDLE_TOOLS = ("get_bookmark", "update_bookmark", "archive_bookmark", "delete_bookmark")


async def test_a_refusal_is_a_result_with_its_envelope_in_both_places(client):
    raw = await client.call_tool_mcp("get_bookmark", {"bookmark_id": UNKNOWN})
    assert raw.is_error is True
    assert raw.structured_content == {
        "error": {
            "code": NOT_FOUND,
            "message": f"No bookmark {UNKNOWN}.",
            "next_step": (
                "Call list_bookmarks to see what exists, then retry with a bookmark_id "
                "from the list."
            ),
        }
    }
    assert [block.type for block in raw.content] == ["text"]
    assert json.loads(raw.content[0].text) == raw.structured_content


async def test_every_handle_tool_refuses_an_unknown_handle_the_same_way(client):
    envelopes = set()
    for name in HANDLE_TOOLS:
        result = await client.call_tool(name, {"bookmark_id": UNKNOWN}, raise_on_error=False)
        assert result.is_error is True, name
        envelopes.add(json.dumps(result.structured_content, sort_keys=True))
    assert len(envelopes) == 1, "the same refusal, whichever tool met it"


async def test_a_malformed_handle_is_bad_input_not_not_found(client):
    for name in HANDLE_TOOLS:
        result = await client.call_tool(name, {"bookmark_id": "nope"}, raise_on_error=False)
        assert result.structured_content["error"]["code"] == BAD_INPUT, name
        assert "bm_" in result.structured_content["error"]["next_step"], name


async def test_a_bad_url_is_refused_before_anything_is_written(client):
    result = await client.call_tool(
        "add_bookmark", {"url": "javascript:alert(1)"}, raise_on_error=False
    )
    assert result.structured_content["error"]["code"] == BAD_INPUT
    page = (await client.call_tool("list_bookmarks", {})).structured_content
    assert page["items"] == []


async def test_the_default_client_still_raises_on_a_refusal(client):
    """A client that wants an exception gets one; the envelope is still on the wire for
    the one that does not."""
    with pytest.raises(ToolError, match=NOT_FOUND):
        await client.call_tool("get_bookmark", {"bookmark_id": UNKNOWN})


async def test_every_tool_still_advertises_an_output_schema(client):
    """Returning `Model | ToolResult` would silently drop the derived schema; each tool
    declares its shape instead, and this pins that."""
    for tool in await client.list_tools():
        assert tool.output_schema is not None, tool.name
        assert tool.output_schema.get("type") == "object", tool.name


async def test_both_a_success_and_a_refusal_conform_to_the_declared_schema(client):
    """The spec holds every structuredContent to the outputSchema, error results included,
    and strict clients enforce it. The declared schema admits both shapes."""
    schemas = {tool.name: tool.output_schema for tool in await client.list_tools()}
    saved = await client.call_tool_mcp("add_bookmark", {"url": "https://example.com"})
    refused = await client.call_tool_mcp("get_bookmark", {"bookmark_id": UNKNOWN})
    jsonschema.validate(saved.structured_content, schemas["add_bookmark"])
    jsonschema.validate(refused.structured_content, schemas["get_bookmark"])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"error": {"code": "x"}}, schemas["get_bookmark"])


async def test_why_refusals_are_returned_not_raised():
    """On a throwaway server: `raise ToolError` keeps the message and drops the body."""
    throwaway = FastMCP("throwaway")

    @throwaway.tool
    def raises() -> dict:
        raise ToolError("No bookmark bm_0.")

    async with Client(throwaway) as c:
        raw = await c.call_tool_mcp("raises", {})
    assert raw.is_error is True
    assert raw.content[0].text == "No bookmark bm_0."
    assert raw.structured_content is None


async def test_this_server_does_not_leak_a_crash_either(client, monkeypatch):
    """The real server, with its store made to fail: the text names no internals."""
    monkeypatch.setattr(
        Store, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database is locked"))
    )
    raw = await client.call_tool_mcp("get_bookmark", {"bookmark_id": UNKNOWN})
    assert raw.is_error is True
    assert "database is locked" not in raw.content[0].text
    assert raw.structured_content is None


async def test_an_unexpected_exception_does_not_leak_its_text():
    """The crash channel: still an isError result, but the server's internals stay home."""
    throwaway = FastMCP("throwaway", mask_error_details=True)

    @throwaway.tool
    def crashes() -> dict:
        raise RuntimeError("sqlite3.OperationalError: database is locked at /data/x.db")

    async with Client(throwaway) as c:
        raw = await c.call_tool_mcp("crashes", {})
    assert raw.is_error is True
    assert "database is locked" not in raw.content[0].text
