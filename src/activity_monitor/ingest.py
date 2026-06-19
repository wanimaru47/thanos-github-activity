"""収集 Collection を SQLite に取り込む。

同一期間 (period_from, period_to) の再取り込みは upsert で冪等にする。
活動が無いメンバーも 0 件の行を必ず作る（低活動メンバー検知に必須）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import db, models

# member_activity の集計カラム名 ← シグナル種別
_SIGNAL_COLUMN = {
    "pr_created": "pr_created",
    "pr_review": "pr_reviews",
    "issue_comment": "issue_comments",
    "pr_review_comment": "pr_review_comments",
}


def ingest_collection(conn: sqlite3.Connection, collection: models.Collection) -> int:
    """Collection を取り込み、collection_id を返す。"""
    _upsert_members(conn, collection.members)
    collection_id = _upsert_collection(conn, collection)

    # 既存データを消してから入れ直す（冪等な置換）
    conn.execute("DELETE FROM member_activity WHERE collection_id = ?", (collection_id,))
    conn.execute("DELETE FROM activity_detail WHERE collection_id = ?", (collection_id,))

    counts = _aggregate(collection)
    _write_member_activity(conn, collection_id, collection.members, counts)
    _write_details(conn, collection_id, collection)

    conn.commit()
    return collection_id


def ingest_file(conn: sqlite3.Connection, path: str | Path) -> int:
    return ingest_collection(conn, models.load_collection(path))


def _upsert_members(conn: sqlite3.Connection, members: list[models.Member]) -> None:
    conn.executemany(
        """
        INSERT INTO members (user_id, login, name) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET login = excluded.login, name = excluded.name
        """,
        [(m.user_id, m.login, m.name) for m in members],
    )


def _upsert_collection(conn: sqlite3.Connection, c: models.Collection) -> int:
    conn.execute(
        """
        INSERT INTO collections (period_from, period_to, collected_at)
        VALUES (?, ?, ?)
        ON CONFLICT(period_from, period_to)
            DO UPDATE SET collected_at = excluded.collected_at
        """,
        (c.period_from, c.period_to, c.collected_at),
    )
    row = conn.execute(
        "SELECT id FROM collections WHERE period_from = ? AND period_to = ?",
        (c.period_from, c.period_to),
    ).fetchone()
    return int(row["id"])


def _aggregate(c: models.Collection) -> dict[int, dict[str, int]]:
    """user_id -> {column_name: count} を集計する。"""
    counts: dict[int, dict[str, int]] = {}
    for signal, events in c.signals.items():
        column = _SIGNAL_COLUMN[signal]
        for e in events:
            counts.setdefault(e.user_id, {}).setdefault(column, 0)
            counts[e.user_id][column] += e.count
    return counts


def _write_member_activity(
    conn: sqlite3.Connection,
    collection_id: int,
    members: list[models.Member],
    counts: dict[int, dict[str, int]],
) -> None:
    rows = []
    for m in members:
        c = counts.get(m.user_id, {})
        pr_created = c.get("pr_created", 0)
        pr_reviews = c.get("pr_reviews", 0)
        issue_comments = c.get("issue_comments", 0)
        pr_review_comments = c.get("pr_review_comments", 0)
        total = pr_created + pr_reviews + issue_comments + pr_review_comments
        rows.append(
            (collection_id, m.user_id, pr_created, pr_reviews,
             issue_comments, pr_review_comments, total)
        )
    conn.executemany(
        """
        INSERT INTO member_activity
            (collection_id, user_id, pr_created, pr_reviews,
             issue_comments, pr_review_comments, total)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _write_details(
    conn: sqlite3.Connection, collection_id: int, c: models.Collection
) -> None:
    rows = []
    for signal, events in c.signals.items():
        for e in events:
            rows.append(
                (collection_id, e.user_id, signal, e.repo_full_name,
                 e.ref_number, e.occurred_at)
            )
    conn.executemany(
        """
        INSERT INTO activity_detail
            (collection_id, user_id, signal_type, repo_full_name, ref_number, occurred_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
