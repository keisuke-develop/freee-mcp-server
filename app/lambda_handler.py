"""
Lambda エントリポイント。

API Gatewayからのイベントを受け取り、MCP JSON-RPC 2.0リクエストとして処理する。
全てのMCPメソッド（initialize / tools/list / tools/call）をここで受け付け、
mcp_router.pyに処理を委譲する。

AWSのデフォルト命名規則に従い、ファイル名は lambda_handler.py、
SAMテンプレートのHandlerは lambda_handler.lambda_handler と設定する。

入力:  API Gateway Proxy Integration イベント
出力:  API Gateway Proxy Integration レスポンス（statusCode + body）
"""

import json
import logging
import os
from typing import Any

from mcp_router import route_request

# ロガー設定（ログレベルは環境変数で制御）
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)


def lambda_handler(event: dict, context: Any) -> dict:
    """
    Lambda メインハンドラー。

    Args:
        event: API Gatewayプロキシ統合イベント
        context: Lambdaコンテキスト（タイムアウト情報など）

    Returns:
        API Gatewayプロキシ統合レスポンス
        {
            "statusCode": 200,
            "headers": {...},
            "body": "<JSON文字列>"
        }
    """
    logger.info("Request received: method=%s path=%s",
                event.get("httpMethod"), event.get("path"))

    # ヘルスチェックエンドポイント
    if event.get("path") == "/health" and event.get("httpMethod") == "GET":
        return _build_response(200, {"status": "ok"})

    # MCPエンドポイント以外は404
    if event.get("path") != "/mcp" or event.get("httpMethod") != "POST":
        return _build_response(404, {"error": "Not Found"})

    # リクエストボディのパース
    body_str = event.get("body", "") or ""
    if not body_str:
        return _build_response(400, _json_rpc_error(None, -32700, "Parse error: empty body"))

    try:
        rpc_request = json.loads(body_str)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse error: %s", str(e))
        return _build_response(400, _json_rpc_error(None, -32700, f"Parse error: {str(e)}"))

    # JSON-RPCの最低限の形式チェック
    if not isinstance(rpc_request, dict) or rpc_request.get("jsonrpc") != "2.0":
        return _build_response(400, _json_rpc_error(
            rpc_request.get("id") if isinstance(rpc_request, dict) else None,
            -32600, "Invalid Request: jsonrpc must be '2.0'"
        ))

    request_id = rpc_request.get("id")
    method = rpc_request.get("method", "")
    logger.info("MCP method: %s id=%s", method, request_id)

    # MCPルーターに委譲
    try:
        result = route_request(rpc_request)
        return _build_response(200, result)
    except Exception as e:
        logger.exception("Unhandled error in route_request")
        return _build_response(200, _json_rpc_error(
            request_id, -32603, f"Internal error: {type(e).__name__}"
        ))


def _build_response(status_code: int, body: dict) -> dict:
    """API Gatewayプロキシ統合レスポンスを構築する。"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            # CORS対応（Claude Custom Connectorから呼ばれる場合に必要な可能性あり）
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }


def _json_rpc_error(request_id: Any, code: int, message: str) -> dict:
    """JSON-RPC 2.0 エラーレスポンスを構築する。"""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        }
    }
