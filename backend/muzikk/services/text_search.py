"""Apostrophe-tolerant matching for the library searches.

An apostrophe reaches the tags in three shapes: "Diam's" typed on a keyboard,
"Diam’s" copied from a web page, and "Diams" from a tagger that dropped it. A
LIKE on the stored text finds one spelling out of three, so every comparison
below runs twice: once on the text as stored, once with the apostrophes removed
on both sides.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import ColumnElement, func, or_

# ASCII quote, the typographic pair, the modifier letter some taggers use, and
# the two keys people hit instead of it.
APOSTROPHES = ("'", "\u2018", "\u2019", "\u02bc", "\u00b4", "`")


def fold(value: str) -> str:
    """The text lowercased and stripped of every apostrophe spelling."""
    text = value.lower()
    for mark in APOSTROPHES:
        text = text.replace(mark, "")
    return text


def _folded(column: ColumnElement[str]) -> ColumnElement[str]:
    """The same fold, computed by the database on a column."""
    expression = func.lower(column)
    for mark in APOSTROPHES:
        expression = func.replace(expression, mark, "")
    return expression


def contains(column: ColumnElement[str], value: str) -> ColumnElement[bool]:
    """Case- and apostrophe-insensitive containment test on one column."""
    text = value.strip()
    return or_(column.ilike(f"%{text}%"), _folded(column).like(f"%{fold(text)}%"))


def contains_any(columns: Iterable[ColumnElement[str]], value: str) -> ColumnElement[bool]:
    """True when any of the columns contains the text."""
    return or_(*(contains(column, value) for column in columns))
