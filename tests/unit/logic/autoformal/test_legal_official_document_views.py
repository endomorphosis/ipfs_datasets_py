"""Complete markup geometry is separate from governing legal source identity."""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal import legal_official_document_views as views
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as v1


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def html(*, heading="§1. Fictional section", statute=None, notes=None, prefix=None, head=None):
    return ("<html><head>" + (head if head is not None else '<meta charset="utf-8"><title>Title metadata</title>') +
        "</head><body>" + (prefix if prefix is not None else '<span style="font-size:10pt">Edition metadata</span><br>') +
        '<!-- documentid:independently observed only -->\n<!-- field-start:head -->' +
        '<h3 class="section-head">' + heading + '</h3><!-- field-end:head -->' +
        '<!-- field-start:statute -->' + (statute if statute is not None else
        '<h4 class="subsection-head">(a) General duty</h4><p class="statutory-body">Café aaa duty.</p>') +
        '<!-- field-end:statute --><!-- field-start:sourcecredit -->' +
        '<p class="source-credit">Source credit.</p><!-- field-end:sourcecredit -->' +
        (notes if notes is not None else '') + '</body></html>')


def inputs(raw, *, legal_id="usc:us:10:1", edition=2024):
    title, section = legal_id.split(":")[-2:]
    package = f"USCODE-{edition}-title{title}"
    granule = package + "-chap1-sec" + section
    url = f"https://www.govinfo.gov/content/pkg/{package}/html/{granule}.htm"
    descriptor = {"schema": custody.DESCRIPTOR_SCHEMA, "legal_id": legal_id, "edition": edition,
        "package_id": package, "granule_id": granule, "url": url, "retrieved_at": "2026-10-13T23:10:00Z",
        "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_bytes": len(raw), "http_provenance": {
            "requested_url": url, "final_url": url, "status_code": 200, "content_type": "text/html",
            "etag": None, "last_modified": None}}
    return {"descriptor": descriptor, "expected_descriptor_sha256": custody.acquisition_descriptor_sha256(descriptor),
        "expected_raw_sha256": descriptor["raw_sha256"], "expected_raw_bytes": len(raw)}


def prepared(**options):
    raw = html(**options).encode()
    args = inputs(raw)
    return raw, args, views.prepare_official_document_view(raw, **args)


NOTES = ('<!-- field-start:notes --><!-- field-start:miscellaneous-note -->'
    '<h4 class="note-head"><strong>Editorial Notes</strong></h4><!-- field-end:miscellaneous-note -->'
    '<!-- field-start:historicalandrevision-note -->'
    '<table class="uschistrev"><caption>History caption</caption>'
    '<tr><th id="h0">Earlier</th><th id="h1">Later</th></tr>'
    '<tr><td class="left">Left<i>1</i></td><td class="right"><p>Right Café</p><p>Tail</p></td></tr></table>'
    '<!-- field-end:historicalandrevision-note --><!-- field-start:amendment-note -->'
    '<p class="statutory-body">Quoted statutory-looking aaa text.</p><!-- field-end:amendment-note -->'
    '<!-- field-start:miscellaneous-note --><h4 class="note-head"><strong>Statutory Notes and Related Subsidiaries</strong></h4>'
    '<!-- field-end:miscellaneous-note --><!-- field-start:effectivedate-note -->'
    '<p class="note-body">Effective-date observation.</p><!-- field-end:effectivedate-note --><!-- field-end:notes -->'
    '<!-- field-start:footnote --><p class="footnote"><a name="n1"><sup>1</sup>&nbsp;Footnote aaa.</a></p><!-- field-end:footnote -->')


def test_complete_DOM_order_retains_headers_nested_table_cells_comments_notes_and_footnote():
    raw, args, report = prepared(notes=NOTES)
    assert report["status"] == "comparison_view_extracted" and report["raw_body_verified"] is True
    doc, view = report["document"], report["normalized_view"]
    assert [b["text"] for b in doc["blocks"]] == ["Edition metadata", "§1. Fictional section", "(a) General duty",
        "Café aaa duty.", "Source credit.", "Editorial Notes", "History caption", "Earlier", "Later", "Left1",
        "Right Café", "Tail", "Quoted statutory-looking aaa text.", "Statutory Notes and Related Subsidiaries",
        "Effective-date observation.", "1 Footnote aaa."]
    assert doc["title_observation"] == "Title metadata" and "Title metadata" not in doc["document_text"]
    assert doc["document_text"] == "\n".join(block["text"] for block in doc["blocks"])
    assert doc["visible_block_count"] == len(doc["blocks"])
    assert doc["blocks"][0]["region_kind"] == "metadata_header"
    assert doc["blocks"][2]["region_kind"] == "statute" and doc["blocks"][2]["block_kind"] == "heading"
    quoted = next(block for block in doc["blocks"] if block["text"].startswith("Quoted"))
    assert quoted["region_kind"] == "editorial_notes" and quoted["field_regions"] == ["notes", "amendment-note"]
    effective = next(block for block in doc["blocks"] if block["text"].startswith("Effective"))
    assert effective["region_kind"] == "statutory_notes"
    assert doc["blocks"][-1]["region_kind"] == "footnote"
    right = next(block for block in doc["blocks"] if block["text"] == "Right Café")
    assert right["table_coordinates"]["row_ordinal"] == 1 and right["table_coordinates"]["column_ordinal"] == 1
    assert right["table_coordinates"]["cell_attributes"] == {"class": "right"}
    assert doc["document_text"].count("Right Café") == 1 and doc["document_text"].count("Left1") == 1
    assert doc["comments"][0]["text"] == " documentid:independently observed only "
    assert all(value is False for value in report["authority"].values())
    assert view["utf8_bytes"] > view["unicode_code_points"] and view["decoder_profile"] == views.DECODER_PROFILE
    assert views.document_view_report_sha256(report) == digest(report)
    assert views.validate_official_document_view(report, raw, expected_report_sha256=digest(report), **args) == report


def test_all_body_text_in_mixed_parent_child_markup_is_retained_once_with_exact_offsets():
    raw, _, report = prepared(statute='<div>Before<p class="statutory-body">Inside <b>bold</b> text.</p>After</div>')
    blocks = report["document"]["blocks"]
    assert [b["text"] for b in blocks][2:5] == ["Before", "Inside bold text.", "After"]
    text = report["document"]["document_text"]
    for block in blocks:
        assert text[block["char_start"]:block["char_end"]] == block["text"]
        assert text.encode()[block["utf8_byte_start"]:block["utf8_byte_end"]].decode() == block["text"]
    assert len({block["block_id"] for block in blocks}) == len(blocks)
    assert report["raw_sha256"] == hashlib.sha256(raw).hexdigest()


def test_inline_PDF_comment_does_not_split_or_duplicate_visible_body_text():
    _, _, report = prepared(statute='<p class="statutory-body">One<!-- PDFPage:123 -->two<i>three</i>.</p>')
    assert any(block["text"] == "Onetwothree." for block in report["document"]["blocks"])
    assert any(comment["text"] == " PDFPage:123 " for comment in report["document"]["comments"])


@pytest.mark.parametrize("render", ["§410<i>oo</i>&ndash;2. Acquisition", "§410oo-2. Acquisition"])
def test_explicit_hyphen_heading_rendering_leaves_canonical_descriptor_identity_unchanged(render):
    raw = html(heading=render).encode()
    args = inputs(raw, legal_id="usc:us:16:410oo-2")
    report = views.prepare_official_document_view(raw, **args)
    assert report["status"] == "comparison_view_extracted"
    assert report["descriptor"]["legal_id"] == report["document"]["legal_id"] == "usc:us:16:410oo-2"
    observation = report["document"]["heading_render_observation"]
    assert observation["canonical_section_token"] == "410oo-2" and observation["cache_identity_aliases_used"] is False


@pytest.mark.parametrize("heading", ["§410oo—2. Different dash", "§410oo−2. Minus", "§410oo-20. Prefix collision",
                                    "§410OO–2. Case alias", "§410 oo–2. Whitespace alias"])
def test_heading_render_profile_never_accepts_other_dashes_aliases_or_prefixes(heading):
    raw = html(heading=heading).encode()
    report = views.prepare_official_document_view(raw, **inputs(raw, legal_id="usc:us:16:410oo-2"))
    assert report["status"] == "comparison_view_profile_refused" and report["document"] is None
    assert report["raw_body_verified"] is True and report["issues"]


def test_exact_overlaps_repeated_positions_Unicode_and_cross_block_intersections_are_unselected():
    raw, args, report = prepared(notes=NOTES)
    pin = digest(report)
    selectors = views.exact_view_occurrences(report, raw, expected_report_sha256=pin, text="aa", **args)
    assert len(selectors) == 6
    assert selectors[1]["char_start"] == selectors[0]["char_start"] + 1
    assert len({selector["occurrence_id"] for selector in selectors}) == len(selectors)
    text = report["document"]["document_text"]
    assert selectors[0]["utf8_byte_start"] > selectors[0]["char_start"]
    for selector in selectors:
        assert text.encode()[selector["utf8_byte_start"]:selector["utf8_byte_end"]].decode() == "aa"
        coverage = views.occurrence_region_intersections(report, selector)
        assert coverage["interblock_separator_codepoints"] == 0
    cross, = views.exact_view_occurrences(report, raw, expected_report_sha256=pin, text="duty.\nSource", **args)
    coverage = views.occurrence_region_intersections(report, cross)
    assert [b["region_kind"] for b in coverage["blocks"]] == ["statute", "source_credit"]
    assert coverage["interblock_separator_codepoints"] == 1
    assert views.exact_view_occurrences(report, raw, expected_report_sha256=pin, text="not present", **args) == []
    assert views.exact_view_occurrences(report, raw, expected_report_sha256=pin, text="Cafe\u0301", **args) == []


def test_nested_tables_preserve_distinct_table_coordinates_without_outer_row_leakage():
    statute = ('<p class="statutory-body">Duty.</p><table><tr><td>Outer<table><caption>Inner caption</caption>'
               '<tr><td>Inner</td></tr></table>Tail</td></tr></table>')
    _, _, report = prepared(statute=statute)
    blocks = {b["text"]: b for b in report["document"]["blocks"]}
    assert blocks["Inner caption"]["table_coordinates"]["row_ordinal"] is None
    assert blocks["Inner"]["table_coordinates"]["row_ordinal"] == 0
    assert blocks["Inner"]["table_coordinates"]["table_dom_path"] != blocks["Outer"]["table_coordinates"]["table_dom_path"]
    assert blocks["Tail"]["table_coordinates"] == blocks["Outer"]["table_coordinates"]


def test_existing_v1_coordinates_remain_distinct_and_are_not_mutated_by_new_view_calls():
    raw = html(statute='<p class="statutory-body">Café duty.</p>').encode()
    args = inputs(raw)
    old = v1.extract_document(raw, url=args["descriptor"]["url"], edition=2024, legal_id="usc:us:10:1")
    old_copy = deepcopy(old)
    old_selector = v1.source_selector(old, raw, char_start=0, char_end=4)
    report = views.prepare_official_document_view(raw, **args)
    selector, = views.exact_view_occurrences(report, raw, expected_report_sha256=digest(report), text="Café", **args)
    assert old == old_copy and old["document_text"] == "Café duty.\nSource credit."
    assert selector["schema"] != old_selector["schema"] and selector["view_id"] != old_selector["view_id"]
    with pytest.raises(ValueError): v1.validate_source_selector(selector, old, raw)
    with pytest.raises(ValueError): views.occurrence_region_intersections(report, old_selector)


@pytest.mark.parametrize("encoding", ["utf-8", "windows-1252", "utf-16"])
def test_new_view_reuses_shared_declared_encoding_decoder(encoding):
    source = html(head=f'<meta charset="{encoding}"><title>Declared encoding</title>')
    raw = source.encode(encoding)
    report = views.prepare_official_document_view(raw, **inputs(raw))
    assert report["status"] == "comparison_view_extracted" and "Café" in report["document"]["document_text"]
    assert report["normalized_view"]["decoder_profile"] == views.DECODER_PROFILE
    assert report["raw_sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("case", ["undeclared_bytes", "conflicting_declarations", "escape_codec"])
def test_shared_decoder_refusals_preserve_raw_custody_without_fabricated_text(case):
    if case == "undeclared_bytes": raw = html(head="<title>Undeclared</title>").encode("windows-1252")
    elif case == "conflicting_declarations": raw = html(head='<meta charset="utf-8"><meta charset="latin-1">').encode()
    else: raw = html(head='<meta charset="unicode-escape">').encode()
    report = views.prepare_official_document_view(raw, **inputs(raw))
    assert report["status"] == "comparison_view_profile_refused" and report["raw_body_verified"] is True
    assert report["document"] is None and report["normalized_view"] is None


@pytest.mark.parametrize("damage", ["descriptor", "body_hash", "body_size", "raw_bytes", "unknown_descriptor"])
def test_independent_acquisition_and_content_pins_cannot_be_replaced_by_self_seals(damage):
    raw = html().encode(); args = inputs(raw)
    if damage == "descriptor": args["expected_descriptor_sha256"] = "0" * 64
    elif damage == "body_hash": args["expected_raw_sha256"] = "0" * 64
    elif damage == "body_size": args["expected_raw_bytes"] += 1
    elif damage == "raw_bytes": raw += b" "
    else: args["descriptor"]["accepted"] = True
    with pytest.raises(ValueError): views.prepare_official_document_view(raw, **args)


def test_missing_body_is_explicit_and_cannot_yield_occurrences():
    raw = html().encode(); args = inputs(raw)
    report = views.prepare_official_document_view(None, **args)
    assert report["status"] == "raw_comparison_document_missing" and report["raw_body_verified"] is False
    assert report["document"] is None and report["normalized_view"] is None
    assert views.validate_official_document_view(report, None, expected_report_sha256=digest(report), **args) == report
    with pytest.raises(ValueError):
        views.exact_view_occurrences(report, None, expected_report_sha256=digest(report), text="Café", **args)


@pytest.mark.parametrize("damage", ["script", "image", "hidden", "CSS", "duplicate_attr", "bad_close", "unclosed_field",
    "crossed_field", "malformed_field", "unmarked_statute", "duplicate_heading", "outside_body", "duplicate_html"])
def test_unsupported_markup_never_returns_a_selected_easy_view(damage):
    source = html()
    if damage == "script": source = source.replace("</body>", "<script>unexecuted()</script></body>")
    elif damage == "image": source = source.replace("</body>", '<img alt="visible nontext"></body>')
    elif damage == "hidden": source = source.replace('class="statutory-body"', 'class="statutory-body" hidden')
    elif damage == "CSS": source = source.replace('class="statutory-body"', 'class="statutory-body" style="display:none"')
    elif damage == "duplicate_attr": source = source.replace('class="statutory-body"', 'class="statutory-body" class="other"')
    elif damage == "bad_close": source = source.replace("</p>", "</div>", 1)
    elif damage == "unclosed_field": source = source.replace("<!-- field-end:statute -->", "")
    elif damage == "crossed_field": source = source.replace("<!-- field-end:statute -->", "<!-- field-end:head -->")
    elif damage == "malformed_field": source = source.replace("<!-- field-start:statute -->", "<!-- field-start:statute extra -->")
    elif damage == "unmarked_statute": source = source.replace("field-start:statute", "field-start:unclassified").replace("field-end:statute", "field-end:unclassified")
    elif damage == "duplicate_heading": source = source.replace("</body>", '<h3 class="section-head">§1. Another</h3></body>')
    elif damage == "outside_body": source += "Undeclared outside visible text."
    else: source += "<html></html>"
    raw = source.encode(); report = views.prepare_official_document_view(raw, **inputs(raw))
    assert report["status"] == "comparison_view_profile_refused" and report["raw_body_verified"]
    assert report["document"] is None and report["normalized_view"] is None and report["issues"]


@pytest.mark.parametrize("damage", ["authority", "block_offset", "byte_offset", "region", "drop_block", "drop_comment", "view_profile", "heading_identity"])
def test_report_forgery_fails_independent_pin_and_full_regeneration_even_after_rehash(damage):
    raw, args, report = prepared(notes=NOTES)
    retained = digest(report)
    if damage == "authority": report["authority"]["source_semantics_verified"] = True
    elif damage == "block_offset": report["document"]["blocks"][0]["char_start"] += 1
    elif damage == "byte_offset": report["document"]["blocks"][3]["utf8_byte_start"] += 1
    elif damage == "region": report["document"]["blocks"][-1]["region_kind"] = "statute"
    elif damage == "drop_block": report["document"]["blocks"].pop()
    elif damage == "drop_comment": report["document"]["comments"].pop()
    elif damage == "view_profile": report["normalized_view"]["decoder_profile"] = "guessed-encoding/v99"
    else: report["document"]["heading_render_observation"]["canonical_section_token"] = "other"
    with pytest.raises(ValueError, match="independent full"):
        views.validate_official_document_view(report, raw, expected_report_sha256=retained, **args)
    with pytest.raises(ValueError, match="complete independent"):
        views.validate_official_document_view(report, raw, expected_report_sha256=digest(report), **args)


@pytest.mark.parametrize("damage", ["char_start", "utf8_byte_end", "view_id", "occurrence_id", "extra", "boolean"])
def test_selector_geometry_and_identity_are_closed_not_self_authenticated(damage):
    raw, args, report = prepared()
    selector, = views.exact_view_occurrences(report, raw, expected_report_sha256=digest(report), text="Café", **args)
    if damage == "extra": selector["accepted"] = True
    elif damage == "boolean": selector["char_start"] = True
    elif damage in ("char_start", "utf8_byte_end"): selector[damage] += 1
    else: selector[damage] = "forged"
    with pytest.raises(ValueError): views.occurrence_region_intersections(report, selector)


@pytest.mark.parametrize("name", list(views.DEFAULT_LIMITS))
def test_incremental_population_bounds_refuse_without_partial_success(name):
    raw = html(notes=NOTES).encode(); args = inputs(raw)
    with pytest.raises(ValueError, match="bound"):
        views.prepare_official_document_view(raw, **args, limits={name: 1})


def test_all_occurrences_or_no_success_when_occurrence_limit_exceeded():
    raw, args, report = prepared()
    with pytest.raises(ValueError, match="occurrence bound"):
        views.exact_view_occurrences(report, raw, expected_report_sha256=digest(report), text="aa", max_occurrences=1, **args)
    with pytest.raises(ValueError, match="view limit"):
        views.prepare_official_document_view(raw, **args, limits={"max_blocks": views.DEFAULT_LIMITS["max_blocks"] + 1})


def test_repeated_long_selectors_refuse_aggregate_bytes_before_large_list_allocation(monkeypatch):
    raw = html(statute='<p class="statutory-body">' + "a" * 4096 + '</p>').encode()
    args = inputs(raw)
    initial = views.prepare_official_document_view(raw, **args)
    args["limits"] = {"max_report_bytes": len(views._wire(initial)) + 1024}
    report = views.prepare_official_document_view(raw, **args)
    observed = []
    original = views._selector
    def count_selector(*args, **kwargs):
        observed.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(views, "_selector", count_selector)
    with pytest.raises(ValueError, match="selector output byte bound"):
        views.exact_view_occurrences(report, raw, expected_report_sha256=digest(report), text="a" * 512, **args)
    assert 0 < len(observed) < 100  # Thousands of physical overlaps were not accumulated.
