"""Independent source fixtures for complete, unselected context inventories."""
from copy import deepcopy
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_parent_parquet_pages as pages
from ipfs_datasets_py.logic.autoformal import legal_parent_text_views as parent_views
from ipfs_datasets_py.logic.autoformal import legal_parent_sentence_candidates as sentences
from ipfs_datasets_py.logic.autoformal import legal_official_document_views as official
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as acquisitions
from ipfs_datasets_py.logic.autoformal import legal_source_view_inventory as document_population
from ipfs_datasets_py.logic.autoformal import legal_parent_source_alignment as alignment
from ipfs_datasets_py.logic.autoformal import legal_candidate_context_inventory as owner


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def fixture(tmp_path, texts=None, bodies=None, *, missing_document=False):
    bodies = ["Café 雪 shall act under section 12.", "Café 雪 shall act under section 12."] if bodies is None else bodies
    texts = [" Header. §1. Heading " + bodies[0] + " Source credit. Editorial Notes " + bodies[0] + " Tail fragment "] if texts is None else texts
    rows = [{"ipfs_cid": "cid:" + str(i), "title_number": "10", "section_number": str(i + 1),
        "law_name": "Heading", "text": text, "subsections_json": '{"(a)":"untrusted notes"}',
        "raw_json": '{"accepted":true}', "parser_warnings": []} for i, text in enumerate(texts)]
    schema = pa.schema([(key, pa.list_(pa.string()) if key == "parser_warnings" else pa.string()) for key in rows[0]])
    path = tmp_path / "parent.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="snappy", data_page_version="1.0", row_group_size=1)
    descriptor = {"repository": "fixture/parent", "revision": "a" * 40, "path_in_repo": path.name,
        "local_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size, "row_count": len(rows), "profile": pages.PARENT_PROFILE}
    preflight = pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=digest(descriptor))
    ordinals = list(range(len(rows))); pins = [digest(row) for row in rows]
    selected = pages.read_selected_parent_rows(descriptor, expected_descriptor_sha256=digest(descriptor),
        preflight_report=preflight, expected_preflight_sha256=digest(preflight), row_ordinals=ordinals, expected_row_sha256s=pins)
    parent_inputs = {"expected_selected_rows_report_sha256": digest(selected), "parent_descriptor": descriptor,
        "expected_parent_descriptor_sha256": digest(descriptor), "preflight_report": preflight,
        "expected_preflight_sha256": digest(preflight), "row_ordinals": ordinals, "expected_row_sha256s": pins}
    parent = parent_views.prepare_parent_text_views(selected, **parent_inputs)
    sentence_inputs = {"expected_parent_text_views_report_sha256": digest(parent), "parent_text_views_inputs": parent_inputs}
    sentence_report = sentences.prepare_parent_sentence_candidates(parent, **sentence_inputs)
    documents = []
    for i, body in enumerate(bodies):
        section = str(i + 1); package = "USCODE-2024-title10"; granule = package + "-chap1-sec" + section
        url = "https://www.govinfo.gov/content/pkg/" + package + "/html/" + granule + ".htm"
        raw = ('<html><head><meta charset="utf-8"><title>Header.</title></head><body>'
            '<!-- field-start:head --><h3 class="section-head">§' + section + '. Heading</h3><!-- field-end:head -->'
            '<!-- field-start:statute --><p class="statutory-body">' + body + '</p><!-- field-end:statute -->'
            '<!-- field-start:sourcecredit --><p>Source credit.</p><!-- field-end:sourcecredit -->'
            '<!-- field-start:notes --><h4 class="note-head">Editorial Notes</h4><p>' + body + '</p><!-- field-end:notes -->'
            '</body></html>').encode()
        acquisition = {"schema": acquisitions.DESCRIPTOR_SCHEMA, "legal_id": "usc:us:10:" + section,
            "edition": 2024, "url": url, "package_id": package, "granule_id": granule,
            "retrieved_at": "2026-10-14T04:00:00Z", "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_bytes": len(raw),
            "http_provenance": {"requested_url": url, "final_url": url, "status_code": 200,
                "content_type": "text/html", "etag": None, "last_modified": None}}
        inputs = {"descriptor": acquisition, "expected_descriptor_sha256": digest(acquisition),
            "expected_raw_sha256": acquisition["raw_sha256"], "expected_raw_bytes": len(raw)}
        body_bytes = None if missing_document else raw
        report = official.prepare_official_document_view(body_bytes, **inputs)
        documents.append({**inputs, "raw_bytes": body_bytes, "view_report": report, "expected_view_report_sha256": digest(report)})
    alignment_inputs = {**sentence_inputs, "document_inputs": documents,
        "expected_document_population_sha256": document_population.view_document_population_sha256(documents)}
    alignment_report = alignment.prepare_parent_source_alignment(parent, **alignment_inputs)
    args = {"expected_sentence_candidates_report_sha256": digest(sentence_report), "sentence_inputs": sentence_inputs,
        "expected_alignment_report_sha256": digest(alignment_report), "alignment_inputs": alignment_inputs}
    return sentence_report, alignment_report, args


def materialize(tmp_path, **options):
    sentence, aligned, args = fixture(tmp_path, **options)
    return owner.prepare_candidate_context_inventory(sentence, aligned, **args), sentence, aligned, args


def resolve_projection(report, reference):
    assert set(reference) == {"schema", "selector_projection_index"}
    assert reference["schema"] == "legal-candidate-context-selector-reference/v1"
    assert type(reference["selector_projection_index"]) is int
    return report["selector_projection_table"][reference["selector_projection_index"]]


def damage_nested_replay(args, damage):
    nested = args["alignment_inputs"]
    if damage == "document_count": nested["document_inputs"] *= 6
    elif damage == "raw_bytes":
        item = nested["document_inputs"][0]
        item["raw_bytes"] = b"x" * (acquisitions.MAX_HTML_BYTES + 1)
        item["expected_raw_bytes"] = len(item["raw_bytes"])
    elif damage == "nested_document_report_bytes":
        nested["document_inputs"][0]["view_report"] = {"oversized": "x" * (owner.DEFAULT_LIMITS["max_input_report_bytes"] + 1)}
    elif damage == "parent_row_population": nested["parent_text_views_inputs"]["row_ordinals"] = list(range(33))
    else:
        deep = None
        for _ in range(80): deep = {"nested": deep}
        if damage == "parent_preflight_depth": nested["parent_text_views_inputs"]["preflight_report"] = deep
        else: nested["document_inputs"][0]["view_report"] = deep


def test_original_characters_all_gaps_boundaries_and_surface_references_are_retained(tmp_path):
    report, sentence, aligned, args = materialize(tmp_path)
    row = report["rows"][0]; original = sentence["rows"][0]
    pieces = row["partition_piece_contexts"]; references = row["surface_reference_contexts"]
    assert [p["original_observation"] for p in pieces] == original["segments"]
    assert [p["original_observation"] for p in references] == original["dependency_candidates"]
    assert "".join(p["original_observation"]["selector"]["text"] for p in pieces) == original["source_text"]
    assert row["original_row_observation"]["boundary_observations"] == original["boundary_observations"]
    assert report["comparison_count"] == 2 and report["official_document_count"] == 2
    assert all(len(p["comparison_contexts"]) == 2 for p in pieces + references)
    assert all(p["authority_ref"] == "report.authority" for p in pieces + references)
    assert report["partition_piece_count"] == sentence["total_segments"]
    assert report["surface_reference_count"] == sentence["total_dependency_candidates"]
    assert report["population_complete"] and report["original_partition_and_references_retained_verbatim"]
    assert owner.candidate_context_inventory_report_sha256(report) == digest(report)
    assert owner.validate_candidate_context_inventory(report, sentence, aligned, expected_report_sha256=digest(report), **args) == report


def test_Unicode_intersections_keep_both_coordinate_owners_without_heading_cropping(tmp_path):
    report, sentence, aligned, _ = materialize(tmp_path)
    original_body = next(p for p in sentence["rows"][0]["segments"] if "Heading Café" in p["selector"]["text"])
    unit = next(p for p in report["rows"][0]["partition_piece_contexts"] if p["source_observation_id"] == original_body["sentence_candidate_id"])
    assert unit["original_observation"] == original_body
    matches = unit["comparison_contexts"][0]["exact_block_intersections"]
    assert any(m["declared_region_kind_observation"] == "statute" for m in matches)
    for match in matches:
        parent, source = resolve_projection(report, match["parent_intersection_selector"]), resolve_projection(report, match["official_intersection_selector"])
        assert parent["selector_schema"] != source["selector_schema"]
        parent_text = report["source_tables"]["parents"][parent["source_ref"]["parent_index"]]["text"]
        source_text = report["source_tables"]["official_documents"][source["source_ref"]["document_index"]]["normalized_text"]
        selected = parent_text[parent["char_start"]:parent["char_end"]]
        assert selected == source_text[source["char_start"]:source["char_end"]]
        assert parent_text.encode()[parent["utf8byte_start"]:parent["utf8byte_end"]].decode() == selected
        assert source_text.encode()[source["utf8_byte_start"]:source["utf8_byte_end"]].decode() == selected
        assert hashlib.sha256(selected.encode()).hexdigest() == parent["text_sha256"] == source["text_sha256"]
        view = aligned["parent_text_views_report"]["views"][0]["text_view"]
        original_parent = parent_views._selector(view, parent["char_start"], parent["char_end"], aligned["parent_text_views_report"]["limits"])
        original_source = official._selector(aligned["official_documents"][source["source_ref"]["document_index"]]["view_report"],
            source["char_start"], source["char_end"])
        assert digest(original_parent) == parent["full_original_selector_sha256"]
        assert digest(original_source) == source["full_original_selector_sha256"]
        assert "text" not in parent and "text" not in source and "authority" not in parent
        assert not match["original_candidate_resegmented"] and not match["legal_region_classification_verified"]
    assert unit["original_observation"]["selector"]["text"].startswith("Heading")


def test_repeated_notes_and_wrong_document_matches_are_all_unselected(tmp_path):
    report, _, _, _ = materialize(tmp_path)
    assert report["alignment_count"] >= 8
    regions = {m["declared_region_kind_observation"] for row in report["rows"] for p in row["partition_piece_contexts"]
        for comparison in p["comparison_contexts"] for m in comparison["exact_block_intersections"]}
    assert {"statute", "editorial_notes"} <= regions
    assert any(p["comparison_contexts"][1]["exact_block_intersections"] for p in report["rows"][0]["partition_piece_contexts"])
    assert all(c["selected_source_occurrence"] is None for p in report["rows"][0]["partition_piece_contexts"] for c in p["comparison_contexts"])
    assert all(flag is False for flag in report["authority"].values())
    assert all(s["status"].startswith("open") and not s["closure_verified"] for p in report["rows"][0]["partition_piece_contexts"] for s in p["context_dependency_slots"])


def test_every_overlapping_exact_block_match_is_preserved(tmp_path):
    report, _, _, _ = materialize(tmp_path, texts=["aaaa"], bodies=["aaa"])
    statute = [a for a in report["alignment_table"] if a["official_block_ref"]["block_index"] == 1]
    assert [a["parent_selector"]["char_start"] for a in statute] == [0, 1]
    assert report["source_block_opportunity_count"] == 2
    contexts = report["rows"][0]["partition_piece_contexts"][0]["comparison_contexts"][0]
    assert len(contexts["exact_block_intersections"]) >= 4
    assert contexts["uncovered_parent_ranges"] == []


def test_uncovered_parent_bytes_and_missing_documents_remain_explicit(tmp_path):
    report, _, _, _ = materialize(tmp_path, missing_document=True)
    assert report["source_block_count"] == report["source_block_opportunity_count"] == report["alignment_count"] == 0
    for unit in report["rows"][0]["partition_piece_contexts"]:
        for comparison in unit["comparison_contexts"]:
            assert len(comparison["uncovered_parent_ranges"]) == 1
            projected, original = resolve_projection(report, comparison["uncovered_parent_ranges"][0]), unit["original_observation"]["selector"]
            assert projected["full_original_selector_sha256"] == digest(original)
            assert all(projected[k] == original[k] for k in ("char_start", "char_end", "utf8byte_start", "utf8byte_end", "text_sha256"))
            assert not comparison["comparison_view_available"]


def test_duplicate_text_rows_keep_distinct_physical_candidate_and_opportunity_identities(tmp_path):
    report, _, _, _ = materialize(tmp_path, texts=["Café 雪 shall act under section 12."] * 2)
    first, second = report["rows"]
    assert first["original_row_observation"]["source_text"] == second["original_row_observation"]["source_text"]
    assert first["partition_piece_contexts"][0]["source_observation_id"] != second["partition_piece_contexts"][0]["source_observation_id"]
    assert first["partition_piece_contexts"][0]["context_unit_id"] != second["partition_piece_contexts"][0]["context_unit_id"]
    assert len({o["opportunity_id"] for o in report["source_block_opportunities"]}) == report["source_block_opportunity_count"]


def test_nontext_parent_row_stays_in_population_with_no_fabricated_context(tmp_path):
    report, sentence, _, _ = materialize(tmp_path, texts=[None, "Available sentence."])
    assert report["parent_row_count"] == 2 and len(report["source_tables"]["parents"]) == 2
    assert report["rows"][0]["partition_piece_contexts"] == report["rows"][0]["surface_reference_contexts"] == []
    assert report["rows"][0]["original_row_observation"]["disposition"] == sentence["rows"][0]["disposition"]


def test_whole_rendered_field_equality_is_retained_as_a_separate_inert_observation(tmp_path):
    text = "Header. §1. Heading Body. Source credit. Editorial Notes Body."
    report, _, _, _ = materialize(tmp_path, texts=[text], bodies=["Body."])
    comparison = report["comparison_table"][0]
    assert comparison["exact_rendered_field_equal"] is True
    rendered = report["source_tables"]["official_documents"][0]["rendered_field_view"]
    assert rendered["text"] == text and rendered["coordinate_origin"] != report["source_tables"]["parents"][0]["coordinate_origin"]
    assert all(flag is False for flag in rendered["authority"].values())
    assert report["paragraph_context_selectors_converted"] is False
    assert all(flag is False for flag in report["authority"].values())


@pytest.mark.parametrize("damage", ["sentence_pin", "alignment_pin", "parent_pin", "document_population_pin", "sentence_extra", "alignment_missing", "different_parent_population"])
def test_independent_complete_input_pins_and_closed_replay_bundles_required(tmp_path, damage):
    sentence, aligned, args = fixture(tmp_path)
    if damage == "sentence_pin": args["expected_sentence_candidates_report_sha256"] = "0" * 64
    elif damage == "alignment_pin": args["expected_alignment_report_sha256"] = "0" * 64
    elif damage == "parent_pin": args["sentence_inputs"]["expected_parent_text_views_report_sha256"] = "0" * 64
    elif damage == "document_population_pin": args["alignment_inputs"]["expected_document_population_sha256"] = "0" * 64
    elif damage == "sentence_extra": args["sentence_inputs"]["validator"] = "untrusted_callback"
    elif damage == "alignment_missing": args["alignment_inputs"].pop("document_inputs")
    else:
        args["sentence_inputs"] = deepcopy(args["sentence_inputs"])
        args["sentence_inputs"]["parent_text_views_inputs"]["row_ordinals"] = []
    with pytest.raises(ValueError): owner.prepare_candidate_context_inventory(sentence, aligned, **args)


@pytest.mark.parametrize("damage", ["drop_piece", "drop_reference", "drop_comparison", "drop_alignment", "retarget_selector"])
def test_resealed_input_omissions_and_retargeting_still_fail_owner_replay(tmp_path, damage):
    sentence, aligned, args = fixture(tmp_path)
    if damage == "drop_piece": sentence["rows"][0]["segments"].pop(0)
    elif damage == "drop_reference": sentence["rows"][0]["dependency_candidates"].pop(0)
    elif damage == "drop_comparison": aligned["rows"][0]["comparisons"].pop(0)
    elif damage == "drop_alignment": aligned["rows"][0]["comparisons"][0]["exact_block_alignments"].pop(0)
    else: aligned["rows"][0]["comparisons"][0]["exact_block_alignments"][0]["parent_selector"]["char_start"] += 1
    args["expected_sentence_candidates_report_sha256"] = digest(sentence)
    args["expected_alignment_report_sha256"] = digest(aligned)
    with pytest.raises(ValueError): owner.prepare_candidate_context_inventory(sentence, aligned, **args)


@pytest.mark.parametrize("damage", ["drop_row", "drop_piece", "drop_reference", "promote", "crop_original", "delete_uncovered"])
def test_resealed_context_output_cannot_drop_population_or_inflate_authority(tmp_path, damage):
    report, sentence, aligned, args = materialize(tmp_path)
    if damage == "drop_row": report["rows"].pop(0)
    elif damage == "drop_piece": report["rows"][0]["partition_piece_contexts"].pop(0)
    elif damage == "drop_reference": report["rows"][0]["surface_reference_contexts"].pop(0)
    elif damage == "promote": report["authority"]["source_semantics_verified"] = True
    elif damage == "crop_original": report["rows"][0]["partition_piece_contexts"][0]["original_observation"]["selector"]["text"] = "cropped"
    else: report["rows"][0]["partition_piece_contexts"][0]["comparison_contexts"][0]["uncovered_parent_ranges"] = []
    with pytest.raises(ValueError): owner.validate_candidate_context_inventory(report, sentence, aligned, expected_report_sha256=digest(report), **args)


@pytest.mark.parametrize("limit", ["max_source_blocks", "max_alignments", "max_partition_pieces", "max_reference_mentions", "max_intersections", "max_uncovered_ranges", "max_input_report_bytes", "max_report_bytes"])
def test_lowered_complete_population_bounds_refuse_without_truncation(tmp_path, limit):
    sentence, aligned, args = fixture(tmp_path)
    with pytest.raises(ValueError): owner.prepare_candidate_context_inventory(sentence, aligned, **args, limits={limit: 1})


@pytest.mark.parametrize("limits", [{"unknown": 1}, {"max_alignments": True}, {"max_alignments": 8193}, {"max_report_bytes": 0}])
def test_unknown_raised_boolean_and_nonpositive_bounds_are_refused(tmp_path, limits):
    sentence, aligned, args = fixture(tmp_path)
    with pytest.raises(ValueError): owner.prepare_candidate_context_inventory(sentence, aligned, **args, limits=limits)


@pytest.mark.parametrize("damage", ["document_count", "raw_bytes", "nested_document_report_bytes", "parent_row_population", "parent_preflight_depth", "nested_document_report_depth"])
def test_nested_replay_population_bytes_and_structure_refused_before_any_deepcopy(tmp_path, monkeypatch, damage):
    sentence, aligned, args = fixture(tmp_path)
    damage_nested_replay(args, damage)
    calls = []
    def snapshot(value):
        calls.append(value)
        raise AssertionError("unqualified nested inputs reached deepcopy")
    monkeypatch.setattr(owner, "deepcopy", snapshot)
    with pytest.raises(ValueError): owner.prepare_candidate_context_inventory(sentence, aligned, **args)
    assert calls == []


@pytest.mark.parametrize("damage", ["parent_byte_geometry", "official_byte_geometry", "parent_source_ref", "full_selector_pin", "uncovered_range"])
def test_compact_projection_tampering_fails_even_after_repairing_projection_and_unit_seals(tmp_path, damage):
    report, sentence, aligned, args = materialize(tmp_path)
    if damage == "uncovered_range":
        unit = next(p for p in report["rows"][0]["partition_piece_contexts"] if p["comparison_contexts"][0]["uncovered_parent_ranges"])
        projection = resolve_projection(report, unit["comparison_contexts"][0]["uncovered_parent_ranges"][0])
        projection["source_ref"]["view_sha256"] = "0" * 64
    else:
        unit = next(p for p in report["rows"][0]["partition_piece_contexts"] if p["comparison_contexts"][0]["exact_block_intersections"])
        match = unit["comparison_contexts"][0]["exact_block_intersections"][0]
        projection = resolve_projection(report, match["official_intersection_selector"] if damage == "official_byte_geometry" else match["parent_intersection_selector"])
        if damage == "parent_byte_geometry": projection["utf8byte_start"] += 1
        elif damage == "official_byte_geometry": projection["utf8_byte_start"] += 1
        elif damage == "parent_source_ref": projection["source_ref"]["parent_index"] = 9
        else: projection["full_original_selector_sha256"] = "0" * 64
    projection["projection_sha256"] = digest({k: v for k, v in projection.items() if k != "projection_sha256"})
    unit["context_unit_id"] = digest({"policy": owner.POLICY, "unit": {k: v for k, v in unit.items() if k != "context_unit_id"}})
    report["context_inventory_sha256"] = digest({k: v for k, v in report.items() if k != "context_inventory_sha256"})
    with pytest.raises(ValueError): owner.validate_candidate_context_inventory(report, sentence, aligned, expected_report_sha256=digest(report), **args)


def test_selector_interning_reuses_exact_geometry_without_omitting_any_reference(tmp_path):
    report, _, _, _ = materialize(tmp_path)
    first = report["rows"][0]["partition_piece_contexts"][0]
    # The same physical leading gap is uncovered in both documents.
    refs = [c["uncovered_parent_ranges"][0] for c in first["comparison_contexts"]]
    assert refs[0] == refs[1]
    assert report["selector_reference_count"] > report["selector_projection_count"]
    assert len({p["projection_sha256"] for p in report["selector_projection_table"]}) == report["selector_projection_count"]
    all_refs = []
    for row in report["rows"]:
        for unit in row["partition_piece_contexts"] + row["surface_reference_contexts"]:
            for comparison in unit["comparison_contexts"]:
                for match in comparison["exact_block_intersections"]:
                    all_refs.extend((match["parent_intersection_selector"], match["official_intersection_selector"]))
                all_refs.extend(comparison["uncovered_parent_ranges"])
    assert len(all_refs) == report["selector_reference_count"]
    assert {r["selector_projection_index"] for r in all_refs} == set(range(report["selector_projection_count"]))


@pytest.mark.parametrize("damage", ["drop", "duplicate", "reorder", "foreign_reference", "boolean_reference"])
def test_resealed_intern_table_and_reference_population_changes_are_refused(tmp_path, damage):
    report, sentence, aligned, args = materialize(tmp_path)
    table = report["selector_projection_table"]
    if damage == "drop": table.pop()
    elif damage == "duplicate": table.append(deepcopy(table[0]))
    elif damage == "reorder": table.reverse()
    else:
        ref = report["rows"][0]["partition_piece_contexts"][0]["comparison_contexts"][0]["uncovered_parent_ranges"][0]
        ref["selector_projection_index"] = True if damage == "boolean_reference" else len(table)
    report["context_inventory_sha256"] = digest({k: v for k, v in report.items() if k != "context_inventory_sha256"})
    with pytest.raises(ValueError): owner.validate_candidate_context_inventory(report, sentence, aligned, expected_report_sha256=digest(report), **args)


def test_intern_cardinality_and_wire_guards_run_before_table_append(tmp_path, monkeypatch):
    _, aligned, _ = fixture(tmp_path)
    parent = aligned["parent_text_views_report"]
    view = parent["views"][0]["text_view"]
    selectors = [parent_views._selector(view, i, i + 1, parent["limits"]) for i in range(4)]
    bounds = dict(owner.DEFAULT_LIMITS, max_intersections=1, max_uncovered_ranges=1)
    pool = owner._ProjectionPool(owner._Budget(bounds))
    for selector in selectors[:3]: pool.reference(selector, parent_index=0)
    calls = []
    def projection(*args, **kwargs): calls.append(1); raise AssertionError("projection beyond cardinality budget")
    monkeypatch.setattr(owner, "_selector_projection", projection)
    with pytest.raises(ValueError): pool.reference(selectors[3], parent_index=0)
    assert calls == [] and len(pool.entries) == 3
    pool = owner._ProjectionPool(owner._Budget(dict(owner.DEFAULT_LIMITS, max_report_bytes=1)))
    monkeypatch.undo()
    with pytest.raises(ValueError): pool.reference(selectors[0], parent_index=0)
    assert pool.entries == [] and pool.by_sha256 == {}
