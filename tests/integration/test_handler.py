"""
結合テスト: handler.py

Lambda handler の全体フローをテストする。
API Gatewayイベント → MCP JSON-RPC → ツール実行 → レスポンスの一連の流れを確認。
freee APIへの実際の通信はモックを使用する。
"""

import sys
import os
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../app"))

import lambda_handler as handler


def _make_api_gw_event(body: dict, path: str = "/mcp", method: str = "POST") -> dict:
    """API Gatewayプロキシ統合イベントを生成するヘルパー。"""
    return {
        "httpMethod": method,
        "path": path,
        "headers": {
            "Content-Type": "application/json",
            "Host": "example.com",
            "Authorization": "Bearer test-token",
        },
        "body": json.dumps(body),
        "queryStringParameters": None,
        "requestContext": {},
    }


def _make_secret() -> dict:
    """テスト用Secrets Managerシークレット。"""
    return {
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "refresh_token": "test-refresh-token",
        "access_token": "test-access-token",
        "access_token_expires_at": (
            datetime.now(tz=timezone.utc) + timedelta(hours=1)
        ).isoformat(),
        "company_id": 12345,
    }


class TestHealthCheck:
    """ヘルスチェックエンドポイントのテスト。"""

    def test_GETヘルスチェックが200を返す(self):
        event = {"httpMethod": "GET", "path": "/health", "body": None}
        response = handler.lambda_handler(event, None)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["status"] == "ok"


class TestMcpEndpoint:
    """MCPエンドポイントの結合テスト。"""

    def test_initialize_が正しく処理される(self):
        event = _make_api_gw_event({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "claude", "version": "1.0"}
            }
        })

        with patch("lambda_handler.get_oauth_config"), \
             patch("lambda_handler.validate_access_token", return_value={"sub": "user-1"}):
            response = handler.lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["result"]["serverInfo"]["name"] == "freee-mcp-server"

    def test_tools_list_が正しく処理される(self):
        event = _make_api_gw_event({
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/list",
            "params": {}
        })

        with patch("lambda_handler.get_oauth_config"), \
             patch("lambda_handler.validate_access_token", return_value={"sub": "user-1"}):
            response = handler.lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "tools" in body["result"]
        assert len(body["result"]["tools"]) == 4  # MVP: 4ツール

    def test_freee_create_expense_がfreee_APIを呼ぶ(self):
        mock_secret = _make_secret()
        mock_deal_response = {
            "deal": {"id": 999, "issue_date": "2026-04-19", "amount": 1500}
        }

        event = _make_api_gw_event({
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tools/call",
            "params": {
                "name": "freee_create_expense",
                "arguments": {
                    "issue_date": "2026-04-19",
                    "amount": 1500,
                    "account_item_id": 100,
                    "tax_code": 1,
                    "description": "テスト支出",
                }
            }
        })

        with patch("lambda_handler.get_oauth_config"), \
             patch("lambda_handler.validate_access_token", return_value={"sub": "user-1"}), \
             patch("freee.auth.load_secret", return_value=mock_secret), \
             patch("freee.auth.update_secret"), \
             patch("freee.client.http_post") as mock_post, \
             patch("freee.client.http_get"):

            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = mock_deal_response
            mock_post.return_value = mock_response

            response = handler.lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "result" in body
        content_text = body["result"]["content"][0]["text"]
        assert "支出登録が完了" in content_text
        assert "999" in content_text  # deal_id


class TestErrorHandling:
    """エラーハンドリングの結合テスト。"""

    def test_不正なJSONは400を返す(self):
        event = {
            "httpMethod": "POST",
            "path": "/mcp",
            "body": "invalid json {{{",
        }
        with patch("lambda_handler.get_oauth_config"), \
             patch("lambda_handler.validate_access_token", return_value={"sub": "user-1"}):
            response = handler.lambda_handler(event, None)
        assert response["statusCode"] == 400

    def test_空のボディは400を返す(self):
        event = {
            "httpMethod": "POST",
            "path": "/mcp",
            "body": "",
        }
        with patch("lambda_handler.get_oauth_config"), \
             patch("lambda_handler.validate_access_token", return_value={"sub": "user-1"}):
            response = handler.lambda_handler(event, None)
        assert response["statusCode"] == 400

    def test_jsonrpcバージョン不正は400を返す(self):
        event = _make_api_gw_event({
            "jsonrpc": "1.0",
            "id": "1",
            "method": "initialize",
            "params": {}
        })
        with patch("lambda_handler.get_oauth_config"), \
             patch("lambda_handler.validate_access_token", return_value={"sub": "user-1"}):
            response = handler.lambda_handler(event, None)
        assert response["statusCode"] == 400

    def test_存在しないパスは404を返す(self):
        event = {
            "httpMethod": "POST",
            "path": "/unknown",
            "body": json.dumps({"jsonrpc": "2.0", "id": "1", "method": "initialize", "params": {}}),
        }
        response = handler.lambda_handler(event, None)
        assert response["statusCode"] == 404

    def test_バリデーションエラーはMCPエラーとして200で返る(self):
        event = _make_api_gw_event({
            "jsonrpc": "2.0",
            "id": "5",
            "method": "tools/call",
            "params": {
                "name": "freee_validate_expense_input",
                "arguments": {
                    "issue_date": "invalid-date",
                    "amount": -1,
                    "account_item_id": 1,
                    "tax_code": 1,
                }
            }
        })

        with patch("lambda_handler.get_oauth_config"), \
             patch("lambda_handler.validate_access_token", return_value={"sub": "user-1"}):
            response = handler.lambda_handler(event, None)
        # バリデーションエラーはHTTP 200でMCPレスポンスとして返る
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        # freee_validate_expense_input はエラーでもresultとしてcontent配列を返す
        assert "result" in body
        assert "バリデーションエラー" in body["result"]["content"][0]["text"]

    def test_認証なしのMCPは401を返す(self):
        event = _make_api_gw_event({
            "jsonrpc": "2.0",
            "id": "6",
            "method": "tools/list",
            "params": {}
        })

        with patch("lambda_handler.get_oauth_config"), \
             patch("lambda_handler.validate_access_token", return_value=None):
            response = handler.lambda_handler(event, None)

        assert response["statusCode"] == 401
        assert "WWW-Authenticate" in response["headers"]

    def test_認可メタデータは200を返す(self):
        event = {
            "httpMethod": "GET",
            "path": "/.well-known/oauth-authorization-server",
            "headers": {"Host": "example.com"},
            "body": None,
            "queryStringParameters": None,
            "requestContext": {},
        }

        with patch(
            "lambda_handler.get_oauth_config",
            return_value=MagicMock(
                cognito_user_pool_id="ap-northeast-1_test",
                cognito_app_client_name="freee-mcp-oauth-prod",
                cognito_domain_url="https://example.auth.ap-northeast-1.amazoncognito.com",
                cognito_issuer_url="https://cognito-idp.ap-northeast-1.amazonaws.com/pool",
            ),
        ):
            response = handler.lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["authorization_endpoint"] == "https://example.com/authorize"
