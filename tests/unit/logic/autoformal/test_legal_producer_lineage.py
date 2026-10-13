"""Exact producer declarations are bounded observations, never legal authority."""
import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import zlib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_producer_lineage as lineage
from ipfs_datasets_py.logic.autoformal import legal_span_cache_intake as intake
from ipfs_datasets_py.logic.autoformal import legal_span_provenance as provenance


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def descriptor(path, **extra):
    return {"repository": "fixture/source", "revision": "b" * 40,
        "path_in_repo": path.name, "local_path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size, **extra}


def provenance_inputs(tmp_path, rows, *, authored=False):
    values = [(rows[0]["source"]["span_id"], rows[0]["source"]["legal_id"], rows[0]["source"]["text"])] if authored else [("unrelated", "usc:us:9:9", "Unrelated text.")]
    text = "raise RuntimeError('never execute')\ndef examples():\n    rows = " + repr(tuple(values)) + "\n    return rows\n"
    source = tmp_path / "catalog.py"; source.write_text(text)
    function = ast.parse(text).body[1]
    pins = [{"source_id": "fixture:authored", "path": str(source), "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "function_name": "examples", "function_ast_sha256": hashlib.sha256(ast.dump(function, include_attributes=False).encode()).hexdigest(),
        "projection_profile": provenance.PROJECTION_PROFILE}]
    catalog = provenance.catalog_from_sources(pins)
    cache = {"repository": "fixture/cache", "revision": "a" * 40, "artifact_sha256": "c" * 64}
    args = {"cache_identity": cache, "start_ordinal": 13,
        "expected_row_sha256s": [intake.row_sha256(row) for row in rows],
        "expected_record_sha256s": [intake.record_sha256(row, ordinal=13 + i, cache_identity=cache) for i, row in enumerate(rows)],
        "demonstration_catalog": catalog, "expected_catalog_sha256": digest(catalog), "expected_catalog_source_pins": pins}
    return provenance.reconcile_span_provenance(rows, **args)


def fixture(tmp_path, *, producer_change=None, parent_change=None, cache_change=None,
            authored=False, raw_report=None, duplicate_artifact=False, artifact_kind="original_producer_receipt"):
    parents = [{"ipfs_cid": "cid:0", "title_number": "10", "section_number": "1", "text": "§1 Café shall retain notice.\nNotes: 雪",
                "unknown_parent": ["é", None]},
               {"ipfs_cid": "cid:1", "title_number": "10", "section_number": "2", "text": "A second duty.", "unknown_parent": ["other"]}]
    if parent_change: parent_change(parents)
    path = tmp_path / "laws.parquet"; pq.write_table(pa.Table.from_pylist(parents), path, row_group_size=1)
    parent = descriptor(path, row_count=2, profile=lineage.PARENT_PROFILE)
    inventory = lineage.read_parent_row_witnesses(parent, expected_descriptor_sha256=digest(parent), row_ordinals=[0, 1])
    rows = []
    for i in range(2):
        text = "Agency shall retain café notice. 雪" if i == 0 else "A second duty."
        rows.append({"source_span_id": "span:" + str(i), "legal_id": "usc:us:10:" + str(i + 1),
            "text": text, "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "entry_cid": "cid:" + str(i),
            "source_section_offset": i, "unknown_producer": {"keep": [None, "雪", True]},
            "source_parent": {"repository_id": parent["repository"], "revision": parent["revision"],
                "path_in_repo": parent["path_in_repo"], "sha256": parent["sha256"], "bytes": parent["bytes"],
                "release_id": "ipfs-uscode-short"}})
    if producer_change: producer_change(rows)
    original = {"schema_version": "legacy-span-cuda-diagnostic/v1", "campaign": {"batch_id": "batch:0"},
        "rows": rows, "unknown_top_level": {"retain": "é and 雪"}}
    payload = wire(original) if raw_report is None else raw_report
    raw_sha = hashlib.sha256(payload).hexdigest()
    raw_path = tmp_path / "original.json"; raw_path.write_bytes(payload)
    artifact = {"artifact_sha256": raw_sha, "kind": artifact_kind, "encoding": "zlib-json/v1",
        "decoded_bytes": len(payload), "payload": zlib.compress(payload)}
    schema = pa.schema([("artifact_sha256", pa.string()), ("kind", pa.string()), ("encoding", pa.string()),
        ("decoded_bytes", pa.int64()), ("payload", pa.binary())])
    artifact_path = tmp_path / "artifacts.parquet"
    pq.write_table(pa.Table.from_pylist([artifact] * (2 if duplicate_artifact else 1), schema=schema), artifact_path)
    report_descriptor = {"profile": lineage.REPORT_PROFILE, "local_path": str(raw_path), "sha256": raw_sha, "bytes": len(payload),
        "origin": {"container": descriptor(artifact_path), "artifact_row_ordinal": 0, "artifact_sha256": raw_sha}}
    caches = [{"schema_version": "uscode-paired-span-census/v1",
        "source": {"span_id": row["source_span_id"], "legal_id": row["legal_id"], "text": row["text"],
            "text_sha256": row["source_sha256"], "revision": "ipfs-uscode-short"},
        "source_target_artifact_sha256": raw_sha, "source_target_artifact_pointer": f"/rows/{i}/logic_target_observation",
        "provenance": {"batch_id": "batch:0"}, "autoencoder": {"model_identity": "legacy-mock-diagnostic", "complete": True},
        "admitted": True, "formalized": True, "unknown_cache": {"keep": ["雪", None, True]}}
        for i, row in enumerate(rows)]
    if cache_change: cache_change(caches)
    observed = provenance_inputs(tmp_path, caches, authored=authored)
    ids = [row["record_sha256"] for row in observed["rows"]]
    manifest = {"schema": lineage.MANIFEST_SCHEMA, "reports": [report_descriptor],
        "parents": [{"descriptor": parent, "row_ordinals": [0, 1],
            "expected_row_sha256s": [row["raw_row_sha256"] for row in inventory["rows"]]}],
        "records": [{"record_sha256": pin, "report_sha256s": [raw_sha]} for pin in ids]}
    args = {"expected_provenance_report_sha256s": [provenance.provenance_report_sha256(observed)],
        "expected_record_sha256s": ids, "witness_manifest": manifest, "expected_witness_manifest_sha256": digest(manifest)}
    return [observed], args, original, inventory


def reconcile(observed, args):
    return lineage.reconcile_producer_lineage(observed, **args)


def reseal(args):
    args["expected_witness_manifest_sha256"] = digest(args["witness_manifest"])


def codes(row):
    return {issue["code"] for issue in row["issues"]}


def test_exact_local_declarations_preserve_unknowns_unicode_and_no_authority(tmp_path):
    observed, args, original, inventory = fixture(tmp_path)
    report = reconcile(observed, args)
    assert report["status_counts"] == {"verified_local_report_parent_declarations_only": 2}
    assert report["parent_row_inventories"][0] == inventory
    assert report["row_count"] == 2 and report["population_complete"] is True
    for row, source in zip(report["rows"], observed[0]["rows"], strict=True):
        assert row["raw_row"] == source["raw_row"]
        assert row["source_identity"]["declared_revision"] == "ipfs-uscode-short"
        assert row["revision_equivalence_inferred"] is False
        assert row["selected_original_occurrence"] is None and row["governing_source_binding"] is None
        assert all(v is False for v in row["authority"].values())
    assert all(v is False for v in report["authority"].values())
    assert report["rows"][0]["producer_row_witness"]["complete_row_sha256"] == digest(original["rows"][0])
    assert lineage.validate_producer_lineage(report, observed, expected_report_sha256=digest(report), **args)["valid"] is True


@pytest.mark.parametrize("damage", ["row_order", "drop", "cache_sha", "unknown_raw", "ordinal", "source_projection", "provenance_pin", "record_pin", "manifest_pin"])
def test_independent_population_and_full_external_pins_reject_retargeting(tmp_path, damage):
    observed, args, _, _ = fixture(tmp_path)
    if damage == "row_order": observed[0]["rows"].reverse()
    elif damage == "drop": observed[0]["rows"].pop()
    elif damage == "cache_sha": observed[0]["cache_identity"]["artifact_sha256"] = "0" * 64
    elif damage == "unknown_raw": observed[0]["rows"][0]["raw_row"]["unknown_cache"]["keep"].append("changed")
    elif damage == "ordinal": observed[0]["rows"][0]["row_ordinal"] += 1
    elif damage == "source_projection": observed[0]["rows"][0]["source_identity"]["source_text"] += " "
    elif damage == "provenance_pin": args["expected_provenance_report_sha256s"][0] = "0" * 64
    elif damage == "record_pin": args["expected_record_sha256s"][0] = "0" * 64
    else: args["expected_witness_manifest_sha256"] = "0" * 64
    with pytest.raises(lineage.ProducerLineageError): reconcile(observed, args)


@pytest.mark.parametrize("damage", ["drop", "reorder", "duplicate", "unknown", "bad_ordinal", "bad_candidate"])
def test_resealed_manifest_still_requires_closed_exact_physical_population(tmp_path, damage):
    observed, args, _, _ = fixture(tmp_path)
    m = args["witness_manifest"]
    if damage == "drop": m["records"].pop()
    elif damage == "reorder": m["records"].reverse()
    elif damage == "duplicate": m["reports"].append(deepcopy(m["reports"][0]))
    elif damage == "unknown": m["records"][0]["admitted"] = True
    elif damage == "bad_ordinal": m["parents"][0]["row_ordinals"][0] = []
    else: m["records"][0]["report_sha256s"] = [[]]
    reseal(args)
    with pytest.raises(lineage.ProducerLineageError): reconcile(observed, args)


@pytest.mark.parametrize("damage,expected", [
    ("missing_reference", "exact_cache_to_producer_reference_missing_or_mismatched"),
    ("source_text", "producer_source_declaration_mismatch"),
    ("source_sha", "producer_source_declaration_mismatch"),
    ("batch", "producer_source_declaration_mismatch"),
    ("unicode", "producer_source_declaration_mismatch"),
    ("missing_pointer", "producer_pointer_row_missing"),
])
def test_exact_cache_reference_and_source_declarations_cannot_normalize_or_select(tmp_path, damage, expected):
    def change(rows):
        if damage == "missing_reference": rows[0].pop("source_target_artifact_sha256")
        elif damage == "missing_pointer": rows[0]["source_target_artifact_pointer"] = "/rows/99/logic_target_observation"
        elif damage == "source_text": rows[0]["source"]["text"] += " "
        elif damage == "source_sha": rows[0]["source"]["text_sha256"] = "0" * 64
        elif damage == "unicode": rows[0]["source"]["text"] = rows[0]["source"]["text"].replace("é", "e\u0301")
        else: rows[0]["provenance"]["batch_id"] = "other"
    observed, args, _, _ = fixture(tmp_path, cache_change=change)
    row = reconcile(observed, args)["rows"][0]
    assert row["status"] == "unresolved" and expected in codes(row)


@pytest.mark.parametrize("damage,expected", [("revision", "producer_parent_descriptor_mismatch"),
    ("entry", "physical_parent_row_identity_mismatch"), ("legal_id", "physical_parent_row_identity_mismatch"),
    ("offset", "independent_physical_parent_row_missing_or_multiple"), ("missing", "producer_parent_identity_or_physical_row_missing")])
def test_parent_full_revision_literal_identity_and_physical_ordinal_are_independent(tmp_path, damage, expected):
    def change(rows):
        if damage == "revision": rows[0]["source_parent"]["revision"] = "b" * 7
        elif damage == "entry": rows[0]["entry_cid"] = "cid:other"
        elif damage == "legal_id": rows[0]["legal_id"] = "usc:us:10:01"
        elif damage == "offset": rows[0]["source_section_offset"] = 999
        else: rows[0].pop("source_parent")
    observed, args, _, _ = fixture(tmp_path, producer_change=change)
    row = reconcile(observed, args)["rows"][0]
    assert row["status"] == "unresolved" and expected in codes(row)
    assert row["revision_equivalence_inferred"] is False


def test_missing_and_multiple_witnesses_are_named_without_first_match(tmp_path):
    observed, args, _, _ = fixture(tmp_path)
    m = args["witness_manifest"]
    m["records"][0]["report_sha256s"] = []
    other = deepcopy(m["reports"][0]); other["sha256"] = "e" * 64; other["origin"]["artifact_sha256"] = "e" * 64
    m["reports"].append(other); m["records"][1]["report_sha256s"].append("e" * 64)
    reseal(args)
    result = reconcile(observed, args)
    assert "producer_report_witness_not_supplied" in codes(result["rows"][0])
    assert "multiple_producer_report_candidates" in codes(result["rows"][1])
    assert all(row["producer_row_witness"] is None for row in result["rows"])


def test_duplicate_producer_source_identity_and_container_artifacts_stay_unresolved(tmp_path):
    observed, args, _, _ = fixture(tmp_path, producer_change=lambda rows: rows[1].update(source_span_id=rows[0]["source_span_id"]))
    assert all("multiple_producer_rows_for_source_identity" in codes(row) for row in reconcile(observed, args)["rows"])
    other = tmp_path / "other"; other.mkdir()
    observed, args, _, _ = fixture(other, duplicate_artifact=True)
    assert all("multiple_original_receipt_artifacts" in codes(row) for row in reconcile(observed, args)["rows"])


def test_authored_projection_remains_unresolved_even_with_matching_local_declarations(tmp_path):
    observed, args, _, _ = fixture(tmp_path, authored=True)
    row = reconcile(observed, args)["rows"][0]
    assert "authored_projection_not_historical_execution" in codes(row)
    assert row["status"] == "unresolved" and all(v is False for v in row["authority"].values())


def test_repeated_raw_presentations_have_distinct_physical_identity(tmp_path):
    observed, args, _, _ = fixture(tmp_path, cache_change=lambda rows: rows.__setitem__(1, deepcopy(rows[0])))
    report = reconcile(observed, args)
    assert report["rows"][0]["raw_row_sha256"] == report["rows"][1]["raw_row_sha256"]
    assert len({row["record_sha256"] for row in report["rows"]}) == 2
    assert report["row_count"] == 2


@pytest.mark.parametrize("raw", [b'{"rows":[],"rows":[]}', b'{"n":NaN}', b'{"n":Infinity}', b'{"n":1e999}', b'{"n":'])
def test_strict_json_duplicate_nonfinite_and_malformed_reports_fail_closed(tmp_path, raw):
    observed, args, _, _ = fixture(tmp_path, raw_report=raw)
    with pytest.raises(lineage.ProducerLineageError): reconcile(observed, args)


@pytest.mark.parametrize("kind", ["node", "depth"])
def test_json_structure_bound_precedes_json_materialization(monkeypatch, kind):
    monkeypatch.setattr(lineage, "MAX_JSON_NODES", 4)
    monkeypatch.setattr(lineage, "MAX_JSON_DEPTH", 2)
    monkeypatch.setattr(lineage.json, "loads", lambda *a, **kw: pytest.fail("JSON parser invoked before preflight refusal"))
    raw = b'[0,0,0,0]' if kind == "node" else b'[[[0]]]'
    with pytest.raises(lineage.ProducerLineageError, match="predecode"): lineage._json(raw)


def test_json_preflight_handles_escaped_quotes_delimiters_and_unicode():
    value = {"quoted": 'é\\\"{}[]雪', "values": [None, False, 123, {"x": "}]"}]}
    assert lineage._json(wire(value)) == value


@pytest.mark.parametrize("parent", [True, False])
def test_compressed_oversized_group_refused_before_any_batch_decoding(tmp_path, monkeypatch, parent):
    observed, args, _, _ = fixture(tmp_path)
    desc = args["witness_manifest"]["parents"][0]["descriptor"] if parent else args["witness_manifest"]["reports"][0]
    monkeypatch.setattr(lineage, "MAX_PARQUET_GROUP_UNCOMPRESSED_BYTES", 1)
    monkeypatch.setattr(pq.ParquetFile, "iter_batches", lambda *a, **kw: pytest.fail("Arrow batch decoder invoked"))
    if parent:
        with pytest.raises(lineage.ProducerLineageError, match="predecode row-group"):
            lineage.read_parent_row_witnesses(desc, expected_descriptor_sha256=digest(desc), row_ordinals=[0])
    else:
        with pytest.raises(lineage.ProducerLineageError, match="predecode row-group"): lineage._load_report(desc)


def test_parent_decoded_profile_refusal_preserves_all_requests_and_producer_declarations(tmp_path, monkeypatch):
    observed, args, _, _ = fixture(tmp_path)
    original_preflight = lineage._parquet_preflight
    def preflight(stream, *, parent):
        if parent:
            raise lineage._UnsupportedParentDecodedProfile("declared group too large", {"declared_uncompressed_bytes": 99, "max_declared_uncompressed_bytes": 8})
        return original_preflight(stream, parent=False)
    monkeypatch.setattr(lineage, "_parquet_preflight", preflight)
    report = reconcile(observed, args)
    assert report["status_counts"] == {"unresolved": 2}
    assert report["parent_file_issues"][0]["expected_row_sha256s"] == args["witness_manifest"]["parents"][0]["expected_row_sha256s"]
    assert report["parent_file_issues"][0]["requested_row_ordinals"] == [0, 1]
    assert report["parent_row_inventories"] == [None]
    for row in report["rows"]:
        assert row["producer_row_witness"] is not None and row["parent_row_witness"] is None
        assert "source_parent_decoded_profile_unsupported" in codes(row)
        assert all(row["local_declaration_checks"].values())


@pytest.mark.parametrize("damage", ["hash", "bytes", "symlink", "footer_rows", "row_hash", "missing"])
def test_parent_custody_failure_is_not_hidden_by_local_report_success(tmp_path, damage):
    observed, args, _, _ = fixture(tmp_path)
    parent = args["witness_manifest"]["parents"][0]
    if damage == "hash": parent["descriptor"]["sha256"] = "0" * 64
    elif damage == "bytes": parent["descriptor"]["bytes"] += 1
    elif damage == "symlink":
        link = tmp_path / "alias.parquet"; link.symlink_to(parent["descriptor"]["local_path"]); parent["descriptor"]["local_path"] = str(link)
    elif damage == "footer_rows": parent["descriptor"]["row_count"] += 1
    elif damage == "row_hash": parent["expected_row_sha256s"][0] = "0" * 64
    else: Path(parent["descriptor"]["local_path"]).unlink()
    reseal(args)
    if damage == "missing":
        report = reconcile(observed, args)
        assert all("source_parent_file_unavailable" in codes(row) for row in report["rows"])
    else:
        with pytest.raises(lineage.ProducerLineageError): reconcile(observed, args)


def test_consumer_pin_and_replay_prevent_resealed_authority_inflation(tmp_path):
    observed, args, _, _ = fixture(tmp_path)
    report = reconcile(observed, args)
    original_pin = digest(report)
    report["rows"][0]["authority"]["admitted"] = True
    report["lineage_sha256"] = digest({k: v for k, v in report.items() if k != "lineage_sha256"})
    with pytest.raises(lineage.ProducerLineageError, match="independent complete lineage report pin"):
        lineage.validate_producer_lineage(report, observed, expected_report_sha256=original_pin, **args)
    with pytest.raises(lineage.ProducerLineageError, match="independent full regeneration"):
        lineage.validate_producer_lineage(report, observed, expected_report_sha256=digest(report), **args)


def test_file_changed_during_reader_is_refused_and_foreign_data_preserved(tmp_path):
    path = tmp_path / "source.bin"; path.write_bytes(b"original")
    desc = descriptor(path)
    with pytest.raises(lineage.ProducerLineageError, match="changed"):
        with lineage._opened(desc, 1024): path.write_bytes(b"changed!")
    assert path.read_bytes() == b"changed!"


def test_closed_parent_type_and_footer_caps_precede_decoding(tmp_path, monkeypatch):
    path = tmp_path / "nested.parquet"; pq.write_table(pa.Table.from_pylist([{"nested": {"x": "y"}}]), path)
    parent = descriptor(path, row_count=1, profile=lineage.PARENT_PROFILE)
    monkeypatch.setattr(pq.ParquetFile, "iter_batches", lambda *a, **kw: pytest.fail("unsupported schema decoded"))
    with pytest.raises(lineage.ProducerLineageError, match="Arrow type profile"):
        lineage.read_parent_row_witnesses(parent, expected_descriptor_sha256=digest(parent), row_ordinals=[0])
    monkeypatch.setattr(lineage, "MAX_PARQUET_FOOTER_BYTES", 1)
    monkeypatch.setattr(pq, "ParquetFile", lambda *a, **kw: pytest.fail("oversized footer parsed"))
    with pytest.raises(lineage.ProducerLineageError, match="footer byte bound"):
        lineage.read_parent_row_witnesses(parent, expected_descriptor_sha256=digest(parent), row_ordinals=[0])


def test_repeated_leaf_value_population_refused_before_arrow_decoding(tmp_path, monkeypatch):
    path = tmp_path / "repeated.parquet"
    pq.write_table(pa.Table.from_pylist([{"ipfs_cid": "cid", "unknown_list": [None] * 10}]), path)
    parent = descriptor(path, row_count=1, profile=lineage.PARENT_PROFILE)
    monkeypatch.setattr(lineage, "MAX_PARQUET_GROUP_LEAF_VALUES", 9)
    monkeypatch.setattr(pq.ParquetFile, "iter_batches", lambda *a, **kw: pytest.fail("repeated values decoded before profile guard"))
    with pytest.raises(lineage.ProducerLineageError, match="predecode"):
        lineage.read_parent_row_witnesses(parent, expected_descriptor_sha256=digest(parent), row_ordinals=[0])


def test_incomplete_source_text_cannot_pass_through_string_coercion(tmp_path):
    def change(rows):
        rows[0]["text"] = None
        rows[0]["source_sha256"] = hashlib.sha256(b"None").hexdigest()
    observed, args, _, _ = fixture(tmp_path, producer_change=change)
    row = reconcile(observed, args)["rows"][0]
    assert row["status"] == "unresolved" and row["local_declaration_checks"]["source_projection_complete"] is False
    assert "producer_source_declaration_mismatch" in codes(row)


def test_malformed_cache_batch_is_unresolved_without_attribute_coercion(tmp_path):
    observed, args, _, _ = fixture(tmp_path, cache_change=lambda rows: rows[0].update(provenance="wrong-shaped declaration"))
    row = reconcile(observed, args)["rows"][0]
    assert row["status"] == "unresolved" and row["local_declaration_checks"]["batch_id"] is False
