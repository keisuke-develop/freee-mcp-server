"""
freee_validate_expense_input ツール。

支出登録の入力値をfreee API呼び出し前にバリデーションする。
形式チェック・必須項目チェックをサーバー側で実施し、
不正な入力でfreee APIを呼ばないようにする。

入力: freee_create_expense と同じ引数
出力: content配列（バリデーション結果テキスト）
"""

import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

# MCPツール定義（tools/list で返す）
TOOL_DEFINITION: dict = {
    "name": "freee_validate_expense_input",
    "description": (
        "支出登録の入力値をバリデーションします。"
        "freee_create_expenseを呼ぶ前にこのツールで入力値を確認することを推奨します。"
        "バリデーション結果（OK / エラー詳細）を返します。"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "issue_date": {
                "type": "string",
                "description": "発生日（YYYY-MM-DD形式）",
                "pattern": r"^\d{4}-\d{2}-\d{2}$"
            },
            "amount": {
                "type": "integer",
                "description": "金額（税込、円単位、1以上の整数）",
                "minimum": 1
            },
            "account_item_id": {
                "type": "integer",
                "description": "勘定科目ID（freee_list_account_itemsで取得したid）"
            },
            "tax_code": {
                "type": "integer",
                "description": "税区分コード（freee_list_tax_codesで取得したcode）"
            },
            "description": {
                "type": "string",
                "description": "備考・説明（任意、500文字以内）",
                "maxLength": 500
            },
            "partner_id": {
                "type": "integer",
                "description": "取引先ID（任意）"
            }
        },
        "required": ["issue_date", "amount", "account_item_id", "tax_code"]
    }
}

# 発生日として受け付ける最古の日付（あまりに古い日付は誤入力の可能性が高い）
_MIN_YEAR = 2000

# 備考の最大文字数
_MAX_DESCRIPTION_LEN = 500


def execute(arguments: dict) -> list[dict]:
    """
    freee_validate_expense_input を実行する。

    Args:
        arguments: {
            issue_date: str,
            amount: int,
            account_item_id: int,
            tax_code: int,
            description?: str,
            partner_id?: int
        }

    Returns:
        MCP content配列。バリデーションOKなら成功メッセージ、
        NGならエラー詳細を返す。
    """
    errors = _validate(arguments)

    if errors:
        error_text = "バリデーションエラー:\n" + "\n".join(f"- {e}" for e in errors)
        logger.info("Validation failed: %d errors", len(errors))
        return [{"type": "text", "text": error_text}]

    # 確認メッセージ
    summary = (
        f"バリデーションOK。以下の内容で登録できます:\n"
        f"- 日付: {arguments['issue_date']}\n"
        f"- 金額: ¥{arguments['amount']:,}\n"
        f"- 勘定科目ID: {arguments['account_item_id']}\n"
        f"- 税区分コード: {arguments['tax_code']}\n"
    )
    if arguments.get("description"):
        summary += f"- 備考: {arguments['description']}\n"
    if arguments.get("partner_id"):
        summary += f"- 取引先ID: {arguments['partner_id']}\n"

    logger.info("Validation passed")
    return [{"type": "text", "text": summary}]


def _validate(arguments: dict) -> list[str]:
    """
    入力値を検証してエラーメッセージのリストを返す。

    Args:
        arguments: バリデーション対象の引数dict

    Returns:
        エラーメッセージのリスト。空なら全バリデーション通過。
    """
    errors: list[str] = []

    # --- issue_date ---
    issue_date_str = arguments.get("issue_date")
    if not issue_date_str:
        errors.append("issue_date は必須です。")
    elif not re.match(r"^\d{4}-\d{2}-\d{2}$", str(issue_date_str)):
        errors.append("issue_date は YYYY-MM-DD 形式で入力してください。")
    else:
        try:
            parsed_date = date.fromisoformat(issue_date_str)
            if parsed_date.year < _MIN_YEAR:
                errors.append(f"issue_date が古すぎます（{_MIN_YEAR}年以降を指定してください）。")
            elif parsed_date > date.today():
                # 未来日付は警告（エラーにはしない）
                pass  # freeeは未来日付の登録を許可しているため
        except ValueError:
            errors.append("issue_date が無効な日付です。")

    # --- amount ---
    amount = arguments.get("amount")
    if amount is None:
        errors.append("amount は必須です。")
    elif not isinstance(amount, int):
        errors.append("amount は整数で入力してください。")
    elif amount < 1:
        errors.append("amount は1円以上で入力してください。")
    elif amount > 100_000_000:
        # 1億円超は個人利用では異常値として警告
        errors.append("amount が大きすぎます（入力値を確認してください）。")

    # --- account_item_id ---
    account_item_id = arguments.get("account_item_id")
    if account_item_id is None:
        errors.append("account_item_id は必須です。freee_list_account_items で取得したIDを使用してください。")
    elif not isinstance(account_item_id, int) or account_item_id < 1:
        errors.append("account_item_id は正の整数で入力してください。")

    # --- tax_code ---
    tax_code = arguments.get("tax_code")
    if tax_code is None:
        errors.append("tax_code は必須です。freee_list_tax_codes で取得したコードを使用してください。")
    elif not isinstance(tax_code, int) or tax_code < 0:
        errors.append("tax_code は0以上の整数で入力してください。")

    # --- description (任意) ---
    description = arguments.get("description")
    if description is not None:
        if not isinstance(description, str):
            errors.append("description は文字列で入力してください。")
        elif len(description) > _MAX_DESCRIPTION_LEN:
            errors.append(f"description は{_MAX_DESCRIPTION_LEN}文字以内で入力してください。")

    # --- partner_id (任意) ---
    partner_id = arguments.get("partner_id")
    if partner_id is not None:
        if not isinstance(partner_id, int) or partner_id < 1:
            errors.append("partner_id は正の整数で入力してください。")

    return errors
