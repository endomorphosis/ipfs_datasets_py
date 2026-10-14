"""Fixed page-owner replay cannot turn injected inventories into lineage proof."""
import ast
from copy import deepcopy
import hashlib
import json
import zlib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_parent_parquet_pages as pages
from ipfs_datasets_py.logic.autoformal import legal_producer_lineage as legacy
from ipfs_datasets_py.logic.autoformal import legal_producer_page_lineage as owner
from ipfs_datasets_py.logic.autoformal import legal_span_cache_intake as intake
from ipfs_datasets_py.logic.autoformal import legal_span_provenance as provenance


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def descriptor(path, **extra):
    return {"repository": "fixture/parent", "revision": "a" * 40, "path_in_repo": path.name,
        "local_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size, **extra}


def fixture(tmp_path, *, parent_text_repeat=1):
    parent_rows = [{"ipfs_cid": "cid:0", "title_number": "10", "section_number": "1", "text": "Original café parent." * parent_text_repeat, "unknown": [None, "雪"]},
                   {"ipfs_cid": "cid:1", "title_number": "10", "section_number": "2", "text": "Other physical parent." * parent_text_repeat, "unknown": []}]
    path = tmp_path / "laws.parquet"
    pq.write_table(pa.Table.from_pylist(parent_rows), path, compression="snappy", data_page_version="1.0")
    parent = descriptor(path, row_count=2, profile=legacy.PARENT_PROFILE)
    declared_rows = [{"source_span_id": "span:" + str(i), "legal_id": "usc:us:10:" + str(i + 1), "text": "Proposed café span " + str(i),
        "source_sha256": hashlib.sha256(("Proposed café span " + str(i)).encode()).hexdigest(), "entry_cid": "cid:" + str(i),
        "source_section_offset": i, "unknown": {"retain": [None, "雪"]}, "source_parent": {
            "repository_id": parent["repository"], "revision": parent["revision"], "path_in_repo": parent["path_in_repo"],
            "sha256": parent["sha256"], "bytes": parent["bytes"]}} for i in range(2)]
    original = {"schema_version": "legacy-span-cuda-diagnostic/v1", "campaign": {"batch_id": "batch:1"}, "rows": declared_rows}
    raw = wire(original); raw_hash = hashlib.sha256(raw).hexdigest()
    original_path = tmp_path / "original.json"; original_path.write_bytes(raw)
    artifact_path = tmp_path / "artifacts.parquet"
    artifact = {"artifact_sha256": raw_hash, "kind": "original_producer_receipt", "encoding": "zlib-json/v1",
        "decoded_bytes": len(raw), "payload": zlib.compress(raw)}
    pq.write_table(pa.Table.from_pylist([artifact], schema=pa.schema([
        ("artifact_sha256", pa.string()), ("kind", pa.string()), ("encoding", pa.string()),
        ("decoded_bytes", pa.int64()), ("payload", pa.binary())])), artifact_path)
    report_descriptor = {"profile": legacy.REPORT_PROFILE, "local_path": str(original_path), "sha256": raw_hash, "bytes": len(raw),
        "origin": {"container": descriptor(artifact_path), "artifact_row_ordinal": 0, "artifact_sha256": raw_hash}}
    rows = [{"schema_version": "uscode-paired-span-census/v1", "source": {"span_id": r["source_span_id"],
        "legal_id": r["legal_id"], "text": r["text"], "text_sha256": r["source_sha256"], "revision": "observed-short"},
        "provenance": {"batch_id": "batch:1"}, "source_target_artifact_sha256": raw_hash,
        "source_target_artifact_pointer": "/rows/" + str(i) + "/logic_target_observation",
        "model_invocation": {"declared_complete": True}, "admitted": True} for i, r in enumerate(declared_rows)]
    source = tmp_path / "catalog.py"; source.write_text("def literals():\n    rows = (('unrelated','usc:us:9:9','Authored literal.'),)\n    return rows\n")
    function = ast.parse(source.read_bytes()).body[0]
    source_pins = [{"source_id": "fixture:authored", "path": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "function_name": "literals", "function_ast_sha256": hashlib.sha256(ast.dump(function, include_attributes=False).encode()).hexdigest(),
        "projection_profile": provenance.PROJECTION_PROFILE}]
    catalog = provenance.catalog_from_sources(source_pins)
    cache = {"repository": "fixture/cache", "revision": "b" * 40, "artifact_sha256": "c" * 64}
    record_pins = [intake.record_sha256(row, ordinal=i, cache_identity=cache) for i, row in enumerate(rows)]
    observed = provenance.reconcile_span_provenance(rows, cache_identity=cache,
        expected_row_sha256s=[intake.row_sha256(row) for row in rows], expected_record_sha256s=record_pins,
        demonstration_catalog=catalog, expected_catalog_sha256=digest(catalog), expected_catalog_source_pins=source_pins)
    manifest = {"schema": legacy.MANIFEST_SCHEMA, "reports": [report_descriptor],
        "parents": [{"descriptor": parent, "row_ordinals": [0, 1], "expected_row_sha256s": [digest(r) for r in parent_rows]}],
        "records": [{"record_sha256": pin, "report_sha256s": [raw_hash]} for pin in record_pins]}
    common = {"expected_provenance_report_sha256s": [digest(observed)], "expected_record_sha256s": record_pins,
        "witness_manifest": manifest, "expected_witness_manifest_sha256": digest(manifest)}
    preflight = pages.preflight_parent_pages(parent, expected_descriptor_sha256=digest(parent))
    row_report = pages.read_selected_parent_rows(parent, expected_descriptor_sha256=digest(parent), preflight_report=preflight,
        expected_preflight_sha256=digest(preflight), row_ordinals=[0, 1], expected_row_sha256s=[digest(r) for r in parent_rows])
    page_inputs = [{"descriptor_sha256": digest(parent), "preflight_report": preflight, "expected_preflight_sha256": digest(preflight),
        "row_report": row_report, "expected_row_report_sha256": digest(row_report)}]
    return [observed], {**common, "parent_page_inputs": page_inputs, "expected_parent_page_inputs_sha256": digest(page_inputs)}, common


def reseal_inputs(args):
    args["expected_parent_page_inputs_sha256"] = digest(args["parent_page_inputs"])


def test_fixed_pagewise_parent_replay_creates_new_unaccepted_schema_without_v1_reinterpretation(tmp_path):
    observed, args, common = fixture(tmp_path)
    before = legacy.reconcile_producer_lineage(observed, **common)
    report = owner.reconcile_producer_page_lineage(observed, **args)
    assert report["schema"] == owner.SCHEMA and report["parent_profile"] == "pagewise_v2"
    assert "lineage_sha256" not in report and "page_lineage_sha256" in report
    assert report["rows"] == before["rows"] and report["status_counts"] == {"verified_local_report_parent_declarations_only": 2}
    assert report["parent_page_input_population"]["inputs"] == args["parent_page_inputs"]
    assert report["historical_v1_report_reinterpreted"] is False
    assert all(value is False for row in report["rows"] for value in row["authority"].values())
    assert all(row["selected_original_occurrence"] is None and row["governing_source_binding"] is None for row in report["rows"])
    assert legacy.reconcile_producer_lineage(observed, **common) == before
    assert digest(report) == owner.producer_page_lineage_report_sha256(report)
    assert owner.validate_producer_page_lineage(report, observed, expected_report_sha256=digest(report), **args)["valid"]


def test_new_page_profile_does_not_weaken_old_group_guard_or_accept_public_callbacks(tmp_path, monkeypatch):
    observed, args, common = fixture(tmp_path, parent_text_repeat=1024)
    manifest = common["witness_manifest"]
    artifact = pq.ParquetFile(manifest["reports"][0]["origin"]["container"]["local_path"])
    parent = pq.ParquetFile(manifest["parents"][0]["descriptor"]["local_path"])
    artifact_bound = max(artifact.metadata.row_group(i).total_byte_size for i in range(artifact.metadata.num_row_groups))
    parent_bound = max(parent.metadata.row_group(i).total_byte_size for i in range(parent.metadata.num_row_groups))
    assert artifact_bound + 1 < parent_bound
    # The legacy bound is shared with receipt containers. Admit that independent
    # receipt while refusing this larger parent group before Arrow batch decode.
    monkeypatch.setattr(legacy, "MAX_PARQUET_GROUP_UNCOMPRESSED_BYTES", artifact_bound + 1)
    old = legacy.reconcile_producer_lineage(observed, **common)
    assert old["status_counts"] == {"unresolved": 2}
    new = owner.reconcile_producer_page_lineage(observed, **args)
    assert new["status_counts"] == {"verified_local_report_parent_declarations_only": 2}
    with pytest.raises(TypeError): legacy.reconcile_producer_lineage(observed, parent_profile="pagewise_v2", **common)
    with pytest.raises(TypeError): owner.reconcile_producer_page_lineage(observed, reader=lambda: "unverified", **args)


@pytest.mark.parametrize("damage", ["population_pin", "missing", "extra", "descriptor", "unknown_field", "callback", "preflight_pin", "row_pin"])
def test_independent_complete_closed_page_population_and_full_pins_reject_injection(tmp_path, damage):
    observed, args, _ = fixture(tmp_path)
    item = args["parent_page_inputs"][0]
    if damage == "population_pin": args["expected_parent_page_inputs_sha256"] = "0" * 64
    elif damage == "missing": args["parent_page_inputs"] = []
    elif damage == "extra": args["parent_page_inputs"].append(deepcopy(item))
    elif damage == "descriptor": item["descriptor_sha256"] = "0" * 64
    elif damage == "unknown_field": item["trusted"] = True
    elif damage == "callback": item["reader"] = "arbitrary-loader"
    elif damage == "preflight_pin": item["expected_preflight_sha256"] = "0" * 64
    else: item["expected_row_report_sha256"] = "0" * 64
    if damage != "population_pin": reseal_inputs(args)
    with pytest.raises(ValueError): owner.reconcile_producer_page_lineage(observed, **args)


@pytest.mark.parametrize("damage", ["raw_unknown", "drop_row", "row_order", "authority", "geometry", "page_unknown"])
def test_self_resealed_page_reports_still_require_fixed_owner_regeneration(tmp_path, damage):
    observed, args, _ = fixture(tmp_path)
    item = args["parent_page_inputs"][0]
    row_report = item["row_report"]
    if damage == "raw_unknown": row_report["rows"][0]["raw_row"]["unknown"] = ["forged"]
    elif damage == "drop_row": row_report["rows"].pop()
    elif damage == "row_order": row_report["rows"].reverse()
    elif damage == "authority": row_report["authority"][next(iter(row_report["authority"]))] = True
    elif damage == "geometry": row_report["rows"][0]["row_group_ordinal"] += 1
    else: item["preflight_report"]["invented_page_acceptance"] = True
    item["expected_preflight_sha256"] = digest(item["preflight_report"])
    item["expected_row_report_sha256"] = digest(row_report)
    reseal_inputs(args)
    with pytest.raises(ValueError): owner.reconcile_producer_page_lineage(observed, **args)


@pytest.mark.parametrize("damage", ["parent_order", "parent_row_hash", "record_order", "provenance_pin"])
def test_original_manifest_hash_order_and_physical_cache_population_still_apply(tmp_path, damage):
    observed, args, _ = fixture(tmp_path)
    if damage == "parent_order": args["witness_manifest"]["parents"][0]["row_ordinals"].reverse()
    elif damage == "parent_row_hash": args["witness_manifest"]["parents"][0]["expected_row_sha256s"].reverse()
    elif damage == "record_order": args["expected_record_sha256s"].reverse()
    else: args["expected_provenance_report_sha256s"][0] = "0" * 64
    args["expected_witness_manifest_sha256"] = digest(args["witness_manifest"])
    with pytest.raises(ValueError): owner.reconcile_producer_page_lineage(observed, **args)


@pytest.mark.parametrize("damage", ["schema", "profile", "authority", "drop_row", "unknown", "seal"])
def test_new_full_report_pin_and_regeneration_both_reject_authority_or_population_forgery(tmp_path, damage):
    observed, args, _ = fixture(tmp_path)
    report = owner.reconcile_producer_page_lineage(observed, **args)
    external = digest(report)
    if damage == "schema": report["schema"] = legacy.SCHEMA
    elif damage == "profile": report["parent_profile"] = "legacy_v1"
    elif damage == "authority": report["authority"]["historical_job_lineage_verified"] = True
    elif damage == "drop_row": report["rows"].pop()
    elif damage == "unknown": report["training_approved"] = True
    else: report["page_lineage_sha256"] = "0" * 64
    with pytest.raises(ValueError): owner.validate_producer_page_lineage(report, observed, expected_report_sha256=external, **args)
    with pytest.raises(ValueError): owner.validate_producer_page_lineage(report, observed, expected_report_sha256=digest(report), **args)


def test_aggregate_page_inputs_rejected_before_snapshot_copy(tmp_path, monkeypatch):
    observed, args, _ = fixture(tmp_path)
    monkeypatch.setattr(owner, "MAX_PARENT_INPUT_BYTES", 1)
    monkeypatch.setattr(owner, "deepcopy", lambda *_: pytest.fail("copied unbounded page population"))
    with pytest.raises(ValueError): owner.reconcile_producer_page_lineage(observed, **args)
