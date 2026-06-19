"""SQLite 接続とスキーマ管理。

活動履歴を蓄積するためのスキーマを定義する。`member_activity` は
収集（collection）ごとのメンバー別集計スナップショットで、時系列に積み上がる。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    user_id INTEGER PRIMARY KEY,
    login   TEXT NOT NULL,
    name    TEXT
);

CREATE TABLE IF NOT EXISTS collections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    period_from  TEXT NOT NULL,
    period_to    TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    UNIQUE (period_from, period_to)
);

CREATE TABLE IF NOT EXISTS member_activity (
    collection_id      INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    user_id            INTEGER NOT NULL REFERENCES members(user_id),
    pr_created         INTEGER NOT NULL DEFAULT 0,
    pr_reviews         INTEGER NOT NULL DEFAULT 0,
    issue_comments     INTEGER NOT NULL DEFAULT 0,
    pr_review_comments INTEGER NOT NULL DEFAULT 0,
    total              INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (collection_id, user_id)
);

CREATE TABLE IF NOT EXISTS activity_detail (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id  INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    user_id        INTEGER NOT NULL REFERENCES members(user_id),
    signal_type    TEXT NOT NULL,
    repo_full_name TEXT,
    ref_number     INTEGER,
    occurred_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_detail_collection
    ON activity_detail (collection_id, user_id);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """SQLite に接続する。`:memory:` も可。"""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """テーブルを作成する（冪等）。"""
    conn.executescript(SCHEMA)
    conn.commit()


def init_db(path: str | Path) -> None:
    """ファイル DB を作成し、必要なら親ディレクトリも掘る。"""
    p = Path(path)
    if p.parent and str(p.parent) not in ("", "."):
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(p)
    try:
        init_schema(conn)
    finally:
        conn.close()
