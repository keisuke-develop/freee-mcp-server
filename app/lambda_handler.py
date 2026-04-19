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
from oauth_server import (
    begin_authorization,
    build_authorization_metadata,
    build_base_url,
    build_resource_metadata,
    build_unauthorized_headers,
    exchange_token,
    get_oauth_config,
    handle_cognito_callback,
    register_client,
    validate_access_token,
)

# ロガー設定（Lambda では basicConfig は無効なため root logger を直接設定する）
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.getLogger().setLevel(log_level)
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
    method = _get_method(event)
    path = _get_path(event)
    logger.info("Request received: method=%s path=%s", method, path)

    # ヘルスチェックエンドポイント
    if path == "/health" and method == "GET":
        return _build_response(200, {"status": "ok"})

    known_paths = {
        "/mcp",
        "/register",
        "/authorize",
        "/oauth/callback",
        "/token",
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
    }
    if path not in known_paths:
        return _build_response(404, {"error": "Not Found"})

    base_url = build_base_url(event)
    oauth_config = get_oauth_config()

    if path == "/.well-known/oauth-protected-resource" and method == "GET":
        return _build_response(200, build_resource_metadata(base_url, oauth_config))

    if path == "/.well-known/oauth-authorization-server" and method == "GET":
        return _build_response(200, build_authorization_metadata(base_url, oauth_config))

    if path == "/register" and method == "POST":
        body = json.loads(event.get("body", "") or "{}")
        status_code, response_body = register_client(body)
        return _build_response(status_code, response_body)

    if path == "/authorize" and method == "GET":
        status_code, response_body = begin_authorization(event, base_url, oauth_config)
        return _build_oauth_response(status_code, response_body)

    if path == "/oauth/callback" and method == "GET":
        status_code, response_body = handle_cognito_callback(event, base_url, oauth_config)
        return _build_oauth_response(status_code, response_body)

    if path == "/token" and method == "POST":
        status_code, response_body = exchange_token(event, base_url, oauth_config)
        return _build_response(status_code, response_body)

    # MCPエンドポイント以外は404
    if path != "/mcp" or method != "POST":
        return _build_response(404, {"error": "Not Found"})

    claims = validate_access_token(_get_header(event, "authorization"), oauth_config)
    if claims is None:
        return {
            "statusCode": 401,
            "headers": build_unauthorized_headers(base_url),
            "body": json.dumps({"error": "unauthorized"}),
        }

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


def _build_oauth_response(status_code: int, body: dict) -> dict:
    """OAuth用リダイレクトまたはJSONレスポンスを構築する。"""
    headers = {"Access-Control-Allow-Origin": "*"}
    if status_code in (301, 302) and body.get("location"):
        headers["Location"] = body["location"]
        return {"statusCode": status_code, "headers": headers, "body": ""}

    headers["Content-Type"] = "application/json"
    return {
        "statusCode": status_code,
        "headers": headers,
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


def _get_method(event: dict) -> str:
    """API Gateway v1/v2 の両方からHTTPメソッドを取得する。"""
    return (
        event.get("httpMethod")
        or event.get("requestContext", {}).get("http", {}).get("method", "")
    )


def _get_path(event: dict) -> str:
    """API Gateway v1/v2 の両方からパスを取得する。"""
    return event.get("path") or event.get("rawPath", "")


def _get_header(event: dict, name: str) -> str | None:
    """ヘッダー名を大文字小文字無視で取得する。"""
    headers = event.get("headers") or {}
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None
