# HTTP再設計・テスト設計・テスト結果

作成日: 2026-04-19

## 1. 結論

今回の見直しでは、Lambda の HTTP 実装を **`requests` を使う方針** に再設計しつつ、
Remote MCP 認証も見直した。  
Cognito はエンドユーザーのログイン画面だけに使い、MCP 用の `access_token` /
`refresh_token` は **このサーバー自身が発行・検証する構成** に変更した。

この判断にした理由:

- 共有 Python 環境と `freee/.venv` を整備したことで、`requests` の導入・テスト・再デプロイが安定して実行できるようになった
- `requests.Session` により Lambda warm start 時の TCP コネクション再利用がしやすい
- `urllib` 直実装より可読性と保守性が高い
- 呼び出し側は `http_get` / `http_post` を使うため、将来のライブラリ差し替え余地も残る

## 2. 再設計内容

対象ファイル:

- [app/utils/http.py](/home/keisuke/00_develop/freee/app/utils/http.py:1)
- [app/freee/auth.py](/home/keisuke/00_develop/freee/app/freee/auth.py:1)
- [app/freee/client.py](/home/keisuke/00_develop/freee/app/freee/client.py:1)
- [requirements.txt](/home/keisuke/00_develop/freee/requirements.txt:1)

設計ポイント:

- `app/utils/http.py` で `requests.Session` をシングルトン管理
- `http_get` / `http_post` で `requests` 例外を `HttpTimeoutError` / `HttpRequestError` に変換
- `freee.auth` と `freee.client` はラッパー経由で HTTP 実行
- テストでは `requests` そのものではなく `http_get` / `http_post` をモック

この形により、Lambda の実装は実運用向けの扱いやすさを取りつつ、テストは境界で止めやすい構造になっている。

## 3. 実行環境

共通 Python 基盤:

- workspace: `/home/keisuke/00_develop`
- 既定 Python: `3.13.13`
- 追加 Python: `3.14.4`
- ツール管理: `uv 0.11.7`

freee プロジェクト用環境:

- 仮想環境: [freee/.venv](/home/keisuke/00_develop/freee/.venv)
- テスト実行 Python: `3.13.13`
- pytest: `8.2.2`
- pytest-cov: `5.0.0`

## 4. テスト設計

今回のテストは次の 4 層で設計した。

### 4-1. 単体テスト

目的:

- 認証トークン管理の分岐
- HTTP ラッパーの例外変換
- Secrets Manager 読み書きロジック
- JSON-RPC ルーターの分岐
- 入力バリデーション

対象:

- [tests/unit/test_freee_auth.py](/home/keisuke/00_develop/freee/tests/unit/test_freee_auth.py:1)
- [tests/unit/test_http.py](/home/keisuke/00_develop/freee/tests/unit/test_http.py:1)
- [tests/unit/test_secrets.py](/home/keisuke/00_develop/freee/tests/unit/test_secrets.py:1)
- [tests/unit/test_mcp_router.py](/home/keisuke/00_develop/freee/tests/unit/test_mcp_router.py:1)
- [tests/unit/test_validate_expense_input.py](/home/keisuke/00_develop/freee/tests/unit/test_validate_expense_input.py:1)

### 4-2. 結合テスト

目的:

- `FreeeClient` が正しい HTTP 呼び出し形を作ること
- Lambda handler が API Gateway イベントから MCP 応答まで正しく流れること

対象:

- [tests/integration/test_freee_client.py](/home/keisuke/00_develop/freee/tests/integration/test_freee_client.py:1)
- [tests/integration/test_handler.py](/home/keisuke/00_develop/freee/tests/integration/test_handler.py:1)

### 4-3. カバレッジ測定

目的:

- 実装変更後に主要ロジックのテスト空白を把握する

手段:

- `pytest-cov` による `app/` 配下の計測

### 4-4. デプロイ後確認

目的:

- CloudFormation 更新後に Lambda が正常に反映されていること
- Secrets Manager 参照設定が維持されていること

確認対象:

- Lambda 関数設定
- CloudFormation 更新完了

## 5. テスト一覧

収集結果: **83 tests**

### Integration

- `tests/integration/test_freee_client.py`
  - 勘定科目一覧取得成功
  - `type` フィルタ付与
  - API エラー時の `RuntimeError`
  - 税区分一覧取得成功
  - 支出登録成功
  - 422 バリデーションエラー
  - タイムアウトエラー

- `tests/integration/test_handler.py`
  - `/health` 正常応答
  - `initialize`
  - `tools/list`
  - `freee_create_expense`
  - 不正 JSON
  - 空ボディ
  - JSON-RPC バージョン不正
  - 未知パス
  - バリデーションエラーの MCP 返却

### Unit

- `tests/unit/test_freee_auth.py`
  - 有効トークン再利用
  - 期限切れトークン refresh
  - `expires_at` 未設定時 refresh
  - refresh 失敗
  - `_is_token_valid` 各分岐
  - `company_id` 取得

- `tests/unit/test_http.py`
  - Session 再利用
  - GET 成功
  - GET Timeout 例外変換
  - GET RequestException 変換
  - POST 成功
  - POST Timeout 例外変換
  - POST RequestException 変換

- `tests/unit/test_oauth_server.py`
  - 認可サーバーメタデータ生成
  - 保護リソースメタデータ生成
  - PKCE 検証
  - Cognito client ID 解決
  - Cognito callback から principal 抽出
  - 認可コード交換
  - refresh token 交換
  - MCP サーバー発行 access token 検証

- `tests/unit/test_mcp_router.py`
  - initialize 応答
  - tools/list 応答
  - tools/call 正常系
  - 不正ツール
  - パラメータ不備
  - 例外変換
  - 未知メソッド
  - `initialized` 無視

- `tests/unit/test_secrets.py`
  - シークレット読み込み成功
  - シークレット未存在
  - 必須フィールド欠落
  - シークレット更新成功

- `tests/unit/test_validate_expense_input.py`
  - 必須項目のみ通過
  - 全項目指定通過
  - 実行成功メッセージ
  - 日付バリデーション各種
  - 金額バリデーション各種
  - 勘定科目 ID バリデーション
  - description 長さ制約
  - エラー時レスポンス形式

## 6. 実行コマンド

```bash
source /home/keisuke/00_develop/activate-python.sh
cd /home/keisuke/00_develop/freee
.venv/bin/pytest -q --cov=app --cov-report=term-missing --cov-report=xml
```

## 7. 実行結果

総合結果:

- **83 passed**
- **0 failed**
- **8 warnings**
- 実行時間: **1.70s**

主要な警告:

- `botocore` 内部の `datetime.utcnow()` に関する `DeprecationWarning`
- 自作コード起因ではなく、moto / botocore 経由の警告

### カバレッジ結果

| モジュール | Cover |
|---|---:|
| `app/freee/auth.py` | 86% |
| `app/freee/client.py` | 79% |
| `app/lambda_handler.py` | 76% |
| `app/mcp_router.py` | 100% |
| `app/oauth_server.py` | 65% |
| `app/tools/freee_create_expense.py` | 95% |
| `app/tools/freee_list_account_items.py` | 30% |
| `app/tools/freee_list_tax_codes.py` | 25% |
| `app/tools/freee_validate_expense_input.py` | 91% |
| `app/utils/http.py` | 100% |
| `app/utils/secrets.py` | 81% |
| **TOTAL** | **76%** |

成果物:

- [coverage.xml](/home/keisuke/00_develop/freee/coverage.xml:1)
- [coverage_html](/home/keisuke/00_develop/freee/coverage_html)

## 8. 判定

今回の再設計は **テスト可能性・保守性・Lambda 実運用性のバランスがもっとも良い形** と判断する。

特に良くなった点:

- `requests` の利便性を取り戻した
- HTTP ライブラリ依存を `utils/http.py` に閉じ込めた
- Session 再利用の意図が明示された
- HTTP 層の単体テストを追加できた
- ローカル環境と Lambda デプロイまで一貫した

## 9. 残課題

次に手を入れるなら優先度が高いのは以下。

- `freee_list_account_items` のテスト追加
- `freee_list_tax_codes` のテスト追加
- 実 AWS / 実 freee API を使うスモークテストの追加
- CloudWatch Logs を見たデプロイ後の実行確認

## 10. デプロイ結果

CloudFormation 更新済み:

- Stack: `freee-mcp-server`
- Lambda: `freee-mcp-server-prod`
- Runtime: `python3.13`
- SecretName: `freee/mcp-server`
- LastUpdateStatus: `Successful`

備考:

- Lambda のランタイムは `python3.13` に更新済み
- ローカル開発・テストも `Python 3.13.13` で統一
- 実行基盤とローカルのメジャーバージョン差分は解消済み
