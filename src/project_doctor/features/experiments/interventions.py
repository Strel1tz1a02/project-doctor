"""Validate and parse intervention recipes so a model cannot submit arbitrary DDL
or arbitrary runtime toggles.

``IndexRecipe`` is the single-statement DDL the runtime applies to a database;
``QueryShapeRecipe`` is the temporary, reversible runtime flag toggle used to prove
an N+1 mechanism before the fix layer performs a permanent rewrite.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_QUERY_SHAPE_STRATEGIES = {"batch_in", "joinedload", "selectinload"}
_RECIPE = re.compile(
    r"\ACREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+(?P<name>\w+)\s+ON\s+(?P<table>\w+)\s*"
    r"\(\s*(?P<columns>\w+(?:\s*,\s*\w+)*)\s*\)\Z",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IndexRecipe:
    name: str
    table: str
    columns: tuple[str, ...]
    unique: bool = False

    @property
    def create_sql(self) -> str:
        prefix = "CREATE UNIQUE INDEX" if self.unique else "CREATE INDEX"
        return f"{prefix} {self.name} ON {self.table} ({', '.join(self.columns)})"

    @property
    def drop_sql(self) -> str:
        return f"DROP INDEX {self.name} ON {self.table}"


def parse_index_recipe(recipe: str) -> IndexRecipe:
    """Accept exactly one ``CREATE [UNIQUE] INDEX name ON table (columns)`` statement.

    Anything else — other DDL, DML, multiple statements, comments, partial-index
    clauses or injected trailing SQL — is rejected. The returned recipe also carries
    the exact reverse statement so the runtime can restore the database.
    """
    text = recipe.strip()
    if text.endswith(";"):
        text = text[:-1].strip()
    if ";" in text or "--" in text or "/*" in text or "#" in text:
        raise ValueError("recipe must be a single statement without comments or trailing SQL")
    match = _RECIPE.match(text)
    if match is None:
        raise ValueError("only CREATE [UNIQUE] INDEX name ON table (columns) is allowed")
    name = match.group("name")
    table = match.group("table")
    columns = tuple(part.strip() for part in match.group("columns").split(","))
    if not all(_IDENTIFIER.fullmatch(part) for part in (name, table, *columns)):
        raise ValueError("unexpected identifier in index recipe")
    return IndexRecipe(name=name, table=table, columns=columns, unique=bool(match.group("unique")))


@dataclass(frozen=True)
class QueryShapeRecipe:
    """A temporary, reversible runtime flag toggle proving an N+1 mechanism.

    Unlike ``IndexRecipe`` (database DDL), this toggles an application runtime flag
    so the demo's two implementation branches (``n1`` loop vs ``batch``) can be
    compared as a single-variable, symmetric, reversible change.
    """

    strategy: str
    flag: str
    baseline_value: str
    candidate_value: str
    child_template: str
    key_column: str


def parse_query_shape_recipe(recipe: str) -> QueryShapeRecipe:
    """Accept exactly one JSON object describing a query-shape flag toggle.

    Unknown fields, a wrong strategy, missing values, or an unchanged flag are
    rejected. The runtime applies ``baseline_value`` for the baseline level, sets
    ``candidate_value`` for the candidate level, then restores ``baseline_value``.
    """
    text = recipe.strip()
    if not text:
        raise ValueError("query_shape recipe is empty")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("query_shape recipe must be a single JSON object") from exc
    if not isinstance(data, dict):
        raise ValueError("query_shape recipe must be a JSON object")
    if set(data) != {
        "strategy",
        "flag",
        "baseline_value",
        "candidate_value",
        "child_template",
        "key_column",
    }:
        raise ValueError(
            "query_shape recipe must declare strategy/flag/baseline_value/"
            "candidate_value/child_template/key_column"
        )
    strategy = data["strategy"]
    if strategy not in _QUERY_SHAPE_STRATEGIES:
        raise ValueError("unsupported query_shape strategy")
    fields = {
        name: data[name]
        for name in ("flag", "baseline_value", "candidate_value", "child_template", "key_column")
    }
    for name, value in fields.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"query_shape recipe field {name} must be a non-empty string")
    if fields["baseline_value"] == fields["candidate_value"]:
        raise ValueError("query_shape baseline and candidate values must differ")
    return QueryShapeRecipe(strategy=strategy, **fields)
