"""Bookmarks MCP server.

A remote MCP server on the 2026-07-28 revision of the protocol. The process holds no state
between requests: every bookmark lives in the store, and a client that wants one back
names it with the handle it was given. Any process with the same database file answers
any request, which is what lets the server run as more than one replica.
"""

import logging
import os
import sys
from functools import lru_cache
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import __version__
from .annotations import ADDS, CHANGES, READS
from .ids import is_bookmark_id
from .models import Bookmark, BookmarkPage, Deleted
from .store import MAX_LIMIT, UNSET, Store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp_bookmarks")

mcp = FastMCP(
    "Bookmarks",
    version=__version__,
    instructions=(
        "Saves links for later. add_bookmark returns a bookmark_id; every other tool takes "
        "that handle. There is no current bookmark and no session: pass the handle each time."
    ),
)


@lru_cache
def _open(path: str) -> Store:
    return Store(path)


def get_store() -> Store:
    """The store for this process. The path comes from the environment, not from a client."""
    return _open(os.environ.get("BOOKMARKS_DB", "bookmarks.db"))


def _require(bookmark_id: str) -> Bookmark:
    if not is_bookmark_id(bookmark_id):
        raise ToolError(
            f"Not a bookmark_id: {bookmark_id!r}. Handles look like bm_<32 hex characters> "
            "and come from add_bookmark or list_bookmarks."
        )
    bookmark = get_store().get(bookmark_id)
    if bookmark is None:
        raise ToolError(
            f"Bookmark not found: {bookmark_id}. Call list_bookmarks to see what exists."
        )
    return bookmark


def _title(title: str | None) -> str | None:
    """A blank title is no title."""
    cleaned = (title or "").strip()
    return cleaned or None


def _require_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned.lower().startswith(("http://", "https://")):
        raise ToolError(f"Not a web URL: {url!r}. Give a full http:// or https:// address.")
    return cleaned


@mcp.tool(annotations=ADDS)
def add_bookmark(
    url: Annotated[str, Field(description="Full http:// or https:// address to save.")],
    title: Annotated[
        str | None, Field(description="Display title. Leave empty when the user gave none.")
    ] = None,
    tags: Annotated[
        list[str] | None,
        Field(
            description="Tags to file it under, such as ['mcp', 'reading']. Case does not matter."
        ),
    ] = None,
) -> Bookmark:
    """Save a link the user wants to keep, and get back the handle for it.

    Call this when the user shares a URL and asks to save, keep, or bookmark it. The
    result's bookmark_id is the handle every other tool takes, so keep it. A bookmark is
    kept until delete_bookmark removes it. Saving the same URL twice makes two bookmarks;
    call list_bookmarks first if you are unsure whether the link is already saved.
    """
    return get_store().add(_require_url(url), _title(title), tags)


@mcp.tool(annotations=READS)
def get_bookmark(
    bookmark_id: Annotated[str, Field(description="Handle from add_bookmark or list_bookmarks.")],
) -> Bookmark:
    """Read one bookmark by its handle.

    Call this when you hold a bookmark_id and need its URL, title, or tags. It does not
    search; to find a bookmark by tag, call list_bookmarks.
    """
    return _require(bookmark_id)


@mcp.tool(annotations=READS)
def list_bookmarks(
    tag: Annotated[
        str | None, Field(description="Only bookmarks carrying this tag. Omit for all.")
    ] = None,
    include_archived: Annotated[
        bool, Field(description="Also return bookmarks that were archived.")
    ] = False,
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT, description="Page size, 1 to 100.")] = 20,
) -> BookmarkPage:
    """List saved bookmarks, newest first.

    Call this to show the user what is saved, to find a bookmark by tag, or to check
    whether a URL is already saved before calling add_bookmark. Each item carries its
    bookmark_id. When has_more is true, narrow by tag or raise limit, up to 100.
    """
    items, has_more = get_store().list_page(tag=tag, include_archived=include_archived, limit=limit)
    return BookmarkPage(items=items, has_more=has_more)


@mcp.tool(annotations=CHANGES)
def update_bookmark(
    bookmark_id: Annotated[str, Field(description="Handle from add_bookmark or list_bookmarks.")],
    title: Annotated[
        str | None,
        Field(
            description="New title. Omit to keep the current one; pass an empty string to clear it."
        ),
    ] = None,
    tags: Annotated[
        list[str] | None,
        Field(description="Replacement tag list. Omit to keep the current tags."),
    ] = None,
) -> Bookmark:
    """Change a bookmark's title or tags.

    Call this when the user wants to rename a bookmark or retag it. Only the fields you
    pass change. To file a bookmark away instead, call archive_bookmark.
    """
    _require(bookmark_id)
    updated = get_store().update(
        bookmark_id,
        title=UNSET if title is None else _title(title),
        tags=UNSET if tags is None else tags,
    )
    assert updated is not None
    return updated


@mcp.tool(annotations=CHANGES)
def archive_bookmark(
    bookmark_id: Annotated[str, Field(description="Handle from add_bookmark or list_bookmarks.")],
) -> Bookmark:
    """Archive a bookmark so list_bookmarks stops showing it by default.

    Call this when the user is done with a link but may want it back. Archiving twice is
    harmless. To remove a bookmark for good, call delete_bookmark.
    """
    _require(bookmark_id)
    archived = get_store().archive(bookmark_id)
    assert archived is not None
    return archived


@mcp.tool(annotations=CHANGES)
def delete_bookmark(
    bookmark_id: Annotated[str, Field(description="Handle from add_bookmark or list_bookmarks.")],
) -> Deleted:
    """Delete a bookmark permanently.

    Call this only when the user asks to delete or remove a bookmark. There is no undo;
    when the user may want it back, call archive_bookmark instead.
    """
    _require(bookmark_id)
    get_store().delete(bookmark_id)
    return Deleted(bookmark_id=bookmark_id, deleted=True)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Healthy means the one dependency answers: a probe that never touches the store would
    pass on a machine that fails every tool call."""
    body = {"service": "mcp-bookmarks", "version": __version__}
    try:
        get_store()
    except Exception as exc:
        logger.error("store unavailable: %r", exc)
        return JSONResponse({"status": "unavailable", **body}, status_code=503)
    return JSONResponse({"status": "ok", **body})


# The ASGI app a container runs: `uvicorn mcp_bookmarks.server:app`.
# stateless_http=True keeps the 2025-era handshake from minting a session either, so a
# client on the old era can also be answered by any replica.
app = mcp.http_app(path="/mcp", stateless_http=True)

if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=os.environ.get("BOOKMARKS_HOST", "127.0.0.1"),
        port=int(os.environ.get("BOOKMARKS_PORT", "8000")),
        path="/mcp",
        stateless_http=True,
    )
