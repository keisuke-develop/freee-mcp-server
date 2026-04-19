# アーキテクチャ設計書

作成日: 2026-04-19

---

## 1. システム構成図（テキスト）

```
┌─────────────────────────────────────────────────────────┐
│  スマートフォン                                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │ Claude アプリ                                     │   │
│  │  ・レシート画像送信                               │   │
│  │  ・画像OCR（Claude本体が処理）                   │   │
│  │  ・MCP Tool呼び出し                               │   │
│  └──────────────────┬───────────────────────────────┘   │
└─────────────────────┼───────────────────────────────────┘
                      │ HTTPS / MCP over HTTP (JSON-RPC 2.0)
                      │ Authorization: Bearer <MCP_API_KEY>
                      ▼
┌─────────────────────────────────────────────────────────┐
│  AWS                                                      │
│                                                           │
│  ┌─────────────────────────────────────┐                 │
│  │  API Gateway (REST API)              │                 │
│  │  POST /mcp                           │                 │
│  │  ・APIキー認証                       │                 │
│  │  ・HTTPS強制                         │                 │
│  │  ・リクエスト/レスポンスのパススルー │                 │
│  └──────────────────┬──────────────────┘                 │
│                     │ Lambda Proxy統合                    │
│                     ▼                                     │
│  ┌─────────────────────────────────────┐                 │
│  │  Lambda Function                     │                 │
│  │  (remote-mcp-freee)                  │                 │
│  │                                      │                 │
│  │  handler.py                          │                 │
│  │    └─ mcp_router.py                  │                 │
│  │         ├─ tools/list                │                 │
│  │         └─ tools/call                │                 │
│  │              ├─ freee_create_expense │                 │
│  │              ├─ freee_list_accounts  │                 │
│  │              ├─ freee_list_tax_codes │                 │
│  │              └─ freee_validate_input │                 │
│  │                                      │                 │
│  │  freee/client.py                     │                 │
│  │    └─ freee/auth.py (token refresh)  │                 │
│  │                                      │                 │
│  │  utils/secrets.py                    │                 │
│  └───────────┬─────────────┬────────────┘                 │
│              │             │                              │
│              ▼             ▼                              │
│  ┌──────────────┐  ┌───────────────────┐                 │
│  │ Secrets      │  │ CloudWatch Logs    │                 │
│  │ Manager      │  │ (ログ出力)         │                 │
│  │              │  └───────────────────┘                 │
│  │ ・client_id  │                                         │
│  │ ・client_sec │                                         │
│  │ ・refresh_tk │                                         │
│  │ ・access_tk  │                                         │
│  │ ・company_id │                                         │
│  └──────────────┘                                         │
└─────────────────────────────────────────────────────────┘
                      │ HTTPS
                      ▼
         ┌────────────────────────┐
         │  freee API             │
         │  (api.freee.co.jp)     │
         │  ・取引登録            │
         │  ・勘定科目取得        │
         │  ・税区分取得          │
         └────────────────────────┘
```

---

## 2. リクエストフロー

### 支出登録の全体フロー

```
1. ユーザー → Claude: 「このレシートを経費登録して」+ レシート画像

2. Claude（本体）:
   a. レシート画像をOCRして構造化データに変換
   b. tools/list を呼び出して利用可能ツール一覧を確認
   c. freee_list_account_items を呼び出して勘定科目一覧取得
   d. freee_list_tax_codes を呼び出して税区分一覧取得
   e. OCR結果と一覧を照合して適切な勘定科目・税区分を判定
   f. freee_validate_expense_input で入力バリデーション
   g. freee_create_expense で支出登録

3. Lambda（Remote MCP Server）:
   a. MCP JSON-RPCリクエストを受信
   b. Secrets Managerからfreee認証情報を取得
   c. access_tokenの有効期限を確認 → 必要ならrefresh
   d. freee APIを呼び出す
   e. MCP JSON-RPCレスポンスを返す

4. Claude → ユーザー: 登録結果をメッセージで返答
```

---

## 3. MCP プロトコルの通信形式

### トランスポート方式の選択

Lambda + API GatewayではSSEストリームの長時間維持が困難なため、  
**HTTP transport（非ストリーミング）** を採用する。

| 方式 | 説明 | Lambda適合性 |
|------|------|-------------|
| stdio | ローカルMCPサーバ向け | ✗ 使用不可 |
| SSE | サーバー送信イベント | △ Lambda実行時間制限あり |
| HTTP (Streamable) | POST 1本でJSON-RPC | ✓ **採用** |

### エンドポイント

| Method | Path | 説明 |
|--------|------|------|
| POST | `/mcp` | 全MCP JSON-RPCリクエストを受付 |

### リクエスト形式（JSON-RPC 2.0）

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "method": "tools/call",
  "params": {
    "name": "freee_create_expense",
    "arguments": { ... }
  }
}
```

### レスポンス形式

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "登録完了: deal_id=12345"
      }
    ]
  }
}
```

---

## 4. 認証フロー

### Claude → API Gateway 認証

```
Claude Custom Connector
  └─ Authorization: x-api-key: <API_GATEWAY_API_KEY>
       └─ API Gateway でAPIキー検証
```

※ 将来的にはCognito JWT認証やLambdaオーソライザーへの移行も可能

### Lambda → freee API 認証（OAuth 2.0）

```
Lambda起動時:
  1. Secrets Managerから (client_id, client_secret, refresh_token) を取得
  2. access_tokenの有効期限を確認
     a. 有効 → そのまま使用
     b. 期限切れ → refresh_tokenで再取得
  3. 新しいaccess_tokenをSecrets Managerに保存
  4. freee APIにアクセス
```

---

## 5. Secrets Manager の構造

### シークレット名: `freee/mcp-server`

```json
{
  "client_id": "freee OAuth client_id",
  "client_secret": "freee OAuth client_secret",
  "refresh_token": "freee OAuth refresh_token（長期トークン）",
  "access_token": "freee OAuth access_token（キャッシュ用）",
  "access_token_expires_at": "ISO8601形式の有効期限",
  "company_id": "freee事業所ID（数値）"
}
```

**補足:**
- `access_token` はキャッシュとしてSecrets Managerに保存（Lambda再起動時も再利用）
- `refresh_token` は期限切れ時に更新してSecrets Managerに上書き保存
- 1つのシークレットにまとめることでSecrets Managerのコストを最小化

---

## 6. API Gateway と Lambda の責務分離

| 責務 | API Gateway | Lambda |
|------|-------------|--------|
| HTTPS終端 | ✓ | ✗ |
| APIキー認証 | ✓ | ✗ |
| レート制限 | ✓ | ✗ |
| リクエストルーティング | ✓（/mcpのみ） | ✗ |
| MCP JSON-RPC解析 | ✗ | ✓ |
| ツールの実行 | ✗ | ✓ |
| freee API呼び出し | ✗ | ✓ |
| トークン管理 | ✗ | ✓ |
| エラーレスポンス整形 | ✗ | ✓ |

---

## 7. Lambda の役割（Remote MCP Server として）

1. **MCP初期化応答** (`initialize`): サーバー情報を返す
2. **ツール一覧提供** (`tools/list`): 利用可能ツールをJSON Schemaで返す
3. **ツール実行** (`tools/call`): 指定ツールを実行してコンテンツで返す
4. **freee認証管理**: access_token取得・更新
5. **freee API代理呼び出し**: 支出登録・マスタデータ取得

---

## 8. 将来的な拡張余地

| 拡張 | 実装イメージ |
|------|------------|
| OCR機能追加 | S3に画像アップロード → Textract / Lambda連携 |
| マルチユーザー | Cognito + ユーザー別Secrets Managerシークレット |
| 支出一覧・検索 | toolsへの追加（`freee_list_expenses`） |
| 非同期処理 | SQS + 別Lambda（長時間処理対応） |
| 監査ログ | DynamoDBへの操作ログ保存 |
| キャッシュ | ElastiCache or Lambda内メモリキャッシュ（勘定科目等） |
