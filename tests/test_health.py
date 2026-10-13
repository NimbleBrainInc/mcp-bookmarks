"""/health answers for the one dependency, not for the process."""

import httpx


def test_health_is_ok_when_the_store_opens(live_server):
    response = httpx.get(live_server.removesuffix("/mcp") + "/health", timeout=5)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_is_503_when_the_store_cannot_open(live_server, tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKMARKS_DB", str(tmp_path / "no-such-dir" / "bookmarks.db"))
    response = httpx.get(live_server.removesuffix("/mcp") + "/health", timeout=5)
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
