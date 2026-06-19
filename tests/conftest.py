import sqlite3

import pytest

from activity_monitor import db


@pytest.fixture
def conn() -> sqlite3.Connection:
    """スキーマ適用済みのインメモリ DB を返す。"""
    c = db.connect(":memory:")
    db.init_schema(c)
    yield c
    c.close()
