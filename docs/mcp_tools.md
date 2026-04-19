# MCP ツール定義書

作成日: 2026-04-19

---

## 1. Remote MCP Server vs 通常 REST API

| 観点 | 通常 REST API | Remote MCP Server |
|------|--------------|-------------------|
| プロトコル | HTTP REST | JSON-RPC 2.0 over HTTP |
| ルーティング | URLパスで決定 | `method` フィールドで決定 |
| ツール定義 | ドキュメントのみ | JSON Schemaで機械可読な形式で提供 |
| 呼び出し元 | 人間またはコード | LLM（Claude）が自律的に判断 |
| レスポンス形式 | 任意のJSON | `content` 配列（text/imageなど） |
| 初期化 | なし | `initialize` ハンドシェイクあり |
| ツール探索 | なし | `tools/list` で動的に取得可能 |

---

## 2. MCPメソッド一覧

### 2.1 initialize

Claudeが接続時に最初に呼び出す。サーバー情報を返す。

**リクエスト:**
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": { "name": "claude", "version": "1.0" }
  }
}
```

**レスポンス:**
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": { "tools": {} },
    "serverInfo": { "name": "freee-mcp-server", "version": "1.0.0" }
  }
}
```

---

### 2.2 tools/list

利用可能なツールをJSON Schema付きで返す。

**リクエスト:**
```json
{
  "jsonrpc": "2.0",
  "id": "2",
  "method": "tools/list",
  "params": {}
}
```

**レスポンス:**
```json
{
  "jsonrpc": "2.0",
  "id": "2",
  "result": {
    "tools": [ ... ]
  }
}
```

---

### 2.3 tools/call

ツールを実行する。

**リクエスト:**
```json
{
  "jsonrpc": "2.0",
  "id": "3",
  "method": "tools/call",
  "params": {
    "name": "freee_create_expense",
    "arguments": {
      "issue_date": "2026-04-19",
      "amount": 1500,
      "account_item_id": 100,
      "tax_code": 1,
      "description": "コンビニ領収書"
    }
  }
}
```

**レスポンス（成功）:**
```json
{
  "jsonrpc": "2.0",
  "id": "3",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "支出登録完了\n- deal_id: 12345\n- 金額: ¥1,500"
      }
    ]
  }
}
```

**レスポンス（エラー）:**
```json
{
  "jsonrpc": "2.0",
  "id": "3",
  "error": {
    "code": -32603,
    "message": "freee API error: 422 Unprocessable Entity",
    "data": { "detail": "account_item_id is invalid" }
  }
}
```

---

## 3. ツール定義（JSON Schema）

### 3.1 freee_list_account_items

```json
{
  "name": "freee_list_account_items",
  "description": "freeeから勘定科目の一覧を取得します。支出登録時に必要なaccount_item_idを確認するために使用します。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "type": {
        "type": "string",
        "description": "勘定科目の種別でフィルタリング。例: 'expense'（経費）。省略時は全件取得。",
        "enum": ["income", "expense", "asset", "liability", "equity", "other"]
      }
    },
    "required": []
  }
}
```

---

### 3.2 freee_list_tax_codes

```json
{
  "name": "freee_list_tax_codes",
  "description": "freeeから税区分の一覧を取得します。支出登録時に必要なtax_codeを確認するために使用します。",
  "inputSchema": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

---

### 3.3 freee_validate_expense_input

```json
{
  "name": "freee_validate_expense_input",
  "description": "支出登録の入力値をバリデーションします。freee APIを呼び出す前に入力値の形式・必須項目を確認します。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "issue_date": {
        "type": "string",
        "description": "発生日（YYYY-MM-DD形式）",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
      },
      "amount": {
        "type": "integer",
        "description": "金額（税込、円単位、正の整数）",
        "minimum": 1
      },
      "account_item_id": {
        "type": "integer",
        "description": "勘定科目ID（freee_list_account_itemsで取得）"
      },
      "tax_code": {
        "type": "integer",
        "description": "税区分コード（freee_list_tax_codesで取得）"
      },
      "description": {
        "type": "string",
        "description": "備考・説明（省略可）",
        "maxLength": 500
      },
      "partner_id": {
        "type": "integer",
        "description": "取引先ID（省略可）"
      }
    },
    "required": ["issue_date", "amount", "account_item_id", "tax_code"]
  }
}
```

---

### 3.4 freee_create_expense

```json
{
  "name": "freee_create_expense",
  "description": "freeeに支出（経費）を登録します。レシートの内容を元に勘定科目・税区分・金額・日付を指定して登録します。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "issue_date": {
        "type": "string",
        "description": "発生日（YYYY-MM-DD形式）",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
      },
      "amount": {
        "type": "integer",
        "description": "金額（税込、円単位、正の整数）",
        "minimum": 1
      },
      "account_item_id": {
        "type": "integer",
        "description": "勘定科目ID（freee_list_account_itemsで取得したid）"
      },
      "tax_code": {
        "type": "integer",
        "description": "税区分コード（freee_list_tax_codesで取得したcode）"
      },
      "description": {
        "type": "string",
        "description": "備考・説明（任意）",
        "maxLength": 500
      },
      "partner_id": {
        "type": "integer",
        "description": "取引先ID（任意）"
      }
    },
    "required": ["issue_date", "amount", "account_item_id", "tax_code"]
  }
}
```

---

## 4. API Gateway + Lambda での実装上の注意点

### 注意点一覧

| 項目 | 内容 |
|------|------|
| Content-Type | リクエスト・レスポンスともに `application/json` 必須 |
| HTTPメソッド | POSTのみ使用。GETはtools/list用途では使わない |
| タイムアウト | API Gateway: 29秒上限。Lambda: 30秒以内に設定 |
| エラー形式 | MCP JSON-RPCエラー形式で返す（HTTPステータスは200を維持） |
| IDのエコーバック | リクエストの `id` を必ずレスポンスにコピーする |
| SSE非対応 | Lambda Function URLを使わない限りSSEストリームは困難。HTTP transport採用 |
| プロトコルバージョン | `2024-11-05` を現時点では固定で使用する（要確認） |

### GET / POST の扱い

```
POST /mcp  ← 全JSON-RPCリクエストを受け付ける唯一のエンドポイント
GET  /health  ← ヘルスチェック用（オプション）
```

GETでMCPを受け付けるSSE方式はAPI Gatewayでは実装困難なため、  
MVPではPOSTのみのHTTP transport方式を採用する。

---

## 5. Claude Custom Connector 接続に必要なこと

| 要件 | 対応 |
|------|------|
| HTTPS | API Gatewayがデフォルト対応 |
| 認証 | APIキーをx-api-keyヘッダーまたはAuthorizationヘッダーで送信 |
| エンドポイントURL | `https://<api-id>.execute-api.<region>.amazonaws.com/<stage>/mcp` |
| MCP仕様バージョン | `2024-11-05`（Claude対応バージョンを要確認） |
| CORS | 必要に応じてAPI Gatewayで設定 |

> **要確認:** Claude Custom ConnectorがサポートするMCPトランスポート方式と  
> 認証方式の詳細仕様は公式ドキュメントで確認が必要。
