"""
AWS Secrets Manager ヘルパー。

freee認証情報（client_id, client_secret, refresh_token, access_token, company_id）を
Secrets Managerから読み書きする。

重要:
  - 取得したシークレット値をログに出力しないこと
  - このモジュールはLambda内でのみ使用する（ローカル開発時はモックに差し替える）
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# シークレット名は環境変数で設定（デフォルト: freee/mcp-server）
_SECRET_NAME = os.environ.get("SECRET_NAME", "freee/mcp-server")
_AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")

# モジュールレベルでクライアントをキャッシュ（Lambda warm start で再利用される）
_client = None


def _get_client():
    """boto3 Secrets Managerクライアントを返す（遅延初期化）。"""
    global _client
    if _client is None:
        _client = boto3.client("secretsmanager", region_name=_AWS_REGION)
    return _client


def load_secret() -> dict:
    """
    Secrets Managerからfreee認証情報を読み込む。

    Returns:
        シークレット内容のdict
        {
            "client_id": str,
            "client_secret": str,
            "refresh_token": str,
            "access_token": str,
            "access_token_expires_at": str,
            "company_id": int | str
        }

    Raises:
        RuntimeError: シークレット取得失敗時（シークレットが存在しない、権限不足など）
    """
    client = _get_client()
    logger.debug("Loading secret: %s", _SECRET_NAME)

    try:
        response = client.get_secret_value(SecretId=_SECRET_NAME)
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ResourceNotFoundException":
            raise RuntimeError(
                f"Secrets Manager にシークレット '{_SECRET_NAME}' が存在しません。"
                f"初期セットアップ手順を確認してください。"
            )
        elif error_code == "AccessDeniedException":
            raise RuntimeError(
                f"Secrets Manager '{_SECRET_NAME}' へのアクセス権限がありません。"
                f"LambdaのIAMロールを確認してください。"
            )
        else:
            raise RuntimeError(f"Secrets Manager エラー [{error_code}]: {str(e)}")

    secret_string = response.get("SecretString")
    if not secret_string:
        raise RuntimeError(f"Secrets Manager '{_SECRET_NAME}' が空です。")

    try:
        secret = json.loads(secret_string)
    except json.JSONDecodeError:
        raise RuntimeError(f"Secrets Manager '{_SECRET_NAME}' のJSON解析に失敗しました。")

    # 必須フィールドの存在確認（値のログ出力はしない）
    required_fields = ["client_id", "client_secret", "refresh_token"]
    missing = [f for f in required_fields if not secret.get(f)]
    if missing:
        raise RuntimeError(
            f"Secrets Manager '{_SECRET_NAME}' に必須フィールドがありません: {missing}"
        )

    logger.debug("Secret loaded successfully: %s", _SECRET_NAME)
    return secret


def update_secret(secret: dict) -> None:
    """
    Secrets Managerのシークレットを更新する。

    access_tokenのrefresh後に新しいトークン情報を保存するために使用する。

    Args:
        secret: 更新後のシークレット全体のdict

    Raises:
        RuntimeError: 更新失敗時
    """
    client = _get_client()
    logger.debug("Updating secret: %s", _SECRET_NAME)

    try:
        client.put_secret_value(
            SecretId=_SECRET_NAME,
            SecretString=json.dumps(secret, ensure_ascii=False),
        )
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        raise RuntimeError(f"Secrets Manager 更新エラー [{error_code}]: {str(e)}")

    logger.info("Secret updated successfully: %s", _SECRET_NAME)
