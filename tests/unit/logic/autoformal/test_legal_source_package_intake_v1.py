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


# These five small files are exact producer outputs retained by the qualified
# 49-case HF wire loader run, not a second Parquet corpus. The original output
# directory is bound by docs/autoformalization/evidence/
# legal-ir-uscode-hf-wire-loader-20261023.json (fba3f8b62d4ae63b...): the first
# successful loader_calls.path in that receipt's original test-result.json.
# The fixture staging receipt retains each exact original path. Its inputs
# were authored fixture records; this test's independent Hub revision is a
# synthetic declaration, distinct from the producer's source_revision. No
# hosted release, remote revision, law currentness, or physical row is verified.
WIRE_FIXTURE_PINS = {
    "manifest.json": (11536, "0a97c6bdd7a2e7bec6e72ef17213bf44317fc9834fc43694f89081de6ccb675a"),
    "release_metadata.json": (2096, "08d0df1cabc353346443a1f93feb2f00e5fe5156feb11bd662bfc4e87b84c944"),
    "dataset_configs.json": (2483, "f69a782ee3e80d577a8002bf0e14b3de67fa12f5ad104679b8112456c8672520"),
    "dataset_infos.json": (391, "586382b507faf4d8fda8400760f22ad8cf054e8c351a2a8188e606e923f0819c"),
    "README.md": (4359, "7835c9c366ae744420ceed8e24ee92db3913aeb7ac40810b12695e4ad5435e84"),
}
WIRE_PROFILE = "hf-default-parquet-envelope/v1"
WIRE_ALIAS = "publicus-ir-graphrag-v2"
WIRE_LOGICAL = "publicus-ir-graphrag/v2"


def wire_intake_inputs():
    root = Path(__file__).resolve().parents[4] / "tests/fixtures/legal_ir/uscode_hf_wire_metadata_v1"
    blobs = {}
    for name, (size, digest) in WIRE_FIXTURE_PINS.items():
        raw = (root / name).read_bytes()
        assert len(raw) == size and sha(raw) == digest
        blobs[name] = raw
    manifest = json.loads(blobs["manifest.json"])
    request = {
        "schema": "legal-source-package-intake-request/v2", "repository_id": intake.REPOSITORY,
        "revision": "a" * 40, "metadata_profile": WIRE_PROFILE,
        "expected_release_identity": {key: manifest[key] for key in (
            "release_profile", "release_point", "release_root_cid", "source_revision",
            "manifest_digest", "graph_ontology_version", "producer")},
        "expected_graph_population": {"graph_nodes": {"files": 1, "rows": 2},
                                      "graph_edges": {"files": 1, "rows": 1}},
        "files": [{"path_in_repo": name, "bytes": len(blobs[name]), "sha256": sha(blobs[name])}
                  for name in intake.FILES],
    }
    return request, blobs


def wire_intake_prepare(request, blobs, raw=None):
    raw = wire(request) if raw is None else raw
    return intake.prepare_source_package_intake_v2(raw, blobs, expected_request_sha256=sha(raw))


def wire_intake_validate(report, request, blobs):
    raw = wire(request)
    return intake.validate_source_package_intake_v2(report, raw, blobs,
        expected_request_sha256=sha(raw), expected_report_sha256=intake.source_package_intake_sha256(report))


def wire_intake_reseal(request, blobs):
    """Make mutations reach semantic metadata checks, not stale input seals."""
    manifest = json.loads(blobs["manifest.json"])
    for descriptor in manifest["artifacts"]:
        name = descriptor["relative_path"]
        if name in blobs and name != "manifest.json":
            descriptor.update(sha256=sha(blobs[name]), size_bytes=len(blobs[name]))
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = sha(wire(manifest))
    blobs["manifest.json"] = wire(manifest)
    request["expected_release_identity"]["manifest_digest"] = manifest["manifest_digest"]
    refresh(request, blobs)


def wire_intake_set_declaration(blobs, declaration):
    for name in ("manifest.json", "release_metadata.json", "dataset_configs.json"):
        value = json.loads(blobs[name]); value["wire_metadata"] = deepcopy(declaration)
        blobs[name] = wire(value)


def wire_intake_preflight_only(monkeypatch):
    monkeypatch.setattr(intake, "_v2_owner_state",
                        lambda: pytest.fail("v2 owners discovered before malformed input refusal"))


def test_wire_intake_retained_producer_five_files_roundtrip_has_no_physical_or_semantic_authority():
    request, blobs = wire_intake_inputs()
    original = deepcopy(request), dict(blobs)
    request["files"].reverse()
    raw = (json.dumps(request, indent=2, ensure_ascii=False) + "\n").encode()
    report = wire_intake_prepare(request, blobs, raw)
    assert sum(size for size, _ in WIRE_FIXTURE_PINS.values()) == 20865
    assert report["schema"] == "legal-source-package-intake/v2"
    assert report["metadata_profile"] == WIRE_PROFILE
    assert report["status"] == "selected_wire_metadata_reconciled" and report["issues"] == []
    assert report["request_raw_utf8"].encode() == raw
    assert report["request"] == request and blobs == original[1]
    assert report["revision"] == "a" * 40
    assert report["source_identity"]["producer_source_revision"] == "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
    assert report["source_identity"]["producer_source_revision"] != report["revision"]
    assert report["source_identity"]["aliases_mapped"] is False
    assert [entry["path_in_repo"] for entry in report["files"]] == [entry["path_in_repo"] for entry in request["files"]]
    assert all(entry["raw_utf8"].encode() == blobs[entry["path_in_repo"]] for entry in report["files"])
    counts = report["count_reconciliation"]
    assert counts["status"] == "advertised_rows_match_exact_wire_population"
    assert counts["selected_descriptor_count"] == 6
    assert counts["selected_descriptor_row_sum"] == counts["advertised_train_num_examples"] == 11
    assert counts["selected_descriptor_byte_sum"] == 20881
    assert counts["declared_arrow_num_bytes"] == 4623
    assert counts["arrow_bytes_physically_measured_here"] is False
    assert counts["corpus_declared_rows"] == 2 and counts["routing_index_declared_rows"] == 6
    assert counts["unique_laws"] is None and counts["rows_read"] == 0
    assert len(counts["selected_descriptor_paths"]) == len(set(counts["selected_descriptor_paths"])) == 6
    assert all(path.startswith("data/") for path in counts["selected_descriptor_paths"])
    reconciliation = report["wire_metadata_reconciliation"]
    assert reconciliation["declaration"] == json.loads(blobs["manifest.json"])["wire_metadata"]
    assert reconciliation["logical_default_config"] == WIRE_LOGICAL
    assert reconciliation["wire_default_config"] == WIRE_ALIAS
    assert reconciliation["declared_Arrow_bytes_verified_here"] is False
    assert report["readme_validation"]["recognized_regions"] == ["dataset_info", "configs"]
    assert report["readme_validation"]["recognized_regions_exact"] is True
    assert report["readme_validation"]["general_yaml_parser_used"] is False
    assert report["readme_validation"]["uninterpreted_prose_retained"] is True
    assert not any(report["authority"].values())
    assert all(type(flag) is bool for flag in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert report["source_join"]["bindings"] == [] and report["source_join"]["source_occurrences"] is None
    assert report["producer_pins"] == report["producer_pins_after"]
    assert report["producer_origins"] == report["producer_origins_after"]
    assert all(report["metadata_validation"][key] is False for key in (
        "table_bodies_read", "table_rows_read", "Arrow_loaded", "network_performed", "database_opened", "models_loaded"))
    assert intake.validate_source_package_intake_v2(wire(report), raw, blobs,
        expected_request_sha256=sha(raw), expected_report_sha256=intake.source_package_intake_sha256(report)) == report
    assert original[0]["files"][0]["path_in_repo"] == "manifest.json"


def test_wire_intake_is_explicit_and_legacy_interpretation_remains_unchanged():
    request, blobs = wire_intake_inputs()
    with pytest.raises(ValueError): prepare(request, blobs)
    old = deepcopy(request); old["schema"] = intake.REQUEST_SCHEMA; del old["metadata_profile"]
    legacy = prepare(old, blobs)
    assert legacy["schema"] == "legal-source-package-intake/v1"
    assert legacy["status"] == "selected_metadata_verified_with_discrepancies"
    assert {"code": "unsupported_companion_schema", "path_in_repo": "dataset_infos.json"} in legacy["issues"]
    assert legacy["count_reconciliation"]["advertised_train_num_examples"] is None
    with pytest.raises(ValueError): wire_intake_prepare(old, blobs)


@pytest.mark.parametrize("profile", [None, False, {}, "", "hf-default-parquet-envelope/v999"])
def test_wire_intake_unknown_metadata_profile_refuses_before_discovery(monkeypatch, profile):
    request, blobs = wire_intake_inputs(); request["metadata_profile"] = profile
    wire_intake_preflight_only(monkeypatch)
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)


def test_wire_intake_duplicate_json_input_and_bad_raw_pin_refuse_before_discovery(monkeypatch):
    request, blobs = wire_intake_inputs(); raw = wire(request)
    wire_intake_preflight_only(monkeypatch)
    with pytest.raises(ValueError):
        intake.prepare_source_package_intake_v2(raw, blobs, expected_request_sha256="0" * 64)
    duplicate = b'{"metadata_profile":"other",' + raw[1:]
    with pytest.raises(ValueError):
        intake.prepare_source_package_intake_v2(duplicate, blobs, expected_request_sha256=sha(duplicate))
    blobs["dataset_infos.json"] = b'{"duplicate":1,"duplicate":2}'
    refresh(request, blobs)
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)


@pytest.mark.parametrize("name", ["manifest.json", "release_metadata.json", "dataset_configs.json"])
def test_wire_intake_independently_resealed_cross_document_declaration_divergence_refuses(name):
    request, blobs = wire_intake_inputs()
    value = json.loads(blobs[name]); value["wire_metadata"]["num_bytes"] += 1
    blobs[name] = wire(value); wire_intake_reseal(request, blobs)
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)


@pytest.mark.parametrize("damage", ["schema", "alias", "logical_default", "wire_default",
                                    "boolean_rows", "boolean_bytes", "wrong_row_sum", "negative_bytes"])
def test_wire_intake_coherent_foreign_profile_alias_or_bad_counts_refuse(damage):
    request, blobs = wire_intake_inputs()
    declaration = json.loads(blobs["manifest.json"])["wire_metadata"]
    if damage == "schema": declaration["schema"] = "uscode-hf-wire-metadata/v999"
    elif damage == "alias": declaration["aliases"][WIRE_LOGICAL] = "foreign-alias"
    elif damage == "logical_default": declaration["logical_default_config"] = "legacy-uscode-parquet/v1"
    elif damage == "wire_default": declaration["default_config"] = WIRE_LOGICAL
    elif damage == "boolean_rows": declaration["num_examples"] = True
    elif damage == "boolean_bytes": declaration["num_bytes"] = False
    elif damage == "wrong_row_sum": declaration["num_examples"] += 6
    else: declaration["num_bytes"] = -1
    wire_intake_set_declaration(blobs, declaration); wire_intake_reseal(request, blobs)
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)


@pytest.mark.parametrize("damage", ["duplicate", "missing", "reordered", "unlisted", "routing", "traversal", "glob", "manifest_extra"])
def test_wire_intake_exact_advertised_population_never_globs_or_includes_routing_legacy(damage):
    request, blobs = wire_intake_inputs()
    declaration = json.loads(blobs["manifest.json"])["wire_metadata"]
    paths = declaration["data_files"][0]["path"]
    old_paths = json.dumps(paths).encode()
    if damage == "duplicate": paths.append(paths[0])
    elif damage == "missing": paths.pop()
    elif damage == "reordered": paths.reverse()
    elif damage == "unlisted": paths.append("data/corpus/unlisted-extra.parquet"); paths.sort()
    elif damage == "routing": paths.append("indexes/corpus_chunks-000000.parquet"); paths.sort()
    elif damage == "traversal": paths[0] = "data/../uscode_parquet/laws.parquet"
    elif damage == "glob": paths[0] = "data/**/*.parquet"
    else:
        manifest = json.loads(blobs["manifest.json"])
        extra = deepcopy(next(item for item in manifest["artifacts"] if item["family"] == "corpus"))
        extra["relative_path"] = "data/corpus/unadvertised-extra.parquet"
        manifest["artifacts"].append(extra); blobs["manifest.json"] = wire(manifest)
    # Coherent recognized card paths ensure this reaches population/path checks,
    # rather than succeeding only because the README still advertises old paths.
    assert blobs["README.md"].count(old_paths) == 1
    blobs["README.md"] = blobs["README.md"].replace(old_paths, json.dumps(paths).encode(), 1)
    wire_intake_set_declaration(blobs, declaration); wire_intake_reseal(request, blobs)
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)


@pytest.mark.parametrize("foreign_family", ["routing_index", "recovery"])
def test_wire_intake_advertised_data_descriptor_cannot_disguise_foreign_family(foreign_family):
    request, blobs = wire_intake_inputs(); manifest = json.loads(blobs["manifest.json"])
    target = next(item for item in manifest["artifacts"] if item["family"] == "bm25_documents")
    assert target["relative_path"].startswith("data/") and target["row_count"] == 2
    target["family"] = foreign_family
    blobs["manifest.json"] = wire(manifest); wire_intake_reseal(request, blobs)
    # Card, infos, explicit paths, row sums, graph population and all outer
    # hashes remain coherent. Only the transport family's eligibility differs.
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)


@pytest.mark.parametrize("damage", ["legacy_wrapper", "wrong_config_name", "feature_type", "boolean_rows", "bytes_mismatch"])
def test_wire_intake_standard_infos_exact_named_features_and_split_declarations_refuse(damage):
    request, blobs = wire_intake_inputs(); infos = json.loads(blobs["dataset_infos.json"])
    if damage == "legacy_wrapper": infos = {"schema_version": "uscode-hf-release/v1", "configs": infos}
    elif damage == "wrong_config_name": infos[WIRE_ALIAS]["config_name"] = "default"
    elif damage == "feature_type": infos[WIRE_ALIAS]["features"]["entry_cid"]["dtype"] = "int64"
    elif damage == "boolean_rows": infos[WIRE_ALIAS]["splits"]["train"]["num_examples"] = True
    else: infos[WIRE_ALIAS]["splits"]["train"]["num_bytes"] += 1
    blobs["dataset_infos.json"] = wire(infos); wire_intake_reseal(request, blobs)
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)


@pytest.mark.parametrize("offered_bytes", [True, 1.0])
def test_wire_intake_infos_numeric_equality_cannot_hide_boolean_or_float_Arrow_bytes(offered_bytes):
    request, blobs = wire_intake_inputs()
    declaration = json.loads(blobs["manifest.json"])["wire_metadata"]
    declaration["num_bytes"] = 1
    wire_intake_set_declaration(blobs, declaration)
    infos = json.loads(blobs["dataset_infos.json"])
    infos[WIRE_ALIAS]["splits"]["train"]["num_bytes"] = offered_bytes
    blobs["dataset_infos.json"] = wire(infos)
    blobs["README.md"] = blobs["README.md"].replace(b"num_bytes: 4623", b"num_bytes: 1", 1)
    wire_intake_reseal(request, blobs)
    assert offered_bytes == declaration["num_bytes"] and type(offered_bytes) is not int
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)


@pytest.mark.parametrize("damage", ["alias", "count", "default", "duplicate_region", "anchor"])
def test_wire_intake_canonical_readme_regions_are_checked_without_general_yaml(damage):
    request, blobs = wire_intake_inputs(); raw = blobs["README.md"]
    if damage == "alias": raw = raw.replace(b'config_name: "publicus-ir-graphrag-v2"', b'config_name: "foreign"', 1)
    elif damage == "count": raw = raw.replace(b"num_examples: 11", b"num_examples: 17", 1)
    elif damage == "default": raw = raw.replace(b"default: true", b"default: false", 1)
    elif damage == "duplicate_region": raw = raw.replace(b"\nconfigs:\n", b"\nconfigs:\nconfigs:\n", 1)
    else: raw = raw.replace(b"\nconfigs:\n", b"\nconfigs: &advertised\n", 1)
    blobs["README.md"] = raw; wire_intake_reseal(request, blobs)
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)


def test_wire_intake_coherent_arrow_bytes_remain_declarations_and_uninterpreted_prose_is_retained():
    request, blobs = wire_intake_inputs()
    declaration = json.loads(blobs["manifest.json"])["wire_metadata"]
    declaration["num_bytes"] += 17
    wire_intake_set_declaration(blobs, declaration)
    infos = json.loads(blobs["dataset_infos.json"]); infos[WIRE_ALIAS]["splits"]["train"]["num_bytes"] += 17
    blobs["dataset_infos.json"] = wire(infos)
    blobs["README.md"] = blobs["README.md"].replace(b"num_bytes: 4623", b"num_bytes: 4640", 1)
    blobs["README.md"] += "\nUnreviewed Café § prose remains opaque.\n".encode()
    wire_intake_reseal(request, blobs)
    report = wire_intake_prepare(request, blobs)
    assert report["count_reconciliation"]["declared_arrow_num_bytes"] == 4640
    assert report["count_reconciliation"]["arrow_bytes_physically_measured_here"] is False
    assert report["wire_metadata_reconciliation"]["declared_Arrow_bytes_verified_here"] is False
    assert report["readme_validation"]["uninterpreted_prose_retained"] is True
    assert report["files"][-1]["raw_utf8"].encode() == blobs["README.md"]
    assert not any(report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0


def test_wire_intake_requires_selected_companion_descriptor_integrity_while_v1_retains_its_discrepancy():
    request, blobs = wire_intake_inputs(); blobs["README.md"] += b"\nUndeclared companion mutation.\n"
    refresh(request, blobs)
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)
    old = deepcopy(request); old["schema"] = intake.REQUEST_SCHEMA; del old["metadata_profile"]
    report = prepare(old, blobs)
    assert any(issue["code"] == "companion_descriptor_mismatch" and issue["path_in_repo"] == "README.md"
               for issue in report["issues"])


@pytest.mark.parametrize("damage", ["wire_count", "opaque_prose", "revision_alias", "admission", "order", "extra"])
def test_wire_intake_resealed_report_still_requires_complete_genuine_regeneration(damage):
    request, blobs = wire_intake_inputs(); report = wire_intake_prepare(request, blobs)
    if damage == "wire_count": report["count_reconciliation"]["advertised_train_num_examples"] += 1
    elif damage == "opaque_prose": report["readme_validation"]["uninterpreted_prose_retained"] = False
    elif damage == "revision_alias": report["source_identity"]["producer_source_revision"] = report["revision"]
    elif damage == "admission": report["authority"]["admitted"] = True
    elif damage == "order": report["files"].reverse()
    else: report["invented"] = "unknown"
    with pytest.raises(ValueError): wire_intake_validate(report, request, blobs)


def test_wire_intake_independent_report_and_graph_population_pins_are_not_self_assertions():
    request, blobs = wire_intake_inputs(); raw = wire(request); report = wire_intake_prepare(request, blobs)
    with pytest.raises(ValueError):
        intake.validate_source_package_intake_v2(report, raw, blobs,
            expected_request_sha256=sha(raw), expected_report_sha256="0" * 64)
    request["expected_graph_population"]["graph_nodes"]["rows"] += 1
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)


@pytest.mark.parametrize("damage", ["original_input", "returned_selection"])
def test_wire_intake_genuine_primary_call_retains_original_inputs_and_independent_return(damage, monkeypatch):
    request, blobs = wire_intake_inputs()
    from ipfs_datasets_py.logic.autoformal import legal_primary_graph_manifest as primary
    genuine = primary.select_primary_graph_manifest; calls = []
    def observed(*args, **kwargs):
        result = genuine(*args, **kwargs); calls.append(True)
        if damage == "original_input": blobs["README.md"] += b"\nChanged after real primary selection.\n"
        else: result["manifest"]["wire_metadata"]["num_examples"] += 1
        return result
    monkeypatch.setattr(primary, "select_primary_graph_manifest", observed)
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)
    assert calls == [True]


def test_wire_intake_final_report_wire_retains_original_input_custody(monkeypatch):
    request, blobs = wire_intake_inputs(); genuine = intake._v2_wire; reached = []
    def observed(value, *args, **kwargs):
        raw = genuine(value, *args, **kwargs)
        if type(value) is dict and value.get("schema") == "legal-source-package-intake/v2":
            reached.append(True); blobs["README.md"] += b"\nFinal wire original-input mutation.\n"
        return raw
    monkeypatch.setattr(intake, "_v2_wire", observed)
    with pytest.raises(ValueError): wire_intake_prepare(request, blobs)
    assert reached


def test_wire_intake_does_not_import_or_dispatch_table_database_model_network_or_process(monkeypatch):
    request, blobs = wire_intake_inputs(); real_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        assert name.split(".")[0] not in {"pyarrow", "datasets", "duckdb", "torch", "huggingface_hub", "requests", "yaml"}
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network attempted"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network attempted"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("process attempted"))
    report = wire_intake_prepare(request, blobs)
    assert report["metadata_validation"]["table_rows_read"] is False
    assert report["readme_validation"]["general_yaml_parser_used"] is False
    assert not any(report["authority"].values())


# Retain the peer v2 interface and its 99-case prefix. These cases cover the
# narrow canonical-frontmatter and logical-config guards missing from that
# generation, using the same five retained HF49 metadata files and no tables.
@pytest.mark.parametrize("boundary", ["opening", "closing"])
def test_wire_intake_card_delimiters_must_be_complete_lines(monkeypatch, boundary):
    request, blobs = wire_intake_inputs()
    card = blobs["README.md"]
    if boundary == "opening":
        changed = card.replace(b"---\n", b"---garbage\n", 1)
    else:
        changed = card.replace(b"\n---\n", b"\n---garbage\n", 1)
    assert changed != card
    blobs["README.md"] = changed
    wire_intake_reseal(request, blobs)
    wire_intake_preflight_only(monkeypatch)
    with pytest.raises(ValueError):
        wire_intake_prepare(request, blobs)


@pytest.mark.parametrize("damage", [
    "default_legacy_role", "default_recovery_role", "integer_legacy_role", "integer_recovery_role",
    "default_primary_key", "default_feature_order",
])
def test_wire_intake_coherent_logical_config_roles_key_and_feature_order_refuse(monkeypatch, damage):
    request, blobs = wire_intake_inputs()
    manifest = json.loads(blobs["manifest.json"])
    logical = manifest["configs"]
    default = next(item for item in logical if item["config_name"] == WIRE_LOGICAL)
    if damage == "default_legacy_role": default["is_legacy"] = True
    elif damage == "default_recovery_role": default["is_recovery"] = True
    elif damage == "integer_legacy_role":
        next(item for item in logical if item["config_name"] == "legacy-uscode-parquet/v1")["is_legacy"] = 1
    elif damage == "integer_recovery_role":
        next(item for item in logical if item["config_name"] == "recovery-quarantine/v1")["is_recovery"] = 1
    elif damage == "default_primary_key": default["primary_key"] = "legal_id"
    else: default["features"].reverse()
    # Both declarations agree; refusal must inspect the qualified logical role,
    # key and order rather than rely on a stale companion or acquisition hash.
    configs = json.loads(blobs["dataset_configs.json"])
    configs["configs"] = deepcopy(logical)
    blobs["manifest.json"], blobs["dataset_configs.json"] = wire(manifest), wire(configs)
    wire_intake_reseal(request, blobs)
    wire_intake_preflight_only(monkeypatch)
    with pytest.raises(ValueError):
        wire_intake_prepare(request, blobs)


def test_wire_intake_literal_triple_hyphen_path_is_not_a_frontmatter_delimiter():
    request, blobs = wire_intake_inputs()
    manifest = json.loads(blobs["manifest.json"])
    descriptor = next(item for item in manifest["artifacts"] if item["family"] == "corpus")
    previous = descriptor["relative_path"]
    renamed = previous.replace("part-", "part---", 1)
    assert renamed != previous and "---" in renamed
    descriptor["relative_path"] = renamed
    old_paths = deepcopy(manifest["wire_metadata"]["data_files"][0]["path"])
    declaration = manifest["wire_metadata"]
    paths = declaration["data_files"][0]["path"]
    paths[paths.index(previous)] = renamed
    paths.sort()
    blobs["manifest.json"] = wire(manifest)
    wire_intake_set_declaration(blobs, declaration)
    before = blobs["README.md"]
    old_line = b"    path: " + json.dumps(old_paths).encode("utf-8")
    new_line = b"    path: " + json.dumps(paths).encode("utf-8")
    assert before.count(old_line) == 1
    blobs["README.md"] = before.replace(old_line, new_line, 1)
    wire_intake_reseal(request, blobs)
    report = wire_intake_prepare(request, blobs)
    assert report["schema"] == intake.SCHEMA_V2 and report["metadata_profile"] == WIRE_PROFILE
    assert report["issues"] == [] and report["readme_validation"]["recognized_regions_exact"] is True
    assert renamed in report["count_reconciliation"]["selected_descriptor_paths"]
    assert previous not in report["count_reconciliation"]["selected_descriptor_paths"]
    assert report["count_reconciliation"]["selected_descriptor_row_sum"] == 11
    assert report["count_reconciliation"]["arrow_bytes_physically_measured_here"] is False
    assert report["metadata_validation"]["table_bodies_read"] is False
    assert report["metadata_validation"]["Arrow_loaded"] is False
    assert report["source_identity"]["aliases_mapped"] is False
    assert not any(report["authority"].values())
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert wire_intake_validate(report, request, blobs) == report
