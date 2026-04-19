"""
OAuth 2.1 helper for the remote MCP server.

This module exposes a minimal OAuth authorization facade for MCP clients while
delegating only end-user authentication to Amazon Cognito. The MCP server
itself issues and validates bearer tokens so the resource server and
authorization server semantics stay consistent for Claude/remote MCP clients.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode

import boto3
import jwt
from botocore.exceptions import ClientError

from utils.http import HttpRequestError, HttpTimeoutError, http_post

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 10
_AUTH_CODE_TTL_SECONDS = 600
_ACCESS_TOKEN_TTL_SECONDS = 3600
_REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60

_ddb_client = None
_cognito_client = None
_resolved_cognito_app_client_id: str | None = None


@dataclass
class OAuthConfig:
    table_name: str
    cognito_user_pool_id: str
    cognito_app_client_name: str
    cognito_domain_url: str
    cognito_issuer_url: str


def get_oauth_config() -> OAuthConfig:
    """Load OAuth-related environment variables."""
    required = {
        "table_name": os.environ.get("OAUTH_TABLE_NAME", ""),
        "cognito_user_pool_id": os.environ.get("COGNITO_USER_POOL_ID", ""),
        "cognito_app_client_name": os.environ.get("COGNITO_APP_CLIENT_NAME", ""),
        "cognito_domain_url": os.environ.get("COGNITO_DOMAIN_URL", ""),
        "cognito_issuer_url": os.environ.get("COGNITO_ISSUER_URL", ""),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"OAuth configuration is incomplete: {missing}")

    return OAuthConfig(**required)


def build_base_url(event: dict) -> str:
    """Build the public base URL from API Gateway headers."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    host = (
        headers.get("x-forwarded-host")
        or headers.get("host")
        or event.get("requestContext", {}).get("domainName")
    )
    proto = headers.get("x-forwarded-proto", "https")
    if not host:
        host = "example.com"
    return f"{proto}://{host}"


def build_authorization_metadata(base_url: str, config: OAuthConfig) -> dict:
    """Return RFC 8414-style authorization server metadata."""
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "registration_endpoint": f"{base_url}/register",
        "authorization_response_iss_parameter_supported": True,
        "resource_parameter_supported": True,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["openid", "email", "profile"],
        "protected_resources": [f"{base_url}/mcp"],
        "upstream_authorization_server": config.cognito_issuer_url,
    }


def build_resource_metadata(base_url: str, config: OAuthConfig) -> dict:
    """Return RFC 9728 protected resource metadata."""
    del config
    return {
        "resource": f"{base_url}/mcp",
        "authorization_servers": [base_url],
        "scopes_supported": ["openid", "email", "profile"],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{base_url}/health",
    }


def register_client(body: dict) -> tuple[int, dict]:
    """Register a public OAuth client for MCP use."""
    redirect_uris = body.get("redirect_uris") or []
    if not redirect_uris or not all(
        isinstance(uri, str) and uri.startswith(("https://", "http://localhost"))
        for uri in redirect_uris
    ):
        return 400, {
            "error": "invalid_client_metadata",
            "error_description": "redirect_uris must contain valid HTTPS or localhost URLs",
        }

    client_id = f"mcp_{secrets.token_urlsafe(16)}"
    client_item = {
        "pk": {"S": f"client#{client_id}"},
        "client_id": {"S": client_id},
        "redirect_uris": {"S": json.dumps(redirect_uris)},
        "client_name": {"S": body.get("client_name", "Claude MCP Client")},
        "created_at": {"N": str(int(time.time()))},
    }
    _put_item(client_item)

    response = {
        "client_id": client_id,
        "client_id_issued_at": int(time.time()),
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": "none",
    }
    return 201, response


def begin_authorization(event: dict, base_url: str, config: OAuthConfig) -> tuple[int, dict]:
    """Start an OAuth authorization flow via Cognito managed login."""
    params = event.get("queryStringParameters") or {}
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")
    state = params.get("state", "")
    response_type = params.get("response_type", "")
    code_challenge = params.get("code_challenge", "")
    code_challenge_method = params.get("code_challenge_method", "")
    scope = params.get("scope", "openid email profile")
    resource = params.get("resource") or f"{base_url}/mcp"

    if response_type != "code":
        return 400, {"error": "unsupported_response_type"}
    if not client_id or not redirect_uri or not state or not code_challenge or code_challenge_method != "S256":
        return 400, {"error": "invalid_request"}
    if resource != f"{base_url}/mcp":
        return 400, {"error": "invalid_target"}

    client = get_registered_client(client_id)
    if not client or redirect_uri not in client["redirect_uris"]:
        return 400, {"error": "invalid_client"}

    state_key = secrets.token_urlsafe(24)
    item = {
        "pk": {"S": f"state#{state_key}"},
        "client_id": {"S": client_id},
        "redirect_uri": {"S": redirect_uri},
        "state": {"S": state},
        "code_challenge": {"S": code_challenge},
        "scope": {"S": scope},
        "resource": {"S": resource},
        "expires_at": {"N": str(int(time.time()) + _AUTH_CODE_TTL_SECONDS)},
    }
    _put_item(item)

    cognito_app_client_id = resolve_cognito_app_client_id(config)
    cognito_params = {
        "response_type": "code",
        "client_id": cognito_app_client_id,
        "redirect_uri": f"{base_url}/oauth/callback",
        "scope": "openid email profile",
        "state": state_key,
    }
    location = f"{config.cognito_domain_url}/oauth2/authorize?{urlencode(cognito_params)}"
    return 302, {"location": location}


def handle_cognito_callback(event: dict, base_url: str, config: OAuthConfig) -> tuple[int, dict]:
    """Exchange Cognito code, then redirect back to the MCP client."""
    params = event.get("queryStringParameters") or {}
    cognito_code = params.get("code", "")
    state_key = params.get("state", "")
    if not cognito_code or not state_key:
        return 400, {"error": "invalid_request"}

    state_item = _consume_item(f"state#{state_key}")
    if not state_item:
        return 400, {
            "error": "invalid_request",
            "error_description": "authorization state not found or expired",
        }

    cognito_app_client_id = resolve_cognito_app_client_id(config)
    try:
        token_response = http_post(
            f"{config.cognito_domain_url}/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": cognito_app_client_id,
                "code": cognito_code,
                "redirect_uri": f"{base_url}/oauth/callback",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=_REQUEST_TIMEOUT,
        )
    except (HttpTimeoutError, HttpRequestError) as e:
        logger.error("Cognito token exchange connection error: %s", e)
        return 502, {"error": "upstream_auth_failed"}
    if token_response.status_code != 200:
        logger.error("Cognito callback token exchange failed: %s", token_response.text)
        return 502, {"error": "upstream_auth_failed"}

    principal = extract_principal(token_response.json())
    auth_code = secrets.token_urlsafe(32)
    code_item = {
        "pk": {"S": f"code#{auth_code}"},
        "client_id": {"S": state_item["client_id"]},
        "redirect_uri": {"S": state_item["redirect_uri"]},
        "state": {"S": state_item["state"]},
        "code_challenge": {"S": state_item["code_challenge"]},
        "scope": {"S": state_item.get("scope", "openid email profile")},
        "resource": {"S": state_item.get("resource", f"{base_url}/mcp")},
        "subject": {"S": principal["subject"]},
        "username": {"S": principal["username"]},
        "expires_at": {"N": str(int(time.time()) + _AUTH_CODE_TTL_SECONDS)},
    }
    _put_item(code_item)

    redirect_uri = state_item["redirect_uri"]
    delimiter = "&" if "?" in redirect_uri else "?"
    location = (
        f"{redirect_uri}{delimiter}"
        f"code={auth_code}&state={state_item['state']}&iss={base_url}"
    )
    return 302, {"location": location}


def exchange_token(event: dict, base_url: str, config: OAuthConfig) -> tuple[int, dict]:
    """Exchange authorization code or refresh token."""
    del config
    raw_body = event.get("body", "") or ""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    content_type = headers.get("content-type", "")
    is_b64 = event.get("isBase64Encoded", False)
    logger.info("POST /token content-type=%s body_len=%d is_base64=%s", content_type, len(raw_body), is_b64)

    if is_b64 and raw_body:
        raw_body = base64.b64decode(raw_body).decode("utf-8")

    if "json" in content_type and raw_body:
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            body = {}
    else:
        body = parse_form_body(raw_body)
    grant_type = body.get("grant_type", "")
    logger.info("POST /token grant_type=%s parsed_keys=%s", grant_type, list(body.keys()))

    if grant_type == "authorization_code":
        code = body.get("code", "")
        client_id = body.get("client_id", "")
        redirect_uri = body.get("redirect_uri", "")
        code_verifier = body.get("code_verifier", "")
        resource = body.get("resource") or f"{base_url}/mcp"
        if not all([code, client_id, redirect_uri, code_verifier]):
            logger.error(
                "exchange_token: missing required fields code=%s client_id=%s redirect_uri=%s code_verifier=%s",
                bool(code), bool(client_id), bool(redirect_uri), bool(code_verifier),
            )
            return 400, {"error": "invalid_request"}

        code_item = _consume_item(f"code#{code}")
        if not code_item:
            logger.error("exchange_token: code not found or expired: %s", code[:16])
            return 400, {"error": "invalid_grant"}
        if code_item["client_id"] != client_id or code_item["redirect_uri"] != redirect_uri:
            logger.error("exchange_token: client_id/redirect_uri mismatch")
            return 400, {"error": "invalid_grant"}
        stored_resource = code_item.get("resource", f"{base_url}/mcp")
        if stored_resource != resource:
            logger.error("exchange_token: resource mismatch stored=%s requested=%s", stored_resource, resource)
            return 400, {"error": "invalid_target"}
        if not verify_pkce(code_verifier, code_item["code_challenge"]):
            logger.error("exchange_token: PKCE verification failed")
            return 400, {"error": "invalid_grant", "error_description": "PKCE verification failed"}

        token_response = issue_tokens(
            client_id=client_id,
            subject=code_item["subject"],
            username=code_item["username"],
            scope=code_item.get("scope", "openid email profile"),
            resource=resource,
        )
        return 200, token_response

    if grant_type == "refresh_token":
        refresh_token = body.get("refresh_token", "")
        client_id = body.get("client_id", "")
        resource = body.get("resource") or f"{base_url}/mcp"
        if not refresh_token:
            return 400, {"error": "invalid_request"}

        refresh_item = _consume_item(f"refresh#{refresh_token}")
        if not refresh_item:
            return 400, {"error": "invalid_grant"}
        if client_id and refresh_item["client_id"] != client_id:
            return 400, {"error": "invalid_grant"}
        if refresh_item.get("resource", f"{base_url}/mcp") != resource:
            return 400, {"error": "invalid_target"}

        token_response = issue_tokens(
            client_id=refresh_item["client_id"],
            subject=refresh_item["subject"],
            username=refresh_item["username"],
            scope=refresh_item.get("scope", "openid email profile"),
            resource=resource,
        )
        return 200, token_response

    logger.error("exchange_token: unsupported grant_type=%s", grant_type)
    return 400, {"error": "unsupported_grant_type"}


def parse_form_body(body: str) -> dict[str, str]:
    """Parse an x-www-form-urlencoded string into a dict."""
    if not body:
        return {}
    return dict(parse_qsl(body, keep_blank_values=True))


def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """Verify PKCE S256 challenge."""
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    generated = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return secrets.compare_digest(generated, code_challenge)


def issue_tokens(
    *,
    client_id: str,
    subject: str,
    username: str,
    scope: str,
    resource: str,
) -> dict[str, Any]:
    """Issue an MCP-server access token and refresh token pair."""
    now = int(time.time())
    access_token = f"atk_{secrets.token_urlsafe(32)}"
    refresh_token = f"rtk_{secrets.token_urlsafe(32)}"

    _put_item(
        {
            "pk": {"S": f"access#{access_token}"},
            "client_id": {"S": client_id},
            "subject": {"S": subject},
            "username": {"S": username},
            "scope": {"S": scope},
            "resource": {"S": resource},
            "issued_at": {"N": str(now)},
            "expires_at": {"N": str(now + _ACCESS_TOKEN_TTL_SECONDS)},
        }
    )
    _put_item(
        {
            "pk": {"S": f"refresh#{refresh_token}"},
            "client_id": {"S": client_id},
            "subject": {"S": subject},
            "username": {"S": username},
            "scope": {"S": scope},
            "resource": {"S": resource},
            "issued_at": {"N": str(now)},
            "expires_at": {"N": str(now + _REFRESH_TOKEN_TTL_SECONDS)},
        }
    )

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": _ACCESS_TOKEN_TTL_SECONDS,
        "refresh_token": refresh_token,
        "scope": scope,
    }


def extract_principal(token_data: dict[str, Any]) -> dict[str, str]:
    """Extract a stable user identity from Cognito tokens."""
    id_token = token_data.get("id_token")
    access_token = token_data.get("access_token")
    token = id_token or access_token
    if not token:
        raise RuntimeError("Cognito token response did not include an id_token or access_token")

    claims = jwt.decode(
        token,
        options={
            "verify_signature": False,
            "verify_exp": False,
            "verify_aud": False,
            "verify_iss": False,
        },
        algorithms=["RS256"],
    )
    subject = claims.get("sub")
    username = claims.get("cognito:username") or claims.get("username") or subject
    if not subject or not username:
        raise RuntimeError("Cognito token response did not contain user identity claims")
    return {"subject": str(subject), "username": str(username)}


def validate_access_token(auth_header: str | None, config: OAuthConfig) -> dict | None:
    """Validate an MCP-server-issued opaque access token."""
    del config
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None

    item = _get_item(f"access#{token}")
    if not item:
        return None

    claims = _parse_ddb_item(item)
    if int(claims["expires_at"]) <= int(time.time()):
        return None

    return {
        "sub": claims["subject"],
        "username": claims["username"],
        "client_id": claims["client_id"],
        "scope": claims.get("scope", ""),
        "resource": claims.get("resource", ""),
    }


def build_unauthorized_headers(base_url: str) -> dict[str, str]:
    """Return OAuth-friendly 401 headers."""
    return {
        "WWW-Authenticate": f'Bearer resource_metadata="{base_url}/.well-known/oauth-protected-resource"',
        "Access-Control-Allow-Origin": "*",
        "Content-Type": "application/json",
    }


def get_registered_client(client_id: str) -> dict[str, Any] | None:
    """Load a registered OAuth client from DynamoDB."""
    item = _get_item(f"client#{client_id}")
    if not item:
        return None
    parsed = _parse_ddb_item(item)
    return {
        "client_id": parsed["client_id"],
        "redirect_uris": json.loads(parsed["redirect_uris"]),
    }


def _get_ddb_client():
    global _ddb_client
    if _ddb_client is None:
        _ddb_client = boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))
    return _ddb_client


def _get_cognito_client():
    global _cognito_client
    if _cognito_client is None:
        _cognito_client = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))
    return _cognito_client


def resolve_cognito_app_client_id(config: OAuthConfig) -> str:
    """Resolve and cache the Cognito app client id from the user pool."""
    global _resolved_cognito_app_client_id
    if _resolved_cognito_app_client_id:
        return _resolved_cognito_app_client_id

    client = _get_cognito_client()
    paginator = client.get_paginator("list_user_pool_clients")
    for page in paginator.paginate(UserPoolId=config.cognito_user_pool_id):
        for user_pool_client in page.get("UserPoolClients", []):
            if user_pool_client.get("ClientName") == config.cognito_app_client_name:
                _resolved_cognito_app_client_id = user_pool_client["ClientId"]
                return _resolved_cognito_app_client_id

    raise RuntimeError(
        f"Cognito app client '{config.cognito_app_client_name}' was not found in user pool '{config.cognito_user_pool_id}'"
    )


def _put_item(item: dict) -> None:
    client = _get_ddb_client()
    client.put_item(TableName=get_oauth_config().table_name, Item=item)


def _get_item(pk: str) -> dict | None:
    client = _get_ddb_client()
    response = client.get_item(
        TableName=get_oauth_config().table_name,
        Key={"pk": {"S": pk}},
    )
    return response.get("Item")


def _consume_item(pk: str) -> dict[str, str] | None:
    client = _get_ddb_client()
    try:
        response = client.delete_item(
            TableName=get_oauth_config().table_name,
            Key={"pk": {"S": pk}},
            ReturnValues="ALL_OLD",
        )
    except ClientError as exc:
        logger.error("DynamoDB delete failed: %s", exc.response["Error"]["Code"])
        return None

    item = response.get("Attributes")
    if not item:
        return None

    return _parse_ddb_item(item)


def _parse_ddb_item(item: dict[str, dict[str, str]]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for key, value in item.items():
        if "S" in value:
            parsed[key] = value["S"]
        elif "N" in value:
            parsed[key] = value["N"]
    return parsed
