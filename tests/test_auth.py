"""Tokens are bound to this server's URL; a handle is a name, not a capability.

The server is an OAuth protected resource. It publishes its metadata, points an
unauthenticated caller at it with 401, and accepts a token only when `aud` names its own
URL exactly. Once a caller is known, every bookmark is theirs or invisible: another
owner's handle gets the very same refusal as a handle that was never minted.
"""

import json
import time

import httpx
import jwt
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth.providers.jwt import RSAKeyPair

from mcp_bookmarks.config import Settings

PUBLIC_URL = "https://bookmarks.example.com"
RESOURCE = f"{PUBLIC_URL}/mcp"
ISSUER = "https://issuer.example.com"
URL = "https://modelcontextprotocol.io"


@pytest.fixture(scope="module")
def keys() -> RSAKeyPair:
    return RSAKeyPair.generate()


@pytest.fixture
def settings(db_path, tmp_path, keys) -> Settings:
    """Authentication on, keyed by a public key written to disk, as production would be."""
    key_file = tmp_path / "public.pem"
    key_file.write_text(keys.public_key)
    return Settings(
        db_path=db_path,
        public_url=PUBLIC_URL,
        issuer=ISSUER,
        public_key_file=str(key_file),
    )


def token(keys: RSAKeyPair, subject: str = "alice", audience: str | list[str] = RESOURCE) -> str:
    return keys.create_token(subject=subject, issuer=ISSUER, audience=audience)


def post_tools_list(url: str, bearer: str | None) -> httpx.Response:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": "tools/list",
    }
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    return httpx.post(
        url,
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
            },
        },
        timeout=5,
    )


def test_protected_resource_metadata_names_this_server(live_server):
    origin = live_server.removesuffix("/mcp")
    response = httpx.get(f"{origin}/.well-known/oauth-protected-resource/mcp", timeout=5)
    assert response.status_code == 200
    document = response.json()
    assert document["resource"] == RESOURCE
    # pydantic's AnyHttpUrl prints an origin with a trailing slash; the issuer is what matters.
    assert document["authorization_servers"] == [ISSUER + "/"]
    assert document["bearer_methods_supported"] == ["header"]


def test_no_token_is_401_with_a_pointer_to_the_metadata(live_server):
    response = post_tools_list(live_server, None)
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert f'resource_metadata="{PUBLIC_URL}/.well-known/oauth-protected-resource/mcp"' in challenge


@pytest.mark.parametrize(
    "audience",
    [
        PUBLIC_URL,  # the bare origin
        RESOURCE + "/",  # a trailing slash
        "https://other.example.com/mcp",  # another server
        "bookmarks-client",  # the client itself
    ],
    ids=["origin", "trailing-slash", "other-server", "client-id"],
)
def test_a_token_for_anything_but_this_url_is_refused(live_server, keys, audience):
    response = post_tools_list(live_server, token(keys, audience=audience))
    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["www-authenticate"]


def test_a_token_with_no_subject_is_refused(live_server, keys):
    """A valid signature and the right audience, but nobody's: the verifier would file it
    under its client_id fallback, so the door refuses it."""
    now = int(time.time())
    anonymous_token = jwt.encode(
        {"iss": ISSUER, "aud": RESOURCE, "iat": now, "exp": now + 600, "client_id": "cli"},
        keys.private_key.get_secret_value(),
        algorithm="RS256",
    )
    response = post_tools_list(live_server, anonymous_token)
    assert response.status_code == 401


def test_a_token_for_this_url_is_accepted(live_server, keys):
    response = post_tools_list(live_server, token(keys))
    assert response.status_code == 200


def test_the_url_may_be_one_of_several_audiences(live_server, keys):
    response = post_tools_list(live_server, token(keys, audience=[RESOURCE, "https://x.example"]))
    assert response.status_code == 200


async def test_another_owners_handle_is_answered_like_an_unknown_one(live_server, keys):
    async with Client(StreamableHttpTransport(live_server, auth=token(keys, "alice"))) as alice:
        saved = (await alice.call_tool("add_bookmark", {"url": URL})).structured_content
    handle = saved["bookmark_id"]

    async with Client(StreamableHttpTransport(live_server, auth=token(keys, "bob"))) as bob:
        foreign = await bob.call_tool_mcp("get_bookmark", {"bookmark_id": handle})
        unknown = await bob.call_tool_mcp("get_bookmark", {"bookmark_id": "bm_" + "0" * 32})
        listed = (await bob.call_tool("list_bookmarks", {})).structured_content
        deleted = await bob.call_tool_mcp("delete_bookmark", {"bookmark_id": handle})

    def envelope(result) -> str:
        body = result.model_dump(by_alias=True, exclude_none=True, exclude={"meta"})
        body["structuredContent"]["error"]["message"] = "<id>"
        body["content"] = [{"type": "text"}]
        return json.dumps(body, sort_keys=True)

    assert foreign.is_error is True
    assert envelope(foreign) == envelope(unknown)
    assert listed["items"] == []
    assert deleted.is_error is True

    async with Client(StreamableHttpTransport(live_server, auth=token(keys, "alice"))) as alice:
        still = (await alice.call_tool("get_bookmark", {"bookmark_id": handle})).structured_content
    assert still == saved


async def test_each_owner_sees_only_their_own_list(live_server, keys):
    async with Client(StreamableHttpTransport(live_server, auth=token(keys, "alice"))) as alice:
        await alice.call_tool("add_bookmark", {"url": URL + "/a"})
    async with Client(StreamableHttpTransport(live_server, auth=token(keys, "bob"))) as bob:
        await bob.call_tool("add_bookmark", {"url": URL + "/b"})
        page = (await bob.call_tool("list_bookmarks", {})).structured_content
    assert [b["url"] for b in page["items"]] == [URL + "/b"]
