"""
結合テスト: freee/client.py

FreeeClientがfreee APIを正しく呼び出すかをテストする。
HTTPリクエストは内部HTTPヘルパーをモックする。
Secrets ManagerとFreeeAuthはpatchで差し替える。
"""

import sys
import os
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../app"))

from freee.client import FreeeClient
from utils.http import HttpTimeoutError


def _make_auth_mock(access_token: str = "test-token", company_id: int = 12345):
    """FreeeAuthのモックを生成するヘルパー。"""
    mock_auth = MagicMock()
    mock_auth.get_valid_access_token.return_value = access_token
    mock_auth.get_company_id.return_value = company_id
    return mock_auth


class TestGetAccountItems:
    """get_account_items のテスト。"""

    def test_正常系_勘定科目一覧が返る(self):
        mock_auth = _make_auth_mock()
        mock_response_data = {
            "account_items": [
                {"id": 1, "name": "交際費", "account_category": "expense"},
                {"id": 2, "name": "消耗品費", "account_category": "expense"},
            ]
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data

        with patch("freee.client.FreeeAuth", return_value=mock_auth), \
             patch("freee.client.http_get", return_value=mock_response):
            client = FreeeClient()
            items = client.get_account_items()

        assert len(items) == 2
        assert items[0]["name"] == "交際費"

    def test_正常系_typeフィルタが渡される(self):
        mock_auth = _make_auth_mock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"account_items": []}

        with patch("freee.client.FreeeAuth", return_value=mock_auth), \
             patch("freee.client.http_get", return_value=mock_response) as mock_get:
            client = FreeeClient()
            client.get_account_items(account_type="expense")

        # typeパラメータがクエリに含まれているか確認
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or {}
        assert params.get("type") == "expense" or "expense" in str(call_kwargs)

    def test_異常系_APIエラー時にRuntimeError(self):
        mock_auth = _make_auth_mock()
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("freee.client.FreeeAuth", return_value=mock_auth), \
             patch("freee.client.http_get", return_value=mock_response):
            client = FreeeClient()
            with pytest.raises(RuntimeError):
                client.get_account_items()


class TestGetTaxes:
    """get_taxes のテスト。"""

    def test_正常系_税区分一覧が返る(self):
        mock_auth = _make_auth_mock()
        mock_response_data = {
            "taxes": [
                {"code": 1, "name": "課税（10%）", "rate_percent": 10.0},
                {"code": 2, "name": "軽減税率（8%）", "rate_percent": 8.0},
                {"code": 0, "name": "非課税", "rate_percent": None},
            ]
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data

        with patch("freee.client.FreeeAuth", return_value=mock_auth), \
             patch("freee.client.http_get", return_value=mock_response):
            client = FreeeClient()
            taxes = client.get_taxes()

        assert len(taxes) == 3
        assert taxes[0]["code"] == 1


class TestCreateDeal:
    """create_deal のテスト。"""

    def test_正常系_支出が登録される(self):
        mock_auth = _make_auth_mock()
        mock_response_data = {
            "deal": {
                "id": 99999,
                "issue_date": "2026-04-19",
                "type": "expense",
                "amount": 1500,
            }
        }

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = mock_response_data

        with patch("freee.client.FreeeAuth", return_value=mock_auth), \
             patch("freee.client.http_post", return_value=mock_response) as mock_post:
            client = FreeeClient()
            result = client.create_deal(
                issue_date="2026-04-19",
                amount=1500,
                account_item_id=100,
                tax_code=1,
                description="テスト",
            )

        assert result["deal"]["id"] == 99999

        # POSTリクエストのボディを確認
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json_body") or {}
        assert payload.get("type") == "expense"
        # 金額は details[0].amount に入る（due_amountはトップレベルには不要）
        assert payload["details"][0]["amount"] == 1500

    def test_異常系_422バリデーションエラーはValueError(self):
        mock_auth = _make_auth_mock()
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.json.return_value = {
            "errors": [{"message": "account_item_id is invalid"}]
        }

        with patch("freee.client.FreeeAuth", return_value=mock_auth), \
             patch("freee.client.http_post", return_value=mock_response):
            client = FreeeClient()
            with pytest.raises(ValueError, match="バリデーションエラー"):
                client.create_deal(
                    issue_date="2026-04-19",
                    amount=1500,
                    account_item_id=9999,  # 存在しないID
                    tax_code=1,
                )

    def test_異常系_タイムアウトはRuntimeError(self):
        mock_auth = _make_auth_mock()

        with patch("freee.client.FreeeAuth", return_value=mock_auth), \
             patch("freee.client.http_post", side_effect=HttpTimeoutError):
            client = FreeeClient()
            with pytest.raises(RuntimeError, match="タイムアウト"):
                client.create_deal(
                    issue_date="2026-04-19",
                    amount=1500,
                    account_item_id=100,
                    tax_code=1,
                )
