# freee Remote MCP Server

ClaudeアプリからfreeeへのAI支出登録を実現する、AWS Lambda上のRemote MCPサーバー。

## 概要

| 項目 | 内容 |
|------|------|
| 用途 | Claude → freee 支出登録 |
| 構成 | API Gateway + Lambda |
| 認証情報 | AWS Secrets Manager |
| 言語 | Python 3.12 |
| デプロイ | AWS SAM |

## ディレクトリ構成

```
freee/
├── README.md
├── requirements.txt          # Lambda本番依存
├── requirements-dev.txt      # テスト用依存
├── pytest.ini
│
├── docs/
│   ├── requirements.md       # 要件定義書
│   ├── architecture.md       # アーキテクチャ設計
│   ├── mvp_scope.md          # MVPスコープ定義
│   ├── mcp_tools.md          # MCP ツール定義
│   ├── freee_oauth_flow.md   # freee OAuth フロー
│   └── security.md           # セキュリティ設計
│
├── infra/
│   ├── template.yaml         # AWS SAM テンプレート
│   ├── samconfig.toml        # SAM CLI 設定
│   └── iam_policy.json       # Lambda IAM ポリシー（参考）
│
├── app/
│   ├── handler.py            # Lambda エントリポイント
│   ├── mcp_router.py         # MCP JSON-RPC ルーター
│   ├── tools/
│   │   ├── __init__.py       # ツールレジストリ
│   │   ├── freee_list_account_items.py
│   │   ├── freee_list_tax_codes.py
│   │   ├── freee_validate_expense_input.py
│   │   └── freee_create_expense.py
│   ├── freee/
│   │   ├── __init__.py
│   │   ├── auth.py           # OAuth トークン管理
│   │   └── client.py         # freee API クライアント
│   └── utils/
│       ├── __init__.py
│       └── secrets.py        # Secrets Manager ヘルパー
│
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_mcp_router.py
    │   ├── test_validate_expense_input.py
    │   ├── test_secrets.py
    │   └── test_freee_auth.py
    └── integration/
        ├── test_handler.py
        └── test_freee_client.py
```

## セットアップ

### 1. freee OAuth 初回認証

1. [freee developers](https://developer.freee.co.jp/) でアプリを作成
2. `client_id` と `client_secret` を取得
3. OAuth認証フローでアクセストークンとリフレッシュトークンを取得
4. `company_id` を取得（freeeのURL等から確認）

詳細は [docs/freee_oauth_flow.md](docs/freee_oauth_flow.md) を参照。

### 2. Secrets Manager に認証情報を登録

```bash
aws secretsmanager create-secret \
  --name "freee/mcp-server" \
  --region ap-northeast-1 \
  --secret-string '{
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "refresh_token": "YOUR_REFRESH_TOKEN",
    "access_token": "",
    "access_token_expires_at": "",
    "company_id": YOUR_COMPANY_ID
  }'
```

### 3. ローカルテスト実行

```bash
cd freee
pip install -r requirements-dev.txt
pytest
```

### 4. AWSデプロイ

```bash
cd freee
sam build --template-file infra/template.yaml
sam deploy --config-file infra/samconfig.toml
```

デプロイ後、Outputsに表示される `ApiEndpoint` URLをメモする。

### 5. Claude Custom Connector への登録

1. Claude設定 → Custom Connectors → Remote MCP を追加
2. エンドポイントURL: `https://<api-id>.execute-api.ap-northeast-1.amazonaws.com/prod/mcp`
3. 認証: APIキー（API Gatewayで発行したキー）

## テスト

```bash
# 全テスト実行
pytest

# 単体テストのみ
pytest tests/unit/

# 結合テストのみ
pytest tests/integration/

# カバレッジ付き
pytest --cov=app --cov-report=term-missing
```

## 利用フロー（Claudeアプリから）

1. スマホのClaudeアプリにレシート画像を送る
2. Claudeが画像を読み取り（OCRはClaude本体）
3. `freee_list_account_items` → 勘定科目一覧取得
4. `freee_list_tax_codes` → 税区分一覧取得
5. `freee_validate_expense_input` → 入力確認（任意）
6. `freee_create_expense` → freeeに支出登録
7. 登録完了メッセージを受け取る

## 要確認事項

詳細は [docs/requirements.md](docs/requirements.md) の「要確認事項」を参照。

- freee APIエンドポイントの最新仕様（取引登録リクエスト形式）
- refresh_tokenの有効期限
- Claude Custom ConnectorのMCPプロトコルバージョン
- OAuthスコープの確定

## セキュリティ注意事項

- `.env` ファイルをGitにコミットしない
- `client_secret` / `refresh_token` をLambda環境変数に書かない
- APIキーをコードに書かない

詳細は [docs/security.md](docs/security.md) を参照。
