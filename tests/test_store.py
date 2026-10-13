"""The store opens the database a reader has from the earlier lessons."""

import sqlite3
from contextlib import closing

from mcp_bookmarks.store import Store

LESSON_THREE_SCHEMA = """
CREATE TABLE bookmarks (
    bookmark_id TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    title       TEXT,
    tags        TEXT NOT NULL,
    archived    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX bookmarks_newest_first ON bookmarks (created_at DESC, bookmark_id DESC);
INSERT INTO bookmarks VALUES ('bm_' || substr(hex(randomblob(16)), 1, 32), 'https://example.com',
    'Kept', '[]', 0, '2026-10-01T00:00:00.000000+00:00', '2026-10-01T00:00:00.000000+00:00');
"""


def test_a_database_from_before_owners_opens_and_keeps_its_rows(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(LESSON_THREE_SCHEMA)
    store = Store(db_path)
    items, _ = store.list_page("anonymous", tag=None, include_archived=False, limit=10)
    assert [b.title for b in items] == ["Kept"]
    with closing(sqlite3.connect(db_path)) as conn:
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(bookmarks)")}
    assert "bookmarks_owner_newest_first" in indexes
    assert "bookmarks_newest_first" not in indexes
