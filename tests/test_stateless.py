"""The server keeps nothing between requests.

State crosses calls as an explicit handle in the arguments, never as a session. These
tests hold the server to that: a handle minted on one connection resolves on another, the
tool list does not depend on who is asking or what they asked before, and the HTTP
endpoint mints no session for either protocol era.
"""

import json

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

URL = "https://modelcontextprotocol.io"


def _json_rpc_body(response: httpx.Response) -> dict:
    """The JSON-RPC body, whether it came back as JSON or as one SSE event."""
    if response.headers["content-type"].startswith("application/json"):
        return response.json()
    data = next(line for line in response.text.splitlines() if line.startswith("data: "))
    return json.loads(data[len("data: ") :])


async def test_a_handle_minted_on_one_connection_resolves_on_another(mcp):
    async with Client(mcp) as first:
        saved = (await first.call_tool("add_bookmark", {"url": URL})).structured_content
    async with Client(mcp) as second:
        fetched = (
            await second.call_tool("get_bookmark", {"bookmark_id": saved["bookmark_id"]})
        ).structured_content
    assert fetched == saved


async def test_the_tool_list_does_not_vary_per_connection(mcp):
    async with Client(mcp) as first:
        before = await first.list_tools()
        await first.call_tool("add_bookmark", {"url": URL})
        after = await first.list_tools()
    async with Client(mcp) as second:
        elsewhere = await second.list_tools()
    assert [t.model_dump() for t in before] == [t.model_dump() for t in after]
    assert [t.model_dump() for t in before] == [t.model_dump() for t in elsewhere]


async def test_over_http_two_clients_share_a_handle_and_no_session(live_server):
    async with Client(StreamableHttpTransport(live_server)) as first:
        assert first.session.protocol_version == "2026-07-28"
        saved = (await first.call_tool("add_bookmark", {"url": URL})).structured_content
    async with Client(StreamableHttpTransport(live_server)) as second:
        fetched = (
            await second.call_tool("get_bookmark", {"bookmark_id": saved["bookmark_id"]})
        ).structured_content
    assert fetched == saved


def test_a_2025_era_handshake_gets_no_session_either(live_server):
    """stateless_http=True: a client on the old era is answered without a session id,
    so it too can be served by any replica."""
    response = httpx.post(
        live_server,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-11-25",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "0"},
            },
        },
        timeout=5,
    )
    assert response.status_code == 200
    assert "mcp-session-id" not in {k.lower() for k in response.headers}


def test_a_2026_era_request_stands_alone(live_server):
    """One POST, no handshake, every piece of context inside the request."""
    response = httpx.post(
        live_server,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/list",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                    "io.modelcontextprotocol/clientInfo": {"name": "probe", "version": "0"},
                }
            },
        },
        timeout=5,
    )
    assert response.status_code == 200
    body = _json_rpc_body(response)
    names = sorted(t["name"] for t in body["result"]["tools"])
    assert names == [
        "add_bookmark",
        "archive_bookmark",
        "delete_bookmark",
        "get_bookmark",
        "list_bookmarks",
        "update_bookmark",
    ]
    assert "mcp-session-id" not in {k.lower() for k in response.headers}
