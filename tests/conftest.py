"""Shared fixtures.

Tools are exercised through `fastmcp.Client`, never by calling the Python functions, so
every test sees what a client sees on the wire. Each test gets its own server, built from
its own settings over a fresh database; `live_server` runs that server's ASGI app under
uvicorn for the tests that need HTTP itself.
"""

import os
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from fastmcp import Client, FastMCP

# The module builds a server from the environment when imported.
os.environ.setdefault("BOOKMARKS_ALLOW_ANONYMOUS", "true")

from mcp_bookmarks.config import Settings  # noqa: E402
from mcp_bookmarks.server import create_app, create_server  # noqa: E402


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "bookmarks.db")


@pytest.fixture
def settings(db_path) -> Settings:
    """Anonymous, as the server runs in local development."""
    return Settings(db_path=db_path, allow_anonymous=True)


@pytest.fixture
def mcp(settings) -> FastMCP:
    return create_server(settings)


@pytest.fixture
async def client(mcp) -> Iterator[Client]:
    async with Client(mcp) as c:
        yield c


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(mcp) -> Iterator[str]:
    """This test's server under uvicorn, on a free port. Yields the MCP endpoint URL."""
    port = _free_port()
    config = uvicorn.Config(create_app(mcp), host="127.0.0.1", port=port, log_level="warning")
    uvi = uvicorn.Server(config)
    thread = threading.Thread(target=uvi.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            # Any answer means the app is up; /health may say 503 on purpose in a test.
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
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
