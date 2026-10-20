"""Synthetic metadata custody and declaration gaps, without source table bodies."""
from copy import deepcopy
import builtins
import hashlib
import json
from pathlib import Path
import socket
import subprocess

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_package_intake_v1 as intake


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def artifact(path, family, rows, raw=b"unread table", schema="fixture/v1"):
    return {"family": family, "first_key": None, "last_key": None,
        "media_type": "application/vnd.apache.parquet" if path.endswith(".parquet") else "application/json",
        "relative_path": path, "row_count": rows, "schema_id": schema,
        "sha256": sha(raw), "size_bytes": len(raw)}


def refresh(request, blobs):
    for entry in request["files"]:
        raw = blobs[entry["path_in_repo"]]
        entry.update(bytes=len(raw), sha256=sha(raw))


def inputs(*, advertised=17, readme_mismatch=False, configs_schema="uscode-hf-release/v1"):
    name = "publicus-ir-graphrag/v2"
    config = {"config_name": name, "data_files": [{"path": "data/**/*.parquet", "split": "train"}],
              "features": ["entry_cid", "legal_id", "family", "record_json", "record_sha256"]}
    release = {"schema_version": "uscode-hf-release/v1", "dataset_id": intake.REPOSITORY,
        "release_profile": name, "release_point": "us/pl/119/102", "release_root_cid": "declared-fixture-root",
        "source_revision": "b" * 40, "graph_ontology_version": "uscode-legal-graph-ontology/v1",
        "producer": "uscode_hf_release.py", "unknown_acquisition_note": "Café § retained"}
    blobs = {
        "release_metadata.json": wire(release),
        "dataset_configs.json": wire({"schema_version": configs_schema,
            "default_config": name, "configs": [config]}),
        "dataset_infos.json": wire({"schema_version": "uscode-hf-release/v1", "configs": {
            name: {"features": config["features"], "splits": {"train": {"num_examples": advertised}}}}}),
        "README.md": "# Source\nCafé § exact spelling.\n".encode(),
    }
    artifacts = [
        artifact("data/corpus/part-000000.parquet", "corpus", 10, schema="uscode-corpus-row/v1"),
        artifact("data/graph/nodes/part-000000.parquet", "graph_nodes", 3, schema="uscode-graph-node/v1"),
        artifact("data/graph/edges/part-000000.parquet", "graph_edges", 2, schema="uscode-graph-edge/v1"),
        artifact("indexes/routes.parquet", "routing_index", 2),
        *[artifact(path, "release_metadata" if path == "release_metadata.json" else "receipt", 0,
                   raw=raw, schema="uscode-hf-release/v1") for path, raw in blobs.items()],
    ]
    manifest = {"schema_version": "uscode-sparse-graphrag-release-schema-v2",
        "hf_release_schema_version": "uscode-hf-release/v1", "dataset_repo_id": intake.REPOSITORY,
        **{key: release[key] for key in ("release_profile", "release_point", "release_root_cid",
            "source_revision", "graph_ontology_version", "producer")},
        "default_config": name, "configs": [config], "artifacts": artifacts,
        "unknown_future_metadata": {"note": "retained without semantic interpretation"}}
    manifest["manifest_digest"] = sha(wire(manifest))
    blobs["manifest.json"] = wire(manifest)
    if readme_mismatch:
        blobs["README.md"] += b"Appended after sealing.\n"
    request = {"schema": intake.REQUEST_SCHEMA, "repository_id": intake.REPOSITORY, "revision": "a" * 40,
        "expected_release_identity": {key: manifest[key] for key in (
            "release_profile", "release_point", "release_root_cid", "source_revision", "manifest_digest",
            "graph_ontology_version", "producer")},
        "expected_graph_population": {"graph_nodes": {"files": 1, "rows": 3},
                                      "graph_edges": {"files": 1, "rows": 2}},
        "files": [{"path_in_repo": path, "bytes": len(blobs[path]), "sha256": sha(blobs[path])}
                  for path in intake.FILES]}
    return request, blobs


def prepare(request, blobs, raw=None):
    raw = wire(request) if raw is None else raw
    return intake.prepare_source_package_intake(raw, blobs, expected_request_sha256=sha(raw))


def validate(report, request, blobs):
    raw = wire(request)
    return intake.validate_source_package_intake(report, raw, blobs,
        expected_request_sha256=sha(raw), expected_report_sha256=intake.source_package_intake_sha256(report))


def owners_must_not_load(monkeypatch):
    monkeypatch.setattr(intake, "_owners", lambda: pytest.fail("owners loaded before preflight rejection"))


def test_exact_metadata_readback_order_spelling_identity_and_false_authority():
    request, blobs = inputs(advertised=15)
    before_request, before_blobs = deepcopy(request), dict(blobs)
    request["files"].reverse()
    raw = (json.dumps(request, indent=2, ensure_ascii=False) + "\n").encode()
    report = prepare(request, blobs, raw)
    assert report["request_raw_utf8"].encode() == raw
    assert report["request"] == request and blobs == before_blobs
    assert [entry["path_in_repo"] for entry in report["files"]] == [entry["path_in_repo"] for entry in request["files"]]
    for ordinal, entry in enumerate(report["files"]):
        assert entry["selection_ordinal"] == ordinal
        assert entry["raw_utf8"].encode() == blobs[entry["path_in_repo"]]
        assert sha(entry["raw_utf8"].encode()) == entry["sha256"]
    assert before_request["files"][0]["path_in_repo"] == "manifest.json"
    assert report["status"] == "selected_metadata_verified" and report["issues"] == []
    assert report["source_identity"]["hub_revision"] == "a" * 40
    assert report["source_identity"]["producer_source_revision"] == "b" * 40
    assert report["source_identity"]["release_point"] == "us/pl/119/102"
    assert report["source_identity"]["aliases_mapped"] is False
    assert report["primary_manifest_selection"]["manifest"]["unknown_future_metadata"]
    assert not any(report["authority"].values()) and all(type(v) is bool for v in report["authority"].values())
    assert report["source_join"]["bindings"] == [] and report["source_join"]["source_occurrences"] is None
    assert report["producer_pins"] == report["producer_pins_after"] and len(report["producer_pins"]) == 3
    assert all(sha(Path(path).read_bytes()) == value for path, value in report["producer_pins"].items())
    assert intake.validate_source_package_intake(wire(report), raw, blobs,
        expected_request_sha256=sha(raw), expected_report_sha256=intake.source_package_intake_sha256(report)) == report


def test_manifest_bound_readme_mismatch_is_retained_under_correct_independent_input_pins():
    request, blobs = inputs(readme_mismatch=True)
    report = prepare(request, blobs)
    comparison = next(item for item in report["companion_comparisons"] if item["path_in_repo"] == "README.md")
    assert comparison["disposition"] == "descriptor_mismatch"
    assert not comparison["size_matches"] and not comparison["sha256_matches"]
    assert comparison["observed_sha256"] == sha(blobs["README.md"])
    assert comparison["descriptor"]["sha256"] != comparison["observed_sha256"]
    assert report["metadata_validation"]["selected_bytes_pinned"] is True
    assert report["metadata_validation"]["companion_descriptors_match"] is False
    assert report["status"] == "selected_metadata_verified_with_discrepancies"
    assert validate(report, request, blobs) == report


def test_data_glob_rows_advertised_rows_routing_rows_and_unique_laws_stay_distinct():
    request, blobs = inputs()
    counts = prepare(request, blobs)["count_reconciliation"]
    assert counts["manifest_data_glob"]["physical_descriptor_row_sum"] == 15
    assert counts["downloaded_config_data_glob"]["physical_descriptor_row_sum"] == 15
    assert counts["advertised_train_num_examples"] == 17
    assert counts["advertised_minus_manifest_data_glob_rows"] == counts["routing_index_declared_rows"] == 2
    assert counts["corpus_declared_rows"] == 10 and counts["unique_laws"] is None and counts["rows_read"] == 0
    assert counts["status"] == "row_count_delta_equals_declared_routing_index_rows"
    assert counts["delta_equals_routing_index_rows"] is True
    assert "indexes/routes.parquet" not in counts["manifest_data_glob"]["physical_descriptor_paths"]


def test_companion_schema_mismatch_is_an_explicit_unresolved_declaration():
    request, blobs = inputs(configs_schema="future-source-package/v99")
    report = prepare(request, blobs)
    assert report["metadata_validation"]["companion_descriptors_match"] is True
    assert report["metadata_validation"]["companion_declarations_match"] is False
    assert {"code": "unsupported_companion_schema", "path_in_repo": "dataset_configs.json"} in report["issues"]
    assert report["companion_metadata"]["dataset_configs.json"]["schema_version"] == "future-source-package/v99"


@pytest.mark.parametrize("field,value", [("extra", None), ("limits", {}), ("repository_id", "other/source"),
    ("schema", "other/v1"), ("revision", "main"), ("revision", "A" * 40), ("revision", "a" * 39)])
def test_unknown_or_bad_request_fields_fail_before_primary_owner_load(monkeypatch, field, value):
    request, blobs = inputs()
    request[field] = value
    owners_must_not_load(monkeypatch)
    with pytest.raises(ValueError): prepare(request, blobs)


@pytest.mark.parametrize("field", ["schema", "repository_id", "revision", "expected_release_identity", "expected_graph_population", "files"])
def test_missing_request_fields_fail_before_primary_owner_load(monkeypatch, field):
    request, blobs = inputs()
    del request[field]
    owners_must_not_load(monkeypatch)
    with pytest.raises(ValueError): prepare(request, blobs)


@pytest.mark.parametrize("field,value", [("path_in_repo", "../manifest.json"), ("path_in_repo", "/manifest.json"),
    ("path_in_repo", "data/model.bin"), ("bytes", True), ("bytes", 1.0), ("bytes", 0),
    ("bytes", intake.MAX_METADATA_BYTES + 1), ("sha256", "A" * 64), ("extra", None)])
def test_unsafe_or_bad_selected_descriptors_fail_before_owner_load(monkeypatch, field, value):
    request, blobs = inputs()
    request["files"][0][field] = value
    owners_must_not_load(monkeypatch)
    with pytest.raises(ValueError): prepare(request, blobs)


@pytest.mark.parametrize("damage", ["duplicate_selection", "missing_mapping", "extra_mapping", "altered_bytes", "wrong_pin", "wrong_size"])
def test_selected_file_population_bytes_and_pins_are_exact(monkeypatch, damage):
    request, blobs = inputs()
    if damage == "duplicate_selection": request["files"][-1] = deepcopy(request["files"][0])
    elif damage == "missing_mapping": del blobs["README.md"]
    elif damage == "extra_mapping": blobs["model.bin"] = b"never open"
    elif damage == "altered_bytes": blobs["README.md"] += b"altered"
    elif damage == "wrong_pin": request["files"][0]["sha256"] = "0" * 64
    else: request["files"][0]["bytes"] += 1
    owners_must_not_load(monkeypatch)
    with pytest.raises(ValueError): prepare(request, blobs)


def test_wrong_request_pin_duplicate_json_and_nonfinite_metadata_are_refused(monkeypatch):
    request, blobs = inputs()
    owners_must_not_load(monkeypatch)
    raw = wire(request)
    with pytest.raises(ValueError, match="request SHA256"):
        intake.prepare_source_package_intake(raw, blobs, expected_request_sha256="0" * 64)
    duplicate_request = b'{"schema":"duplicate",' + raw[1:]
    with pytest.raises(ValueError, match="duplicate-free"):
        intake.prepare_source_package_intake(duplicate_request, blobs, expected_request_sha256=sha(duplicate_request))
    for malformed in [b'{"a":1,"a":2}', b'{"a":NaN}', b'"not an object"', b'{"a":"\\ud800"}']:
        changed = dict(blobs, **{"dataset_infos.json": malformed})
        supplied = deepcopy(request); refresh(supplied, changed)
        with pytest.raises(ValueError): prepare(supplied, changed)


def test_fixed_request_file_and_aggregate_bounds_are_refused_without_truncation(monkeypatch):
    request, blobs = inputs()
    owners_must_not_load(monkeypatch)
    raw = wire(request) + b" " * intake.MAX_REQUEST_BYTES
    with pytest.raises(ValueError, match="bounded exact"):
        intake.prepare_source_package_intake(raw, blobs, expected_request_sha256=sha(raw))
    request["files"][0]["bytes"] = intake.MAX_METADATA_BYTES + 1
    with pytest.raises(ValueError, match="file bytes"):
        prepare(request, blobs)
    request, blobs = inputs()
    for entry in request["files"]:
        entry["bytes"] = intake.MAX_METADATA_TOTAL_BYTES // 5 + 1
    with pytest.raises(ValueError, match="aggregate"):
        prepare(request, blobs)


@pytest.mark.parametrize("field", ["source_revision", "manifest_digest"])
def test_independent_release_identity_is_delegated_and_cannot_be_resealed_away(field):
    request, blobs = inputs()
    request["expected_release_identity"][field] = "c" * (40 if field == "source_revision" else 64)
    with pytest.raises(ValueError): prepare(request, blobs)


def test_independent_graph_population_is_not_replaced_by_manifest_self_claims():
    request, blobs = inputs()
    request["expected_graph_population"]["graph_nodes"]["rows"] = 1
    with pytest.raises(ValueError, match="population"):
        prepare(request, blobs)


@pytest.mark.parametrize("damage", ["remove_issue", "rewrite_count", "map_revision", "add_authority", "reorder_files", "extra_report_field"])
def test_resealed_report_mutations_fail_complete_authoritative_readback(damage):
    request, blobs = inputs(readme_mismatch=True)
    report = prepare(request, blobs)
    if damage == "remove_issue": report["issues"].clear()
    elif damage == "rewrite_count": report["count_reconciliation"]["advertised_train_num_examples"] = 15
    elif damage == "map_revision": report["source_identity"]["producer_source_revision"] = report["revision"]
    elif damage == "add_authority": report["authority"]["admitted"] = True
    elif damage == "reorder_files": report["files"].reverse()
    else: report["invented"] = "unknown"
    with pytest.raises(ValueError, match="authoritative replay"):
        validate(report, request, blobs)


def test_wrong_independent_report_pin_is_refused():
    request, blobs = inputs()
    report = prepare(request, blobs); raw = wire(request)
    with pytest.raises(ValueError, match="report SHA256"):
        intake.validate_source_package_intake(report, raw, blobs,
            expected_request_sha256=sha(raw), expected_report_sha256="0" * 64)


def test_preparation_does_not_load_table_database_model_or_network_clients(monkeypatch):
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        assert name.split(".")[0] not in {"pyarrow", "duckdb", "torch", "huggingface_hub", "datasets", "requests"}
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network attempted"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network attempted"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("subprocess attempted"))
    request, blobs = inputs()
    report = prepare(request, blobs)
    assert all(report["metadata_validation"][key] is False for key in (
        "table_bodies_read", "table_rows_read", "Arrow_loaded", "network_performed", "database_opened", "models_loaded"))
