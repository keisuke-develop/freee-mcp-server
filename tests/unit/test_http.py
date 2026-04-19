"""
単体テスト: utils/http.py

requests.Session を共有していることと、
例外がアプリ内の抽象例外へ変換されることを確認する。
"""

import sys
import os
from unittest.mock import MagicMock

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../app"))

from utils import http


class TestGetSession:
    """_get_session のテスト。"""

    def test_正常系_Sessionを再利用する(self, monkeypatch):
        session = requests.Session()
        monkeypatch.setattr(http, "_session", None)

        first = http._get_session()
        second = http._get_session()

        assert isinstance(first, requests.Session)
        assert first is second
        assert first.headers["User-Agent"] == "freee-mcp-server/1.0"


class TestHttpGet:
    """http_get のテスト。"""

    def test_正常系_GETリクエストを送れる(self, monkeypatch):
        mock_session = MagicMock()
        mock_response = MagicMock(status_code=200)
        mock_session.get.return_value = mock_response
        monkeypatch.setattr(http, "_get_session", lambda: mock_session)

        response = http.http_get(
            "https://example.com/api",
            params={"company_id": 1},
            headers={"Authorization": "Bearer test"},
            timeout=3,
        )

        assert response is mock_response
        mock_session.get.assert_called_once_with(
            "https://example.com/api",
            params={"company_id": 1},
            headers={"Authorization": "Bearer test"},
            timeout=3,
        )

    def test_異常系_TimeoutはHttpTimeoutErrorになる(self, monkeypatch):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.Timeout("timeout")
        monkeypatch.setattr(http, "_get_session", lambda: mock_session)

        with pytest.raises(http.HttpTimeoutError):
            http.http_get("https://example.com/api")

    def test_異常系_RequestExceptionはHttpRequestErrorになる(self, monkeypatch):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.ConnectionError("boom")
        monkeypatch.setattr(http, "_get_session", lambda: mock_session)

        with pytest.raises(http.HttpRequestError):
            http.http_get("https://example.com/api")


class TestHttpPost:
    """http_post のテスト。"""

    def test_正常系_POSTリクエストを送れる(self, monkeypatch):
        mock_session = MagicMock()
        mock_response = MagicMock(status_code=200)
        mock_session.post.return_value = mock_response
        monkeypatch.setattr(http, "_get_session", lambda: mock_session)

        response = http.http_post(
            "https://example.com/token",
            data={"grant_type": "refresh_token"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5,
        )

        assert response is mock_response
        mock_session.post.assert_called_once_with(
            "https://example.com/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token"},
            json=None,
            timeout=5,
        )

    def test_異常系_POST_TimeoutはHttpTimeoutErrorになる(self, monkeypatch):
        mock_session = MagicMock()
        mock_session.post.side_effect = requests.exceptions.Timeout("timeout")
        monkeypatch.setattr(http, "_get_session", lambda: mock_session)

        with pytest.raises(http.HttpTimeoutError):
            http.http_post("https://example.com/api")

    def test_異常系_POST_RequestExceptionはHttpRequestErrorになる(self, monkeypatch):
        mock_session = MagicMock()
        mock_session.post.side_effect = requests.exceptions.RequestException("boom")
        monkeypatch.setattr(http, "_get_session", lambda: mock_session)

        with pytest.raises(http.HttpRequestError):
            http.http_post("https://example.com/api")
