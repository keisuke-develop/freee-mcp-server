# freee OAuth 認証フロー

作成日: 2026-04-19

---

## 1. freee OAuth 2.0 の概要

freee APIはOAuth 2.0 Authorization Code Flowを採用している。  
サーバーレス環境では「初回だけブラウザでOAuth認証 → refresh_tokenをSecrets Managerに保存 → 以降はrefresh_tokenでアクセストークンを自動更新」という運用が適切。

### トークンの種類

| トークン | 有効期限 | 用途 |
|----------|----------|------|
| access_token | **6時間**（expires_in: 21600秒） | freee API呼び出しに使用 |
| refresh_token | **90日** | access_token更新に使用。使用するたびに新しいものが発行される |

> refresh_tokenが90日以上未使用になると失効する。
> 失効した場合は再度ブラウザでOAuth認証（Step 2）が必要になる。

---

## 2. 初回認証フロー（セットアップ時のみ）

```
開発者（ブラウザ）                freee認証サーバー
      │                                  │
      │── GET /oauth/authorize ──────────>│
      │   ?client_id=...                 │
      │   &redirect_uri=...              │
      │   &response_type=code            │
      │   &scope=write:...               │
      │                                  │
      │<── ログイン画面 ─────────────────│
      │                                  │
      │── 認証・認可 ────────────────────>│
      │                                  │
      │<── redirect_uri?code=AUTH_CODE ──│
      │                                  │
      │── POST /oauth/token ─────────────>│
      │   grant_type=authorization_code  │
      │   code=AUTH_CODE                 │
      │   client_id=...                  │
      │   client_secret=...              │
      │                                  │
      │<── access_token + refresh_token ─│
      │                                  │
      └── Secrets Managerに保存 ─────────┘
```

**初回認証後の作業:**
1. `access_token`, `refresh_token`, `access_token_expires_at` をSecrets Managerに保存
2. `client_id`, `client_secret`, `company_id` も同一シークレットに保存

---

## 3. 通常利用時のトークン更新フロー

```
Lambda（起動時）                 Secrets Manager      freee API
     │                                │                    │
     │── GetSecretValue ─────────────>│                    │
     │<── secret（全フィールド） ─────│                    │
     │                                │                    │
     │── access_token有効期限チェック ─┘                    │
     │                                                      │
     │  [有効期限まで余裕あり]                              │
     │── Bearer access_token ──────────────────────────────>│
     │<── API レスポンス ─────────────────────────────────── │
     │                                                      │
     │  [有効期限切れ or まもなく切れる]                    │
     │── POST /oauth/token ─────────────────────────────────>│
     │   grant_type=refresh_token                           │
     │   refresh_token=...                                  │
     │   client_id=...                                      │
     │   client_secret=...                                  │
     │                                                      │
     │<── 新 access_token (+ 新 refresh_token) ─────────────│
     │                                                      │
     │── PutSecretValue（更新） ─────>│                     │
     │                                │                     │
     │── Bearer 新access_token ──────────────────────────── >│
     │<── API レスポンス ─────────────────────────────────── │
```

---

## 4. Secrets Manager への保存形式

### シークレット名
```
freee/mcp-server
```

### シークレット内容（JSON）
```json
{
  "client_id": "xxxxxxxx",
  "client_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "refresh_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "access_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "access_token_expires_at": "2026-04-20T10:00:00+09:00",
  "company_id": 1234567
}
```

### 更新タイミング
- `access_token` と `access_token_expires_at`：access_token更新のたびに更新
- `refresh_token`：freeeがrefresh時に新しいrefresh_tokenを返す場合は更新
- その他：変更なし

---

## 5. freee API に必要な OAuth スコープ

> **要確認:** 以下は想定スコープ。freee公式ドキュメントで必要スコープを確認すること。

| スコープ | 用途 |
|----------|------|
| `read:companies` | 事業所情報取得 |
| `read:account_items` | 勘定科目取得 |
| `read:taxes` | 税区分取得 |
| `write:deals` | 取引（支出）登録 |
| `read:partners` | 取引先取得（任意） |

---

## 6. company_id の扱い

- `company_id` はfreeeの事業所IDで、ほぼ全てのAPIエンドポイントで必要
- 個人利用のため固定値として扱い、Secrets Managerに保存する
- 複数事業所対応が必要な場合は設計変更が必要（MVPスコープ外）

---

## 7. freee API 呼び出し失敗時のリトライ方針

| エラー種別 | HTTPステータス | 対応 |
|-----------|---------------|------|
| 認証エラー | 401 | access_tokenをrefreshして1回リトライ |
| バリデーションエラー | 422 | リトライしない。エラー詳細をClaudeに返す |
| レート制限 | 429 | Retry-Afterヘッダーを確認してリトライ（MVPでは単純な1回リトライ） |
| サーバーエラー | 5xx | 1回リトライ |
| タイムアウト | - | リトライしない。Claudeにエラー返却 |

---

## 8. refresh_token 失効時の対処

refresh_tokenが失効した場合、自動復旧は不可能。以下の手順で手動対応:

1. 開発者がブラウザで再度 freee OAuth認証を実施
2. 新しい `access_token` と `refresh_token` を取得
3. Secrets Managerの `freee/mcp-server` を更新

> **運用メモ:** refresh_tokenの失効を検知してアラートを上げる仕組みを  
> 将来的に追加することを推奨（CloudWatch Alarms → SNS など）

---

## 9. 重複登録を防ぐための考え方

freee APIは現時点では冪等性を保証していない（要確認）。  
MVPでは以下の軽量なアプローチを採用:

1. Claude側で登録前に `freee_validate_expense_input` を呼び出して確認を促す
2. 登録成功時のレスポンスに `deal_id` を含めてClaudeが会話に記録
3. 同じ `deal_id` が既に言及されている場合はClaudeが重複登録を抑制

> より厳密な重複検知（DBによる登録履歴管理等）はMVPスコープ外。
