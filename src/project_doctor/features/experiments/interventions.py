"""Validate and parse index recipes so a model cannot submit arbitrary DDL."""

from __future__ import annotations

import re
from dataclasses import dataclass

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
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
