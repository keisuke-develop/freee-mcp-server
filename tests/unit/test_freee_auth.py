"""
単体テスト: freee/auth.py

FreeeAuth クラスのトークン有効期限チェックとrefreshロジックをテストする。
外部HTTP通信とSecrets Managerはモックを使用する。
"""

import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../app"))

from freee.auth import FreeeAuth


def _make_secret(expires_in_seconds: int | None = 86400, access_token: str = "dummy-token") -> dict:
    """テスト用シークレットdictを生成するヘルパー。"""
    base = {
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "refresh_token": "test-refresh-token",
        "access_token": access_token,
        "company_id": 12345,
    }
    if expires_in_seconds is not None:
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in_seconds)
        base["access_token_expires_at"] = expires_at.isoformat()
    return base


class TestGetValidAccessToken:
    """get_valid_access_token のテスト。"""

    def test_正常系_有効なトークンがあればそのまま返す(self):
        secret = _make_secret(expires_in_seconds=3600)  # 1時間後に期限切れ

        with patch("freee.auth.load_secret", return_value=secret):
            auth = FreeeAuth()
            token = auth.get_valid_access_token()

        assert token == "dummy-token"

    def test_正常系_期限切れトークンはrefreshされる(self):
        secret = _make_secret(expires_in_seconds=-100)  # 100秒前に期限切れ

        new_token_response = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 86400,
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = new_token_response

        with patch("freee.auth.load_secret", return_value=secret), \
             patch("freee.auth.update_secret") as mock_update, \
             patch("freee.auth.http_post", return_value=mock_response):
            auth = FreeeAuth()
            token = auth.get_valid_access_token()

        assert token == "new-access-token"
        # Secrets Managerの更新が呼ばれたことを確認
        mock_update.assert_called_once()

    def test_正常系_expires_at未設定はrefreshされる(self):
        secret = _make_secret(expires_in_seconds=None)  # expires_at なし

        new_token_response = {
            "access_token": "refreshed-token",
            "expires_in": 86400,
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = new_token_response

        with patch("freee.auth.load_secret", return_value=secret), \
             patch("freee.auth.update_secret"), \
             patch("freee.auth.http_post", return_value=mock_response):
            auth = FreeeAuth()
            token = auth.get_valid_access_token()

        assert token == "refreshed-token"

    def test_異常系_refreshが失敗するとRuntimeErrorが上がる(self):
        secret = _make_secret(expires_in_seconds=-100)  # 期限切れ

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")

        with patch("freee.auth.load_secret", return_value=secret), \
             patch("freee.auth.http_post") as mock_post:
            mock_post.return_value = MagicMock(status_code=401)
            auth = FreeeAuth()

            with pytest.raises(RuntimeError):
                auth.get_valid_access_token()


class TestIsTokenValid:
    """_is_token_valid の内部ロジックテスト。"""

    def test_有効期限まで十分な余裕がある場合はTrue(self):
        secret = _make_secret(expires_in_seconds=600)  # 10分後
        auth = FreeeAuth()
        assert auth._is_token_valid(secret) is True

    def test_バッファ内の場合はFalse(self):
        # バッファは300秒。200秒後に期限切れ → バッファ内なのでFalse
        secret = _make_secret(expires_in_seconds=200)
        auth = FreeeAuth()
        assert auth._is_token_valid(secret) is False

    def test_access_tokenが空の場合はFalse(self):
        secret = _make_secret(expires_in_seconds=3600, access_token="")
        auth = FreeeAuth()
        assert auth._is_token_valid(secret) is False

    def test_access_tokenがない場合はFalse(self):
        secret = {"client_id": "x", "client_secret": "y", "refresh_token": "z"}
        auth = FreeeAuth()
        assert auth._is_token_valid(secret) is False


class TestGetCompanyId:
    """get_company_id のテスト。"""

    def test_正常系_company_idが返る(self):
        secret = _make_secret()
        with patch("freee.auth.load_secret", return_value=secret):
            auth = FreeeAuth()
            company_id = auth.get_company_id()
        assert company_id == 12345

    def test_異常系_company_idが未設定(self):
        secret = _make_secret()
        del secret["company_id"]

        with patch("freee.auth.load_secret", return_value=secret):
            auth = FreeeAuth()
            with pytest.raises(RuntimeError, match="company_id"):
                auth.get_company_id()
