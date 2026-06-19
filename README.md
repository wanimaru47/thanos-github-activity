# github-activity

チームメンバーの GitHub 活動をレポーティングするためのワークスペース。

データは **GitHub → Fivetran → Snowflake** で連携されており、Snowflake を参照することで
GitHub API のレート制限を気にせず活動情報を取得できる。Snowflake への問い合わせは
[`thanos-management-mcp`](https://github.com/voyagegroup/thanos/tree/main/experimental/thanos-management-mcp)
（MCP サーバ）経由で行う。

## 構成

| パス | 役割 |
|---|---|
| `.mcp.json` | `thanos-management` MCP サーバへの接続設定（SSE / localhost:22930） |
| `.claude/skills/` | レポート生成スキルの置き場 |
| `reports/` | 生成レポートの出力先（`.gitignore` 済み。個人の稼働状況を含むためローカルのみ） |

## 前提

- MCP サーバ本体は `thanos` リポジトリ配下にある（このリポジトリには含めない）
- Snowflake 認証は SSO（`externalbrowser`）。初回クエリ時にブラウザ認証が走る

## セットアップ

### 1. MCP サーバを起動する

別ターミナルで `thanos` リポジトリの MCP サーバを起動しておく。

```bash
cd <path-to>/thanos/experimental/thanos-management-mcp

# 初回のみ: Snowflake 接続設定を作成し、snowflake.user に自分のメールを設定
cd app/src/main/resources
cp snowflake_connection.properties.template snowflake_connection.properties
#   snowflake.user=yourname@cartahd.com に編集

# 起動（デフォルト port 22930）
cd <path-to>/thanos/experimental/thanos-management-mcp
./gradlew jettyRun
```

### 2. このリポジトリで Claude Code を起動する

```bash
cd <path-to>/github-activity
claude
```

`.mcp.json` により `thanos-management` MCP サーバが認識される。
（ポートを変えて起動した場合は `.mcp.json` の URL を合わせる）

## 使い方

`.claude/skills/` 配下のスキルを実行してレポートを生成する。
生成物は `reports/` に出力する運用とする。

> レポートを Git で共有したい場合は `.gitignore` の `/reports/*` 行を外す。
> 内容にメンバーの稼働状況が含まれる点に留意すること。

## 参考

- MCP サーバ: https://github.com/voyagegroup/thanos/tree/main/experimental/thanos-management-mcp
- 既存スキルの参考実装: https://github.com/voyagegroup/thanos/blob/main/.claude/skills/app-team-activity-report/SKILL.md
