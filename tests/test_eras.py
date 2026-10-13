"""One server, two protocol eras, the same surface.

FastMCP 4 answers a 2026-07-28 request as a self-contained POST and a 2025-era client's
`initialize` handshake from the same process, with nothing for the server to choose. These
tests hold what the server advertises and returns to be identical on both, and hold a
handle minted on one era to resolve on the other. The `client` fixture already runs every
tool test on both eras; what is here is the comparison between them.
"""

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from tests.conftest import ERAS

URL = "https://modelcontextprotocol.io"
UNKNOWN = "bm_" + "0" * 32


async def surface(mcp, mode: str) -> dict:
    async with Client(mcp, mode=mode) as c:
        tools = await c.list_tools()
        refusal = await c.call_tool_mcp("get_bookmark", {"bookmark_id": UNKNOWN})
    return {
        "tools": [t.model_dump(exclude_none=True) for t in tools],
        # Result `_meta` is the one field that differs by design: the SDK stamps
        # `io.modelcontextprotocol/serverInfo` into every 2026-07-28 result and nothing
        # into a 2025-era one, so it is left out of the comparison.
        "refusal": refusal.model_dump(exclude_none=True, exclude={"meta"}),
    }


async def test_both_eras_advertise_the_same_tools_and_refuse_the_same_way(mcp):
    modern = await surface(mcp, ERAS["2026-07-28"])
    legacy = await surface(mcp, ERAS["2025-11-25"])
    assert modern["tools"] == legacy["tools"]
    assert modern["refusal"] == legacy["refusal"]


@pytest.mark.parametrize(
    ("minted_on", "read_on"),
    [("2026-07-28", "2025-11-25"), ("2025-11-25", "2026-07-28")],
    ids=["modern-to-legacy", "legacy-to-modern"],
)
async def test_a_handle_minted_on_one_era_resolves_on_the_other(live_server, minted_on, read_on):
    async with Client(StreamableHttpTransport(live_server), mode=ERAS[minted_on]) as first:
        assert first.protocol_version == minted_on
        saved = (await first.call_tool("add_bookmark", {"url": URL})).structured_content
    async with Client(StreamableHttpTransport(live_server), mode=ERAS[read_on]) as second:
        assert second.protocol_version == read_on
        fetched = (
            await second.call_tool("get_bookmark", {"bookmark_id": saved["bookmark_id"]})
        ).structured_content
    assert fetched == saved


def test_a_version_the_server_does_not_speak_is_refused_naming_the_modern_ones(live_server):
    """A client that guesses wrong learns the answer from the error, not from a 500. The
    list names the modern versions; the handshake era the server also answers is reached by
    `initialize`, not by this list."""
    response = httpx.post(
        live_server,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2027-01-01",
            "Mcp-Method": "tools/list",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2027-01-01",
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
            },
        },
        timeout=5,
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == -32022
    assert "2026-07-28" in error["data"]["supported"]
