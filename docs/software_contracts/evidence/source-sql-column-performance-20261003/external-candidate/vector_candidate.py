"""External SQL-only candidate. Not a production owner or qualification result.

Replay hook: temporarily bind DuckDBASTStore._insert_rows to
insert_rows_unnest, then restore the original method in finally.
"""
from __future__ import annotations

import re

from ipfs_datasets_py.logic.software_contracts import duckdb_ast_store as owner


def insert_rows_unnest(self, statement, rows):
    """Use one list parameter per column, preserving the native chunk policy."""
    prefix, separator, placeholders = statement.partition("VALUES")
    if not separator or re.fullmatch(r"\s*\(\s*\?(?:\s*,\s*\?)*\s*\)\s*", placeholders) is None:
        raise owner.DuckDBASTStoreError("candidate requires the native placeholder-only INSERT layout")
    width = placeholders.count("?")
    sql = prefix + "SELECT " + ",".join(["unnest(?)"] * width)
    columns = [[] for _ in range(width)]
    count = size = 0
    for row in rows:
        if len(row) != width:
            raise owner.DuckDBASTStoreError("fact row differs from INSERT column layout")
        row_bytes = sum(len(value.encode("utf-8")) if type(value) is str else 8 for value in row)
        if count and (count >= owner._INSERT_BATCH_ROWS
                      or size + row_bytes > owner._INSERT_BATCH_PARAMETER_BYTES):
            self._connection.execute(sql, columns)
            columns, count, size = [[] for _ in range(width)], 0, 0
        for column, value in zip(columns, row):
            column.append(value)
        count += 1
        size += row_bytes
    if count:
        self._connection.execute(sql, columns)
