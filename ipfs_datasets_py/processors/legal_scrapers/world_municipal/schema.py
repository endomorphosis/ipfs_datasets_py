"""The 19-column generalized schema for the world municipal-law program.

Canonical contract shared by the NL/PT/ES pilots (byte-identical Arrow
schemas, asserted exact-match by each pilot's validator) and the published
Portugal full harvest. One row per article (plus preamble/annex rows); one
parquet file per jurisdiction named ``{jurisdiction_id}_html.parquet``.

Country-specific provenance columns follow the sanctioned extension pattern:
they are appended AFTER column 19, never reordered or interleaved
(e.g. Portugal full harvest appends ``tipo`` as column 20).

Conventions (from the pilots):
- every column is nullable in Arrow, but writers serialize missing values
  as ``""`` — NULLs are a validation failure;
- ``doc_order`` is the only non-string column (uint32), 0-based and strictly
  sequential within a jurisdiction file;
- all other columns are plain UTF-8 strings.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pyarrow as pa

#: The 19 canonical columns, in exact order.
EXPECTED_COLUMNS: List[str] = [
    "cid",
    "jurisdiction_id",
    "jurisdiction_name",
    "country",
    "doc_id",
    "regeling_id",
    "regeling_work_id",
    "doc_order",
    "title",
    "structural_path",
    "node_label",
    "html_title",
    "html",
    "text",
    "source_url",
    "xml_url",
    "date_effective",
    "date_modified",
    "retrieved",
]

_STRING = pa.string()
_UINT32 = pa.uint32()


def build_schema(
    extra_columns: Sequence[Tuple[str, pa.DataType]] = (),
) -> pa.Schema:
    """Build the Arrow schema: the 19 canonical columns plus any extras.

    Extra columns (e.g. PT's ``tipo``) are appended after column 19 per the
    sanctioned extension pattern.
    """
    fields = [
        pa.field(name, _UINT32 if name == "doc_order" else _STRING, nullable=True)
        for name in EXPECTED_COLUMNS
    ]
    for name, dtype in extra_columns:
        if name in EXPECTED_COLUMNS:
            raise ValueError(f"extra column {name!r} collides with a canonical column")
        fields.append(pa.field(name, dtype, nullable=True))
    return pa.schema(fields)


def _col(table: pa.Table, name: str) -> pa.ChunkedArray:
    return table.column(name)


def validate_table(
    table: pa.Table,
    *,
    jurisdiction_id: Optional[str] = None,
    jurisdiction_name: Optional[str] = None,
    country: Optional[str] = None,
    allow_empty: bool = False,
) -> List[str]:
    """Fail-closed validation of a jurisdiction's article table.

    Returns a list of human-readable error strings; an empty list means the
    table is valid. Gates (mirroring the pilot validators):
    1. exact canonical column order (extras allowed only after column 19);
    2. canonical dtypes (doc_order uint32, everything else string);
    3. no NULL values anywhere (missing serializes as "");
    4. zero empty docs (text/html must be non-blank);
    5. doc_order strictly sequential 0..n-1;
    6. doc_id and cid unique within the file;
    7. jurisdiction attribution constant and matching the expected values.
    """
    errors: List[str] = []
    names = table.schema.names

    # 1. column order
    if names[: len(EXPECTED_COLUMNS)] != EXPECTED_COLUMNS:
        errors.append(
            "column order mismatch: expected first 19 columns "
            f"{EXPECTED_COLUMNS}, got {names[: len(EXPECTED_COLUMNS)]}"
        )
        return errors  # further checks are meaningless without the columns

    # 2. dtypes
    for name in EXPECTED_COLUMNS:
        want = _UINT32 if name == "doc_order" else _STRING
        got = table.schema.field(name).type
        if got != want:
            errors.append(f"column {name!r}: expected {want}, got {got}")
    for name in names[len(EXPECTED_COLUMNS) :]:
        if table.schema.field(name).type != _STRING:
            errors.append(f"extra column {name!r}: expected string, got {table.schema.field(name).type}")

    n = table.num_rows
    if n == 0:
        if not allow_empty:
            errors.append("table has 0 rows: do not ship empty jurisdiction files")
        return errors

    def pylist(name: str) -> List[Any]:
        return _col(table, name).to_pylist()

    # 3. no NULLs
    for name in names:
        nulls = _col(table, name).null_count
        if nulls:
            errors.append(f"column {name!r}: {nulls} NULL values (serialize missing as \"\")")

    texts = pylist("text")
    htmls = pylist("html")

    # 4. zero empty docs
    empty_text = sum(1 for t in texts if not (t or "").strip())
    if empty_text:
        errors.append(f"{empty_text} rows with empty text")
    empty_html = sum(1 for h in htmls if not (h or "").strip())
    if empty_html:
        errors.append(f"{empty_html} rows with empty html")

    # 5. sequential doc_order
    orders = pylist("doc_order")
    if orders != list(range(n)):
        errors.append("doc_order is not strictly sequential 0..n-1")

    # 6. uniqueness
    doc_ids = pylist("doc_id")
    if len(set(doc_ids)) != len(doc_ids):
        errors.append("duplicate doc_id values present")
    cids = pylist("cid")
    if len(set(cids)) != len(cids):
        errors.append("duplicate cid values present")

    # 7. attribution
    for col, want in (
        ("jurisdiction_id", jurisdiction_id),
        ("jurisdiction_name", jurisdiction_name),
        ("country", country),
    ):
        vals = set(pylist(col))
        if len(vals) != 1:
            errors.append(f"column {col!r}: not constant within file ({len(vals)} distinct)")
        elif want is not None and next(iter(vals)) != want:
            errors.append(f"column {col!r}: {next(iter(vals))!r} != expected {want!r}")

    return errors


def assert_valid(table: pa.Table, **kwargs: Any) -> None:
    """Raise ValueError listing every validation failure, if any."""
    errors = validate_table(table, **kwargs)
    if errors:
        raise ValueError("world_municipal schema validation failed:\n- " + "\n- ".join(errors))


def rows_to_table(
    rows: Sequence[Dict[str, Any]],
    extra_columns: Sequence[Tuple[str, pa.DataType]] = (),
) -> pa.Table:
    """Build an Arrow table from row dicts, coercing to the schema.

    String columns are coerced with ``str(v or "")`` (never NULL);
    ``doc_order`` is coerced to int. Unknown keys are dropped unless they
    are declared in ``extra_columns``.
    """
    schema = build_schema(extra_columns)
    string_cols = [c for c in EXPECTED_COLUMNS if c != "doc_order"] + [
        name for name, _ in extra_columns
    ]
    columns: Dict[str, List[Any]] = {c: [] for c in string_cols}
    orders: List[int] = []
    for row in rows:
        for c in string_cols:
            v = row.get(c, "")
            columns[c].append("" if v is None else str(v))
        orders.append(int(row.get("doc_order", 0)))
    arrays = [pa.array(columns[c], type=pa.string()) for c in string_cols]
    # splice doc_order back into canonical position (index 7)
    arrays.insert(
        EXPECTED_COLUMNS.index("doc_order"), pa.array(orders, type=pa.uint32())
    )
    return pa.Table.from_arrays(arrays, schema=schema)


def validation_report(
    table: pa.Table,
    *,
    jurisdiction_id: Optional[str] = None,
    jurisdiction_name: Optional[str] = None,
    country: Optional[str] = None,
) -> Dict[str, Any]:
    """Machine-readable validation summary (for validation.json sidecars)."""
    errors = validate_table(
        table,
        jurisdiction_id=jurisdiction_id,
        jurisdiction_name=jurisdiction_name,
        country=country,
    )
    return {
        "rows": table.num_rows,
        "columns": table.schema.names,
        "valid": not errors,
        "errors": errors,
    }
