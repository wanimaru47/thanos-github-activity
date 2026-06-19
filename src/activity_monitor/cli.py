"""activity-monitor CLI: init-db / ingest / detect / report。

MCP には触れない。収集 JSON の取り込みと検知・レポート生成だけを担う。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db, detect, ingest, report

DEFAULT_DB = "data/activity.db"
DEFAULT_CONFIG = "config.toml"
DEFAULT_REPORTS = "reports"


def _load_thresholds(path: str) -> detect.Thresholds:
    if Path(path).exists():
        return detect.load_thresholds(path)
    return detect.Thresholds()  # 設定が無ければ既定値


def cmd_init_db(args: argparse.Namespace) -> int:
    db.init_db(args.db)
    print(f"initialized: {args.db}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    db.init_db(args.db)
    conn = db.connect(args.db)
    try:
        for path in args.json:
            cid = ingest.ingest_file(conn, path)
            print(f"ingested {path} -> collection_id={cid}")
    finally:
        conn.close()
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        thresholds = _load_thresholds(args.config)
        verdicts = detect.detect(conn, thresholds, args.__dict__.get("from"), args.to)
    finally:
        conn.close()

    flagged = [v for v in verdicts if v.status != "ok"]
    for v in verdicts:
        if v.status == "ok":
            continue
        reasons = "; ".join(v.reasons)
        print(f"[{v.status}] {v.login} (total={v.total}) {reasons}")
    if not flagged:
        print("全メンバーが閾値を満たしています。")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        thresholds = _load_thresholds(args.config)
        period_from = args.__dict__.get("from")
        collection = detect.resolve_collection(conn, period_from, args.to)
        if collection is None:
            print("対象の収集データがありません。先に ingest してください。", file=sys.stderr)
            return 1
        verdicts = detect.detect(conn, thresholds, period_from, args.to)
    finally:
        conn.close()

    path = report.write_report(
        args.out, collection["period_from"], collection["period_to"], verdicts
    )
    print(f"report written: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="activity-monitor")
    p.add_argument("--db", default=DEFAULT_DB, help=f"SQLite パス (既定: {DEFAULT_DB})")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init-db", help="DB を初期化する")
    sp.set_defaults(func=cmd_init_db)

    sp = sub.add_parser("ingest", help="収集 JSON を取り込む")
    sp.add_argument("json", nargs="+", help="収集 JSON ファイル")
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("detect", help="閾値判定して標準出力に表示")
    sp.add_argument("--config", default=DEFAULT_CONFIG)
    sp.add_argument("--from", dest="from", help="期間開始 (YYYY-MM-DD)")
    sp.add_argument("--to", help="期間終了 (YYYY-MM-DD)")
    sp.set_defaults(func=cmd_detect)

    sp = sub.add_parser("report", help="Markdown レポートを出力")
    sp.add_argument("--config", default=DEFAULT_CONFIG)
    sp.add_argument("--out", default=DEFAULT_REPORTS, help="出力先ディレクトリ")
    sp.add_argument("--from", dest="from", help="期間開始 (YYYY-MM-DD)")
    sp.add_argument("--to", help="期間終了 (YYYY-MM-DD)")
    sp.set_defaults(func=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
