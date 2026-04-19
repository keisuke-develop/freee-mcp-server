"""
単体テスト: freee_validate_expense_input.py

入力バリデーションロジックを網羅的にテストする。
外部サービスへの通信は発生しない。
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../app"))

from tools.freee_validate_expense_input import execute, _validate


class TestValidateOk:
    """正常系: バリデーション通過のケース。"""

    def test_必須項目のみで通過(self):
        args = {
            "issue_date": "2026-04-19",
            "amount": 1500,
            "account_item_id": 100,
            "tax_code": 1,
        }
        errors = _validate(args)
        assert errors == []

    def test_全項目指定で通過(self):
        args = {
            "issue_date": "2026-04-19",
            "amount": 500,
            "account_item_id": 200,
            "tax_code": 8,
            "description": "コンビニ購入",
            "partner_id": 999,
        }
        errors = _validate(args)
        assert errors == []

    def test_executeが成功メッセージを返す(self):
        args = {
            "issue_date": "2026-04-19",
            "amount": 1000,
            "account_item_id": 100,
            "tax_code": 1,
        }
        result = execute(args)
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert "バリデーションOK" in result[0]["text"]


class TestIssueDateValidation:
    """issue_date のバリデーションテスト。"""

    def test_異常系_issue_dateなし(self):
        args = {"amount": 1000, "account_item_id": 1, "tax_code": 1}
        errors = _validate(args)
        assert any("issue_date" in e for e in errors)

    def test_異常系_形式不正_スラッシュ区切り(self):
        args = {"issue_date": "2026/04/19", "amount": 1000, "account_item_id": 1, "tax_code": 1}
        errors = _validate(args)
        assert any("YYYY-MM-DD" in e for e in errors)

    def test_異常系_無効な日付(self):
        args = {"issue_date": "2026-13-99", "amount": 1000, "account_item_id": 1, "tax_code": 1}
        errors = _validate(args)
        assert any("無効な日付" in e or "YYYY-MM-DD" in e for e in errors)

    def test_異常系_年が古すぎる(self):
        args = {"issue_date": "1999-12-31", "amount": 1000, "account_item_id": 1, "tax_code": 1}
        errors = _validate(args)
        assert any("古すぎ" in e for e in errors)

    def test_正常系_未来日付は許可(self):
        # freeeは未来日付を許可しているため警告にしない
        args = {"issue_date": "2099-01-01", "amount": 1000, "account_item_id": 1, "tax_code": 1}
        errors = _validate(args)
        # issue_date関連のエラーがないことを確認
        assert not any("issue_date" in e for e in errors)


class TestAmountValidation:
    """amount のバリデーションテスト。"""

    def test_異常系_amountなし(self):
        args = {"issue_date": "2026-04-19", "account_item_id": 1, "tax_code": 1}
        errors = _validate(args)
        assert any("amount" in e for e in errors)

    def test_異常系_amount_0(self):
        args = {"issue_date": "2026-04-19", "amount": 0, "account_item_id": 1, "tax_code": 1}
        errors = _validate(args)
        assert any("1円以上" in e for e in errors)

    def test_異常系_amount_負数(self):
        args = {"issue_date": "2026-04-19", "amount": -1, "account_item_id": 1, "tax_code": 1}
        errors = _validate(args)
        assert any("1円以上" in e for e in errors)

    def test_異常系_amount_文字列(self):
        args = {"issue_date": "2026-04-19", "amount": "千円", "account_item_id": 1, "tax_code": 1}
        errors = _validate(args)
        assert any("整数" in e for e in errors)

    def test_異常系_amount_1億超(self):
        args = {"issue_date": "2026-04-19", "amount": 100_000_001, "account_item_id": 1, "tax_code": 1}
        errors = _validate(args)
        assert any("大きすぎ" in e for e in errors)

    def test_正常系_amount_1(self):
        args = {"issue_date": "2026-04-19", "amount": 1, "account_item_id": 1, "tax_code": 1}
        errors = [e for e in _validate(args) if "amount" in e]
        assert errors == []


class TestAccountItemIdValidation:
    """account_item_id のバリデーションテスト。"""

    def test_異常系_account_item_idなし(self):
        args = {"issue_date": "2026-04-19", "amount": 1000, "tax_code": 1}
        errors = _validate(args)
        assert any("account_item_id" in e for e in errors)

    def test_異常系_account_item_id_0(self):
        args = {"issue_date": "2026-04-19", "amount": 1000, "account_item_id": 0, "tax_code": 1}
        errors = _validate(args)
        assert any("account_item_id" in e for e in errors)


class TestDescriptionValidation:
    """description のバリデーションテスト。"""

    def test_正常系_descriptionなしはOK(self):
        args = {"issue_date": "2026-04-19", "amount": 1000, "account_item_id": 1, "tax_code": 1}
        errors = [e for e in _validate(args) if "description" in e]
        assert errors == []

    def test_異常系_500文字超(self):
        args = {
            "issue_date": "2026-04-19",
            "amount": 1000,
            "account_item_id": 1,
            "tax_code": 1,
            "description": "a" * 501
        }
        errors = _validate(args)
        assert any("500文字" in e for e in errors)

    def test_正常系_500文字はOK(self):
        args = {
            "issue_date": "2026-04-19",
            "amount": 1000,
            "account_item_id": 1,
            "tax_code": 1,
            "description": "a" * 500
        }
        errors = [e for e in _validate(args) if "description" in e]
        assert errors == []


class TestExecuteErrorFormat:
    """execute のエラーレスポンス形式テスト。"""

    def test_エラー時はcontent配列を返す(self):
        args = {"amount": 1000, "account_item_id": 1, "tax_code": 1}  # issue_date なし
        result = execute(args)
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert "バリデーションエラー" in result[0]["text"]
