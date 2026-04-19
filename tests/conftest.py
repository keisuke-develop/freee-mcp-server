"""
pytest共通設定。

テスト全体で共有するフィクスチャや設定を定義する。
"""

import os
import sys

import pytest


# テスト実行時のAWS設定（motoが必要とするダミー認証情報）
@pytest.fixture(autouse=True)
def aws_credentials():
    """motoが必要とするダミーのAWS認証情報を設定する。"""
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "ap-northeast-1")
    os.environ.setdefault("AWS_REGION", "ap-northeast-1")
    os.environ.setdefault("SECRET_NAME", "freee/mcp-server-test")
    os.environ.setdefault("FREEE_API_BASE_URL", "https://api.freee.co.jp")
