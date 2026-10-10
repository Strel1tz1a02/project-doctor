"""Parameterize SQL text into a shape template for N+1 grouping (pure, no I/O).

``normalize_sql`` stays literal-exact because slow-query diagnosis and evidence
verification depend on it (``WHERE id = 123`` and ``WHERE id = 456`` are two
different statements). N+1 detection needs a *shape* template that merges those
two, so this module normalizes literal values to ``?`` independently.

The normalization range is deliberately conservative: quoted string literals and
plain numeric literals are replaced, nothing else. Identifiers containing digits
(e.g. ``col_1``) are left untouched by the negative lookaround, and IN-lists
collapse each value to ``?`` without merging different SQL shapes.
"""

import re

_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_NUMERIC_LITERAL = re.compile(r"(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?(?![A-Za-z0-9_])")


def parameterize_sql(sql_text: str) -> str:
    """Return a shape template with string/numeric literals normalized to ``?``."""
    text = _STRING_LITERAL.sub("?", sql_text)
    text = _NUMERIC_LITERAL.sub("?", text)
    return " ".join(text.split())


def extract_sql_literals(sql_text: str) -> list[str]:
    """Extract quoted string and numeric literals in order of appearance.

    String literals are unquoted and ``''`` escapes are unescaped; numeric literals
    are returned as their original text. This feeds the "N distinct key values"
    parameter-provenance check without claiming the values are a subset of the
    parent result set (the diagnosis only proves count correlation, see the design).
    """
    strings = [
        match.group(0)[1:-1].replace("''", "'") for match in _STRING_LITERAL.finditer(sql_text)
    ]
    numbers = [match.group(0) for match in _NUMERIC_LITERAL.finditer(sql_text)]
    return strings + numbers
