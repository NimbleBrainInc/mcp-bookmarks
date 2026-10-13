"""Pages by key, never by offset.

A walk returns every bookmark that existed when it began, and still matches, exactly
once, even while bookmarks are added and removed between pages. The cursor is opaque,
tagged with the listing it came from, refused as bad input when it is anything else, and
replayed by another owner it returns only that owner's rows.
"""

import base64
import json
import sqlite3
from contextlib import closing

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth.providers.jwt import RSAKeyPair

from mcp_bookmarks import paging
from mcp_bookmarks.config import Settings

URL = "https://example.com/"


async def seed(client, n: int, prefix: str = "") -> list[str]:
    handles = []
    for i in range(n):
        saved = (
            await client.call_tool("add_bookmark", {"url": f"{URL}{prefix}{i}"})
        ).structured_content
        handles.append(saved["bookmark_id"])
    return handles


async def walk(client, limit: int, **filters) -> list[list[str]]:
    """Every page's handles, following next_cursor to the end."""
    pages, cursor = [], None
    while True:
        args = {"limit": limit, **filters}
        if cursor is not None:
            args["cursor"] = cursor
        page = (await client.call_tool("list_bookmarks", args)).structured_content
        pages.append([b["bookmark_id"] for b in page["items"]])
        cursor = page["next_cursor"]
        if cursor is None:
            return pages


async def test_a_walk_covers_everything_once(client):
    handles = await seed(client, 7)
    pages = await walk(client, limit=3)
    assert [len(p) for p in pages] == [3, 3, 1]
    assert [h for page in pages for h in page] == list(reversed(handles))


async def test_a_walk_neither_skips_nor_repeats_while_rows_come_and_go(client):
    handles = await seed(client, 6)
    first = (await client.call_tool("list_bookmarks", {"limit": 2})).structured_content
    seen = [b["bookmark_id"] for b in first["items"]]

    # Between pages: a bookmark the walk has passed is deleted (an offset would now skip
    # one), and a new one is saved (it sorts before the walk's start, so it is not met).
    await client.call_tool("delete_bookmark", {"bookmark_id": seen[0]})
    newest = (await client.call_tool("add_bookmark", {"url": URL + "new"})).structured_content

    cursor = first["next_cursor"]
    while cursor is not None:
        page = (
            await client.call_tool("list_bookmarks", {"limit": 2, "cursor": cursor})
        ).structured_content
        seen.extend(b["bookmark_id"] for b in page["items"])
        cursor = page["next_cursor"]

    assert seen == list(reversed(handles))
    assert newest["bookmark_id"] not in seen
    assert "without cursor" in page["next_step"]


async def test_rows_that_share_a_timestamp_are_still_walked_once(client, db_path):
    """The id is the tiebreak: five rows written in the same microsecond, pages of two.

    The ORDER BY and the index declare the same order, so SQLite answers this from the
    index even if the ORDER BY lost its tiebreak; the test catches the predicate losing it,
    and both together. Keep the two declarations in step."""
    handles = await seed(client, 5)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("UPDATE bookmarks SET created_at = '2026-10-13T00:00:00.000000+00:00'")
        conn.commit()
    pages = await walk(client, limit=2)
    flat = [h for page in pages for h in page]
    assert sorted(flat) == sorted(handles)
    assert len(flat) == len(set(flat)) == 5


async def test_filters_travel_with_the_caller_not_the_cursor(client):
    await seed(client, 4, prefix="plain-")
    for i in range(3):
        await client.call_tool("add_bookmark", {"url": f"{URL}tagged-{i}", "tags": ["mcp"]})
    pages = await walk(client, limit=2, tag="mcp")
    assert [len(p) for p in pages] == [2, 1]


@pytest.mark.parametrize(
    "cursor",
    ["", "not base64!", "bm_0", paging.encode("2026-01-01T00:00:00+00:00", "bm_0")[:-4] + "zzzz"],
    ids=["empty", "garbage", "a-handle", "corrupted"],
)
async def test_a_cursor_that_is_not_a_position_is_bad_input(client, cursor):
    result = await client.call_tool("list_bookmarks", {"cursor": cursor}, raise_on_error=False)
    assert result.is_error is True
    error = result.structured_content["error"]
    assert error["code"] == "bad_input"
    assert "without cursor" in error["next_step"]


async def test_a_cursor_from_another_listing_is_refused(client):
    other = (
        base64.urlsafe_b64encode(json.dumps(["tags:alphabetical", "a", "b"]).encode())
        .decode()
        .rstrip("=")
    )
    result = await client.call_tool("list_bookmarks", {"cursor": other}, raise_on_error=False)
    assert result.structured_content["error"]["code"] == "bad_input"


class TestAnotherOwner:
    """A cursor grants nothing: replayed by another owner, the read runs as that owner."""

    PUBLIC_URL = "https://bookmarks.example.com"
    ISSUER = "https://issuer.example.com"

    @pytest.fixture
    def keys(self) -> RSAKeyPair:
        return RSAKeyPair.generate()

    @pytest.fixture
    def settings(self, db_path, tmp_path, keys) -> Settings:
        key_file = tmp_path / "public.pem"
        key_file.write_text(keys.public_key)
        return Settings(
            db_path=db_path,
            public_url=self.PUBLIC_URL,
            issuer=self.ISSUER,
            public_key_file=str(key_file),
        )

    def token(self, keys, subject):
        return keys.create_token(
            subject=subject, issuer=self.ISSUER, audience=self.PUBLIC_URL + "/mcp"
        )

    async def test_a_replayed_cursor_shows_only_the_replayers_rows(self, live_server, keys):
        async with Client(StreamableHttpTransport(live_server, auth=self.token(keys, "b"))) as b:
            await seed(b, 3, prefix="b-")
        async with Client(StreamableHttpTransport(live_server, auth=self.token(keys, "a"))) as a:
            await seed(a, 5, prefix="a-")
            first = (await a.call_tool("list_bookmarks", {"limit": 2})).structured_content
        async with Client(StreamableHttpTransport(live_server, auth=self.token(keys, "b"))) as b:
            page = (
                await b.call_tool("list_bookmarks", {"limit": 10, "cursor": first["next_cursor"]})
            ).structured_content
        urls = [item["url"] for item in page["items"]]
        assert len(urls) == 3 and all("/b-" in url for url in urls)
