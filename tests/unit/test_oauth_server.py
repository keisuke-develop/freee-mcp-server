"""
単体テスト: oauth_server.py

Cognito ログイン連携と、MCP サーバー自身が発行する OAuth トークンの
主要分岐を確認する。
"""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../app"))

import oauth_server


def _config() -> oauth_server.OAuthConfig:
    return oauth_server.OAuthConfig(
        table_name="dummy",
        cognito_user_pool_id="ap-northeast-1_test",
        cognito_app_client_name="freee-mcp-oauth-prod",
        cognito_domain_url="https://freee.auth.ap-northeast-1.amazoncognito.com",
        cognito_issuer_url="https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_test",
    )


class TestMetadata:
    def test_認可サーバーメタデータを生成できる(self):
        metadata = oauth_server.build_authorization_metadata("https://example.com", _config())

        assert metadata["issuer"] == "https://example.com"
        assert metadata["authorization_endpoint"] == "https://example.com/authorize"
        assert metadata["token_endpoint"] == "https://example.com/token"
        assert metadata["registration_endpoint"] == "https://example.com/register"
        assert metadata["authorization_response_iss_parameter_supported"] is True
        assert metadata["resource_parameter_supported"] is True

    def test_保護リソースメタデータを生成できる(self):
        metadata = oauth_server.build_resource_metadata("https://example.com", _config())

        assert metadata["resource"] == "https://example.com/mcp"
        assert metadata["authorization_servers"] == ["https://example.com"]
        assert metadata["bearer_methods_supported"] == ["header"]


class TestPkce:
    def test_PKCE検証_一致すればTrue(self):
        verifier = "plain-code-verifier-value"

        import base64
        import hashlib

        digest = hashlib.sha256(verifier.encode("utf-8")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

        assert oauth_server.verify_pkce(verifier, challenge) is True

    def test_PKCE検証_不一致ならFalse(self):
        assert oauth_server.verify_pkce("verifier", "invalid") is False


class TestTokenIssuance:
    def test_アクセストークン発行結果を返せる(self, monkeypatch):
        stored_items = []
        monkeypatch.setattr(oauth_server, "_put_item", stored_items.append)

        response = oauth_server.issue_tokens(
            client_id="mcp_client",
            subject="user-sub",
            username="kuskus_ainan",
            scope="openid profile",
            resource="https://example.com/mcp",
        )

        assert response["token_type"] == "Bearer"
        assert response["expires_in"] == 3600
        assert response["access_token"].startswith("atk_")
        assert response["refresh_token"].startswith("rtk_")
        assert len(stored_items) == 2

    def test_認可コード交換でサーバートークンを返す(self, monkeypatch):
        monkeypatch.setattr(
            oauth_server,
            "_consume_item",
            lambda pk: {
                "client_id": "mcp_client",
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "code_challenge": "challenge",
                "subject": "user-sub",
                "username": "kuskus_ainan",
                "scope": "openid email profile",
                "resource": "https://example.com/mcp",
            },
        )
        monkeypatch.setattr(oauth_server, "verify_pkce", lambda verifier, challenge: True)
        monkeypatch.setattr(
            oauth_server,
            "issue_tokens",
            lambda **kwargs: {
                "access_token": "atk_test",
                "refresh_token": "rtk_test",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": kwargs["scope"],
            },
        )

        status_code, body = oauth_server.exchange_token(
            {
                "body": (
                    "grant_type=authorization_code&code=code123&client_id=mcp_client"
                    "&redirect_uri=https%3A%2F%2Fclaude.ai%2Fapi%2Fmcp%2Fauth_callback"
                    "&code_verifier=verifier&resource=https%3A%2F%2Fexample.com%2Fmcp"
                )
            },
            "https://example.com",
            _config(),
        )

        assert status_code == 200
        assert body["access_token"] == "atk_test"
        assert body["refresh_token"] == "rtk_test"

    def test_リフレッシュトークン交換で新トークンを返す(self, monkeypatch):
        monkeypatch.setattr(
            oauth_server,
            "_consume_item",
            lambda pk: {
                "client_id": "mcp_client",
                "subject": "user-sub",
                "username": "kuskus_ainan",
                "scope": "openid email profile",
                "resource": "https://example.com/mcp",
            },
        )
        monkeypatch.setattr(
            oauth_server,
            "issue_tokens",
            lambda **kwargs: {
                "access_token": "atk_new",
                "refresh_token": "rtk_new",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": kwargs["scope"],
            },
        )

        status_code, body = oauth_server.exchange_token(
            {
                "body": (
                    "grant_type=refresh_token&refresh_token=rtk_old&client_id=mcp_client"
                    "&resource=https%3A%2F%2Fexample.com%2Fmcp"
                )
            },
            "https://example.com",
            _config(),
        )

        assert status_code == 200
        assert body["access_token"] == "atk_new"
        assert body["refresh_token"] == "rtk_new"


class TestValidateAccessToken:
    def test_正常系_有効なアクセストークンを受け入れる(self, monkeypatch):
        monkeypatch.setattr(
            oauth_server,
            "_get_item",
            lambda pk: {
                "client_id": {"S": "mcp_client"},
                "subject": {"S": "user-sub"},
                "username": {"S": "kuskus_ainan"},
                "scope": {"S": "openid"},
                "resource": {"S": "https://example.com/mcp"},
                "expires_at": {"N": str(int(oauth_server.time.time()) + 3600)},
            },
        )

        claims = oauth_server.validate_access_token("Bearer atk_token", _config())
        assert claims["sub"] == "user-sub"
        assert claims["username"] == "kuskus_ainan"

    def test_異常系_BearerなしはNone(self):
        assert oauth_server.validate_access_token(None, _config()) is None
        assert oauth_server.validate_access_token("Basic xxx", _config()) is None

    def test_異常系_期限切れならNone(self, monkeypatch):
        monkeypatch.setattr(
            oauth_server,
            "_get_item",
            lambda pk: {
                "client_id": {"S": "mcp_client"},
                "subject": {"S": "user-sub"},
                "username": {"S": "kuskus_ainan"},
                "expires_at": {"N": str(int(oauth_server.time.time()) - 1)},
            },
        )

        assert oauth_server.validate_access_token("Bearer atk_token", _config()) is None

    def test_CognitoアプリクライアントIDを名前から解決できる(self, monkeypatch):
        paginator = MagicMock()
        paginator.paginate.return_value = [{
            "UserPoolClients": [
                {"ClientName": "other", "ClientId": "client-x"},
                {"ClientName": "freee-mcp-oauth-prod", "ClientId": "client-123"},
            ]
        }]

        cognito_client = MagicMock()
        cognito_client.get_paginator.return_value = paginator

        monkeypatch.setattr(oauth_server, "_cognito_client", cognito_client)
        monkeypatch.setattr(oauth_server, "_resolved_cognito_app_client_id", None)

        client_id = oauth_server.resolve_cognito_app_client_id(_config())
        assert client_id == "client-123"


class TestAuthorizationCallback:
    def test_Cognitoコールバックはiss付きでリダイレクトする(self, monkeypatch):
        monkeypatch.setattr(
            oauth_server,
            "_consume_item",
            lambda pk: {
                "client_id": "mcp_client",
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "state": "state-123",
                "code_challenge": "challenge-123",
                "scope": "openid email profile",
                "resource": "https://example.com/mcp",
            },
        )
        stored_items = []
        monkeypatch.setattr(oauth_server, "_put_item", stored_items.append)
        monkeypatch.setattr(oauth_server, "resolve_cognito_app_client_id", lambda config: "client-123")
        monkeypatch.setattr(
            oauth_server,
            "extract_principal",
            lambda token_data: {"subject": "user-sub", "username": "kuskus_ainan"},
        )

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"id_token": "token"}
        monkeypatch.setattr(oauth_server.requests, "post", lambda *args, **kwargs: response)

        status_code, body = oauth_server.handle_cognito_callback(
            {
                "queryStringParameters": {
                    "code": "cognito-code",
                    "state": "state-key",
                }
            },
            "https://example.com",
            _config(),
        )

        assert status_code == 302
        assert "code=" in body["location"]
        assert "state=state-123" in body["location"]
        assert "iss=https://example.com" in body["location"]
        assert stored_items[0]["subject"]["S"] == "user-sub"

    def test_Cognito応答からユーザー識別子を抽出できる(self):
        token = jwt_like_token({"sub": "user-sub", "cognito:username": "kuskus_ainan"})
        principal = oauth_server.extract_principal({"id_token": token})
        assert principal == {"subject": "user-sub", "username": "kuskus_ainan"}


def jwt_like_token(payload: dict[str, str]) -> str:
    import base64
    import json

    def encode_part(data: dict[str, str]) -> str:
        raw = json.dumps(data).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    signature = base64.urlsafe_b64encode(b"sig").decode("utf-8").rstrip("=")
    return f"{encode_part({'alg': 'RS256'})}.{encode_part(payload)}.{signature}"
