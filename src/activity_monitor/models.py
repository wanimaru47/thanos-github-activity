"""収集 JSON の契約（skill が書き、ingest が読む）を表すモデル。

イベント単位の配列を受け取り、ここでシグナル横断の共通形 (Event) に正規化する。
件数集計やバリデーションを Python 側に閉じ込め、テスト可能にする。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# シグナル種別 → (配列キー, ref番号フィールド, 日時フィールド)
SIGNALS: dict[str, tuple[str, str, str]] = {
    "pr_created": ("pr_created", "number", "created_at"),
    "pr_review": ("pr_reviews", "pr_number", "submitted_at"),
    "issue_comment": ("issue_comments", "issue_number", "created_at"),
    "pr_review_comment": ("pr_review_comments", "pr_number", "created_at"),
}


@dataclass(frozen=True)
class Member:
    user_id: int
    login: str
    name: str | None = None


@dataclass(frozen=True)
class Event:
    user_id: int
    repo_full_name: str | None
    ref_number: int | None
    occurred_at: str | None
    count: int = 1


@dataclass
class Collection:
    period_from: str
    period_to: str
    collected_at: str
    members: list[Member]
    signals: dict[str, list[Event]] = field(default_factory=dict)


def parse_collection(data: dict) -> Collection:
    """dict を Collection に変換する。必須項目が欠ければ ValueError。"""
    period = data.get("period")
    if not isinstance(period, dict) or "from" not in period or "to" not in period:
        raise ValueError("period.from / period.to は必須です")

    collected_at = data.get("collected_at")
    if not collected_at:
        raise ValueError("collected_at は必須です")

    members = []
    for m in data.get("members", []):
        if "user_id" not in m or "login" not in m:
            raise ValueError("member には user_id と login が必要です")
        members.append(Member(int(m["user_id"]), m["login"], m.get("name")))

    signals: dict[str, list[Event]] = {}
    for signal, (array_key, ref_key, at_key) in SIGNALS.items():
        events = []
        for row in data.get(array_key, []):
            if "user_id" not in row:
                raise ValueError(f"{array_key} の各行に user_id が必要です")
            events.append(
                Event(
                    user_id=int(row["user_id"]),
                    repo_full_name=row.get("repo_full_name"),
                    ref_number=row.get(ref_key),
                    occurred_at=row.get(at_key),
                    count=int(row.get("count", 1)),
                )
            )
        signals[signal] = events
    return Collection(
        period_from=str(period["from"]),
        period_to=str(period["to"]),
        collected_at=str(collected_at),
        members=members,
        signals=signals,
    )


def load_collection(path: str | Path) -> Collection:
    with open(path, encoding="utf-8") as f:
        return parse_collection(json.load(f))
