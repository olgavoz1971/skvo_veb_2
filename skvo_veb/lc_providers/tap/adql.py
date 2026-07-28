"""ADQL formatting helpers shared by TAP mission providers."""

from __future__ import annotations


def adql_top_limit_clause(row_limit: int | None) -> str:
    """Builds an ADQL ``TOP`` prefix for ``SELECT`` statements.

    Args:
        row_limit (int, optional): Maximum number of rows to return. When ``None``,
            no ``TOP`` clause is emitted.

    Returns:
        str: Empty string or ``"TOP n "`` suitable after ``SELECT``.

    Raises:
        ValueError: When ``row_limit`` is not a positive integer.
    """
    if row_limit is None:
        return ""
    limit = int(row_limit)
    if limit <= 0:
        raise ValueError(f"ADQL row limit must be positive, got {row_limit!r}.")
    return f"TOP {limit} "
