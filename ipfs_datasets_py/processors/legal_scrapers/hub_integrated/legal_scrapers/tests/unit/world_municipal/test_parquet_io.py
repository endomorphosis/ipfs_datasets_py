"""Unit tests for parquet I/O (round-trip, compression default)."""


def _table(wm):
    rows = [
        wm.normalize.make_row(
            jurisdiction_id="0363",
            jurisdiction_name="Amsterdam",
            country="NL",
            doc_id=f"CVDR178438_1/artikel-{i + 1}",
            node_label=f"Artikel {i + 1}",
            body_html=f"<p>Lid {i + 1}.</p>",
        )
        for i in range(2)
    ]
    rows = wm.normalize.finalize_rows(rows)
    return wm.schema.rows_to_table(rows)


def test_round_trip(wm, tmp_path):
    table = _table(wm)
    path = tmp_path / "0363_html.parquet"
    n = wm.parquet_io.write_html_parquet(path, table)
    assert n == 2
    back = wm.parquet_io.read_html_parquet(path)
    assert back.schema.names == table.schema.names
    assert back.num_rows == 2
    assert back.column("doc_id").to_pylist() == table.column("doc_id").to_pylist()


def test_default_compression(wm):
    assert wm.parquet_io.default_compression() in ("zstd", "snappy")


def test_write_validation_report(wm, tmp_path):
    table = _table(wm)
    report = wm.schema.validation_report(table)
    path = tmp_path / "validation.json"
    wm.parquet_io.write_validation_report(path, report)
    assert path.exists()
