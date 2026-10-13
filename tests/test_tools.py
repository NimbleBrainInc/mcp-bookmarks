"""Each tool, as a client sees it."""

import pytest
from fastmcp.exceptions import ToolError

URL = "https://modelcontextprotocol.io/specification/2026-07-28/changelog"


async def refusal(client, name, arguments):
    """The error envelope of a call the tool refused."""
    result = await client.call_tool(name, arguments, raise_on_error=False)
    assert result.is_error is True
    return result.structured_content["error"]


async def add(client, url=URL, **kwargs):
    result = await client.call_tool("add_bookmark", {"url": url, **kwargs})
    return result.structured_content


async def test_add_returns_a_handle(client):
    bookmark = await add(client, title=" Changelog ", tags=["MCP", "mcp", " Spec "])
    assert bookmark["bookmark_id"].startswith("bm_")
    assert bookmark["url"] == URL
    assert bookmark["title"] == "Changelog"
    assert bookmark["tags"] == ["mcp", "spec"]
    assert bookmark["archived"] is False
    assert bookmark["created_at"] == bookmark["updated_at"]


async def test_add_refuses_a_non_web_url(client):
    error = await refusal(client, "add_bookmark", {"url": "ftp://example.com/file"})
    assert error["code"] == "bad_input"
    assert "not a web URL" in error["message"]


async def test_get_by_handle(client):
    saved = await add(client)
    fetched = (
        await client.call_tool("get_bookmark", {"bookmark_id": saved["bookmark_id"]})
    ).structured_content
    assert fetched == saved


async def test_get_unknown_handle(client):
    error = await refusal(client, "get_bookmark", {"bookmark_id": "bm_" + "0" * 32})
    assert error["code"] == "not_found"


async def test_get_malformed_handle(client):
    error = await refusal(client, "get_bookmark", {"bookmark_id": "42"})
    assert error["code"] == "bad_input"
    assert "not a bookmark_id" in error["message"]


async def test_list_newest_first_with_tag_filter(client):
    first = await add(client, url="https://example.com/1", tags=["a"])
    second = await add(client, url="https://example.com/2", tags=["b"])
    third = await add(client, url="https://example.com/3", tags=["a", "b"])

    page = (await client.call_tool("list_bookmarks", {})).structured_content
    assert [b["bookmark_id"] for b in page["items"]] == [
        third["bookmark_id"],
        second["bookmark_id"],
        first["bookmark_id"],
    ]
    assert page["next_cursor"] is None

    page = (await client.call_tool("list_bookmarks", {"tag": "A"})).structured_content
    assert [b["bookmark_id"] for b in page["items"]] == [third["bookmark_id"], first["bookmark_id"]]


async def test_list_reports_more(client):
    for i in range(3):
        await add(client, url=f"https://example.com/{i}")
    page = (await client.call_tool("list_bookmarks", {"limit": 2})).structured_content
    assert len(page["items"]) == 2
    assert page["next_cursor"] is not None
    assert "cursor" in page["next_step"]


async def test_list_rejects_a_limit_out_of_range(client):
    with pytest.raises(ToolError):
        await client.call_tool("list_bookmarks", {"limit": 0})
    with pytest.raises(ToolError):
        await client.call_tool("list_bookmarks", {"limit": 101})


async def test_update_changes_only_what_is_passed(client):
    saved = await add(client, title="Old", tags=["x"])
    handle = saved["bookmark_id"]
    retitled = (
        await client.call_tool("update_bookmark", {"bookmark_id": handle, "title": "New"})
    ).structured_content
    assert retitled["title"] == "New"
    assert retitled["tags"] == ["x"]
    retagged = (
        await client.call_tool("update_bookmark", {"bookmark_id": handle, "tags": ["y"]})
    ).structured_content
    assert retagged["title"] == "New"
    assert retagged["tags"] == ["y"]
    cleared = (
        await client.call_tool("update_bookmark", {"bookmark_id": handle, "title": ""})
    ).structured_content
    assert cleared["title"] is None


async def test_archive_hides_from_the_default_list_and_is_idempotent(client):
    saved = await add(client)
    handle = saved["bookmark_id"]
    once = (await client.call_tool("archive_bookmark", {"bookmark_id": handle})).structured_content
    twice = (await client.call_tool("archive_bookmark", {"bookmark_id": handle})).structured_content
    assert once["archived"] is twice["archived"] is True
    assert once["updated_at"] == twice["updated_at"]

    default = (await client.call_tool("list_bookmarks", {})).structured_content
    assert default["items"] == []
    with_archived = (
        await client.call_tool("list_bookmarks", {"include_archived": True})
    ).structured_content
    assert [b["bookmark_id"] for b in with_archived["items"]] == [handle]


async def test_delete_makes_the_handle_stop_resolving(client):
    saved = await add(client)
    handle = saved["bookmark_id"]
    gone = (await client.call_tool("delete_bookmark", {"bookmark_id": handle})).structured_content
    assert gone == {"bookmark_id": handle, "deleted": True}
    assert (await refusal(client, "get_bookmark", {"bookmark_id": handle}))["code"] == "not_found"
    assert (await refusal(client, "delete_bookmark", {"bookmark_id": handle}))[
        "code"
    ] == "not_found"
