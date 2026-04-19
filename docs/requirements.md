# 要件定義書 — freee支出登録用 Remote MCP Server

作成日: 2026-04-19  
ステータス: 確定（MVP版）

---

## 目的

Claudeアプリから利用するための「freee支出登録用 Remote MCP Server」をAWS上に構築する。  
スマートフォンのClaudeアプリにレシート画像を送るだけで、freee会計に支出登録が完了する体験を実現する。

---

## 利用イメージ

1. スマホのClaudeアプリにレシート画像を送る
2. ClaudeがレシートをOCR・内容を読み取る（Claude本体側が担当）
3. ClaudeがRemote MCP toolを使ってfreeeに支出登録する
4. 必要に応じて登録内容を返答する

---

## 前提条件

| 項目 | 内容 |
|------|------|
| 利用者 | 個人利用を想定 |
| サーバ構成 | 常時起動サーバは使わない（サーバレス） |
| クラウド | AWS |
| 公開入口 | API Gateway |
| 処理本体 | Lambda |
| MCP役割 | Lambda側でRemote MCP Serverとして振る舞う |
| freee連携 | freee APIを使って支出登録 |
| 認証情報管理 | Secrets Managerで管理。Lambdaの環境変数に秘密情報を埋め込まない |
| 画像長期保存 | 必須ではない（MVPでは不要） |
| メッセージング | LINEは使わない |
| 実装言語 | Python優先 |
| 設計方針 | インフラはシンプルに。過剰設計は避ける |
| 接続方法 | ClaudeアプリからCustom Connector / Remote MCPを通じて利用 |

---

## MVP機能スコープ

### 対象ツール

| ツール名 | 説明 |
|----------|------|
| `freee_list_account_items` | 勘定科目一覧取得 |
| `freee_list_tax_codes` | 税区分一覧取得 |
| `freee_validate_expense_input` | 入力バリデーション |
| `freee_create_expense` | 支出登録（メインツール） |

### MVPのスコープ外

- レシート画像のOCR処理（Claude本体側に委ねる）
- 複数事業所対応
- 承認ワークフロー
- 取引先登録・検索
- 請求書管理
- モバイルアプリ専用UI

---

## 機能要件

### freee_create_expense

- ClaudeからStructured Inputを受け取りfreeeに支出登録する
- 必須項目: 日付、金額、勘定科目ID、税区分ID
- 任意項目: 備考、取引先ID、タグ
- レスポンス: 登録結果（deal_id、登録日時など）

### freee_list_account_items

- freeeから勘定科目一覧を取得して返す
- Claudeが適切な勘定科目IDを選べるよう補助する

### freee_list_tax_codes

- freeeから税区分一覧を取得して返す
- Claudeが適切な税区分コードを選べるよう補助する

### freee_validate_expense_input

- 入力値の形式・必須チェックをサーバ側で行う
- freee APIを呼ぶ前の事前バリデーション

---

## 非機能要件

| 項目 | 内容 |
|------|------|
| 認証 | freee OAuth 2.0。refresh_tokenをSecrets Managerで管理 |
| 認可 | API Gatewayのエンドポイント認証（APIキーまたはLambdaオーソライザー） |
| 秘密情報 | Secrets Manager必須。Lambda環境変数への秘密情報埋め込み禁止 |
| 可用性 | サーバレスのため自動スケール対応 |
| ログ | CloudWatch Logsに出力。秘密情報はログ禁止 |
| コスト | 個人利用のため最小コスト構成 |
| デプロイ | AWS SAM（CloudFormation）で管理 |

---

## セキュリティ要件

- freee client_id / client_secret / refresh_token はSecrets Managerで管理
- APIキーはAPI Gatewayで管理
- LambdaのIAMロールは最小権限原則に従う
- ログにトークン・シークレット・個人情報を出力しない
- HTTPS必須（API Gatewayはデフォルト対応）

---

## 将来的な拡張余地

- 取引先検索・登録ツールの追加
- 支出一覧取得ツールの追加
- 重複登録検知の強化
- freeeの他機能（請求書、給与など）への対応
- マルチユーザー対応（Cognito等）

---

## 要確認事項

| # | 内容 | 影響範囲 |
|---|------|----------|
| 1 | Claude Custom ConnectorのOAuth2認証フローの詳細仕様 | API Gateway認証設計 |
| 2 | freee APIのOAuthスコープ（アプリ設定画面で権限チェックが必要） | Lambda/OAuth設計 |
| 3 | company_idの取得方法（`GET /api/1/companies` で確認可能） | ★解決済み: setup_guide.md Step 2-3参照 |
| 4 | 重複登録の許容度（freee APIは冪等性を保証するか） | 登録ロジック設計 |
| 5 | refresh_tokenが90日未使用の場合の失効アラート実装 | 運用設計 |
