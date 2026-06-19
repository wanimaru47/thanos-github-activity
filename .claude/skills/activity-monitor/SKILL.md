---
name: activity-monitor
description: thanos-app チームメンバーの GitHub 活動を MCP(Snowflake) 経由で収集し、ローカル SQLite に履歴を蓄積して、極端に活動が少ないメンバーを検知・警告する。「活動モニタリング」「低活動メンバー検知」「フォロー漏れチェック」で使う。
allowed-tools: mcp__thanos-management__query, mcp__thanos-management__describe_table, mcp__thanos-management__list_tables, Write, Read, Bash
argument-hint: "[from-date] [to-date]"
---

# activity-monitor

thanos-app チームの GitHub 活動をモニタリングし、極端に活動が少ないメンバーを検知するスキル。

パイプライン:

```
MCP(Snowflake) で activity 取得 → 収集JSONを書き出し
  → activity-monitor ingest で SQLite に蓄積
  → activity-monitor detect / report で低活動メンバーを検知・警告
```

決定的な処理（DB 取り込み・集計・閾値判定・レポート生成）は同梱の Python CLI
`activity-monitor` が担う。このスキルは MCP からの収集と CLI の呼び出しに徹する。

## 設定

- 対象チーム: `thanos-app`（voyagegroup org、team.SLUG = `thanos-app`）
- 対象期間: デフォルト2週間（実行日の14日前〜実行日）。`$ARGUMENTS` で `from to` 指定可
- ローカル DB: `data/activity.db`（gitignore 済み）
- 収集中間 JSON: `data/incoming/collection-{from}-{to}.json`（gitignore 済み）
- 出力レポート: `reports/activity-{from}-{to}.md`（gitignore 済み）
- 閾値設定: `config.toml`

## 重要な前提（実データで検証済み）

- **日時フィルタは文字列日付で渡す**。`CREATED_AT` / `SUBMITTED_AT` は TIMESTAMP_TZ 型で、
  `{"type": "STRING", "text": "2026-06-05"}` のように比較する。
  INT(エポックms) を渡すと型エラーになる。
- **クエリ結果の日時はエポックミリ秒（整数）で返る**。JSON に書く `created_at` 等は
  ISO 8601(UTC) に変換する（例: `1781253230000` → `2026-06-12T...Z`）。
- **メンバー ID の絞り込みは OR 条件**で列挙する（`IN` は使わない / 動作未保証）。
- **JOIN type は `INNER` / `LEFT_OUTER`** を使う。
- `repository.FULL_NAME` は `owner/name` 形式。リンク生成に使う。

## 処理手順

### 1. 対象期間の決定

- `$ARGUMENTS` に `from to`（`YYYY-MM-DD`）があればそれを使う
- 無ければ実行日を `to`、その14日前を `from` とする
- フィルタ用に `to_plus_1 = to + 1日` を用意する（`< to_plus_1` で当日を含める）

### 2. チームメンバー取得

```json
{
  "select": [
    {"expr": {"ref": "u.ID"}, "alias": "USER_ID"},
    {"expr": {"ref": "u.LOGIN"}, "alias": "LOGIN"},
    {"expr": {"ref": "u.NAME"}, "alias": "NAME"}
  ],
  "from": {"name": "raw.github_zucks.team", "alias": "t"},
  "join": [
    {"table": {"name": "raw.github_zucks.team_membership", "alias": "tm"}, "type": "INNER",
     "on": {"binaryOperator": "EQUALS", "left": {"ref": "t.ID"}, "right": {"ref": "tm.TEAM_ID"}}},
    {"table": {"name": "raw.github_zucks.user", "alias": "u"}, "type": "INNER",
     "on": {"binaryOperator": "EQUALS", "left": {"ref": "tm.USER_ID"}, "right": {"ref": "u.ID"}}}
  ],
  "where": {"expression": {"binaryOperator": "EQUALS", "left": {"ref": "t.SLUG"}, "right": {"type": "STRING", "text": "thanos-app"}}},
  "limit": 100
}
```

得られた `USER_ID` のリストを、以降の各クエリの OR 条件に使う。

### 3. データ収集（4シグナル）

各クエリの WHERE には「期間（`>= from` かつ `< to_plus_1`）」と
「メンバー USER_ID の OR 列挙」を AND で必ず含める。以下は条件部を省略した骨子。

#### 3a. PR 作成（`issue` WHERE PULL_REQUEST=true）

```json
{
  "select": [
    {"expr": {"ref": "i.USER_ID"}, "alias": "USER_ID"},
    {"expr": {"ref": "r.FULL_NAME"}, "alias": "REPO_FULL_NAME"},
    {"expr": {"ref": "i.NUMBER"}, "alias": "NUMBER"},
    {"expr": {"ref": "i.CREATED_AT"}, "alias": "CREATED_AT"},
    {"expr": {"ref": "i.STATE"}, "alias": "STATE"},
    {"expr": {"ref": "im.MERGED_AT"}, "alias": "MERGED_AT"}
  ],
  "from": {"name": "raw.github_zucks.issue", "alias": "i"},
  "join": [
    {"table": {"name": "raw.github_zucks.repository", "alias": "r"}, "type": "INNER",
     "on": {"binaryOperator": "EQUALS", "left": {"ref": "i.REPOSITORY_ID"}, "right": {"ref": "r.ID"}}},
    {"table": {"name": "raw.github_zucks.issue_merged", "alias": "im"}, "type": "LEFT_OUTER",
     "on": {"binaryOperator": "EQUALS", "left": {"ref": "i.ID"}, "right": {"ref": "im.ISSUE_ID"}}}
  ],
  "where": {"expression": {"and": [
    {"binaryOperator": "GREATER_THAN_OR_EQUALS", "left": {"ref": "i.CREATED_AT"}, "right": {"type": "STRING", "text": "{FROM}"}},
    {"binaryOperator": "LESS_THAN", "left": {"ref": "i.CREATED_AT"}, "right": {"type": "STRING", "text": "{TO_PLUS_1}"}},
    {"binaryOperator": "EQUALS", "left": {"ref": "i.PULL_REQUEST"}, "right": {"type": "BOOLEAN", "text": "true"}},
    {"or": [
      {"binaryOperator": "EQUALS", "left": {"ref": "i.USER_ID"}, "right": {"type": "INT", "text": "{MEMBER_ID_1}"}}
    ]}
  ]}},
  "limit": 1000
}
```

→ JSON `pr_created[]`: `{user_id, repo_full_name, number, created_at(ISO), state, merged_at(ISO|null)}`

#### 3b. PR レビュー（`pull_request_review`）

`pull_request_review` → `pull_request` → `issue` → `repository` を結合。
`SUBMITTED_AT` で期間を絞り、`prv.USER_ID` を OR 列挙。
自分の PR への self-review を除くため `prv.USER_ID != i.USER_ID`（PR作成者）を AND する。

主な select: `prv.USER_ID`, `r.FULL_NAME`, `i.NUMBER`(pr_number), `prv.STATE`, `prv.SUBMITTED_AT`
結合キー: `prv.PULL_REQUEST_ID = pr.ID`, `pr.ISSUE_ID = i.ID`, `i.REPOSITORY_ID = r.ID`

→ JSON `pr_reviews[]`: `{user_id, repo_full_name, pr_number, state, submitted_at(ISO)}`（1行=1レビュー）

#### 3c. Issue コメント（`issue_comment` × `issue` WHERE PULL_REQUEST=false）

`issue_comment ic` → `issue i` → `repository r` を結合。
`ic.CREATED_AT` で期間、`ic.USER_ID` を OR 列挙、`i.PULL_REQUEST = false`。
`ic.USER_ID, i.NUMBER, r.FULL_NAME` で GROUP BY し、`COUNT(ic.ID)` と `MAX(ic.CREATED_AT)`。

→ JSON `issue_comments[]`: `{user_id, repo_full_name, issue_number, created_at(ISO), count: COMMENT_COUNT}`

#### 3d. PR レビューコメント（`pull_request_review_comments`）

`prc` → `pull_request pr` → `issue i` → `repository r` を結合。
`prc.CREATED_AT` で期間、`prc.USER_ID` を OR 列挙。
`prc.USER_ID, i.NUMBER, r.FULL_NAME` で GROUP BY、`COUNT(prc.ID)` と `MAX(prc.CREATED_AT)`。

→ JSON `pr_review_comments[]`: `{user_id, repo_full_name, pr_number, created_at(ISO), count}`

### 4. 収集 JSON の書き出し

次の形に整形して `data/incoming/collection-{FROM}-{TO}.json` に Write する。
（`count` 省略時は 1 として集計される。3c/3d はグループ済みなので `count` を必ず付ける）

```json
{
  "period": {"from": "{FROM}", "to": "{TO}"},
  "collected_at": "{NOW_ISO_UTC}",
  "members": [{"user_id": 0, "login": "", "name": ""}],
  "pr_created": [],
  "pr_reviews": [],
  "issue_comments": [],
  "pr_review_comments": []
}
```

`members` には**取得した全メンバー**を入れる（活動 0 のメンバーも検知対象に含めるため必須）。

### 5. 取り込み・検知・レポート

リポジトリルートで CLI を実行する。

```bash
uv run activity-monitor ingest data/incoming/collection-{FROM}-{TO}.json
uv run activity-monitor detect
uv run activity-monitor report
```

- `detect` は warn/critical のメンバーを標準出力に表示する
- `report` は `reports/activity-{FROM}-{TO}.md` を生成する（既存は上書きせず連番）
- 閾値は `config.toml`（`critical_total_max` / `warn_total_min` / `warn_pr_created_min`）

### 6. 結果の要約

生成されたレポートを Read し、要確認メンバー（critical/warn）とその理由を会話で簡潔に伝える。

## 検知の考え方（絶対閾値）

- `critical`: 期間内の活動合計が `critical_total_max` 以下（既定 0 = ほぼ無活動）
- `warn`: 活動合計が `warn_total_min` 未満、または PR 作成が `warn_pr_created_min` 未満
- 履歴は `collections` / `member_activity` に時系列で蓄積され、将来のトレンド検知の土台になる

## テーブル参照

| テーブル | 主要カラム | 用途 |
|---|---|---|
| `raw.github_zucks.team` / `team_membership` / `user` | SLUG, TEAM_ID, USER_ID, ID, LOGIN, NAME | メンバー解決 |
| `raw.github_zucks.issue` | ID, NUMBER, REPOSITORY_ID, PULL_REQUEST, USER_ID, CREATED_AT, STATE | PR作成 / Issue判定 |
| `raw.github_zucks.issue_merged` | ISSUE_ID, MERGED_AT | マージ判定 |
| `raw.github_zucks.pull_request_review` | PULL_REQUEST_ID, USER_ID, STATE, SUBMITTED_AT | PRレビュー |
| `raw.github_zucks.pull_request` | ID, ISSUE_ID | review→issue 結合 |
| `raw.github_zucks.issue_comment` | ID, ISSUE_ID, USER_ID, CREATED_AT | Issueコメント |
| `raw.github_zucks.pull_request_review_comments` | ID, PULL_REQUEST_ID, USER_ID, CREATED_AT | PRレビューコメント |
| `raw.github_zucks.repository` | ID, FULL_NAME | リポジトリ名 |
