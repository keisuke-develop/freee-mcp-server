# MVP スコープ定義

作成日: 2026-04-19

---

## 1. MVPの目的

「ClaudeアプリからStructured Inputを受け取ってfreeeに支出登録できる」状態を  
最小構成で成立させる。

OCRはClaude本体側が担うため、Remote MCP Server側はAPIのみ提供する。

---

## 2. MVPに含める機能

### ツール一覧

| ツール名 | 優先度 | 説明 | 依存 |
|----------|--------|------|------|
| `freee_list_account_items` | P0 | 勘定科目一覧取得（Claude判断用） | freee API |
| `freee_list_tax_codes` | P0 | 税区分一覧取得（Claude判断用） | freee API |
| `freee_validate_expense_input` | P1 | 入力バリデーション（登録前確認） | なし |
| `freee_create_expense` | P0 | 支出登録（メイン機能） | freee API |

### MCPメソッド

| メソッド | 説明 |
|----------|------|
| `initialize` | サーバー情報・対応プロトコルバージョンを返す |
| `tools/list` | 上記4ツールの定義を返す |
| `tools/call` | 指定ツールを実行して結果を返す |

---

## 3. MVPに含めない機能（V2以降）

| 機能 | 理由 |
|------|------|
| レシート画像OCR | Claude本体側に委ねる |
| 取引先（partner）検索・登録 | MVP後に追加 |
| 支出一覧取得 | MVP後に追加 |
| 重複登録検知 | MVP後に強化 |
| マルチユーザー対応 | 個人利用のため不要 |
| Cognito認証 | APIキーで代替 |
| CI/CD パイプライン | 手動デプロイで可 |

---

## 4. freee_create_expense の入出力定義

### 入力（Claudeから渡されるarguments）

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `issue_date` | string | ✓ | 発生日 (YYYY-MM-DD) |
| `amount` | integer | ✓ | 金額（税込、円） |
| `account_item_id` | integer | ✓ | 勘定科目ID（list_account_itemsで取得） |
| `tax_code` | integer | ✓ | 税区分コード（list_tax_codesで取得） |
| `description` | string | | 備考・説明 |
| `partner_id` | integer | | 取引先ID（省略可） |

### 出力（MCPレスポンスのcontent）

```json
{
  "type": "text",
  "text": "支出登録完了\n- deal_id: 12345\n- 日付: 2026-04-19\n- 金額: ¥1,500\n- 勘定科目: 交際費"
}
```

---

## 5. MVPのデータフロー

```
Claude（OCR済みデータを持っている）
  │
  ├─ tools/call: freee_list_account_items
  │     └─ 勘定科目一覧を受け取る
  │
  ├─ tools/call: freee_list_tax_codes
  │     └─ 税区分一覧を受け取る
  │
  ├─ (Claude内部で) 適切な account_item_id と tax_code を決定
  │
  ├─ tools/call: freee_validate_expense_input（任意）
  │     └─ バリデーションOKを確認
  │
  └─ tools/call: freee_create_expense
        └─ 登録完了レスポンスを受け取る
```

---

## 6. 実装優先順位

```
Phase 1（MVP基盤）:
  [1] Lambda handler + MCP router（initialize / tools/list / tools/call）
  [2] Secrets Manager ヘルパー
  [3] freee OAuth クライアント（token取得・refresh）

Phase 2（ツール実装）:
  [4] freee_list_account_items
  [5] freee_list_tax_codes
  [6] freee_validate_expense_input
  [7] freee_create_expense

Phase 3（インフラ）:
  [8] SAM template（API Gateway + Lambda + IAM）
  [9] Secrets Managerへの初期登録手順
  [10] デプロイ・動作確認

Phase 4（テスト）:
  [11] 単体テスト（各ツール・クライアント）
  [12] 結合テスト（Lambda handler → freee API）
```

---

## 7. 成功条件（MVPの完了定義）

- [ ] ClaudeアプリからMCP tool一覧が取得できる
- [ ] freee_list_account_items が勘定科目一覧を返す
- [ ] freee_list_tax_codes が税区分一覧を返す
- [ ] freee_create_expense で freeeに支出が登録される
- [ ] freeeのWebUIで登録された支出が確認できる
- [ ] 全単体テストがパスする
- [ ] Secrets Managerにシークレットが適切に保存されている
