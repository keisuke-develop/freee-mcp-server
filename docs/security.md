# セキュリティ設計

作成日: 2026-04-19

---

## 1. Secrets Manager 利用方針

### 保存するもの（Secrets Manager必須）

| シークレット | 説明 |
|-------------|------|
| `client_secret` | freee OAuth client_secret |
| `refresh_token` | freee OAuth refresh_token |
| `access_token` | freee OAuth access_token（キャッシュ） |
| `access_token_expires_at` | access_token有効期限 |

### Lambda環境変数に置いてよいもの

| 環境変数 | 説明 | 理由 |
|----------|------|------|
| `SECRET_NAME` | Secrets Managerのシークレット名 | シークレットではなくポインター |
| `AWS_REGION` | AWSリージョン | 公開情報 |
| `LOG_LEVEL` | ログレベル | 公開情報 |
| `FREEE_API_BASE_URL` | freee APIのベースURL | 公開情報 |

### Lambda環境変数に置いてはいけないもの

| 変数名 | 理由 |
|--------|------|
| `CLIENT_SECRET` | CloudFormationや設定ファイルに平文で残るリスク |
| `REFRESH_TOKEN` | 同上 |
| `ACCESS_TOKEN` | 同上 |
| `client_id` | 機密性は低いが一貫してSecrets Managerに集約する |

---

## 2. IAM 最小権限原則

### Lambda実行ロールに付与するポリシー

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadWriteFreeeSecret",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:PutSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:<region>:<account-id>:secret:freee/mcp-server-*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:<region>:<account-id>:log-group:/aws/lambda/remote-mcp-freee:*"
    }
  ]
}
```

**付与しないもの:**
- `secretsmanager:ListSecrets`
- `secretsmanager:DeleteSecret`
- `iam:*`（IAMの変更は一切不要）
- `s3:*`（MVPではS3不使用）
- その他すべての未使用権限

---

## 3. API Gatewayの公開範囲

### 認証方式（MVP）

| 方式 | 採用 | 理由 |
|------|------|------|
| APIキー（x-api-key） | ✓ MVP採用 | 設定が簡単。個人利用に十分 |
| Lambda オーソライザー | 将来対応 | JWT検証などに拡張可能 |
| Cognito | 将来対応 | マルチユーザー時に検討 |
| IAM認証 | ✗ | Claude Custom Connectorからは使いにくい |

### API Gatewayの設定

```
- HTTPSのみ許可（HTTP非対応）
- APIキーを必須化（Usage Planに紐付ける）
- スロットリング設定（個人利用: バースト100, レート50）
- CloudWatch Logsへのアクセスログ有効化
```

---

## 4. ログに出してはいけない情報

### 禁止リスト

| 情報 | 対応 |
|------|------|
| `access_token` | マスクまたは出力禁止 |
| `refresh_token` | マスクまたは出力禁止 |
| `client_secret` | マスクまたは出力禁止 |
| `client_id` | 出力禁止（機密ではないが一貫性のため） |
| freee APIの詳細エラーボディ（個人情報含む可能性） | 要約のみ出力 |

### ロギングのベストプラクティス

```python
# NG: トークンをそのまま出力
logger.info(f"Using access_token: {access_token}")

# OK: マスク処理
logger.info(f"Using access_token: {access_token[:8]}...")

# OK: トークンの存在確認のみ
logger.info(f"access_token loaded: {bool(access_token)}")
```

---

## 5. 想定される誤操作・リスクと対策

| リスク | 説明 | 対策 |
|--------|------|------|
| APIキー漏洩 | GitにAPIキーをコミット | `.gitignore` でSAM設定ファイルを管理。APIキーはCloudFormationパラメータで注入 |
| 誤った支出登録 | 不正なamountや日付 | `freee_validate_expense_input` でバリデーション |
| refresh_token流出 | Secrets Manager外に保存 | 必ずSecrets Managerのみに保存。ローカル開発では`.env`を`.gitignore` |
| 他人からのMCP呼び出し | APIキーを知っている第三者 | APIキーを厳重に管理。定期ローテーション |
| CloudFormationへの平文埋め込み | Parametersに秘密情報を書く | Secrets ManagerのARNを参照するように設計 |
| 大量リクエストによるコスト増 | Lambda大量起動 | API Gatewayスロットリング。WAF追加（将来） |
| freee API誤操作（削除等） | バグで意図しないAPIを呼ぶ | Lambdaコードでは登録・参照のみ実装。削除APIは実装しない |

---

## 6. Secrets Manager のローテーション方針

### refresh_token のローテーション

- freeeのrefresh_tokenは使用するたびに新しいトークンが発行される場合がある（要確認）
- 新しいrefresh_tokenを受け取ったら即座にSecrets Managerを更新する
- 更新に失敗した場合はCloudWatch Logsにエラーを記録してアラート

### APIキーのローテーション

- 手動ローテーション（3〜6ヶ月に1回推奨）
- API Gatewayで新しいAPIキーを発行 → Claude Custom Connectorの設定を更新 → 旧キーを削除

---

## 7. 開発時のセキュリティルール

1. `.env` ファイルを作る場合は必ず `.gitignore` に追加
2. SAMテンプレートに秘密情報を書かない
3. テストコードにモックトークンを書く場合も `"dummy-token-for-test"` 程度に留める
4. Secrets Managerの `PutSecretValue` はLambdaのみが行う設計（開発者はAWS CLIまたはコンソールで初期設定）
5. PRレビュー時に秘密情報の混入を必ず確認する
