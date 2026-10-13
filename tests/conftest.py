"""Shared fixtures.

Tools are exercised through `fastmcp.Client`, never by calling the Python functions, so
every test sees what a client sees on the wire. `live_server` runs the real ASGI app under
uvicorn for the tests that need HTTP itself.
"""

import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from fastmcp import Client

from mcp_bookmarks import server


@pytest.fixture(autouse=True)
def db_path(tmp_path, monkeypatch) -> str:
    """A fresh database per test. The store is opened by path, so no cache to clear."""
    path = str(tmp_path / "bookmarks.db")
    monkeypatch.setenv("BOOKMARKS_DB", path)
    return path


@pytest.fixture
def mcp():
    return server.mcp


@pytest.fixture
async def client(mcp) -> Iterator[Client]:
    async with Client(mcp) as c:
        yield c


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(db_path) -> Iterator[str]:
    """The ASGI app under uvicorn, on a free port. Yields the MCP endpoint URL."""
    port = _free_port()
    config = uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning")
    uvi = uvicorn.Server(config)
    thread = threading.Thread(target=uvi.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        raise RuntimeError("server did not start")
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        uvi.should_exit = True
        thread.join(timeout=5)
