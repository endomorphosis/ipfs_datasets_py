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


# Additive original-byte lineage; these controls confer no legal authority.
def origin_fixture(*, statute=None, encoding="utf-8"):
    source = html(statute=statute, head='<meta charset="' + encoding + '"><title>Origin metadata</title>')
    raw = source.encode(encoding)
    args = inputs(raw)
    report = views.prepare_official_document_view(raw, **args)
    before = deepcopy(report)
    mapping = views.prepare_official_document_origin_map(report, raw, expected_view_report_sha256=digest(report), **args)
    assert report == before
    return raw, args, report, mapping


def origin_span(raw, args, report, mapping, text, *, number=0):
    selectors = views.exact_view_occurrences(report, raw, expected_report_sha256=digest(report), text=text, **args)
    return views.official_origin_span_fragments(mapping, report, raw, selector=selectors[number],
        expected_origin_map_sha256=digest(mapping), expected_view_report_sha256=digest(report), **args)


def test_origin_map_exact_entity_whitespace_inline_origins_preserve_full_V2_report():
    raw, args, report, mapping = origin_fixture(statute='<p>Caf&eacute;  <i>x</i>&nbsp;雪</p>')
    selected = origin_span(raw, args, report, mapping, 'Café x 雪')
    entity, = [f for f in selected['fragments'] if f['kind'] == 'HTML_reference_decoded']
    assert raw[entity['source_origins'][0]['raw_byte_start']:entity['source_origins'][-1]['raw_byte_end']] == b'&eacute;'
    spaces = [f for f in selected['fragments'] if f['kind'] == 'collapsed_whitespace']
    assert len(spaces) == 2
    assert [b''.join(raw[s['raw_byte_start']:s['raw_byte_end']] for s in f['source_origins']) for f in spaces] == [b'  ', b'&nbsp;']
    assert any(raw[p['raw_byte_start']:p['raw_byte_end']] == b'<i>' and p['kind'] == 'not_in_normalized_output' for p in mapping['raw_partition'])
    assert mapping['raw_partition'][0]['raw_byte_start'] == 0 and mapping['raw_partition'][-1]['raw_byte_end'] == len(raw)
    assert all(a['raw_byte_end'] == b['raw_byte_start'] for a,b in zip(mapping['raw_partition'],mapping['raw_partition'][1:]))
    assert all(flag is False for flag in mapping['authority'].values())
    assert report['normalized_view']['raw_html_coordinate_mapping_verified'] is False
    assert views.validate_official_document_view(report, raw, expected_report_sha256=digest(report), **args) == report


@pytest.mark.parametrize('encoding', ['utf-8-sig', 'utf-16', 'utf-32', 'windows-1252', 'iso2022_jp', 'utf-7'])
def test_origin_map_reuses_shared_strict_codec_with_actual_BOM_state_and_emission_relations(encoding):
    text = 'Café' if encoding == 'windows-1252' else '雪雷'
    raw, args, report, mapping = origin_fixture(statute='<p>' + text + '</p>', encoding=encoding)
    decoded, chosen = v1._decode_source_html_with_encoding(raw)
    assert v1._decode_source_html(raw) == decoded and mapping['chosen_codec'] == chosen
    result = origin_span(raw, args, report, mapping, text)
    assert result['selector']['text'] == text
    assert all(0 <= s['raw_byte_start'] < s['raw_byte_end'] <= len(raw) for f in result['fragments'] for s in f['source_origins'])
    if encoding in {'utf-8-sig', 'utf-16', 'utf-32', 'iso2022_jp'}:
        assert mapping['decoder_controls']
    if encoding == 'utf-7':
        assert any(r['relation'] == 'emission_envelope' for r in mapping['decoder_runs'])
        partial=origin_span(raw,args,report,mapping,text[0])
        source_origin,=[source for fragment in partial['fragments'] for source in fragment['source_origins']]
        run=mapping['decoder_runs'][source_origin['decoder_run_index']]
        assert source_origin['relation']=='emission_envelope'
        assert source_origin['minimal_per_character_raw_slice_claimed'] is False
        assert source_origin['decoded_html_char_end']-source_origin['decoded_html_char_start']==1
        assert run['decoded_char_end']-run['decoded_char_start']==3
        assert (source_origin['raw_byte_start'],source_origin['raw_byte_end'])==(run['raw_byte_start'],run['raw_byte_end'])
        assert raw[source_origin['raw_byte_start']:source_origin['raw_byte_end']]==(text+'<').encode('utf-7')
    assert all(flag is False for flag in result['authority'].values())


def test_origin_map_LF_only_parser_positions_empty_reference_and_literal_less_than_are_exact():
    raw, args, report, mapping = origin_fixture(statute='<p>A\r\nB\rC\u2028D &#1; E < F</p>')
    result = origin_span(raw, args, report, mapping, 'A B C D E < F')
    assert result['selector']['text'] == 'A B C D E < F'
    zero, = mapping['zero_output_references']
    assert b''.join(raw[s['raw_byte_start']:s['raw_byte_end']] for s in zero['source_origins']) == b'&#1;'
    assert any(p['kind'] == 'not_in_normalized_output' and b'&#1;' in raw[p['raw_byte_start']:p['raw_byte_end']] for p in mapping['raw_partition'])


def test_origin_map_partial_multicodepoint_entity_repeated_occurrences_and_synthetic_LF_remain_distinct():
    raw, args, report, mapping = origin_fixture(statute='<p>X&NotEqualTilde;Y</p><p>X&NotEqualTilde;Y</p>')
    text = 'X≂̸Y'
    first = origin_span(raw,args,report,mapping,text,number=0)
    second = origin_span(raw,args,report,mapping,text,number=1)
    assert first['selector']['occurrence_id'] != second['selector']['occurrence_id']
    assert first['fragments'][0]['source_origins'] != second['fragments'][0]['source_origins']
    partial = origin_span(raw,args,report,mapping,'̸',number=0)
    fragment, = partial['fragments']
    assert fragment['entity_output_char_start'] == 1 and fragment['entity_output_char_end'] == 2
    assert fragment['partial_entity_uses_whole_transform_envelope'] is True
    assert b''.join(raw[s['raw_byte_start']:s['raw_byte_end']] for s in fragment['source_origins']) == b'&NotEqualTilde;'
    cross = origin_span(raw,args,report,mapping,text+'\n'+text)
    gap, = [f for f in cross['fragments'] if f['kind'] == 'synthetic_interblock_LF']
    assert gap['source_origins'] == [] and gap['output_utf8_byte_end'] - gap['output_utf8_byte_start'] == 1


@pytest.mark.parametrize('damage', ['profile', 'codec', 'gap', 'origin', 'output_byte', 'decoder', 'producer', 'authority'])
def test_origin_map_resealed_mutations_do_not_replace_complete_original_regeneration(damage):
    raw,args,report,mapping=origin_fixture(statute='<p>Caf&eacute; duty.</p>')
    changed=deepcopy(mapping)
    if damage=='profile': changed['profile']='other/v1'
    elif damage=='codec': changed['chosen_codec']='ascii'
    elif damage=='gap': changed['output_fragments'].pop()
    elif damage=='origin': changed['output_fragments'][-1]['source_origins'][0]['raw_byte_start']+=1
    elif damage=='output_byte': changed['output_fragments'][-1]['output_utf8_byte_end']+=1
    elif damage=='decoder': changed['decoder_runs'][0]['raw_byte_end']-=1
    elif damage=='producer': changed['producer_code_pins']['python_version'][0]+=1
    else: changed['authority']['legal_roles_verified']=True
    changed.pop('origin_map_sha256');changed['origin_map_sha256']=digest(changed)
    with pytest.raises(views.OfficialDocumentViewError):
        views.validate_official_document_origin_map(changed,report,raw,expected_origin_map_sha256=digest(changed),expected_view_report_sha256=digest(report),**args)


@pytest.mark.parametrize('damage', ['raw', 'map_pin', 'selector'])
def test_origin_map_independent_raw_map_and_exact_occurrence_pins_refuse_substitution(damage):
    raw,args,report,mapping=origin_fixture(statute='<p>Café duty.</p>')
    selector,=views.exact_view_occurrences(report,raw,expected_report_sha256=digest(report),text='Café',**args)
    if damage=='raw':raw=raw.replace(b'duty',b'evil')
    elif damage=='selector':selector=dict(selector,occurrence_id='foreign')
    with pytest.raises(views.OfficialDocumentViewError):
        views.official_origin_span_fragments(mapping,report,raw,selector=selector,
            expected_origin_map_sha256='f'*64 if damage=='map_pin' else digest(mapping),
            expected_view_report_sha256=digest(report),**args)


def test_origin_map_stateful_buffer_refusal_is_explicit_without_narrowing_existing_view_decoder():
    source=html(statute='<p>'+'雪'*4000+'</p>',head='<meta charset="utf-7"><title>Origin</title>')
    raw=source.encode('utf-7');args=inputs(raw)
    report=views.prepare_official_document_view(raw,**args)
    assert report['status']=='comparison_view_extracted'
    assert v1._decode_source_html(raw)==source
    with pytest.raises(views.OfficialDocumentViewError,match='explicit origin-profile bound'):
        views.prepare_official_document_origin_map(report,raw,expected_view_report_sha256=digest(report),**args)


def test_origin_map_complete_token_bound_refuses_without_truncating_existing_V2_view(monkeypatch):
    source=html(prefix='',statute='<p>'+'x&amp;'*40+'</p>')
    raw=source.encode();args=inputs(raw)
    report=views.prepare_official_document_view(raw,limits={'max_nodes':16},**args)
    assert report['status']=='comparison_view_extracted'
    before=deepcopy(report)
    counter=origin_entity_match_probe(monkeypatch)
    with pytest.raises(views.OfficialDocumentViewError,match='origin-token bound'):
        views.prepare_official_document_origin_map(report,raw,expected_view_report_sha256=digest(report),limits={'max_nodes':16},**args)
    assert counter['matches']<40
    assert report==before and all(flag is False for flag in report['authority'].values())


def test_origin_span_rechecks_full_view_after_map_replay_before_using_mutable_caller_text(monkeypatch):
    raw,args,report,mapping=origin_fixture(statute='<p>Café duty.</p>')
    pin=digest(report)
    selector,=views.exact_view_occurrences(report,raw,expected_report_sha256=pin,text='Café',**args)
    original=views.validate_official_document_origin_map
    def replay_then_mutate(*values,**keywords):
        result=original(*values,**keywords)
        report['document']['document_text']='X'*len(report['document']['document_text'])
        return result
    monkeypatch.setattr(views,'validate_official_document_origin_map',replay_then_mutate)
    with pytest.raises(views.OfficialDocumentViewError,match='independent full document-view report pin'):
        views.official_origin_span_fragments(mapping,report,raw,selector=selector,
            expected_origin_map_sha256=digest(mapping),expected_view_report_sha256=pin,**args)



def origin_entity_match_probe(monkeypatch):
    import html as stdlib_html
    original=stdlib_html._charref
    counter={'matches':0}
    class Probe:
        pattern=original.pattern
        def sub(self,*args,**kwargs):return original.sub(*args,**kwargs)
        def finditer(self,value):
            for match in original.finditer(value):
                counter['matches']+=1
                yield match
    monkeypatch.setattr(stdlib_html,'_charref',Probe())
    return counter


def test_origin_map_serialized_budget_refuses_before_dense_source_origin_population_is_retained(monkeypatch):
    source=html(prefix='',statute='<p>'+'a&amp;'*200+'</p>')
    raw=source.encode();args=inputs(raw)
    report=views.prepare_official_document_view(raw,limits={'max_report_bytes':12000},**args)
    assert report['status']=='comparison_view_extracted'
    before=deepcopy(report);counter=origin_entity_match_probe(monkeypatch)
    with pytest.raises(views.OfficialDocumentViewError,match='origin observation byte budget'):
        views.prepare_official_document_origin_map(report,raw,expected_view_report_sha256=digest(report),limits={'max_report_bytes':12000},**args)
    assert counter['matches']<200 and report==before


def test_origin_map_producer_pins_are_path_independent_and_rechecked_after_complete_replay(monkeypatch):
    raw,args,report,mapping=origin_fixture(statute='<p>Café duty.</p>')
    pins=mapping['producer_code_pins']
    assert set(pins['source_sha256'])=={'mapping_owner','shared_decoder_owner','stdlib_html','stdlib_html_parser'}
    assert all(len(value)==64 and '/' not in value for value in pins['source_sha256'].values())
    original=views._origin_producer_code_pins;calls={'count':0}
    def changed_after_start():
        result=original();calls['count']+=1
        if calls['count']>1:result['source_sha256']['mapping_owner']='f'*64
        return result
    monkeypatch.setattr(views,'_origin_producer_code_pins',changed_after_start)
    with pytest.raises(views.OfficialDocumentViewError,match='producer code changed'):
        views.prepare_official_document_origin_map(report,raw,expected_view_report_sha256=digest(report),**args)


@pytest.mark.parametrize('damage',['container','string'])
def test_origin_map_caller_payload_bounds_precede_canonical_buffer_and_ignore_offered_looser_limits(monkeypatch,damage):
    def forbidden_wire(_value):
        raise AssertionError('oversized caller payload reached canonical allocation')
    monkeypatch.setattr(views,'_wire',forbidden_wire)
    if damage=='container':
        offered={'output_fragments':[None]*(views.DEFAULT_LIMITS['max_nodes']+1),
            'limits':{'max_nodes':views.DEFAULT_LIMITS['max_nodes']*2}}
    else:
        monkeypatch.setitem(views.DEFAULT_LIMITS,'max_report_bytes',128)
        offered={'note':'x'*129,'limits':{'max_report_bytes':2**62}}
    with pytest.raises(views.OfficialDocumentViewError,match='before serialization'):
        views.official_document_origin_map_sha256(offered)
