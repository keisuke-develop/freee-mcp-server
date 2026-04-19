"""
MCPツールのレジストリ。

各ツールモジュールをインポートし、TOOL_REGISTRYに登録する。
mcp_router.pyはこのレジストリを参照してツールを実行する。

新しいツールを追加する場合:
  1. tools/ 配下に新しいモジュールを作成する
  2. このファイルでインポートしてTOOL_REGISTRYに登録する
"""

from typing import Callable

from tools.freee_list_account_items import execute as list_account_items, TOOL_DEFINITION as ACCOUNT_ITEMS_DEF
from tools.freee_list_tax_codes import execute as list_tax_codes, TOOL_DEFINITION as TAX_CODES_DEF
from tools.freee_validate_expense_input import execute as validate_expense, TOOL_DEFINITION as VALIDATE_DEF
from tools.freee_create_expense import execute as create_expense, TOOL_DEFINITION as CREATE_EXPENSE_DEF


# ツール名 → 実行関数のマッピング
TOOL_REGISTRY: dict[str, Callable] = {
    "freee_list_account_items": list_account_items,
    "freee_list_tax_codes": list_tax_codes,
    "freee_validate_expense_input": validate_expense,
    "freee_create_expense": create_expense,
}

# tools/list で返すツール定義の順序付きリスト
_TOOL_DEFINITIONS = [
    ACCOUNT_ITEMS_DEF,
    TAX_CODES_DEF,
    VALIDATE_DEF,
    CREATE_EXPENSE_DEF,
]


def get_tool_definitions() -> list[dict]:
    """tools/list で返すツール定義一覧を返す。"""
    return _TOOL_DEFINITIONS
