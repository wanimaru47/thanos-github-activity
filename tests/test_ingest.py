from pathlib import Path

import pytest

from activity_monitor import ingest, models

FIXTURE = Path(__file__).parent / "fixtures" / "sample_collection.json"


def _activity_by_login(conn, collection_id):
    rows = conn.execute(
        """
        SELECT m.login, a.pr_created, a.pr_reviews, a.issue_comments,
               a.pr_review_comments, a.total
        FROM member_activity a JOIN members m ON m.user_id = a.user_id
        WHERE a.collection_id = ?
        """,
        (collection_id,),
    ).fetchall()
    return {r["login"]: r for r in rows}


def test_load_collection_parses_contract():
    c = models.load_collection(FIXTURE)
    assert c.period_from == "2026-06-05"
    assert c.period_to == "2026-06-19"
    assert len(c.members) == 3


def test_load_collection_rejects_missing_period(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"members": []}')
    with pytest.raises(ValueError):
        models.load_collection(bad)


def test_ingest_registers_members_and_collection(conn):
    c = models.load_collection(FIXTURE)
    ingest.ingest_collection(conn, c)
    assert conn.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0] == 1


def test_ingest_aggregates_counts(conn):
    c = models.load_collection(FIXTURE)
    cid = ingest.ingest_collection(conn, c)
    acts = _activity_by_login(conn, cid)
    foo = acts["foo"]
    # PR作成2, レビュー1, Issueコメント3(count指定), レビューコメント1 → total 7
    assert (foo["pr_created"], foo["pr_reviews"], foo["issue_comments"],
            foo["pr_review_comments"]) == (2, 1, 3, 1)
    assert foo["total"] == 7


def test_count_field_defaults_to_one(conn):
    c = models.load_collection(FIXTURE)
    cid = ingest.ingest_collection(conn, c)
    acts = _activity_by_login(conn, cid)
    # bar は issue_comment 1件のみ（count未指定→1）
    assert acts["bar"]["issue_comments"] == 1
    assert acts["bar"]["total"] == 1


def test_zero_activity_member_gets_row_with_zeros(conn):
    c = models.load_collection(FIXTURE)
    cid = ingest.ingest_collection(conn, c)
    acts = _activity_by_login(conn, cid)
    # baz はイベントが無くても行が作られ、全て0であること（検知対象に必須）
    assert "baz" in acts
    assert acts["baz"]["total"] == 0


def test_detail_rows_recorded(conn):
    c = models.load_collection(FIXTURE)
    cid = ingest.ingest_collection(conn, c)
    n = conn.execute(
        "SELECT COUNT(*) FROM activity_detail WHERE collection_id = ?", (cid,)
    ).fetchone()[0]
    # イベント行数（count フィールドの値ではなく行数）= 2+1+2+1 = 6
    assert n == 6


def test_ingest_is_idempotent(conn):
    c = models.load_collection(FIXTURE)
    cid1 = ingest.ingest_collection(conn, c)
    cid2 = ingest.ingest_collection(conn, c)
    assert cid1 == cid2  # 同一期間は同じ collection に upsert
    assert conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM member_activity").fetchone()[0] == 3
    # detail も二重化しない
    assert conn.execute("SELECT COUNT(*) FROM activity_detail").fetchone()[0] == 6
    # 集計値も変わらない
    acts = _activity_by_login(conn, cid2)
    assert acts["foo"]["total"] == 7
