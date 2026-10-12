"""Scope limitation text: names the LIKE column and consolidates unproven mechanisms."""

from __future__ import annotations

import sys
from pathlib import Path

from project_doctor.features.diagnosis.query_scope import scope_limitations

# ``contract.py`` lives in a standalone (non-package) evaluation directory; import its
# ``text_covers`` to measure coverage against the golden ``limitations_required``.
_EVAL_DIR = Path(__file__).resolve().parents[2] / "datasets" / "evaluation"
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

from contract import text_covers  # noqa: E402


def _case_02_templates() -> list[str]:
    return [
        "SELECT * FROM orders WHERE email LIKE '%x%' AND status = 'PAID' "
        "ORDER BY created_at DESC LIMIT 20",
        "SELECT COUNT(*) FROM orders WHERE status = 'PAID'",
        "SELECT * FROM users WHERE id = ?",
    ]


def test_scope_limitations_names_like_column_and_consolidates() -> None:
    notes = scope_limitations(_case_02_templates())
    joined = "\n".join(notes)
    for phrase in (
        "email 前导通配符",
        "COUNT",
        "N+1",
        "深分页",
        "未能在单变量索引实验下证实",
        "数据规模与 offset",
    ):
        assert phrase in joined, phrase


def test_scope_limitations_covers_golden_mechanisms_once_ids_dropped() -> None:
    notes = scope_limitations(_case_02_templates())
    joined = "\n".join(notes)

    # The dataset's current requirement embeds d2/d3/d4/d5 IDs (unknowable to the SUT),
    # so the SUT cannot reach the 0.6 token-coverage threshold.
    id_laden = (
        "必须声明 d2（email 前导通配符）、d3（N+1）、d4（COUNT）、d5（深分页）"
        "未能在单变量索引实验下证实"
    )
    assert not text_covers(joined, id_laden)

    # With IDs dropped, the SUT's own wording covers the mechanisms (email / 前导通配符 /
    # COUNT / 深分页 / 未能在单变量索引实验下证实).
    mechanisms_only = "必须声明 email 前导通配符、N+1、COUNT、深分页未能在单变量索引实验下证实"
    assert text_covers(joined, mechanisms_only)
