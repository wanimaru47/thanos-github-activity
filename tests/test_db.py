from activity_monitor import db


def _table_names(conn) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {r["name"] for r in rows}


def test_init_schema_creates_expected_tables(conn):
    assert {
        "members",
        "collections",
        "member_activity",
        "activity_detail",
    } <= _table_names(conn)


def test_init_schema_is_idempotent(conn):
    # 2 回流してもエラーにならず、テーブルも増えない
    before = _table_names(conn)
    db.init_schema(conn)
    assert _table_names(conn) == before


def test_collections_period_is_unique(conn):
    conn.execute(
        "INSERT INTO collections (period_from, period_to, collected_at) "
        "VALUES ('2026-06-05', '2026-06-19', '2026-06-19T00:00:00Z')"
    )
    conn.commit()
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO collections (period_from, period_to, collected_at) "
            "VALUES ('2026-06-05', '2026-06-19', '2026-06-19T09:00:00Z')"
        )


def test_init_db_creates_file(tmp_path):
    dbfile = tmp_path / "nested" / "activity.db"
    db.init_db(dbfile)
    assert dbfile.exists()
    c = db.connect(dbfile)
    try:
        assert "members" in _table_names(c)
    finally:
        c.close()
