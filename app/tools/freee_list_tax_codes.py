"""
freee_list_tax_codes ツール。

freeeから税区分の一覧を取得して返す。
Claudeが適切な税区分コードを判断するための補助ツール。

入力: {}
出力: content配列（税区分一覧のテキスト）
"""

import logging

from freee.client import FreeeClient

logger = logging.getLogger(__name__)

# MCPツール定義（tools/list で返す）
TOOL_DEFINITION: dict = {
    "name": "freee_list_tax_codes",
    "description": (
        "freeeから税区分の一覧を取得します。"
        "支出登録時に必要なtax_codeを確認するために使用します。"
        "例: 消費税10%（課税仕入れ）、消費税8%（軽減税率）、非課税 など。"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}


def execute(arguments: dict) -> list[dict]:
    """
    freee_list_tax_codes を実行する。

    Args:
        arguments: {}（現時点では未使用）

    Returns:
        MCP content配列
        [{ "type": "text", "text": "<税区分一覧>" }]

    Raises:
        RuntimeError: freee API呼び出し失敗時
    """
    logger.info("freee_list_tax_codes: fetching tax codes")

    client = FreeeClient()
    tax_codes = client.get_taxes()

    if not tax_codes:
        return [{"type": "text", "text": "税区分が見つかりませんでした。"}]

    lines = ["# 税区分一覧\n"]
    lines.append(f"{'コード':>8}  {'名前':<40}  {'税率'}")
    lines.append("-" * 65)

    for tax in tax_codes:
        rate = tax.get("rate_percent")
        rate_str = f"{rate}%" if rate is not None else "-"
        lines.append(
            f"{tax['code']:>8}  {tax['name']:<40}  {rate_str}"
        )

    text = "\n".join(lines)
    logger.info("freee_list_tax_codes: retrieved %d tax codes", len(tax_codes))

    return [{"type": "text", "text": text}]
