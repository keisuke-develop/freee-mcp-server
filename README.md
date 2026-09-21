# freee Remote MCP Server

Claude アプリから freee へ支出を登録するための、AWS Lambda 上で動く Remote MCP サーバー。
スマホの Claude にレシート画像を送ると、勘定科目と税区分を引いたうえで freee に登録される。

> **非公式ツールです。** 個人が自分の経費登録のために作ったもので、freee株式会社とは一切関係ありません。
> freee は freee株式会社の登録商標です。本ソフトウェアの利用により生じた損害について作者は責任を負いません。
> freee API の利用にあたっては、[freee developers](https://developer.freee.co.jp/) の利用規約を各自でご確認ください。

## 概要

| 項目 | 内容 |
|------|------|
| 用途 | Claude → freee 支出登録 |
| 構成 | HTTP API + Lambda + Cognito + DynamoDB + Secrets Manager |
| 認証 | MCP クライアント向けに OAuth 2.1 + PKCE を自前実装。エンドユーザー認証は Cognito |
| 言語 | Python 3.13 |
| デプロイ | AWS SAM |
| テスト | pytest 83 ケース（unit / integration） |

## 設計上の要点

**freee の認証情報を Claude 側に渡さない。** MCP クライアントに渡すのはこのサーバーが発行するトークンだけで、
freee の `client_id` / `client_secret` / `refresh_token` は Secrets Manager から外に出さない。
どの値をどこに置いてよいかの整理は [docs/security.md](docs/security.md) にまとめた。

**OAuth 2.1 + PKCE をサーバー側で実装している。** Claude の Remote MCP は OAuth クライアントとして振る舞うため、
認可サーバーの役割をこちら側で持つ必要がある。認可コードとリフレッシュトークンは DynamoDB で管理し、
エンドユーザーの認証だけ Cognito に委譲している。フローは [docs/freee_oauth_flow.md](docs/freee_oauth_flow.md) を参照。

**IAM は最小権限で切っている。** Lambda 実行ロールに与えるのは、対象シークレットへの読み書きと
CloudWatch Logs、該当 DynamoDB テーブルのみ。ポリシーは [infra/iam_policy.json](infra/iam_policy.json) にある。

## ドキュメント

| ファイル | 内容 |
|---|---|
| [docs/requirements.md](docs/requirements.md) | 要件定義 |
| [docs/mvp_scope.md](docs/mvp_scope.md) | MVP スコープ（何を作らないか） |
| [docs/architecture.md](docs/architecture.md) | アーキテクチャ設計 |
| [docs/mcp_tools.md](docs/mcp_tools.md) | MCP ツール定義 |
| [docs/freee_oauth_flow.md](docs/freee_oauth_flow.md) | OAuth フロー |
| [docs/security.md](docs/security.md) | セキュリティ設計（シークレットの置き場所と IAM） |
| [docs/deployment_flow.md](docs/deployment_flow.md) | デプロイ手順 |
| [docs/setup_guide.md](docs/setup_guide.md) | セットアップ手順 |
| [docs/test_strategy_and_results.md](docs/test_strategy_and_results.md) | テスト戦略と結果 |

## ディレクトリ構成

```
.
├── app/
│   ├── lambda_handler.py     # Lambda エントリポイント
│   ├── mcp_router.py         # MCP JSON-RPC ルーター
│   ├── oauth_server.py       # OAuth 2.1 + PKCE 認可サーバー
│   ├── tools/                # MCP ツール
│   │   ├── freee_list_account_items.py
│   │   ├── freee_list_tax_codes.py
│   │   ├── freee_validate_expense_input.py
│   │   └── freee_create_expense.py
│   ├── freee/
│   │   ├── auth.py           # freee OAuth トークン管理
│   │   └── client.py         # freee API クライアント
│   └── utils/
│       ├── http.py           # HTTP 共通処理
│       └── secrets.py        # Secrets Manager ヘルパー
│
├── infra/
│   ├── template.yaml         # AWS SAM テンプレート
│   ├── samconfig.toml        # SAM CLI 設定
│   └── iam_policy.json       # Lambda IAM ポリシー
│
├── scripts/
│   └── upsert_freee_secret.sh
│
├── docs/                     # 設計ドキュメント（上表）
├── tests/
│   ├── unit/                 # 単体テスト
│   └── integration/          # 結合テスト（外部APIはモック）
│
├── .github/workflows/ci.yml  # pytest + SAM テンプレート検証
├── requirements.txt          # Lambda 本番依存
├── requirements-dev.txt      # テスト用依存
└── pytest.ini
```

## セットアップ

### 1. freee OAuth の初回認証

1. [freee developers](https://developer.freee.co.jp/) でアプリを作成
2. `client_id` と `client_secret` を取得
3. OAuth 認証フローでアクセストークンとリフレッシュトークンを取得
4. `company_id` を取得

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

`scripts/upsert_freee_secret.sh` でも登録できる。

### 3. ローカルでテストを実行

```bash
pip install -r requirements-dev.txt
pytest
```

外部 API は moto とモックで置き換えているため、実際の freee / AWS には接続しない。

### 4. AWS へデプロイ

```bash
sam build --template-file infra/template.yaml
sam deploy --config-file infra/samconfig.toml
```

デプロイ後、Outputs の `ApiEndpoint` を控える。

### 5. Claude への登録

1. Claude 設定 → Remote MCP を追加
2. エンドポイント URL: `https://<api-id>.execute-api.ap-northeast-1.amazonaws.com/mcp`
3. `OAuth Client ID` / `OAuth Client Secret` は空欄のまま保存
4. 接続時に表示される Cognito のログイン画面で認証する

Cognito はエンドユーザー認証だけに使い、MCP 用のトークンはこのサーバー自身が発行する。
Claude 側に freee の認証情報を登録する必要はない。

## 利用フロー

1. Claude アプリにレシート画像を送る
2. Claude が画像を読み取る（OCR は Claude 側）
3. `freee_list_account_items` → 勘定科目一覧を取得
4. `freee_list_tax_codes` → 税区分一覧を取得
5. `freee_validate_expense_input` → 入力内容を検証
6. `freee_create_expense` → freee に支出を登録

## テスト

```bash
pytest                                        # 全テスト
pytest tests/unit/                            # 単体のみ
pytest tests/integration/                     # 結合のみ
pytest --cov=app --cov-report=term-missing    # カバレッジ付き
```

方針は [docs/test_strategy_and_results.md](docs/test_strategy_and_results.md) を参照。

## 制約と未確認事項

作った時点で確定していないもの。実装は暫定で、動作を見ながら追随する前提。

- freee API の取引登録リクエスト形式は仕様変更の可能性がある
- `refresh_token` の有効期限は freee 側の仕様に依存する
- Claude Custom Connector の MCP プロトコルバージョンは変わりうる
- OAuth スコープは必要最小限に絞る方針だが、確定していない

詳細は [docs/requirements.md](docs/requirements.md) の「要確認事項」を参照。

## セキュリティ

- `.env` はコミットしない（`.gitignore` で除外済み。設定例は `.env.example`）
- `client_secret` / `refresh_token` / `access_token` を Lambda 環境変数に置かない
- Cognito のログイン情報をコードに書かない

方針の詳細は [docs/security.md](docs/security.md) を参照。

## ライセンス

MIT License. 詳細は [LICENSE](LICENSE) を参照。
