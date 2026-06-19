"""検知結果から Markdown レポートを生成する。"""

from __future__ import annotations

from pathlib import Path

from .detect import MemberVerdict

_STATUS_LABEL = {"critical": "🔴 critical", "warn": "🟡 warn", "ok": "🟢 ok"}


def render_report(
    period_from: str, period_to: str, verdicts: list[MemberVerdict]
) -> str:
    critical = [v for v in verdicts if v.status == "critical"]
    warn = [v for v in verdicts if v.status == "warn"]

    lines: list[str] = []
    lines.append("# GitHub 活動モニタリング")
    lines.append("")
    lines.append(f"対象期間: {period_from} 〜 {period_to}")
    lines.append(f"対象メンバー: {len(verdicts)} 名")
    lines.append("")
    lines.append(
        f"判定: 🔴 critical {len(critical)} 名 / "
        f"🟡 warn {len(warn)} 名 / "
        f"🟢 ok {len(verdicts) - len(critical) - len(warn)} 名"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # 警告セクション
    flagged = critical + warn
    lines.append("## ⚠️ 要確認メンバー")
    lines.append("")
    if not flagged:
        lines.append("該当なし。全メンバーが閾値を満たしています。")
    else:
        lines.append("| メンバー | 判定 | 活動合計 | 理由 |")
        lines.append("|---|---|---|---|")
        for v in flagged:
            reason = "<br>".join(v.reasons) if v.reasons else "-"
            lines.append(f"| {v.login} | {_STATUS_LABEL[v.status]} | {v.total} | {reason} |")
    lines.append("")

    # 全メンバー内訳
    lines.append("## 全メンバー活動内訳")
    lines.append("")
    lines.append("| メンバー | 判定 | PR作成 | レビュー | Issueｺﾒﾝﾄ | PRｺﾒﾝﾄ | 合計 |")
    lines.append("|---|---|---|---|---|---|---|")
    for v in verdicts:
        lines.append(
            f"| {v.login} | {_STATUS_LABEL[v.status]} | {v.pr_created} | "
            f"{v.pr_reviews} | {v.issue_comments} | {v.pr_review_comments} | {v.total} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(
    reports_dir: str | Path,
    period_from: str,
    period_to: str,
    verdicts: list[MemberVerdict],
) -> Path:
    """レポートを書き出す。既存ファイルは上書きせず連番を付ける。"""
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    stem = f"activity-{period_from.replace('-', '')}-{period_to.replace('-', '')}"

    path = reports_dir / f"{stem}.md"
    seq = 2
    while path.exists():
        path = reports_dir / f"{stem}-{seq}.md"
        seq += 1

    path.write_text(render_report(period_from, period_to, verdicts), encoding="utf-8")
    return path
