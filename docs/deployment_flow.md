# デプロイ全体フロー

作成日: 2026-04-19

初回構築から日常運用まで、全工程を一本のフローで整理する。

---

## 全体像

```
┌─────────────────────────────────────────────────────────────────┐
│  Phase 1        Phase 2           Phase 3          Phase 4      │
│  事前準備   →  freee認証情報取得  →  AWS準備    →  デプロイ     │
│                                                                   │
│  Phase 5        Phase 6           Phase 7                        │
│  動作確認   →  Claude登録      →  日常運用                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: 事前準備

### 1-1. 必要なアカウント・ツール

| 必要なもの | 確認コマンド / 入手先 |
|-----------|----------------------|
| freeeアカウント | freee.co.jp（有料プランまたは試用） |
| AWSアカウント | aws.amazon.com |
| AWS CLI v2 | `aws --version` |
| AWS SAM CLI | `sam --version` |
| Python 3.13 | `python3 --version` |
| Git | `git --version` |

### 1-2. AWS CLIの設定確認

```bash
# 認証情報が設定されているか確認
aws sts get-caller-identity

# 出力例
{
    "UserId": "AIDAXXXXXXXXXXXXXXXX",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/your-user"
}

# デフォルトリージョン確認（ap-northeast-1 推奨）
aws configure get region
```

### 1-3. リポジトリのセットアップ

```bash
cd /home/keisuke/00_develop/freee

# 開発依存パッケージをインストール（テスト実行に必要）
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# テストが通ることを確認してから進む
pytest
# → 61 passed であることを確認
```

---

## Phase 2: freee認証情報の取得

> ブラウザとターミナルを使う。この情報を次のPhase 3でAWSに登録する。

### 2-1. freee Developersでアプリを作成

1. [https://developer.freee.co.jp/](https://developer.freee.co.jp/) にログイン
2. 「アプリ管理」→「新規アプリを作成」
3. 以下を設定する

| 項目 | 値 |
|------|----|
| アプリ名 | `freee-mcp-server`（任意） |
| コールバックURL | `urn:ietf:wg:oauth:2.0:oob` |
| 権限 | 「会計」にチェック |

4. 作成後に表示される値を必ず控える

```
client_id     = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
client_secret = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
               ↑ この画面でしか確認できないので必ず控える
```

### 2-2. 認可URLでOAuth認証を実施

以下のURLをブラウザで開く（`YOUR_CLIENT_ID` を実際の値に置き換える）。

```
https://accounts.secure.freee.co.jp/public_api/authorize?client_id=YOUR_CLIENT_ID&redirect_uri=urn:ietf:wg:oauth:2.0:oob&response_type=code
```

freeeのログイン・認可画面が表示される。「許可する」をクリックすると、
ブラウザ画面に **認可コード（Authorization Code）** が表示される。

```
認可コード例: abc123def456...
             ↑ コピーして控える（有効期限が短いので素早く次に進む）
```

### 2-3. 認可コードをトークンに交換する

```bash
CLIENT_ID="YOUR_CLIENT_ID"
CLIENT_SECRET="YOUR_CLIENT_SECRET"
AUTH_CODE="YOUR_AUTH_CODE"  # Step 2-2でコピーした値

curl -s -X POST "https://accounts.secure.freee.co.jp/public_api/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "code=${AUTH_CODE}" \
  -d "redirect_uri=urn:ietf:wg:oauth:2.0:oob" | python3 -m json.tool
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

以下を控える。

```
access_token  = xxxxxxxx...  （有効期限: 6時間）
refresh_token = xxxxxxxx...  （有効期限: 90日）
```

### 2-4. company_id を取得する

```bash
ACCESS_TOKEN="YOUR_ACCESS_TOKEN"

curl -s -X GET "https://api.freee.co.jp/api/1/companies" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Accept: application/json" | python3 -m json.tool
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

```
company_id = 1234567  ← この数値を控える
```

### 2-5. この時点で手元に揃っているもの

| 情報 | 取得元 |
|------|--------|
| `client_id` | Step 2-1 |
| `client_secret` | Step 2-1 |
| `access_token` | Step 2-3 |
| `refresh_token` | Step 2-3 |
| `company_id` | Step 2-4 |

> これらをメモ帳などに一時保存しておく。
> ファイルに書く場合は `.gitignore` 対象のファイルに書くこと。

---

## Phase 3: AWS Secrets Managerに認証情報を登録する

> CloudFormationデプロイより**前**に実施する。
> Lambda実行時にこのシークレットを参照するため、先に作成しておく必要がある。

### 3-1. シークレットを作成する

```bash
# Phase 2で控えた値を変数にセット
CLIENT_ID="YOUR_CLIENT_ID"
CLIENT_SECRET="YOUR_CLIENT_SECRET"
ACCESS_TOKEN="YOUR_ACCESS_TOKEN"
REFRESH_TOKEN="YOUR_REFRESH_TOKEN"
COMPANY_ID=1234567  # 数値のまま

# access_tokenの有効期限を現在時刻+6時間で設定
EXPIRES_AT=$(python3 -c "
from datetime import datetime, timedelta, timezone
dt = datetime.now(tz=timezone.utc) + timedelta(hours=6)
print(dt.isoformat())
")

aws secretsmanager create-secret \
  --name "freee/mcp-server" \
  --region "ap-northeast-1" \
  --description "freee Remote MCP Server OAuth credentials" \
  --secret-string "{
    \"client_id\": \"${CLIENT_ID}\",
    \"client_secret\": \"${CLIENT_SECRET}\",
    \"refresh_token\": \"${REFRESH_TOKEN}\",
    \"access_token\": \"${ACCESS_TOKEN}\",
    \"access_token_expires_at\": \"${EXPIRES_AT}\",
    \"company_id\": ${COMPANY_ID}
  }"
```

### 3-2. 登録内容を確認する

```bash
aws secretsmanager get-secret-value \
  --secret-id "freee/mcp-server" \
  --region "ap-northeast-1" \
  --query "SecretString" \
  --output text | python3 -m json.tool
```

**確認ポイント:**
- [ ] `client_id` が入っている
- [ ] `client_secret` が入っている
- [ ] `refresh_token` が入っている
- [ ] `access_token` が入っている
- [ ] `access_token_expires_at` が入っている
- [ ] `company_id` が入っている（数値型）

---

## Phase 4: CloudFormation（SAM）でAWSリソースをデプロイする

> Secrets Managerの登録が完了してから実施する。

### 4-1. SAMビルド

```bash
cd /home/keisuke/00_develop/freee

sam build --template-file infra/template.yaml
```

**正常終了の目安:**
```
Build Succeeded

Built Artifacts  : .aws-sam/build
Built Template   : .aws-sam/build/template.yaml
```

### 4-2. SAMデプロイ（初回は --guided）

```bash
sam deploy \
  --config-file infra/samconfig.toml \
  --guided
```

**対話形式の入力:**

| 質問 | 入力値 |
|------|--------|
| Stack Name | `freee-mcp-server` |
| AWS Region | `ap-northeast-1` |
| Parameter StageName | `prod` |
| Parameter SecretName | `freee/mcp-server` |
| Parameter LogLevel | `INFO` |
| Confirm changes before deploy | `Y` |
| Allow SAM CLI IAM role creation | `Y` |
| Disable rollback | `N` |
| Save arguments to configuration file | `Y` |
| SAM configuration file | `infra/samconfig.toml` |

Changesetの内容が表示されたら内容を確認して `Y` で実行。

```
CloudFormation stack changeset
-----------------------------------------
Operation  LogicalResourceId          ResourceType
---------  -------------------------  --------------------------------
+ Add      FreeeeMcpApi               AWS::ApiGateway::RestApi
+ Add      FreeeeMcpFunction          AWS::Lambda::Function
+ Add      FreeeeMcpLambdaRole        AWS::IAM::Role
+ Add      FreeeeMcpApiLogGroup       AWS::Logs::LogGroup
+ Add      FreeeeMcpFunctionLogGroup  AWS::Logs::LogGroup
...
```

### 4-3. デプロイ結果からエンドポイントURLを取得する

デプロイ完了後に表示される `Outputs` を確認する。

```
CloudFormation outputs from deployed stack
------------------------------------------
Key         ApiEndpoint
Value       https://xxxxxxxxxx.execute-api.ap-northeast-1.amazonaws.com/prod/mcp
Description Remote MCP Server のエンドポイントURL
```

**`ApiEndpoint` のURLを控える。**

### 4-4. APIキーを取得する

```bash
# APIキーの一覧とその値を確認
aws apigateway get-api-keys \
  --region ap-northeast-1 \
  --include-values \
  --query "items[?contains(name, 'freee-mcp')].{name:name, value:value}" \
  --output table
```

**APIキーの値（`value`）を控える。**

### 4-5. デプロイ後のAWSリソース確認

```bash
# CloudFormationスタックの状態確認
aws cloudformation describe-stacks \
  --stack-name freee-mcp-server \
  --region ap-northeast-1 \
  --query "Stacks[0].StackStatus"
# → "CREATE_COMPLETE" であることを確認

# Lambda Functionの確認
aws lambda get-function \
  --function-name freee-mcp-server-prod \
  --region ap-northeast-1 \
  --query "Configuration.{State:State,Handler:Handler,Runtime:Runtime}"
# → State: Active, Handler: lambda_handler.lambda_handler

# IAMロールの権限確認（Secrets Managerへのアクセス権があるか）
aws iam list-attached-role-policies \
  --role-name freee-mcp-lambda-role-prod \
  --query "AttachedPolicies[].PolicyName"
```

---

## Phase 5: 動作確認

### 5-1. ヘルスチェック

```bash
API_URL="https://xxxxxxxxxx.execute-api.ap-northeast-1.amazonaws.com/prod"
API_KEY="YOUR_API_KEY"

curl -s "${API_URL}/health" -H "x-api-key: ${API_KEY}" | python3 -m json.tool
# → {"status": "ok"}
```

### 5-2. MCP initialize

```bash
curl -s -X POST "${API_URL}/mcp" \
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
  }' | python3 -m json.tool
```

**期待レスポンス:**
```json
{
    "jsonrpc": "2.0",
    "id": "1",
    "result": {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "freee-mcp-server", "version": "1.0.0"}
    }
}
```

### 5-3. ツール一覧取得

```bash
curl -s -X POST "${API_URL}/mcp" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${API_KEY}" \
  -d '{"jsonrpc":"2.0","id":"2","method":"tools/list","params":{}}' \
  | python3 -m json.tool
```

4ツール（`freee_list_account_items`, `freee_list_tax_codes`, `freee_validate_expense_input`, `freee_create_expense`）が返ることを確認。

### 5-4. freee API連携テスト（勘定科目一覧）

```bash
curl -s -X POST "${API_URL}/mcp" \
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
  }' | python3 -m json.tool
```

freeeの勘定科目一覧が返ればfreee API連携も正常。

### 5-5. Lambdaログの確認

```bash
aws logs tail /aws/lambda/freee-mcp-server-prod \
  --region ap-northeast-1 \
  --since 10m
```

エラーがないことを確認する。

---

## Phase 6: Claude Custom Connectorに登録する

> 要確認: ClaudeアプリのUIはバージョンにより異なる。
> 以下は2024年時点の一般的な手順。公式ドキュメントで最新UIを確認すること。

### 6-1. Claudeアプリで設定を開く

1. Claude.ai（PCブラウザまたはアプリ）にログイン
2. 設定 → 「Integrations」または「Connected Apps」を開く
3. 「Add MCP Server」または「Custom Connector」を選択

### 6-2. 接続情報を入力する

| 項目 | 入力値 |
|------|--------|
| サーバーURL | `https://xxxxxxxxxx.execute-api.ap-northeast-1.amazonaws.com/prod/mcp` |
| 認証ヘッダー名 | `x-api-key` |
| 認証ヘッダー値 | Phase 4-4で取得したAPIキー |

### 6-3. ツール確認

接続後、Claudeとの会話でMCPツールが使えるか確認する。

**確認プロンプト例:**
```
freeeの勘定科目の一覧を見せて
```

---

## Phase 7: 日常運用

### コード変更時の再デプロイ

```bash
cd /home/keisuke/00_develop/freee

# テストで動作確認
pytest

# ビルド・デプロイ
sam build --template-file infra/template.yaml
sam deploy --config-file infra/samconfig.toml --config-env prod
```

### refresh_tokenの更新（90日ごと、または失効時）

refresh_tokenは90日で失効する。失効前に以下を実施する。

```bash
# 現在のシークレットからrefresh_tokenを取得
CURRENT=$(aws secretsmanager get-secret-value \
  --secret-id "freee/mcp-server" \
  --region ap-northeast-1 \
  --query "SecretString" --output text)

CLIENT_ID=$(echo $CURRENT | python3 -c "import sys,json; print(json.load(sys.stdin)['client_id'])")
CLIENT_SECRET=$(echo $CURRENT | python3 -c "import sys,json; print(json.load(sys.stdin)['client_secret'])")
REFRESH_TOKEN=$(echo $CURRENT | python3 -c "import sys,json; print(json.load(sys.stdin)['refresh_token'])")

# refresh_tokenで新しいaccess_tokenを取得
curl -s -X POST "https://accounts.secure.freee.co.jp/public_api/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=refresh_token" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "refresh_token=${REFRESH_TOKEN}" | python3 -m json.tool
```

新しい `access_token` と `refresh_token` が返ったらSecrets Managerを更新する。

```bash
NEW_ACCESS_TOKEN="新しいaccess_token"
NEW_REFRESH_TOKEN="新しいrefresh_token"
EXPIRES_AT=$(python3 -c "
from datetime import datetime, timedelta, timezone
dt = datetime.now(tz=timezone.utc) + timedelta(hours=6)
print(dt.isoformat())
")
COMPANY_ID=$(echo $CURRENT | python3 -c "import sys,json; print(json.load(sys.stdin)['company_id'])")

aws secretsmanager put-secret-value \
  --secret-id "freee/mcp-server" \
  --region ap-northeast-1 \
  --secret-string "{
    \"client_id\": \"${CLIENT_ID}\",
    \"client_secret\": \"${CLIENT_SECRET}\",
    \"refresh_token\": \"${NEW_REFRESH_TOKEN}\",
    \"access_token\": \"${NEW_ACCESS_TOKEN}\",
    \"access_token_expires_at\": \"${EXPIRES_AT}\",
    \"company_id\": ${COMPANY_ID}
  }"
```

> Lambdaはaccess_tokenの自動refreshを行う（`freee/auth.py`）。
> refresh_token自体の更新は手動が必要（90日ごと）。

### スタックの削除（不要になった場合）

```bash
# APIキーを先に削除
aws apigateway get-api-keys --region ap-northeast-1 --include-values \
  --query "items[?contains(name, 'freee-mcp')].id" --output text | \
  xargs -I {} aws apigateway delete-api-key --api-key {} --region ap-northeast-1

# CloudFormationスタックを削除
aws cloudformation delete-stack \
  --stack-name freee-mcp-server \
  --region ap-northeast-1

# Secrets Managerのシークレットを削除（7日後に完全削除）
aws secretsmanager delete-secret \
  --secret-id "freee/mcp-server" \
  --region ap-northeast-1 \
  --recovery-window-in-days 7
```

---

## フロー全体のチェックリスト

### Phase 1: 事前準備
- [ ] freeeアカウントでログインできる
- [ ] `aws sts get-caller-identity` が通る
- [ ] `sam --version` が動く
- [ ] `pytest` で 61 passed

### Phase 2: freee認証情報取得
- [ ] client_id を控えた
- [ ] client_secret を控えた
- [ ] access_token を取得した
- [ ] refresh_token を取得した
- [ ] company_id を確認した

### Phase 3: Secrets Manager登録
- [ ] `freee/mcp-server` シークレットが作成された
- [ ] 6フィールドすべてが入っている

### Phase 4: CloudFormationデプロイ
- [ ] `sam build` が成功した
- [ ] `sam deploy` が `CREATE_COMPLETE` で完了した
- [ ] ApiEndpointのURLを控えた
- [ ] APIキーを控えた

### Phase 5: 動作確認
- [ ] `/health` が `{"status":"ok"}` を返す
- [ ] `initialize` が正常レスポンスを返す
- [ ] `tools/list` で4ツールが返る
- [ ] `freee_list_account_items` でfreeeの勘定科目が返る

### Phase 6: Claude登録
- [ ] Custom ConnectorにURLとAPIキーを登録した
- [ ] Claudeとの会話でfreeeツールが使える

---

## 各フェーズの責任分担まとめ

```
何を管理するか          管理場所               操作タイミング
─────────────────────────────────────────────────────────
client_id/secret      Secrets Manager        Phase 3（手動）
refresh_token         Secrets Manager        Phase 3（手動）+ 90日ごと更新
access_token          Secrets Manager        Lambda が自動更新
company_id            Secrets Manager        Phase 3（手動）
─────────────────────────────────────────────────────────
Lambda定義            CloudFormation(SAM)    Phase 4（sam deploy）
API Gateway定義       CloudFormation(SAM)    Phase 4（sam deploy）
IAMロール             CloudFormation(SAM)    Phase 4（sam deploy）
SECRET_NAME(環境変数) CloudFormation(SAM)    Phase 4（sam deploy）
─────────────────────────────────────────────────────────
APIキー               API Gateway            Phase 4後に取得
エンドポイントURL      API Gateway            Phase 4後に確認
─────────────────────────────────────────────────────────
Lambdaコード          app/ ディレクトリ      変更時に sam deploy
```
