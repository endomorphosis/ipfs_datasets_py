"""Unit tests for row builders (normalize module)."""


def _base_kwargs():
    return dict(
        jurisdiction_id="0363",
        jurisdiction_name="Amsterdam",
        country="NL",
        doc_id="CVDR178438_1/artikel-1",
        node_label="Artikel 1",
        body_html="<p>Lid 1 tekst.</p>",
    )


def test_make_cid_format(wm):
    cid = wm.normalize.make_cid("0363", "CVDR178438_1/artikel-1")
    assert cid.startswith("bafkrei")
    # deterministic
    assert cid == wm.normalize.make_cid("0363", "CVDR178438_1/artikel-1")
    # jurisdiction embedded
    assert cid != wm.normalize.make_cid("0364", "CVDR178438_1/artikel-1")


def test_chunk_wrappers(wm):
    assert wm.normalize.chunk_title("Artikel 1") == (
        '<div class="chunk-title">Artikel 1</div>'
    )
    assert wm.normalize.chunk_content("<p>x</p>") == (
        '<div class="chunk-content"><p>x</p></div>'
    )


def test_make_row_defaults(wm):
    row = wm.normalize.make_row(**_base_kwargs())
    assert row["html"] == '<div class="chunk-content"><p>Lid 1 tekst.</p></div>'
    assert row["html_title"] == '<div class="chunk-title">Artikel 1</div>'
    assert row["text"] == "Lid 1 tekst."
    assert row["cid"] == wm.normalize.make_cid("0363", "CVDR178438_1/artikel-1")
    assert row["doc_order"] == 0
    # every canonical column present
    for col in wm.schema.EXPECTED_COLUMNS:
        assert col in row, col


def test_make_row_explicit_overrides(wm):
    row = wm.normalize.make_row(
        **_base_kwargs(), html="<b>custom</b>", text="custom text", cid="custom-cid"
    )
    assert row["html"] == "<b>custom</b>"
    assert row["text"] == "custom text"
    assert row["cid"] == "custom-cid"


def test_finalize_rows_order_and_dedupe(wm):
    rows = [wm.normalize.make_row(**_base_kwargs()) for _ in range(3)]
    out = wm.normalize.finalize_rows(rows)
    assert [r["doc_order"] for r in out] == [0, 1, 2]
    assert out[0]["doc_id"] == "CVDR178438_1/artikel-1"
    assert out[1]["doc_id"] == "CVDR178438_1/artikel-1-2"
    assert out[2]["doc_id"] == "CVDR178438_1/artikel-1-3"
    # cids recomputed to embed the suffixed doc_ids
    assert out[1]["cid"] == wm.normalize.make_cid("0363", "CVDR178438_1/artikel-1-2")
    assert len({r["cid"] for r in out}) == 3


def test_drop_empty_rows(wm):
    rows = [wm.normalize.make_row(**_base_kwargs())]
    kw = dict(_base_kwargs())
    kw["body_html"] = ""
    rows.append(wm.normalize.make_row(**kw))
    # second row has empty html/text after defaults
    rows[1]["html"] = ""
    rows[1]["text"] = "  "
    kept = wm.normalize.drop_empty_rows(rows)
    assert len(kept) == 1


def test_slugify(wm):
    assert wm.normalize.slugify("Artículo 24.º — Disposiciones") == "art-culo-24-disposiciones"


def test_strip_tags_reused(wm):
    assert wm.normalize.strip_tags("<p>a<br/>b</p>") == "a b"
