"""
MCP JSON-RPC 2.0 ルーター。

受け取ったJSON-RPCリクエストの `method` フィールドを見て、
適切なハンドラーに処理を振り分ける。

対応メソッド:
  - initialize       : サーバー情報を返す
  - initialized      : 初期化完了通知（no-op）
  - tools/list       : 利用可能なツール一覧を返す
  - tools/call       : 指定ツールを実行して結果を返す

入力:  dict（JSON-RPC 2.0リクエスト）
出力:  dict（JSON-RPC 2.0レスポンス）
"""

import logging
from typing import Any

from tools import TOOL_REGISTRY, get_tool_definitions

logger = logging.getLogger(__name__)

# サーバー情報
SERVER_NAME = "freee-mcp-server"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"


def route_request(rpc_request: dict) -> dict:
    """
    JSON-RPCリクエストを適切なハンドラーに振り分ける。

    Args:
        rpc_request: JSON-RPC 2.0リクエストdict

    Returns:
        JSON-RPC 2.0レスポンスdict
    """
    request_id = rpc_request.get("id")
    method = rpc_request.get("method", "")
    params = rpc_request.get("params", {}) or {}

    logger.debug("Routing method: %s", method)

    if method == "initialize":
        return _handle_initialize(request_id, params)

    if method == "initialized":
        # 通知（idなし）。レスポンス不要だが200を返す
        return _success_response(request_id, {})

    if method == "tools/list":
        return _handle_tools_list(request_id, params)

    if method == "tools/call":
        return _handle_tools_call(request_id, params)

    # 未知のメソッド
    logger.warning("Unknown method: %s", method)
    return _error_response(request_id, -32601, f"Method not found: {method}")


def _handle_initialize(request_id: Any, params: dict) -> dict:
    """
    initialize ハンドラー。

    Claudeが接続時に最初に呼び出す。
    サーバー情報と対応プロトコルバージョンを返す。

    Args:
        request_id: JSON-RPC リクエストID
        params: { protocolVersion, capabilities, clientInfo }

    Returns:
        JSON-RPC 成功レスポンス
    """
    client_info = params.get("clientInfo", {})
    logger.info("Client connected: %s %s",
                client_info.get("name"), client_info.get("version"))

    return _success_response(request_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {
            "tools": {}
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        }
    })


def _handle_tools_list(request_id: Any, params: dict) -> dict:
    """
    tools/list ハンドラー。

    Claudeが利用可能なツール一覧を取得するために呼び出す。
    各ツールの name, description, inputSchema を返す。

    Args:
        request_id: JSON-RPC リクエストID
        params: {} （現時点では未使用）

    Returns:
        JSON-RPC 成功レスポンス（tools配列）
    """
    tools = get_tool_definitions()
    logger.info("tools/list: returning %d tools", len(tools))

    return _success_response(request_id, {
        "tools": tools
    })


def _handle_tools_call(request_id: Any, params: dict) -> dict:
    """
    tools/call ハンドラー。

    指定されたツールを実行して結果を返す。

    Args:
        request_id: JSON-RPC リクエストID
        params: { name: str, arguments: dict }

    Returns:
        JSON-RPC 成功レスポンス（content配列）またはエラーレスポンス
    """
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {}) or {}

    if not tool_name:
        return _error_response(request_id, -32602, "Invalid params: 'name' is required")

    tool_fn = TOOL_REGISTRY.get(tool_name)
    if tool_fn is None:
        logger.warning("Tool not found: %s", tool_name)
        return _error_response(request_id, -32601, f"Tool not found: {tool_name}")

    logger.info("Executing tool: %s", tool_name)

    try:
        content = tool_fn(arguments)
        return _success_response(request_id, {"content": content})
    except ValueError as e:
        # バリデーションエラー（想定内）
        logger.warning("Tool validation error [%s]: %s", tool_name, str(e))
        return _error_response(request_id, -32602, f"Invalid input: {str(e)}")
    except Exception as e:
        # 予期しないエラー
        logger.exception("Tool execution error [%s]", tool_name)
        return _error_response(request_id, -32603, f"Tool error: {type(e).__name__}: {str(e)}")


def _success_response(request_id: Any, result: dict) -> dict:
    """JSON-RPC 2.0 成功レスポンスを構築する。"""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def _error_response(request_id: Any, code: int, message: str) -> dict:
    """JSON-RPC 2.0 エラーレスポンスを構築する。"""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        }
    }
