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
Step 6. Claude / Claude Code にURLを登録（Claudeアプリ）
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
| Python 3.13 | `python3 --version` |
| curl または Postman | トークン取得用 |

---

## Step 1. freeeアプリを作成する

### 1-1. freee Developersにアクセス

[https://developer.freee.co.jp/](https://developer.freee.co.jp/) にログインした後、
トップ上部メニューの `freeeアプリストア` から開発者向け画面に進む。

その後の導線は以下。

1. 開発者向けアプリ一覧画面で、アプリを作成する事業所を選択
2. 右上の `アプリ管理` をクリック
3. `新規追加` をクリック

> **重要:** `APIリファレンス` 画面や、freee本体の「アカウント管理」画面では
> `client_id` / `client_secret` は取得できない。
> 必ず **freeeアプリストアの開発者ページ** から `アプリ管理` に進むこと。
>
> `アプリ管理` が見つからない場合は、
> - 開発者向けアプリ一覧画面ではなく `developer.freee.co.jp` の記事ページを見ている
> - 対象事業所をまだ選択していない
> - 顧問先にアドバイザーとして所属しているだけで、従業員権限の事業所を選べていない
> のいずれかであることが多い。

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
>
> 保存後、アプリ詳細の `基本設定` タブで `Client ID` / `Client Secret` と
> 認証用URLを確認できる。

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

もっとも確実なのは、`アプリ管理` → 対象アプリ → `基本設定` タブに表示される
認証用URLをそのまま使う方法。

手動で組み立てる場合は、以下のURLをブラウザで開く
（`YOUR_CLIENT_ID` を実際の値に置き換える）。

```
https://accounts.secure.freee.co.jp/public_api/authorize?response_type=code&client_id=YOUR_CLIENT_ID&redirect_uri=urn:ietf:wg:oauth:2.0:oob&prompt=select_company
```

`prompt=select_company` を付けると、freee標準の事業所選択画面が使われる。

**freeeの認可画面で対象事業所を選び、「許可する」をクリックすると、画面に認可コードが表示される。**

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
  "scope": "read write default_read",
  "created_at": 1713520000,
  "company_id": 1234567
}
```

`access_token` と `refresh_token` を控える。

> - `access_token` の有効期限: **6時間**（`expires_in: 21600`秒）
> - `refresh_token` の有効期限: **90日**（使用するたびに新しいものが発行される）

### 2-3. company_id を取得する

通常は **Step 2-2 のトークンレスポンスに含まれる `company_id` をそのまま使えばよい**。
これは `prompt=select_company` 付きの認証用URL、またはアプリ管理画面に表示される
デフォルトの認証用URLを使った場合の挙動。

もしトークンレスポンスに `company_id` が含まれなかった場合のみ、
補助手段として以下を実行して事業所IDを確認する。

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

ローカルの `.env` に `FREEE_CLIENT_ID` / `FREEE_CLIENT_SECRET` /
`FREEE_REFRESH_TOKEN` / `FREEE_ACCESS_TOKEN` / `FREEE_COMPANY_ID`
が入っている場合は、以下のスクリプトで作成または更新できる。

```bash
cd freee
./scripts/upsert_freee_secret.sh
```

手動で作成する場合は次のコマンドを使う。

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

デプロイ成功後に表示される `Outputs` から `ApiEndpoint` と `CognitoHostedUiUrl` をメモする。

```
CloudFormation outputs from deployed stack
-----------------------------------------
Key    ApiEndpoint
Value  https://xxxxxxxxxx.execute-api.ap-northeast-1.amazonaws.com/mcp
```

### 5-5. Cognitoのログイン情報を準備する

```bash
# User Pool IDを確認
aws cloudformation describe-stacks \
  --stack-name freee-mcp-server \
  --region ap-northeast-1 \
  --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolId'].OutputValue" \
  --output text
```

個人利用なら、管理者で Cognito ユーザーを1件だけ作成して使うのが最も簡単。

```bash
USER_POOL_ID="ap-northeast-1_xxxxxxxx"
USERNAME="demo-user"
PASSWORD="十分に強いパスワード"

aws cognito-idp admin-create-user \
  --user-pool-id "${USER_POOL_ID}" \
  --username "${USERNAME}" \
  --temporary-password "${PASSWORD}" \
  --message-action SUPPRESS \
  --region ap-northeast-1

aws cognito-idp admin-set-user-password \
  --user-pool-id "${USER_POOL_ID}" \
  --username "${USERNAME}" \
  --password "${PASSWORD}" \
  --permanent \
  --region ap-northeast-1
```

> Claude 側にはこのユーザー名・パスワードを保存しない。
> 接続時に開く Cognito ログイン画面で入力する。

### 5-6. 動作確認（curlで直接テスト）

```bash
API_URL="https://xxxxxxxxxx.execute-api.ap-northeast-1.amazonaws.com/mcp"

# ヘルスチェック
curl -X GET "${API_URL%/mcp}/health"

# OAuth metadata
curl -X GET "${API_URL%/mcp}/.well-known/oauth-authorization-server"
curl -X GET "${API_URL%/mcp}/.well-known/oauth-protected-resource"
```

> `/mcp` 本体は Bearer token が必要。
> 直接 curl で叩くより、Claude 側の Remote MCP 接続で OAuth ログインを完了させて確認する方が確実。

---

## Step 6. Claude / Claude Code にURLを登録する

### 6-1. Claudeアプリの設定を開く

1. Claudeアプリ（PC版）を開く
2. 設定 → 「Integrations」または「MCP Servers」（UIはバージョンにより異なる）
3. 「Add Remote MCP Server」をクリック

### 6-2. 接続情報を入力する

| 項目 | 入力値 |
|------|--------|
| Server URL | `https://xxxxxxxxxx.execute-api.ap-northeast-1.amazonaws.com/mcp` |
| OAuth Client ID | 空欄 |
| OAuth Client Secret | 空欄 |

保存後に Cognito ログイン画面が開いたら、Step 5-5 で作成したユーザー名とパスワードを入力する。

> この構成では、Cognito はユーザー認証のみ担当する。
> Claude が最終的に使う `access_token` / `refresh_token` は MCP サーバー自身が発行する。

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

### Cognitoパスワードの変更

```bash
# パスワードを更新
aws cognito-idp admin-set-user-password \
  --user-pool-id YOUR_USER_POOL_ID \
  --username YOUR_USERNAME \
  --password 'NEW_STRONG_PASSWORD' \
  --permanent \
  --region ap-northeast-1 \
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
| MCP接続できない | エンドポイントURL違い / Cognitoログイン失敗 / OAuthセッション不整合 | Step 5-5, 5-6を再確認し、Claude側の接続を作り直す |
| タイムアウト | Lambda実行時間が28秒超 | freee API応答遅延の可能性。CloudWatch Logsで確認 |
