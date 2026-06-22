---
name: pr-leadtime-stats
description: PR のリードタイム（作成→マージ）をメンバー（PR作者）ごとに集計し、件数・平均・分散・標準偏差・中央値・80%tile を MCP(Snowflake) 経由で算出する。「リードタイム統計」「PRリードタイム」「lead time」「リードタイムの平均/中央値/分位点」で使う。
allowed-tools: mcp__thanos-management__query, mcp__thanos-management__describe_table, Write, Read
argument-hint: "[from-date] [to-date] [min-count] [team-slug]"
---

# pr-leadtime-stats

PR のリードタイム分布を**メンバー（PR作者）ごと**に統計量で要約するスキル。

- **リードタイム** = `issue_merged.MERGED_AT` − `issue.CREATED_AT`（PR 作成からマージまで）
- 出力統計: **件数 n / 平均 / 分散 / 標準偏差 / 中央値 / 80%tile**（時間単位）
- すべて **Snowflake 側の集計関数で完結**させる。生レコードは引かない
  （GROUP BY 集計のみ。行数上限による切り捨てを回避する。[[activity-monitor-aggregate-to-avoid-row-cap]]）

## 設計上の前提（実データで検証済み）

- **統計量はすべて SQL 関数で出せる**: `AVG` / `VARIANCE`（= 標本分散 VAR_SAMP）/ `STDDEV` /
  `MEDIAN` / `APPROX_PERCENTILE(expr, 0.8)`。
  `PERCENTILE_CONT ... WITHIN GROUP` 構文はこの MCP では表現できないため、
  80%tile は **`APPROX_PERCENTILE`（近似）** を使う。誤差は監視用途では許容範囲。
- **時間換算は秒ベース + `DIV0` で行う**。`DATEDIFF('hour', ...)` は整数切り捨てで
  1時間未満の PR がすべて 0 になり中央値が潰れる。
  `DATEDIFF('second', created, merged)` を基準に `DIV0(x, 3600)` で時間へ換算する。
  分散（時間²）は秒²を `DIV0(x, 12960000)`（= 3600²）で換算する。
- **日時フィルタは文字列日付**で渡す（`{"type": "STRING", "text": "2026-01-01"}`）。INT は型エラー。
- **bot / Organization を除く**ため `user.TYPE = 'User'` を必ず AND する。
- **`HAVING` は当 MCP で確実に効かない**。少数 PR（`n` が小さい）メンバーの除外は
  **取得後にクライアント側で `n >= min-count` でフィルタ**する。
- **クエリ結果の日時はエポックミリ秒で返る**が、本スキルは集計値（数値）のみ返すため変換不要。

## パラメータ

`$ARGUMENTS` = `[from-date] [to-date] [min-count] [team-slug]`

- `from-date` / `to-date`（`YYYY-MM-DD`）: **マージ日時**の範囲。`MERGED_AT >= from` かつ `MERGED_AT < to`。
  未指定なら `to` = 実行日翌日、`from` = その90日前。
- `min-count`: レポートに載せる最小マージ PR 数。未指定なら `5`。
  これ未満のメンバーは「参考」として別枠表示（平均/分位点が母数不足で不安定なため）。
- `team-slug`: チームで絞る場合の team SLUG（例 `thanos-app`）。未指定なら全 `User`。
  指定時は **手順 0 でメンバー USER_ID を解決**し、メインクエリ WHERE に
  `i.USER_ID` の OR 列挙を AND する（`IN` は使わない）。`u.TYPE='User'` 条件は外してよい
  （チームメンバーは User 確定のため）。

### 0. （team-slug 指定時のみ）メンバー USER_ID 解決

[[activity-monitor]] と同じクエリで対象チームの `USER_ID` を引く。SLUG はメンバーの
入れ替えがあるため**毎回動的に解決**する（ID 直書きしない）。

```json
{
  "select": [{"expr": {"ref": "u.ID"}, "alias": "USER_ID"}, {"expr": {"ref": "u.LOGIN"}, "alias": "LOGIN"}],
  "from": {"name": "raw.github_zucks.team", "alias": "t"},
  "join": [
    {"table": {"name": "raw.github_zucks.team_membership", "alias": "tm"}, "type": "INNER",
     "on": {"binaryOperator": "EQUALS", "left": {"ref": "t.ID"}, "right": {"ref": "tm.TEAM_ID"}}},
    {"table": {"name": "raw.github_zucks.user", "alias": "u"}, "type": "INNER",
     "on": {"binaryOperator": "EQUALS", "left": {"ref": "tm.USER_ID"}, "right": {"ref": "u.ID"}}}
  ],
  "where": {"expression": {"binaryOperator": "EQUALS", "left": {"ref": "t.SLUG"}, "right": {"type": "STRING", "text": "{TEAM_SLUG}"}}},
  "limit": 100
}
```

得られた `USER_ID` を手順 1 の WHERE に OR 列挙で差し込む:

```json
{"or": [
  {"binaryOperator": "EQUALS", "left": {"ref": "i.USER_ID"}, "right": {"type": "INT", "text": "{ID_1}"}},
  {"binaryOperator": "EQUALS", "left": {"ref": "i.USER_ID"}, "right": {"type": "INT", "text": "{ID_2}"}}
]}
```

## 処理手順

### 1. クエリ実行（1本で全統計を取得）

`mcp__thanos-management__query` を以下のテンプレートで実行する。
`{FROM}` / `{TO}` を期間で置換する。`orderBy` は中央値降順（遅い人を上に）。

```json
{
  "select": [
    {"expr": {"ref": "LOGIN"}, "alias": "author"},
    {"expr": {"function": "COUNT", "args": [{"ref": "MERGED_AT"}]}, "alias": "n"},
    {"expr": {"function": "ROUND", "args": [
      {"function": "DIV0", "args": [
        {"function": "AVG", "args": [{"function": "DATEDIFF", "args": [{"type": "STRING", "text": "second"}, {"ref": "i.CREATED_AT"}, {"ref": "MERGED_AT"}]}]},
        {"type": "INT", "text": "3600"}]},
      {"type": "INT", "text": "2"}]}, "alias": "mean_h"},
    {"expr": {"function": "ROUND", "args": [
      {"function": "DIV0", "args": [
        {"function": "VARIANCE", "args": [{"function": "DATEDIFF", "args": [{"type": "STRING", "text": "second"}, {"ref": "i.CREATED_AT"}, {"ref": "MERGED_AT"}]}]},
        {"type": "INT", "text": "12960000"}]},
      {"type": "INT", "text": "2"}]}, "alias": "variance_h2"},
    {"expr": {"function": "ROUND", "args": [
      {"function": "DIV0", "args": [
        {"function": "STDDEV", "args": [{"function": "DATEDIFF", "args": [{"type": "STRING", "text": "second"}, {"ref": "i.CREATED_AT"}, {"ref": "MERGED_AT"}]}]},
        {"type": "INT", "text": "3600"}]},
      {"type": "INT", "text": "2"}]}, "alias": "stddev_h"},
    {"expr": {"function": "ROUND", "args": [
      {"function": "DIV0", "args": [
        {"function": "MEDIAN", "args": [{"function": "DATEDIFF", "args": [{"type": "STRING", "text": "second"}, {"ref": "i.CREATED_AT"}, {"ref": "MERGED_AT"}]}]},
        {"type": "INT", "text": "3600"}]},
      {"type": "INT", "text": "2"}]}, "alias": "median_h"},
    {"expr": {"function": "ROUND", "args": [
      {"function": "DIV0", "args": [
        {"function": "APPROX_PERCENTILE", "args": [{"function": "DATEDIFF", "args": [{"type": "STRING", "text": "second"}, {"ref": "i.CREATED_AT"}, {"ref": "MERGED_AT"}]}, {"type": "DOUBLE", "text": "0.8"}]},
        {"type": "INT", "text": "3600"}]},
      {"type": "INT", "text": "2"}]}, "alias": "p80_h"}
  ],
  "from": {"name": "raw.github_zucks.issue", "alias": "i"},
  "join": [
    {"type": "INNER", "table": {"name": "raw.github_zucks.issue_merged", "alias": "m"},
     "on": {"binaryOperator": "EQUALS", "left": {"ref": "m.ISSUE_ID"}, "right": {"ref": "i.ID"}}},
    {"type": "INNER", "table": {"name": "raw.github_zucks.user", "alias": "u"},
     "on": {"binaryOperator": "EQUALS", "left": {"ref": "u.ID"}, "right": {"ref": "i.USER_ID"}}}
  ],
  "where": {"expression": {"and": [
    {"binaryOperator": "EQUALS", "left": {"ref": "i.PULL_REQUEST"}, "right": {"type": "BOOLEAN", "text": "true"}},
    {"binaryOperator": "GREATER_THAN_OR_EQUALS", "left": {"ref": "m.MERGED_AT"}, "right": {"type": "STRING", "text": "{FROM}"}},
    {"binaryOperator": "LESS_THAN", "left": {"ref": "m.MERGED_AT"}, "right": {"type": "STRING", "text": "{TO}"}},
    {"binaryOperator": "EQUALS", "left": {"ref": "u.TYPE"}, "right": {"type": "STRING", "text": "User"}}
  ]}},
  "groupBy": [{"expr": {"ref": "LOGIN"}}],
  "orderBy": [{"expr": {"ref": "median_h"}, "order": "DESC"}],
  "limit": 500
}
```

> 注意: `i.CREATED_AT` は `issue` と `user` 両方に存在し曖昧になるため **必ず `i.` で修飾**する。
> `MERGED_AT` は `issue_merged` 固有なので修飾不要。

### 2. クライアント側でフィルタ・整形

- `n >= min-count` のメンバーを**本表**、`n < min-count` を**参考（母数不足）**に分ける。
- 必要に応じてチーム（`thanos-app`）に絞る場合は、先に
  [[activity-monitor]] の「2. チームメンバー取得」で `USER_ID` を引き、
  WHERE に `i.USER_ID` の OR 列挙を AND する（`IN` は使わない）。

### 3. レポート出力

`reports/pr-leadtime-{FROM}-{TO}.md` に Write し、会話では本表と所見を簡潔に伝える。
表は中央値降順。列は `author | n | mean_h | median_h | p80_h | stddev_h | variance_h2`。

## 解釈の指針

- **中央値で序列を見る／平均は外れ値チェックに使う**。`mean_h ≫ median_h` のメンバーは
  「普段は速いが一部の PR が長期放置」を意味する（分散・標準偏差が大きく出る）。
- **80%tile** は「悪い方の実力」。SLO（例: 80% を 24h 以内）の達成判定に使う。
- `n` が小さいメンバーの分位点は信用しない（`min-count` で足切り）。
- リードタイムを**レビュー着手以降**で見たい場合は、起点を
  `pull_request_ready_for_review_history`（Ready 化時刻）に差し替える。Draft 期間を除外できる。

## テーブル参照

| テーブル | 主要カラム | 用途 |
|---|---|---|
| `raw.github_zucks.issue` | ID, PULL_REQUEST, USER_ID, CREATED_AT | PR 起点（作成時刻・作者） |
| `raw.github_zucks.issue_merged` | ISSUE_ID, MERGED_AT | マージ時刻 |
| `raw.github_zucks.user` | ID, LOGIN, TYPE | 作者名解決 / bot 除外 |
| `raw.github_zucks.team` / `team_membership` | SLUG, TEAM_ID, USER_ID | （任意）チーム絞り込み |
