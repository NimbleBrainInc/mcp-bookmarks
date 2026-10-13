"""/health answers for the one dependency, not for the process."""

import httpx
import pytest


def test_health_is_ok_when_the_store_opens(live_server):
    response = httpx.get(live_server.removesuffix("/mcp") + "/health", timeout=5)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


class TestStoreUnavailable:
    @pytest.fixture
    def db_path(self, tmp_path) -> str:
        return str(tmp_path / "no-such-dir" / "bookmarks.db")

    def test_health_is_503(self, live_server):
        response = httpx.get(live_server.removesuffix("/mcp") + "/health", timeout=5)
        assert response.status_code == 503
        assert response.json()["status"] == "unavailable"
