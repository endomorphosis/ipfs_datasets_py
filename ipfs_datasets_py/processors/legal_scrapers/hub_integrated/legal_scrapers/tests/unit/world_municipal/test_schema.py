"""Unit tests for the 19-column generalized schema + fail-closed validation."""

import pyarrow as pa
import pytest


def _rows(wm, n=3):
    rows = []
    for i in range(n):
        rows.append(
            wm.normalize.make_row(
                jurisdiction_id="0363",
                jurisdiction_name="Amsterdam",
                country="NL",
                doc_id=f"CVDR178438_1/artikel-{i + 1}",
                regeling_id="CVDR178438_1",
                regeling_work_id="CVDR178438",
                title="Algemene plaatselijke verordening",
                structural_path=f"Hoofdstuk 1 > Artikel {i + 1}",
                node_label=f"Artikel {i + 1}",
                body_html=f"<p>Lid {i + 1} tekst.</p>",
                source_url="https://lokaleregelgeving.overheid.nl/CVDR178438/1",
                xml_url="https://repository.officiele-overheidspublicaties.nl/cvdr/CVDR178438/1/xml/CVDR178438_1.xml",
                date_effective="2025-01-01",
                date_modified="2025-06-01",
                retrieved="2026-10-10",
            )
        )
    return wm.normalize.finalize_rows(rows)


def test_expected_columns_exact(wm):
    assert wm.schema.EXPECTED_COLUMNS == [
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


def test_build_schema_types(wm):
    schema = wm.schema.build_schema()
    assert schema.names == wm.schema.EXPECTED_COLUMNS
    for name in wm.schema.EXPECTED_COLUMNS:
        field = schema.field(name)
        assert field.nullable, name
        if name == "doc_order":
            assert field.type == pa.uint32(), name
        else:
            assert field.type == pa.string(), name


def test_build_schema_extra_column_appended(wm):
    # Portugal's sanctioned extension pattern: provenance columns go last.
    schema = wm.schema.build_schema([("tipo", pa.string())])
    assert schema.names[-1] == "tipo"
    assert schema.names[:19] == wm.schema.EXPECTED_COLUMNS


def test_build_schema_extra_collision_rejected(wm):
    with pytest.raises(ValueError):
        wm.schema.build_schema([("text", pa.string())])


def test_validate_ok(wm):
    table = wm.schema.rows_to_table(_rows(wm))
    errors = wm.schema.validate_table(
        table, jurisdiction_id="0363", jurisdiction_name="Amsterdam", country="NL"
    )
    assert errors == []


def test_validate_zero_empty_docs(wm):
    rows = _rows(wm)
    rows[1]["text"] = "   "
    table = wm.schema.rows_to_table(rows)
    errors = wm.schema.validate_table(table)
    assert any("empty text" in e for e in errors)


def test_validate_duplicate_doc_id(wm):
    rows = _rows(wm)
    rows[1]["doc_id"] = rows[0]["doc_id"]
    rows[1]["cid"] = rows[0]["cid"]  # keep cids unique to isolate the gate
    table = wm.schema.rows_to_table(rows)
    errors = wm.schema.validate_table(table)
    assert any("duplicate doc_id" in e for e in errors)


def test_validate_duplicate_cid(wm):
    rows = _rows(wm)
    rows[1]["cid"] = rows[0]["cid"]
    table = wm.schema.rows_to_table(rows)
    errors = wm.schema.validate_table(table)
    assert any("duplicate cid" in e for e in errors)


def test_validate_nonsequential_doc_order(wm):
    rows = _rows(wm)
    rows[1]["doc_order"] = 7
    table = wm.schema.rows_to_table(rows)
    errors = wm.schema.validate_table(table)
    assert any("doc_order" in e and "sequential" in e for e in errors)


def test_validate_attribution_mismatch(wm):
    rows = _rows(wm)
    table = wm.schema.rows_to_table(rows)
    errors = wm.schema.validate_table(table, jurisdiction_id="9999")
    assert any("jurisdiction_id" in e for e in errors)


def test_validate_null_rejected(wm):
    table = wm.schema.rows_to_table(_rows(wm))
    # inject a NULL into a nullable column: writers must serialize as ""
    table = table.set_column(
        table.schema.get_field_index("title"),
        "title",
        pa.array([None, "t", "t"], type=pa.string()),
    )
    errors = wm.schema.validate_table(table)
    assert any("NULL" in e for e in errors)


def test_validate_zero_rows_rejected(wm):
    table = wm.schema.rows_to_table([])
    errors = wm.schema.validate_table(table)
    assert any("0 rows" in e for e in errors)


def test_validate_column_order_enforced(wm):
    table = wm.schema.rows_to_table(_rows(wm))
    swapped = table.select(["jurisdiction_id", "cid"] + [c for c in table.schema.names if c not in ("cid", "jurisdiction_id")])
    errors = wm.schema.validate_table(swapped)
    assert any("column order mismatch" in e for e in errors)


def test_assert_valid_raises(wm):
    table = wm.schema.rows_to_table([])
    with pytest.raises(ValueError, match="0 rows"):
        wm.schema.assert_valid(table)


def test_validation_report_shape(wm):
    table = wm.schema.rows_to_table(_rows(wm))
    report = wm.schema.validation_report(table, jurisdiction_id="0363")
    assert report["valid"] is True
    assert report["rows"] == 3
    assert report["errors"] == []
