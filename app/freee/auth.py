"""
freee OAuth 2.0 トークン管理。

Secrets Managerからfreee認証情報を読み込み、
access_tokenの有効期限を確認し、必要に応じてrefresh_tokenで更新する。

重要: access_token / refresh_token をログに出力しないこと。
"""

import logging
from datetime import datetime, timedelta, timezone

import requests

from utils.secrets import load_secret, update_secret

logger = logging.getLogger(__name__)

# freee OAuth トークンエンドポイント
_TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"

# access_tokenの有効期限をこの秒数前に「期限切れ」と判断してrefreshする（バッファ）
_EXPIRY_BUFFER_SECONDS = 300  # 5分前にrefreshする


class FreeeAuth:
    """
    freee OAuth 2.0 認証情報を管理するクラス。

    Secrets Managerからシークレットを読み込み、
    access_tokenの有効期限を管理する。
    """

    def __init__(self) -> None:
        self._secret: dict | None = None

    def get_valid_access_token(self) -> str:
        """
        有効なaccess_tokenを返す。

        access_tokenが期限切れ（またはまもなく切れる）場合は
        refresh_tokenを使って自動更新する。

        Returns:
            有効なaccess_token文字列

        Raises:
            RuntimeError: トークン取得・更新失敗時
        """
        secret = self._load_secret()

        if self._is_token_valid(secret):
            logger.debug("access_token is valid, using cached token")
            return secret["access_token"]

        logger.info("access_token expired or missing, refreshing...")
        return self._refresh_access_token(secret)

    def get_company_id(self) -> int:
        """
        freee事業所IDを返す。

        Returns:
            company_id (int)

        Raises:
            RuntimeError: シークレット取得失敗時
            KeyError: company_idがシークレットに存在しない場合
        """
        secret = self._load_secret()
        company_id = secret.get("company_id")
        if not company_id:
            raise RuntimeError(
                "company_id がSecrets Managerに設定されていません。"
                "freee/mcp-serverシークレットにcompany_idを追加してください。"
            )
        return int(company_id)

    def _load_secret(self) -> dict:
        """Secrets Managerからシークレットを読み込む（キャッシュあり）。"""
        if self._secret is None:
            self._secret = load_secret()
        return self._secret

    def _is_token_valid(self, secret: dict) -> bool:
        """
        access_tokenが有効かどうかを確認する。

        Args:
            secret: Secrets Managerから取得したシークレットdict

        Returns:
            True: トークンが有効
            False: トークンが存在しないか期限切れ
        """
        access_token = secret.get("access_token")
        if not access_token:
            return False

        expires_at_str = secret.get("access_token_expires_at")
        if not expires_at_str:
            # 有効期限情報なし → 安全側に倒してrefresh
            return False

        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            # タイムゾーン情報がない場合はUTCとして扱う
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            now = datetime.now(tz=timezone.utc)
            buffer = timedelta(seconds=_EXPIRY_BUFFER_SECONDS)

            return now < (expires_at - buffer)
        except (ValueError, TypeError):
            logger.warning("access_token_expires_at のパースに失敗しました。refreshします。")
            return False

    def _refresh_access_token(self, secret: dict) -> str:
        """
        refresh_tokenを使ってaccess_tokenを更新する。

        freee OAuth2.0のrefreshエンドポイントを呼び出し、
        新しいaccess_tokenをSecrets Managerに保存する。

        Args:
            secret: 現在のシークレットdict（refresh_tokenを含む）

        Returns:
            新しいaccess_token文字列

        Raises:
            RuntimeError: refresh失敗時
        """
        refresh_token = secret.get("refresh_token")
        client_id = secret.get("client_id")
        client_secret = secret.get("client_secret")

        if not all([refresh_token, client_id, client_secret]):
            raise RuntimeError(
                "refresh_token / client_id / client_secret がSecrets Managerに設定されていません。"
            )

        try:
            response = requests.post(
                _TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=10,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout:
            raise RuntimeError("freee OAuthトークンのrefreshがタイムアウトしました。")
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"freee OAuthトークンのrefreshに失敗しました: {e.response.status_code}")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"freee OAuthへの接続エラー: {type(e).__name__}")

        token_data = response.json()
        new_access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 21600)  # freeeのaccess_token有効期限は6時間（21600秒）

        if not new_access_token:
            raise RuntimeError("freee OAuthレスポンスにaccess_tokenが含まれていません。")

        # 有効期限を計算（バッファを含まない実際の有効期限）
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in)

        # 更新するフィールドのみ上書き
        updates: dict = {
            "access_token": new_access_token,
            "access_token_expires_at": expires_at.isoformat(),
        }

        # freeeが新しいrefresh_tokenを返した場合は更新する
        new_refresh_token = token_data.get("refresh_token")
        if new_refresh_token and new_refresh_token != refresh_token:
            logger.info("refresh_token が更新されました。Secrets Managerを更新します。")
            updates["refresh_token"] = new_refresh_token

        # Secrets Managerを更新
        updated_secret = {**secret, **updates}
        update_secret(updated_secret)

        # キャッシュも更新
        self._secret = updated_secret

        logger.info("access_token refresh 完了。有効期限: %s", expires_at.isoformat())
        return new_access_token
