"""
freee API クライアント。

freee APIへのHTTPリクエストを担当する。
認証はFreeeAuthクラスに委譲し、このクラスはAPIエンドポイント呼び出しに専念する。

対応エンドポイント（MVP）:
  - GET  /api/1/account_items  : 勘定科目一覧取得
  - GET  /api/1/taxes/companies/{company_id}  : 税区分一覧取得
  - POST /api/1/deals  : 取引（支出）登録

freee API リファレンス: https://developer.freee.co.jp/reference/accounting/reference
（要確認: 最新のAPIエンドポイントは公式リファレンスで確認すること）
"""

import logging
import os
from typing import Any

from freee.auth import FreeeAuth
from utils.http import http_get, http_post, HttpRequestError, HttpTimeoutError

logger = logging.getLogger(__name__)

_FREEE_API_BASE = os.environ.get("FREEE_API_BASE_URL", "https://api.freee.co.jp")

# freee APIリクエストのタイムアウト（秒）
_REQUEST_TIMEOUT = 15

# 401エラー時の最大リトライ回数（access_token refresh後の再試行）
_MAX_RETRY_ON_401 = 1


class FreeeClient:
    """
    freee API クライアント。

    各メソッドでfreee APIを呼び出す。
    access_tokenの有効期限管理はFreeeAuthに委譲する。
    """

    def __init__(self) -> None:
        self._auth = FreeeAuth()

    def get_account_items(self, account_type: str | None = None) -> list[dict]:
        """
        勘定科目一覧を取得する。

        Args:
            account_type: フィルタリング種別（"expense", "income" など）。Noneなら全件。

        Returns:
            勘定科目dictのリスト
            [{ "id": int, "name": str, "account_category": str, ... }]

        Raises:
            RuntimeError: API呼び出し失敗時
        """
        company_id = self._auth.get_company_id()
        params: dict = {"company_id": company_id}
        if account_type:
            params["type"] = account_type

        response = self._get("/api/1/account_items", params=params)
        return response.get("account_items", [])

    def get_taxes(self) -> list[dict]:
        """
        税区分一覧を取得する。

        Returns:
            税区分dictのリスト
            [{ "code": int, "name": str, "rate_percent": float | None, ... }]

        Raises:
            RuntimeError: API呼び出し失敗時

        公式ドキュメント確認済み:
          GET /api/1/taxes/codes が推奨エンドポイント（認証のみ、company_id不要）。
          GET /api/1/taxes は非推奨のため使用しない。
        """
        response = self._get("/api/1/taxes/codes")
        return response.get("taxes", [])

    def create_deal(
        self,
        issue_date: str,
        amount: int,
        account_item_id: int,
        tax_code: int,
        description: str = "",
        partner_id: int | None = None,
    ) -> dict:
        """
        取引（支出）を登録する。

        Args:
            issue_date: 発生日（YYYY-MM-DD）
            amount: 金額（税込、円）
            account_item_id: 勘定科目ID
            tax_code: 税区分コード
            description: 備考（空文字も可）
            partner_id: 取引先ID（任意）

        Returns:
            freee APIのレスポンスdict
            { "deal": { "id": int, "issue_date": str, "amount": int, ... } }

        Raises:
            RuntimeError: API呼び出し失敗時

        """
        company_id = self._auth.get_company_id()

        # freee API POST /api/1/deals のリクエストボディ（公式ドキュメント確認済み）
        # due_amount はトップレベルには不要。金額は details[].amount で指定する。
        payload = {
            "company_id": company_id,
            "issue_date": issue_date,
            "type": "expense",   # 支出（経費）
            "details": [
                {
                    "account_item_id": account_item_id,
                    "tax_code": tax_code,
                    "amount": amount,
                    "description": description,
                }
            ]
        }

        if partner_id is not None:
            payload["partner_id"] = partner_id

        logger.info(
            "create_deal: date=%s amount=%d account_item_id=%d",
            issue_date, amount, account_item_id
        )
        return self._post("/api/1/deals", json=payload)

    def _get(self, path: str, params: dict | None = None, retry: int = 0) -> dict:
        """
        freee APIにGETリクエストを送る。

        Args:
            path: APIパス（/api/1/... 形式）
            params: クエリパラメータ
            retry: リトライ回数（内部使用）

        Returns:
            レスポンスのJSONをdictとして返す

        Raises:
            RuntimeError: API呼び出し失敗時
        """
        access_token = self._auth.get_valid_access_token()
        headers = self._build_headers(access_token)

        try:
            response = http_get(
                f"{_FREEE_API_BASE}{path}",
                params=params,
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
            )
        except HttpTimeoutError:
            raise RuntimeError(f"freee API タイムアウト: GET {path}")
        except HttpRequestError as e:
            raise RuntimeError(f"freee API 接続エラー: {type(e).__name__}")

        return self._handle_response(response, path, "GET", params, retry)

    def _post(self, path: str, json: dict, retry: int = 0) -> dict:
        """
        freee APIにPOSTリクエストを送る。

        Args:
            path: APIパス
            json: リクエストボディ
            retry: リトライ回数（内部使用）

        Returns:
            レスポンスのJSONをdictとして返す

        Raises:
            RuntimeError: API呼び出し失敗時
        """
        access_token = self._auth.get_valid_access_token()
        headers = self._build_headers(access_token)

        try:
            response = http_post(
                f"{_FREEE_API_BASE}{path}",
                json_body=json,
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
            )
        except HttpTimeoutError:
            raise RuntimeError(f"freee API タイムアウト: POST {path}")
        except HttpRequestError as e:
            raise RuntimeError(f"freee API 接続エラー: {type(e).__name__}")

        return self._handle_response(response, path, "POST", None, retry, json)

    def _handle_response(
        self,
        response: Any,
        path: str,
        method: str,
        params: Any,
        retry: int,
        json_body: dict | None = None,
    ) -> dict:
        """
        freee APIレスポンスを処理する。

        401の場合はaccess_tokenをrefreshして1回リトライする。
        422はバリデーションエラーとしてそのまま例外にする。
        その他のエラーはRuntimeErrorに変換する。
        """
        status = response.status_code

        if status == 200 or status == 201:
            return response.json()

        # 401: access_token期限切れ → refresh して1回だけリトライ
        if status == 401 and retry < _MAX_RETRY_ON_401:
            logger.warning("401 Unauthorized: refreshing access_token and retrying...")
            # キャッシュをリセットしてrefreshを強制
            self._auth._secret = None
            if method == "GET":
                return self._get(path, params=params, retry=retry + 1)
            else:
                return self._post(path, json=json_body or {}, retry=retry + 1)

        # 422: バリデーションエラー（freee側の入力拒否）
        if status == 422:
            try:
                error_body = response.json()
                errors = error_body.get("errors", [])
                error_msg = "; ".join(
                    e.get("message", "") for e in errors if isinstance(e, dict)
                ) or response.text
            except Exception:
                error_msg = response.text
            raise ValueError(f"freee APIバリデーションエラー: {error_msg}")

        # 429: レート制限
        if status == 429:
            retry_after = response.headers.get("Retry-After", "不明")
            raise RuntimeError(f"freee API レート制限。Retry-After: {retry_after}秒")

        # その他エラー
        try:
            error_body = response.json()
        except Exception:
            error_body = response.text
        logger.error("freee API error: %s %s -> %d body=%s", method, path, status, error_body)
        raise RuntimeError(f"freee API エラー: {method} {path} -> HTTP {status}")

    @staticmethod
    def _build_headers(access_token: str) -> dict:
        """freee API用のHTTPヘッダーを構築する。"""
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
