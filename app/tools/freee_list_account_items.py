"""
freee_list_account_items ツール。

freeeから勘定科目の一覧を取得して返す。
Claudeが適切な勘定科目IDを判断するための補助ツール。

入力: { type?: str }
出力: content配列（勘定科目一覧のテキスト）
"""

import logging
from typing import Any

from freee.client import FreeeClient

logger = logging.getLogger(__name__)

# MCPツール定義（tools/list で返す）
TOOL_DEFINITION: dict = {
    "name": "freee_list_account_items",
    "description": (
        "freeeから勘定科目の一覧を取得します。"
        "支出登録時に必要なaccount_item_idを確認するために使用します。"
        "経費登録の場合はtype='expense'を指定すると絞り込めます。"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "description": (
                    "勘定科目の種別でフィルタリング。"
                    "expense（経費）を指定すると経費科目のみ取得できます。"
                    "省略時は全件取得。"
                ),
                "enum": ["income", "expense", "asset", "liability", "equity", "other"]
            }
        },
        "required": []
    }
}


def execute(arguments: dict) -> list[dict]:
    """
    freee_list_account_items を実行する。

    Args:
        arguments: { type?: str }

    Returns:
        MCP content配列
        [{ "type": "text", "text": "<勘定科目一覧>" }]

    Raises:
        RuntimeError: freee API呼び出し失敗時
    """
    account_type = arguments.get("type")
    logger.info("freee_list_account_items: type=%s", account_type)

    client = FreeeClient()
    account_items = client.get_account_items(account_type=account_type)

    if not account_items:
        return [{"type": "text", "text": "勘定科目が見つかりませんでした。"}]

    # Claudeが理解しやすいテキスト形式に整形
    lines = ["# 勘定科目一覧\n"]
    lines.append(f"{'ID':>8}  {'名前':<30}  {'種別'}")
    lines.append("-" * 55)

    for item in account_items:
        lines.append(
            f"{item['id']:>8}  {item['name']:<30}  {item.get('account_category', '')}"
        )

    text = "\n".join(lines)
    logger.info("freee_list_account_items: retrieved %d items", len(account_items))

    return [{"type": "text", "text": text}]
