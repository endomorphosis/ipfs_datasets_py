"""All physical records, parents and literal overlaps survive unreviewed intake."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import zlib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_cache_parent_occurrences as owner
from ipfs_datasets_py.logic.autoformal import legal_parent_parquet_pages as pages
from ipfs_datasets_py.logic.autoformal import legal_parent_text_views as views
from ipfs_datasets_py.logic.autoformal import legal_producer_lineage as legacy
from ipfs_datasets_py.logic.autoformal import legal_producer_page_lineage as lineage
from ipfs_datasets_py.logic.autoformal import legal_span_cache_intake as intake
from ipfs_datasets_py.logic.autoformal import legal_span_provenance as provenance


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value): return hashlib.sha256(wire(value)).hexdigest()


def descriptor(path, **extra):
    return {"repository": "fixture/parent", "revision": "a" * 40, "path_in_repo": path.name,
        "local_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size, **extra}


def fixture(tmp_path, *, cache_change=None, source_text="aa", parent_texts=None, view_ordinals=None):
    parent_texts = parent_texts or ["Prelude aa aaaa. Historical and Revision Notes aa.", "Second aa body."]
    raw_parents = [{"ipfs_cid": "cid:" + str(i), "title_number": "10", "section_number": "1", "text": text,
        "law_name": "body", "unknown_parent": [None, "雪"], "raw_json": '{"text":"WRONG producer segmentation"}',
        "subsections_json": '[{"text":"WRONG"}]'} for i, text in enumerate(parent_texts)]
    parent_path = tmp_path / "laws.parquet"
    pq.write_table(pa.Table.from_pylist(raw_parents), parent_path, compression="snappy", data_page_version="1.0")
    parent = descriptor(parent_path, row_count=len(raw_parents), profile=legacy.PARENT_PROFILE)
    original_rows = [{"source_span_id": "span:" + str(i), "legal_id": "usc:us:10:1", "text": source_text,
        "source_sha256": hashlib.sha256(source_text.encode()).hexdigest(), "entry_cid": "cid:" + str(i),
        "source_section_offset": i, "unknown": {"keep": [None, "雪"]}, "source_parent": {
            "repository_id": parent["repository"], "revision": parent["revision"], "path_in_repo": parent["path_in_repo"],
            "sha256": parent["sha256"], "bytes": parent["bytes"]}} for i in range(len(raw_parents))]
    original = {"schema_version": "legacy-span-cuda-diagnostic/v1", "campaign": {"batch_id": "batch:1"}, "rows": original_rows}
    raw = wire(original); raw_hash = hashlib.sha256(raw).hexdigest()
    original_path = tmp_path / "original.json"; original_path.write_bytes(raw)
    artifact_path = tmp_path / "artifacts.parquet"
    pq.write_table(pa.Table.from_pylist([{"artifact_sha256": raw_hash, "kind": "original_producer_receipt", "encoding": "zlib-json/v1",
        "decoded_bytes": len(raw), "payload": zlib.compress(raw)}], schema=pa.schema([
        ("artifact_sha256", pa.string()), ("kind", pa.string()), ("encoding", pa.string()),
        ("decoded_bytes", pa.int64()), ("payload", pa.binary())])), artifact_path)
    report_descriptor = {"profile": legacy.REPORT_PROFILE, "local_path": str(original_path), "sha256": raw_hash, "bytes": len(raw),
        "origin": {"container": descriptor(artifact_path), "artifact_row_ordinal": 0, "artifact_sha256": raw_hash}}
    caches = [{"schema_version": "uscode-paired-span-census/v1", "source": {"span_id": r["source_span_id"],
        "legal_id": r["legal_id"], "text": r["text"], "text_sha256": r["source_sha256"], "revision": "observed-short"},
        "source_target_artifact_sha256": raw_hash, "source_target_artifact_pointer": f"/rows/{i}/logic_target_observation",
        "provenance": {"batch_id": "batch:1"}, "admitted": True, "formalized": True,
        "autoencoder": {"complete": True, "model_identity": "legacy-mock-diagnostic", "formal_outputs": [{"target_conditioned": True}]},
        "unknown_cache": {"keep": [None, "雪", False]}} for i, r in enumerate(original_rows)]
    if cache_change: cache_change(caches)
    source = tmp_path / "catalog.py"
    source.write_text("raise RuntimeError('must not execute')\ndef literals():\n    rows = (('different','usc:us:9:9','Authored literal.'),)\n    return rows\n")
    function = ast.parse(source.read_bytes()).body[1]
    pins = [{"source_id": "fixture:authored", "path": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "function_name": "literals", "function_ast_sha256": hashlib.sha256(ast.dump(function, include_attributes=False).encode()).hexdigest(),
        "projection_profile": provenance.PROJECTION_PROFILE}]
    catalog = provenance.catalog_from_sources(pins)
    cache = {"repository": "fixture/cache", "revision": "b" * 40, "artifact_sha256": "c" * 64}
    record_pins = [intake.record_sha256(row, ordinal=11 + i, cache_identity=cache) for i, row in enumerate(caches)]
    observed = provenance.reconcile_span_provenance(caches, cache_identity=cache, start_ordinal=11,
        expected_row_sha256s=[intake.row_sha256(row) for row in caches], expected_record_sha256s=record_pins,
        demonstration_catalog=catalog, expected_catalog_sha256=digest(catalog), expected_catalog_source_pins=pins)
    ordinals = list(range(len(raw_parents))); row_pins = [digest(row) for row in raw_parents]
    preflight = pages.preflight_parent_pages(parent, expected_descriptor_sha256=digest(parent))
    selected = pages.read_selected_parent_rows(parent, expected_descriptor_sha256=digest(parent), preflight_report=preflight,
        expected_preflight_sha256=digest(preflight), row_ordinals=ordinals, expected_row_sha256s=row_pins)
    page_inputs = [{"descriptor_sha256": digest(parent), "preflight_report": preflight, "expected_preflight_sha256": digest(preflight),
        "row_report": selected, "expected_row_report_sha256": digest(selected)}]
    manifest = {"schema": legacy.MANIFEST_SCHEMA, "reports": [report_descriptor],
        "parents": [{"descriptor": parent, "row_ordinals": ordinals, "expected_row_sha256s": row_pins}],
        "records": [{"record_sha256": pin, "report_sha256s": [raw_hash]} for pin in record_pins]}
    lineage_inputs = {"expected_provenance_report_sha256s": [digest(observed)], "expected_record_sha256s": record_pins,
        "witness_manifest": manifest, "expected_witness_manifest_sha256": digest(manifest),
        "parent_page_inputs": page_inputs, "expected_parent_page_inputs_sha256": digest(page_inputs)}
    chain = lineage.reconcile_producer_page_lineage([observed], **lineage_inputs)
    view_ordinals = ordinals if view_ordinals is None else view_ordinals
    if view_ordinals != ordinals:
        selected = pages.read_selected_parent_rows(parent, expected_descriptor_sha256=digest(parent), preflight_report=preflight,
            expected_preflight_sha256=digest(preflight), row_ordinals=view_ordinals, expected_row_sha256s=[row_pins[i] for i in view_ordinals])
    view_inputs = {"expected_selected_rows_report_sha256": digest(selected), "parent_descriptor": parent,
        "expected_parent_descriptor_sha256": digest(parent), "preflight_report": preflight, "expected_preflight_sha256": digest(preflight),
        "row_ordinals": view_ordinals, "expected_row_sha256s": [row_pins[i] for i in view_ordinals]}
    parent_views = views.prepare_parent_text_views(selected, **view_inputs)
    args = {"expected_provenance_report_sha256s": [digest(observed)], "expected_record_sha256s": record_pins,
        "expected_lineage_report_sha256": digest(chain), "lineage_inputs": lineage_inputs,
        "expected_parent_text_views_report_sha256": digest(parent_views), "parent_text_views_inputs": view_inputs}
    return [observed], chain, parent_views, args


def run(inputs): return owner.prepare_cache_parent_occurrences(*inputs[:3], **inputs[3])


def test_all_views_all_overlaps_same_legal_ids_and_prior_local_declarations_retained(tmp_path):
    inputs = fixture(tmp_path); report = run(inputs)
    assert report["row_count"] == 2 and [row["row_ordinal"] for row in report["rows"]] == [11, 12]
    assert report["exact_occurrence_count"] == 12
    assert report["prior_lineage_status_counts"] == {"verified_local_report_parent_declarations_only": 2}
    for i, row in enumerate(report["rows"]):
        assert row["raw_row"] == inputs[0][0]["rows"][i]["raw_row"]
        assert row["local_parent_reference_view_indices"] == [i]
        assert [c["occurrence_count"] for c in row["comparison_views"]] == [5, 1]
        assert len(row["comparison_views"]) == 2 and all(c["literal_legal_id_matches"] for c in row["comparison_views"])
        assert row["selected_occurrence"] is None and row["governing_source_binding"] is None
        assert row["raw_row"]["admitted"] is True and row["raw_row"]["autoencoder"]["formal_outputs"][0]["target_conditioned"] is True
        assert all(value is False for value in row["authority"].values())
        assert all(not item["selected"] for c in row["comparison_views"] for item in c["occurrences"])
    starts = [item["selector"]["char_start"] for item in report["rows"][0]["comparison_views"][0]["occurrences"]]
    assert any(b - a == 1 for a, b in zip(starts, starts[1:]))
    assert all(r["region_kind"] == "entire_text_unclassified" for c in report["rows"][0]["comparison_views"] for o in c["occurrences"] for r in o["region_intersections"]["regions"])
    assert owner.cache_parent_occurrences_report_sha256(report) == digest(report)
    assert owner.validate_cache_parent_occurrences(report, *inputs[:3], expected_report_sha256=digest(report), **inputs[3])["valid"]


@pytest.mark.parametrize("damage", ["missing_legal_id", "different_legal_id", "wrong_source_hash", "missing_source_hash"])
def test_legacy_identity_or_hash_declarations_never_filter_custodied_literal_observations(tmp_path, damage):
    def change(rows):
        if damage == "missing_legal_id": rows[0]["source"]["legal_id"] = None
        elif damage == "different_legal_id": rows[0]["source"]["legal_id"] = "usc:us:99:99"
        elif damage == "wrong_source_hash": rows[0]["source"]["text_sha256"] = "0" * 64
        else: rows[0]["source"].pop("text_sha256")
    report = run(fixture(tmp_path, cache_change=change)); row = report["rows"][0]
    assert len(row["comparison_views"]) == 2 and row["exact_occurrence_count"] == 6
    if "legal_id" in damage: assert not any(c["literal_legal_id_matches"] for c in row["comparison_views"])
    else: assert row["status"] == "source_text_hash_mismatch" and row["source_text_sha256_matches_raw_declaration"] is False
    assert row["prior_lineage_status"] == "unresolved" and all(value is False for value in row["authority"].values())


def test_unicode_original_byte_coordinates_are_exact_without_normalization(tmp_path):
    inputs = fixture(tmp_path, source_text="é", parent_texts=["雪 é e\u0301 é.", "é."])
    report = run(inputs); observations = report["rows"][0]["comparison_views"][0]["occurrences"]
    assert len(observations) == 2
    text = inputs[2]["views"][0]["text_view"]["text"]
    for item in observations:
        s = item["selector"]
        assert s["text"] == "é" and text[s["char_start"]:s["char_end"]] == "é"
        assert text.encode()[s["utf8byte_start"]:s["utf8byte_end"]].decode() == "é"
    assert observations[0]["selector"]["utf8byte_start"] != observations[0]["selector"]["char_start"]


def test_repeated_raw_presentations_keep_distinct_physical_records(tmp_path):
    report = run(fixture(tmp_path, cache_change=lambda rows: rows.__setitem__(1, deepcopy(rows[0]))))
    assert report["rows"][0]["raw_row_sha256"] == report["rows"][1]["raw_row_sha256"]
    assert len({row["record_sha256"] for row in report["rows"]}) == 2
    assert report["exact_occurrence_count"] == 12 and report["row_count"] == 2


def test_missing_declared_parent_view_is_named_without_erasing_local_chain_truth(tmp_path):
    report = run(fixture(tmp_path, view_ordinals=[1]))
    first, second = report["rows"]
    assert first["prior_lineage_status"] == second["prior_lineage_status"] == "verified_local_report_parent_declarations_only"
    assert first["local_parent_reference_view_indices"] == [] and second["local_parent_reference_view_indices"] == [0]
    assert "verified_local_parent_reference_comparison_view_missing_or_multiple" in {issue["code"] for issue in first["issues"]}
    assert first["exact_occurrence_count"] == 1 and first["selected_occurrence"] is None


@pytest.mark.parametrize("damage", ["outer_records", "outer_provenance", "chain_pin", "views_pin", "view_order", "drop_view", "raw_unknown", "ordinal"])
def test_independent_complete_external_pins_reject_population_or_coordinate_changes(tmp_path, damage):
    observed, chain, parent_views, args = fixture(tmp_path)
    if damage == "outer_records": args["expected_record_sha256s"] = list(reversed(args["expected_record_sha256s"]))
    elif damage == "outer_provenance": args["expected_provenance_report_sha256s"][0] = "0" * 64
    elif damage == "chain_pin": args["expected_lineage_report_sha256"] = "0" * 64
    elif damage == "views_pin": args["expected_parent_text_views_report_sha256"] = "0" * 64
    elif damage == "view_order": parent_views["views"].reverse(); args["expected_parent_text_views_report_sha256"] = digest(parent_views)
    elif damage == "drop_view": parent_views["views"].pop(); args["expected_parent_text_views_report_sha256"] = digest(parent_views)
    elif damage == "raw_unknown": observed[0]["rows"][0]["raw_row"]["unknown_cache"]["keep"].append("changed")
    else: parent_views["views"][0]["row_ordinal"] += 1; args["expected_parent_text_views_report_sha256"] = digest(parent_views)
    with pytest.raises(ValueError): owner.prepare_cache_parent_occurrences(observed, chain, parent_views, **args)


@pytest.mark.parametrize("damage", ["missing", "extra", "callback", "population_callback"])
def test_closed_replay_inputs_never_admit_bare_seals_or_custom_readers(tmp_path, damage):
    inputs = fixture(tmp_path); args = inputs[3]
    if damage == "missing": args["lineage_inputs"].pop("witness_manifest")
    elif damage == "extra": args["parent_text_views_inputs"]["expected_report_sha256"] = "0" * 64
    elif damage == "callback": args["lineage_inputs"]["loader"] = lambda: pytest.fail("must not run")
    else: args["parent_text_views_inputs"]["loader"] = lambda: pytest.fail("must not run")
    with pytest.raises(ValueError): run(inputs)


@pytest.mark.parametrize("limit,value", [("max_occurrences", 3), ("max_source_characters", 5), ("max_report_bytes", 128), ("max_parent_views", 1), ("max_records", 1)])
def test_bounds_refuse_complete_population_instead_of_partial_or_easy_selection(tmp_path, limit, value):
    inputs = fixture(tmp_path); inputs[3]["limits"] = {limit: value}
    with pytest.raises(ValueError): run(inputs)


@pytest.mark.parametrize("damage", ["occurrence", "drop_row", "promote", "select", "reference"])
def test_resealed_output_cannot_replace_fixed_full_regeneration(tmp_path, damage):
    inputs = fixture(tmp_path); report = run(inputs); original_pin = digest(report)
    if damage == "occurrence": report["rows"][0]["comparison_views"][0]["occurrences"].pop()
    elif damage == "drop_row": report["rows"].pop()
    elif damage == "promote": report["rows"][0]["authority"]["admitted"] = True
    elif damage == "select": report["rows"][0]["selected_occurrence"] = report["rows"][0]["comparison_views"][0]["occurrences"][0]
    else: report["rows"][0]["local_parent_reference_view_indices"] = [1]
    report["occurrences_sha256"] = digest({k: v for k, v in report.items() if k != "occurrences_sha256"})
    with pytest.raises(ValueError): owner.validate_cache_parent_occurrences(report, *inputs[:3], expected_report_sha256=original_pin, **inputs[3])
    with pytest.raises(ValueError): owner.validate_cache_parent_occurrences(report, *inputs[:3], expected_report_sha256=digest(report), **inputs[3])
