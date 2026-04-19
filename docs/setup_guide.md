# セットアップ & AWS適用手順

作成日: 2026-04-19

freee Remote MCP Serverを実際にAWS上に構築・稼働させるまでの完全手順。

---

## 全体の流れ

```
Step 1. freee開発者アカウントでアプリを作成（ブラウザ）
Step 2. freee OAuth認証を実施してトークン取得（ブラウザ + ターミナル）
Step 3. AWSリソースを準備（ターミナル）
Step 4. Secrets Managerに認証情報を登録（ターミナル）
Step 5. SAMでビルド & デプロイ（ターミナル）
Step 6. Claude Custom ConnectorにURLを登録（Claudeアプリ）
Step 7. 動作確認
```

---

## 前提条件

| 必要なもの | 確認方法 |
|-----------|---------|
| freeeアカウント（有料プランまたは試用） | freee.co.jp |
| AWSアカウント | aws.amazon.com |
| AWS CLI（設定済み） | `aws sts get-caller-identity` |
| AWS SAM CLI | `sam --version` |
| Python 3.12 | `python3 --version` |
| curl または Postman | トークン取得用 |

---

## Step 1. freeeアプリを作成する

### 1-1. freee Developersにアクセス

[https://developer.freee.co.jp/](https://developer.freee.co.jp/) にログインし、
「アプリ管理」→「新規アプリを作成」をクリックする。

### 1-2. アプリ設定

| 設定項目 | 入力値 |
|---------|--------|
| アプリ名 | 任意（例: `freee-mcp-server`） |
| 説明 | 任意 |
| コールバックURL | `urn:ietf:wg:oauth:2.0:oob`（初回トークン取得用） |
| 権限 | 「会計」にチェック（最低限） |

> **補足:** `urn:ietf:wg:oauth:2.0:oob` はOOB（Out-Of-Band）方式。
> 認可コードをブラウザに表示してコピーする方式なので、
> コールバックサーバー不要で個人利用に最適。

### 1-3. client_id と client_secret を控える

アプリ作成後に表示される以下の値を安全な場所に保存する。

```
client_id     = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
client_secret = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> ⚠️ `client_secret` はこの画面でしか確認できない。必ず保存すること。

---

## Step 2. OAuth認証でトークンを取得する

### 2-1. 認可URLにアクセスする

以下のURLをブラウザで開く（`YOUR_CLIENT_ID` を実際の値に置き換える）。

```
https://accounts.secure.freee.co.jp/public_api/authorize?client_id=YOUR_CLIENT_ID&redirect_uri=urn:ietf:wg:oauth:2.0:oob&response_type=code
```

**freeeの認可画面で「許可する」をクリックすると、画面に認可コードが表示される。**

```
認可コード例: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

この値をコピーして控えておく。

### 2-2. 認可コードをアクセストークンに交換する

ターミナルで以下のcurlを実行する（各変数を実際の値に置き換える）。

```bash
CLIENT_ID="YOUR_CLIENT_ID"
CLIENT_SECRET="YOUR_CLIENT_SECRET"
AUTH_CODE="YOUR_AUTH_CODE"   # Step 2-1でコピーした値

curl -X POST "https://accounts.secure.freee.co.jp/public_api/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "code=${AUTH_CODE}" \
  -d "redirect_uri=urn:ietf:wg:oauth:2.0:oob"
```

**レスポンス例:**
```json
{
  "access_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "token_type": "bearer",
  "expires_in": 21600,
  "refresh_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "scope": "read write",
  "created_at": 1713520000
}
```

`access_token` と `refresh_token` を控える。

> - `access_token` の有効期限: **6時間**（`expires_in: 21600`秒）
> - `refresh_token` の有効期限: **90日**（使用するたびに新しいものが発行される）

### 2-3. company_id を取得する

ターミナルで以下を実行して事業所IDを確認する。

```bash
ACCESS_TOKEN="YOUR_ACCESS_TOKEN"

curl -X GET "https://api.freee.co.jp/api/1/companies" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Accept: application/json"
```

**レスポンス例:**
```json
{
  "companies": [
    {
      "id": 1234567,
      "name": "自分の事業所名",
      ...
    }
  ]
}
```

`id` の値が `company_id`。この値を控える。

---

## Step 3. AWSリソースを準備する

### 3-1. AWS CLIのプロファイルを確認する

```bash
aws sts get-caller-identity
```

デプロイ先のアカウントIDとリージョンを確認しておく。

### 3-2. デプロイリージョンを確認する

```bash
# ap-northeast-1（東京）を推奨
aws configure get region
```

`ap-northeast-1` 以外を使う場合は `infra/samconfig.toml` の `region` を変更する。

---

## Step 4. Secrets Managerに認証情報を登録する

### 4-1. シークレットを新規作成する

```bash
aws secretsmanager create-secret \
  --name "freee/mcp-server" \
  --region "ap-northeast-1" \
  --description "freee Remote MCP Server OAuth credentials" \
  --secret-string '{
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "refresh_token": "YOUR_REFRESH_TOKEN",
    "access_token": "YOUR_ACCESS_TOKEN",
    "access_token_expires_at": "2026-04-19T10:00:00+09:00",
    "company_id": YOUR_COMPANY_ID
  }'
```

> ⚠️ `access_token_expires_at` は現在時刻から6時間後のISO 8601形式。
> 多少古くても問題ない（Lambda起動時に自動refreshされる）。

### 4-2. 登録内容を確認する

```bash
aws secretsmanager get-secret-value \
  --secret-id "freee/mcp-server" \
  --region "ap-northeast-1" \
  --query "SecretString" \
  --output text | python3 -m json.tool
```

全フィールドが正しく入っていることを確認する。

### 4-3. シークレットのARNを控える（後で使う）

```bash
aws secretsmanager describe-secret \
  --secret-id "freee/mcp-server" \
  --region "ap-northeast-1" \
  --query "ARN" \
  --output text
```

---

## Step 5. SAMでビルド & デプロイする

### 5-1. 依存パッケージのインストール確認

```bash
cd /home/keisuke/00_develop/freee
pip install -r requirements.txt
```

### 5-2. SAMビルド

```bash
sam build --template-file infra/template.yaml
```

正常終了すると `.aws-sam/` ディレクトリが作成される。

### 5-3. SAMデプロイ（初回）

```bash
sam deploy \
  --config-file infra/samconfig.toml \
  --config-env prod \
  --guided
```

`--guided` オプションで対話形式で確認できる。主な確認項目:

| 項目 | 入力値 |
|------|--------|
| Stack Name | `freee-mcp-server` |
| AWS Region | `ap-northeast-1` |
| Parameter StageName | `prod` |
| Parameter SecretName | `freee/mcp-server` |
| Parameter LogLevel | `INFO` |
| Confirm changes before deploy | `Y` |
| Allow SAM CLI IAM role creation | `Y` |
| Save arguments to config file | `Y` |

### 5-4. デプロイ結果の確認

デプロイ成功後に表示される `Outputs` から `ApiEndpoint` の値をメモする。

```
CloudFormation outputs from deployed stack
-----------------------------------------
Key    ApiEndpoint
Value  https://xxxxxxxxxx.execute-api.ap-northeast-1.amazonaws.com/prod/mcp
```

### 5-5. APIキーを取得する

```bash
# スタックのAPIキー名を確認
aws apigateway get-api-keys \
  --region ap-northeast-1 \
  --include-values \
  --query "items[?contains(name, 'freee-mcp')].{name:name, value:value}" \
  --output table
```

表示された `value` がAPIキー。Claude Custom Connectorへの登録に使用する。

### 5-6. 動作確認（curlで直接テスト）

```bash
API_URL="https://xxxxxxxxxx.execute-api.ap-northeast-1.amazonaws.com/prod/mcp"
API_KEY="YOUR_API_KEY"

# ヘルスチェック
curl -X GET "${API_URL%/mcp}/health" -H "x-api-key: ${API_KEY}"

# MCPのinitialize
curl -X POST "${API_URL}" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${API_KEY}" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "curl-test", "version": "1.0"}
    }
  }'

# ツール一覧取得
curl -X POST "${API_URL}" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${API_KEY}" \
  -d '{
    "jsonrpc": "2.0",
    "id": "2",
    "method": "tools/list",
    "params": {}
  }'

# 勘定科目一覧取得（freee API連携テスト）
curl -X POST "${API_URL}" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${API_KEY}" \
  -d '{
    "jsonrpc": "2.0",
    "id": "3",
    "method": "tools/call",
    "params": {
      "name": "freee_list_account_items",
      "arguments": {"type": "expense"}
    }
  }'
```

---

## Step 6. Claude Custom ConnectorにURLを登録する

### 6-1. Claudeアプリの設定を開く

1. Claudeアプリ（PC版）を開く
2. 設定 → 「Integrations」または「MCP Servers」（UIはバージョンにより異なる）
3. 「Add Remote MCP Server」または「Add Custom Connector」をクリック

### 6-2. 接続情報を入力する

| 項目 | 入力値 |
|------|--------|
| Server URL | `https://xxxxxxxxxx.execute-api.ap-northeast-1.amazonaws.com/prod/mcp` |
| 認証方式 | API Key |
| APIキー | Step 5-5で取得した値 |
| ヘッダー名 | `x-api-key` |

> **要確認:** Claude Custom ConnectorのUI・設定項目名はClaudeのバージョンにより異なる。
> 公式ドキュメントで最新の手順を確認すること。

### 6-3. ツールの確認

接続成功後、Claudeの会話画面でMCPツールが利用可能になる。
「freeeに支出登録」などのプロンプトで動作を確認する。

---

## Step 7. 2回目以降のデプロイ

コードを変更した場合:

```bash
cd /home/keisuke/00_develop/freee

# テスト実行
pytest

# ビルド & デプロイ
sam build --template-file infra/template.yaml
sam deploy --config-file infra/samconfig.toml --config-env prod
```

---

## 運用上の注意事項

### refresh_tokenの管理

| 状況 | 対応 |
|------|------|
| refresh_tokenが90日以上未使用 | 失効。Step 2からやり直してSecrets Managerを更新 |
| refresh後に新しいrefresh_tokenが発行された | Lambda側で自動更新される（要確認: freeeの仕様） |
| アクセストークンのrefreshに失敗 | CloudWatch Logsでエラーを確認 |

### トークン失効時の手動更新

```bash
# 新しいrefresh_tokenでSecrets Managerを更新する
aws secretsmanager put-secret-value \
  --secret-id "freee/mcp-server" \
  --region "ap-northeast-1" \
  --secret-string '{
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "refresh_token": "NEW_REFRESH_TOKEN",
    "access_token": "",
    "access_token_expires_at": "",
    "company_id": YOUR_COMPANY_ID
  }'
```

### APIキーのローテーション（3〜6ヶ月ごと推奨）

```bash
# 新しいAPIキーを作成
aws apigateway create-api-key \
  --region ap-northeast-1 \
  --enabled \
  --name "freee-mcp-server-prod-new"

# Usage Planに紐付け（APIキーIDを確認して実行）
aws apigateway create-usage-plan-key \
  --usage-plan-id YOUR_USAGE_PLAN_ID \
  --key-id NEW_API_KEY_ID \
  --key-type API_KEY

# Claude Custom Connectorの設定を新しいキーに更新してから旧キーを削除
aws apigateway delete-api-key --api-key OLD_API_KEY_ID
```

### ログの確認

```bash
# 最新のLambdaログを確認
aws logs tail /aws/lambda/freee-mcp-server-prod \
  --region ap-northeast-1 \
  --follow
```

---

## トラブルシューティング

| 症状 | 原因 | 対応 |
|------|------|------|
| `ResourceNotFoundException` | Secrets Managerにシークレットがない | Step 4を再実行 |
| `AccessDeniedException` | Lambda IAMロールの権限不足 | `infra/iam_policy.json` を確認してIAMを修正 |
| `401 Unauthorized` (freee API) | access_tokenが失効 | refresh_tokenが有効ならLambdaが自動更新。失効ならStep 2からやり直し |
| `422 Unprocessable Entity` | freee APIのバリデーションエラー | CloudWatch Logsのエラー詳細を確認。`account_item_id` / `tax_code` が正しいか確認 |
| MCP接続できない | APIキーが違う or エンドポイントURLが間違い | Step 5-5, 5-6を再確認 |
| タイムアウト | Lambda実行時間が28秒超 | freee API応答遅延の可能性。CloudWatch Logsで確認 |
