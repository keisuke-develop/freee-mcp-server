"""
HTTPヘルパー。

requests.Session を共有して、Lambda warm start 時のコネクション再利用を効かせる。
呼び出し側はこの薄いラッパーを経由し、HTTPライブラリへの依存を局所化する。
"""

from __future__ import annotations

from typing import Any

import requests


class HttpTimeoutError(Exception):
    """HTTPタイムアウト。"""


class HttpRequestError(Exception):
    """ネットワークやDNSなどの接続失敗。"""


_session: requests.Session | None = None


def http_get(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 10,
) -> requests.Response:
    """GETリクエストを送信する。"""
    session = _get_session()
    try:
        return session.get(url, params=params, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout as e:
        raise HttpTimeoutError(str(e)) from e
    except requests.exceptions.RequestException as e:
        raise HttpRequestError(str(e)) from e


def http_post(
    url: str,
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 10,
) -> requests.Response:
    """POSTリクエストを送信する。"""
    session = _get_session()
    try:
        return session.post(
            url,
            headers=headers,
            data=data,
            json=json_body,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as e:
        raise HttpTimeoutError(str(e)) from e
    except requests.exceptions.RequestException as e:
        raise HttpRequestError(str(e)) from e


def _get_session() -> requests.Session:
    """共有 Session を返す。"""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": "freee-mcp-server/1.0"})
    return _session
