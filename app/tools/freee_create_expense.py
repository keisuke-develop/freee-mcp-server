"""
freee_create_expense ツール。

freeeに支出（経費）を登録するメインツール。
レシートの内容をClaudeが構造化して渡してくれる前提で動作する。

入力: 支出情報（日付、金額、勘定科目ID、税区分など）
出力: content配列（登録結果テキスト）
"""

import logging

from freee.client import FreeeClient
from tools.freee_validate_expense_input import _validate as validate_input

logger = logging.getLogger(__name__)

# MCPツール定義（tools/list で返す）
TOOL_DEFINITION: dict = {
    "name": "freee_create_expense",
    "description": (
        "freeeに支出（経費）を登録します。"
        "レシートの内容を元に勘定科目・税区分・金額・日付を指定して登録します。"
        "事前にfreee_list_account_itemsとfreee_list_tax_codesでIDを確認してください。"
        "不明な場合はfreee_validate_expense_inputで入力を確認してから呼び出すことを推奨します。"
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


def execute(arguments: dict) -> list[dict]:
    """
    freee_create_expense を実行する。

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
        MCP content配列。登録成功なら deal_id を含む確認メッセージを返す。

    Raises:
        ValueError: 入力バリデーションエラー
        RuntimeError: freee API呼び出し失敗
    """
    # 事前バリデーション（freee APIを呼ぶ前に弾く）
    errors = validate_input(arguments)
    if errors:
        raise ValueError("Input validation failed: " + "; ".join(errors))

    logger.info(
        "freee_create_expense: date=%s amount=%d account_item_id=%d",
        arguments.get("issue_date"),
        arguments.get("amount", 0),
        arguments.get("account_item_id", 0),
    )

    client = FreeeClient()
    result = client.create_deal(
        issue_date=arguments["issue_date"],
        amount=arguments["amount"],
        account_item_id=arguments["account_item_id"],
        tax_code=arguments["tax_code"],
        description=arguments.get("description", ""),
        partner_id=arguments.get("partner_id"),
    )

    deal_id = result.get("deal", {}).get("id", "不明")
    issue_date = result.get("deal", {}).get("issue_date", arguments["issue_date"])
    amount = result.get("deal", {}).get("amount", arguments["amount"])

    # 登録結果をClaudeが読みやすいテキストで返す
    text = (
        f"支出登録が完了しました。\n"
        f"- deal_id: {deal_id}\n"
        f"- 日付: {issue_date}\n"
        f"- 金額: ¥{int(amount):,}\n"
        f"- 勘定科目ID: {arguments['account_item_id']}\n"
        f"- 税区分コード: {arguments['tax_code']}\n"
    )
    if arguments.get("description"):
        text += f"- 備考: {arguments['description']}\n"

    logger.info("freee_create_expense: success deal_id=%s", deal_id)
    return [{"type": "text", "text": text}]
