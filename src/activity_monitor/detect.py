"""絶対閾値による低活動メンバー検知。

判定ロジックは純粋関数 `classify` に閉じ込め、境界値テストしやすくする。
critical > warn > ok の優先順位で分類する。
"""

from __future__ import annotations

import sqlite3
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Thresholds:
    critical_total_max: int = 0
    warn_total_min: int = 3
    warn_pr_created_min: int = 1

    @classmethod
    def from_dict(cls, d: Mapping) -> "Thresholds":
        return cls(
            critical_total_max=int(d.get("critical_total_max", 0)),
            warn_total_min=int(d.get("warn_total_min", 3)),
            warn_pr_created_min=int(d.get("warn_pr_created_min", 1)),
        )


@dataclass(frozen=True)
class MemberVerdict:
    user_id: int
    login: str
    pr_created: int
    pr_reviews: int
    issue_comments: int
    pr_review_comments: int
    total: int
    status: str  # "ok" | "warn" | "critical"
    reasons: list[str]


def load_thresholds(config_path: str | Path) -> Thresholds:
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    return Thresholds.from_dict(data.get("thresholds", {}))


def classify(row: Mapping, t: Thresholds) -> tuple[str, list[str]]:
    """1 メンバーの集計行を ok/warn/critical に分類し、理由を返す。"""
    total = row["total"]
    pr_created = row["pr_created"]

    if total <= t.critical_total_max:
        return "critical", [
            f"期間内の活動が合計 {total} 件（critical 閾値 {t.critical_total_max} 以下）"
        ]

    reasons: list[str] = []
    if total < t.warn_total_min:
        reasons.append(f"活動合計 {total} 件が warn 閾値 {t.warn_total_min} 未満")
    if pr_created < t.warn_pr_created_min:
        reasons.append(
            f"PR 作成 {pr_created} 件が warn 閾値 {t.warn_pr_created_min} 未満"
        )

    return ("warn", reasons) if reasons else ("ok", [])


def detect(
    conn: sqlite3.Connection,
    thresholds: Thresholds,
    period_from: str | None = None,
    period_to: str | None = None,
) -> list[MemberVerdict]:
    """対象 collection のメンバーを分類して返す。

    period 未指定なら最新（id 最大）の collection を対象にする。
    """
    collection = resolve_collection(conn, period_from, period_to)
    if collection is None:
        return []
    collection_id = collection["id"]

    rows = conn.execute(
        """
        SELECT m.user_id, m.login, a.pr_created, a.pr_reviews,
               a.issue_comments, a.pr_review_comments, a.total
        FROM member_activity a JOIN members m ON m.user_id = a.user_id
        WHERE a.collection_id = ?
        ORDER BY a.total ASC, m.login ASC
        """,
        (collection_id,),
    ).fetchall()

    verdicts = []
    for r in rows:
        status, reasons = classify(r, thresholds)
        verdicts.append(
            MemberVerdict(
                user_id=r["user_id"], login=r["login"], pr_created=r["pr_created"],
                pr_reviews=r["pr_reviews"], issue_comments=r["issue_comments"],
                pr_review_comments=r["pr_review_comments"], total=r["total"],
                status=status, reasons=reasons,
            )
        )
    return verdicts


def resolve_collection(
    conn: sqlite3.Connection, period_from: str | None, period_to: str | None
) -> sqlite3.Row | None:
    """対象 collection の行 (id, period_from, period_to, collected_at) を返す。

    period 未指定なら最新（id 最大）。該当が無ければ None。
    """
    if period_from and period_to:
        return conn.execute(
            "SELECT * FROM collections WHERE period_from = ? AND period_to = ?",
            (period_from, period_to),
        ).fetchone()
    return conn.execute("SELECT * FROM collections ORDER BY id DESC LIMIT 1").fetchone()
