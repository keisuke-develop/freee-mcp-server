"""
単体テスト: mcp_router.py

MCPルーターのメソッドルーティングが正しく機能するかをテストする。
freee APIへの実際の通信は行わない（ツール実行はモック）。
"""

import sys
import os
import json
from unittest.mock import patch, MagicMock

import pytest

# app/ をパスに追加（Lambda実行環境と同じ構成）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../app"))

import mcp_router


class TestInitialize:
    """initialize メソッドのテスト。"""

    def test_正常系_サーバー情報が返る(self):
        request = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "claude", "version": "1.0"}
            }
        }

        response = mcp_router.route_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "1"
        assert "result" in response
        assert response["result"]["protocolVersion"] == "2024-11-05"
        assert response["result"]["serverInfo"]["name"] == "freee-mcp-server"
        assert "tools" in response["result"]["capabilities"]

    def test_正常系_idがNoneでも動作する(self):
        request = {
            "jsonrpc": "2.0",
            "id": None,
            "method": "initialize",
            "params": {}
        }
        response = mcp_router.route_request(request)
        assert response["id"] is None
        assert "result" in response


class TestToolsList:
    """tools/list メソッドのテスト。"""

    def test_正常系_ツール一覧が返る(self):
        request = {
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/list",
            "params": {}
        }

        response = mcp_router.route_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "2"
        assert "result" in response
        tools = response["result"]["tools"]
        assert isinstance(tools, list)
        assert len(tools) > 0

        # 必須ツールの存在確認
        tool_names = [t["name"] for t in tools]
        assert "freee_create_expense" in tool_names
        assert "freee_list_account_items" in tool_names
        assert "freee_list_tax_codes" in tool_names
        assert "freee_validate_expense_input" in tool_names

    def test_正常系_各ツールにinputSchemaが存在する(self):
        request = {
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/list",
            "params": {}
        }
        response = mcp_router.route_request(request)
        tools = response["result"]["tools"]

        for tool in tools:
            assert "name" in tool, f"ツール '{tool}' に name がありません"
            assert "description" in tool, f"ツール '{tool['name']}' に description がありません"
            assert "inputSchema" in tool, f"ツール '{tool['name']}' に inputSchema がありません"


class TestToolsCall:
    """tools/call メソッドのテスト。"""

    def test_正常系_ツール実行成功(self):
        mock_content = [{"type": "text", "text": "テスト結果"}]

        with patch("mcp_router.TOOL_REGISTRY", {"test_tool": lambda args: mock_content}):
            request = {
                "jsonrpc": "2.0",
                "id": "3",
                "method": "tools/call",
                "params": {
                    "name": "test_tool",
                    "arguments": {}
                }
            }
            response = mcp_router.route_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "3"
        assert "result" in response
        assert response["result"]["content"] == mock_content

    def test_異常系_存在しないツール名(self):
        request = {
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tools/call",
            "params": {
                "name": "nonexistent_tool",
                "arguments": {}
            }
        }
        response = mcp_router.route_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32601

    def test_異常系_tool_nameが未指定(self):
        request = {
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tools/call",
            "params": {}
        }
        response = mcp_router.route_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32602

    def test_異常系_ツール内でValueError発生(self):
        def failing_tool(args):
            raise ValueError("不正な入力値です")

        with patch("mcp_router.TOOL_REGISTRY", {"bad_tool": failing_tool}):
            request = {
                "jsonrpc": "2.0",
                "id": "3",
                "method": "tools/call",
                "params": {"name": "bad_tool", "arguments": {}}
            }
            response = mcp_router.route_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32602

    def test_異常系_ツール内で予期しないエラー発生(self):
        def crashing_tool(args):
            raise RuntimeError("予期しないエラー")

        with patch("mcp_router.TOOL_REGISTRY", {"crash_tool": crashing_tool}):
            request = {
                "jsonrpc": "2.0",
                "id": "3",
                "method": "tools/call",
                "params": {"name": "crash_tool", "arguments": {}}
            }
            response = mcp_router.route_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32603


class TestUnknownMethod:
    """未知のメソッドのテスト。"""

    def test_異常系_未知のメソッド(self):
        request = {
            "jsonrpc": "2.0",
            "id": "99",
            "method": "unknown/method",
            "params": {}
        }
        response = mcp_router.route_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32601
        assert response["id"] == "99"

    def test_正常系_initializedは無視される(self):
        # initialized は通知（no-op）
        request = {
            "jsonrpc": "2.0",
            "id": None,
            "method": "initialized",
            "params": {}
        }
        response = mcp_router.route_request(request)
        assert "error" not in response
