"""Conservative scope checks; unsupported SQL shapes never prove a negative."""

import re
from typing import Any

from project_doctor.models.observation import SqlCall

_COUNT = re.compile(
    r"SELECT\s+COUNT\s*\(\s*\*\s*\)\s+FROM\s+`?([a-zA-Z_]\w*)`?\s+"
    r"WHERE\s+`?([a-zA-Z_]\w*)`?\s*=\s*(?:'[^']*'|\d+|\?)\s*;?",
    re.IGNORECASE,
)


def already_covering_count(calls: list[SqlCall], plans: dict[str, dict[str, Any]]) -> bool:
    """Only single-table equality COUNT with verified, existing covering ref access.

    Estimated row counts are deliberately ignored. The caller must also establish
    unchanged actual work, valid controls, and stable measured durations.
    """
    if not calls:
        return False
    for call in calls:
        match = _COUNT.fullmatch(call.normalized_sql)
        if match is None or not call.plan_evidence_ids or call.rows_returned != 1:
            return False
        table_name, column = match.groups()
        for key in call.plan_evidence_ids:
            block = plans.get(key, {}).get("query_block")
            if not isinstance(block, dict) or set(block) - {"select_id", "cost_info", "table"}:
                return False
            table = block.get("table")
            if not isinstance(table, dict):
                return False
            if (
                table.get("table_name") != table_name
                or table.get("access_type") != "ref"
                or not table.get("key")
                or table.get("using_index") is not True
                or table.get("used_key_parts") != [column]
                or table.get("used_columns") != [column]
            ):
                return False
    return True


def scope_limitations(templates: list[str]) -> list[str]:
    """Explain observed SQL shapes without asserting untested root causes."""
    sql = "\n".join(templates).upper()
    notes = [
        "结论仅适用于本次请求参数、数据规模、过滤值和数据分布；分布变化会改变索引收益。",
        "索引收益依赖被查询的过滤值：高占比取值下优化器可能仍走全表扫描，收益不稳定；"
        "本次没有改变状态分布倾斜比例，不能外推其他取值。",
    ]
    if "COUNT(" in sql or "COUNT (" in sql:
        notes.append(
            "COUNT(*) 的耗时贡献未通过单独删除或改写计数查询的实验证实；"
            "计数是否冗余取决于业务用途，不能由索引实验推断。"
        )
    if "LIKE" in sql:
        notes.append("LIKE 前导通配符可能限制普通索引收益；本次未单独改写 LIKE，不能证实该根因。")
    if len(templates) > 2:
        notes.append("多条查询可能涉及 N+1，但本次未单独改变调用次数，不能证实 N+1 根因。")
    if "LIMIT" in sql:
        notes.append(
            "深分页未通过改变 offset 或分页方式的单变量实验单独证实；"
            "分页与 COUNT 的耗时结论依赖数据规模及 offset 大小。"
        )
    return notes
