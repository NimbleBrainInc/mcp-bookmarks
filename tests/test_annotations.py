"""Every tool says what it does to the world.

The spec's defaults make an unannotated tool a destructive, non-idempotent, open-world
write. These tests refuse a tool that leaves that to the default: each one must be in the
table below, and what the server advertises must match the table field for field.
"""

from mcp.types import ToolAnnotations

from mcp_bookmarks.annotations import ADDS, CHANGES, READS

EXPECTED: dict[str, ToolAnnotations] = {
    "add_bookmark": ADDS,
    "get_bookmark": READS,
    "list_bookmarks": READS,
    "update_bookmark": CHANGES,
    "archive_bookmark": CHANGES,
    "delete_bookmark": CHANGES,
}

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


async def test_every_tool_is_in_the_table(client):
    advertised = {tool.name for tool in await client.list_tools()}
    assert advertised == set(EXPECTED), (
        "a tool is missing from EXPECTED; decide whether it reads, adds, or changes"
    )


async def test_every_tool_advertises_the_annotations_the_table_says(client):
    for tool in await client.list_tools():
        assert tool.annotations is not None, f"{tool.name} is unannotated"
        expected = EXPECTED[tool.name]
        assert tool.annotations.read_only_hint is expected.read_only_hint, tool.name
        assert tool.annotations.destructive_hint is expected.destructive_hint, tool.name
        assert tool.annotations.idempotent_hint is expected.idempotent_hint, tool.name
        assert tool.annotations.open_world_hint is expected.open_world_hint, tool.name


async def test_every_hint_is_present_on_the_wire(client):
    """Each hint is written out, so no client falls back to the spec's defaults."""
    listing = await client.list_tools_mcp()
    for tool in listing.tools:
        wire = tool.model_dump(by_alias=True, exclude_none=True)
        assert set(wire["annotations"]) >= set(HINTS), tool.name


async def test_a_reader_and_a_writer_differ_where_a_host_would_look(client):
    """The hints a careful host reads before calling: writes are not read-only, and the
    ones that overwrite or remove say so."""
    by_name = {tool.name: tool.annotations for tool in await client.list_tools()}
    assert by_name["get_bookmark"].read_only_hint is True
    assert by_name["add_bookmark"].read_only_hint is False
    assert by_name["add_bookmark"].destructive_hint is False
    assert by_name["delete_bookmark"].destructive_hint is True
