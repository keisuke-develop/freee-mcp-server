"""
単体テスト: utils/secrets.py

Secrets Managerとのやり取りをmoto（AWSモックライブラリ）でテストする。
実際のAWS環境への接続は不要。
"""

import sys
import os
import json

import pytest
import boto3
from moto import mock_aws

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../app"))

# テスト用のシークレット名（本番とは別の名前を使う）
_TEST_SECRET_NAME = "freee/mcp-server-test"
_TEST_REGION = "ap-northeast-1"

# テスト用の有効なシークレット内容
_VALID_SECRET = {
    "client_id": "test-client-id",
    "client_secret": "test-client-secret",
    "refresh_token": "test-refresh-token",
    "access_token": "test-access-token",
    "access_token_expires_at": "2099-12-31T00:00:00+00:00",
    "company_id": 12345,
}


@mock_aws
class TestLoadSecret:
    """load_secret のテスト。"""

    def _create_secret(self, secret_value: dict):
        """テスト用シークレットをモックに作成する。"""
        client = boto3.client("secretsmanager", region_name=_TEST_REGION)
        client.create_secret(
            Name=_TEST_SECRET_NAME,
            SecretString=json.dumps(secret_value),
        )

    def test_正常系_有効なシークレットを読み込む(self, monkeypatch):
        # 環境変数をテスト用に上書き
        monkeypatch.setenv("SECRET_NAME", _TEST_SECRET_NAME)
        monkeypatch.setenv("AWS_REGION", _TEST_REGION)

        # モジュールキャッシュをリセット
        import utils.secrets as secrets_module
        secrets_module._client = None
        monkeypatch.setattr("utils.secrets._SECRET_NAME", _TEST_SECRET_NAME)

        self._create_secret(_VALID_SECRET)

        from utils.secrets import load_secret
        result = load_secret()

        assert result["client_id"] == "test-client-id"
        assert result["refresh_token"] == "test-refresh-token"
        assert result["company_id"] == 12345

    def test_異常系_シークレットが存在しない(self, monkeypatch):
        import utils.secrets as secrets_module
        secrets_module._client = None
        monkeypatch.setattr("utils.secrets._SECRET_NAME", "nonexistent/secret")

        from utils.secrets import load_secret
        with pytest.raises(RuntimeError, match="存在しません"):
            load_secret()

    def test_異常系_必須フィールドが欠けている(self, monkeypatch):
        import utils.secrets as secrets_module
        secrets_module._client = None
        monkeypatch.setattr("utils.secrets._SECRET_NAME", _TEST_SECRET_NAME)

        # refresh_tokenが欠けているシークレット
        invalid_secret = {
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            # refresh_token なし
        }
        self._create_secret(invalid_secret)

        from utils.secrets import load_secret
        with pytest.raises(RuntimeError, match="必須フィールド"):
            load_secret()


@mock_aws
class TestUpdateSecret:
    """update_secret のテスト。"""

    def _create_secret(self, secret_value: dict):
        client = boto3.client("secretsmanager", region_name=_TEST_REGION)
        client.create_secret(
            Name=_TEST_SECRET_NAME,
            SecretString=json.dumps(secret_value),
        )

    def test_正常系_シークレットを更新できる(self, monkeypatch):
        import utils.secrets as secrets_module
        secrets_module._client = None
        monkeypatch.setattr("utils.secrets._SECRET_NAME", _TEST_SECRET_NAME)

        self._create_secret(_VALID_SECRET)

        updated_secret = {**_VALID_SECRET, "access_token": "new-access-token"}

        from utils.secrets import update_secret, load_secret
        update_secret(updated_secret)

        # 更新後に読み直して確認（キャッシュをリセット）
        secrets_module._client = None
        result = load_secret()
        assert result["access_token"] == "new-access-token"
