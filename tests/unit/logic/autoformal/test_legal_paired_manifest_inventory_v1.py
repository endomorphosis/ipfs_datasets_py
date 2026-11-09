"""Selected manifest custody and declared denominators, with no table execution."""
from copy import deepcopy
import builtins
import hashlib
import json
from pathlib import Path
import socket
import subprocess

import pytest

from ipfs_datasets_py.logic.autoformal import legal_paired_manifest_inventory_v1 as inventory


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def seal(manifest):
    value = deepcopy(manifest)
    value.pop("fingerprint", None)
    value.pop("path_in_repo", None)
    fingerprint = sha(wire(value))
    version = value["schema"].rsplit("/v", 1)[1]
    agent = value["agent_id"]
    value["fingerprint"] = fingerprint
    value["path_in_repo"] = f"autoformal/uscode/paired-v{version}/manifests/{agent}/manifest-{fingerprint}.json"
    return value


def manifest(version=2, *, marker="a", shared=None):
    tables = {}
    for index, kind in enumerate(inventory.TABLES):
        digest = sha((kind + marker).encode())
        filename = kind + "-" + digest + ".parquet"
        tables[kind] = {"path_in_repo": f"autoformal/uscode/paired-v{version}/{kind}/agent/{filename}",
                        "filename": filename, "sha256": digest, "bytes": 100 + index,
                        "row_count": 2 + index}
    if shared is not None:
        tables = deepcopy(shared)
    return seal({"schema": f"uscode-paired-span-bundle/v{version}", "repository_id": inventory.REPOSITORY,
        "agent_id": "agent", "tables": tables, "exporter_sha256": sha(b"exporter"),
        "original_receipt_artifact_sha256": sha(marker.encode()),
        "admitted": False, "formalized": False, "enqueued": False})


def inputs(*values):
    blobs = {value["path_in_repo"]: wire(value) for value in values}
    request = {"schema": inventory.REQUEST_SCHEMA, "repository_id": inventory.REPOSITORY,
        "revision": "a" * 40, "selection_scope": inventory.SELECTION_SCOPE,
        "manifests": [{"path_in_repo": value["path_in_repo"], "bytes": len(blobs[value["path_in_repo"]]),
                       "sha256": sha(blobs[value["path_in_repo"]])} for value in values]}
    return request, blobs


def prepare(request, blobs):
    raw = wire(request)
    return inventory.prepare_paired_manifest_inventory(raw, blobs, expected_request_sha256=sha(raw))


def validate(report, request, blobs):
    raw = wire(request)
    return inventory.validate_paired_manifest_inventory(report, raw, blobs,
        expected_request_sha256=sha(raw), expected_report_sha256=inventory.paired_manifest_inventory_sha256(report))


def owner_must_not_load(monkeypatch):
    monkeypatch.setattr(inventory, "_owners", lambda: pytest.fail("owners loaded before input preflight rejection"))


def coordinate_manifest():
    value = manifest(3)
    value["coordinate_transport"] = {
        "schema": "paired-source-coordinate-transport/v1",
        "report_artifact_sha256": sha(b"exact report artifact"),
        "report_sha256": sha(b"independently retained complete report"),
        "index_artifact_sha256": sha(b"exact coordinate index"),
    }
    return seal(value)


def coordinate_inputs(value=None):
    value = coordinate_manifest() if value is None else value
    request, blobs = inputs(value)
    request["schema"] = inventory.REQUEST_SCHEMA_V2
    request["manifests"][0]["source_coordinate_report_sha256"] = value["coordinate_transport"]["report_sha256"]
    return request, blobs


def prepare_coordinate(request, blobs):
    raw = wire(request)
    return inventory.prepare_paired_manifest_inventory_v2(raw, blobs, expected_request_sha256=sha(raw))


def test_v2_metadata_retains_independent_coordinate_declarations_without_reading_tables(monkeypatch):
    from ipfs_datasets_py.logic.autoformal import span_cache_feed
    monkeypatch.setattr(span_cache_feed, "_read_regular_snapshot",
                        lambda *a, **k: pytest.fail("metadata read a table or artifact"))
    request, blobs = coordinate_inputs()
    report = prepare_coordinate(request, blobs)
    assert report["schema"] == inventory.SCHEMA_V2
    assert set(report["analysis"]["banks"]) == {"paired-v3"}
    assert report["request"] == request
    selected = report["manifests"][0]
    assert selected["raw_utf8"].encode() == blobs[selected["path_in_repo"]]
    transport = selected["manifest"]["coordinate_transport"]
    assert selected["source_coordinate_report_sha256"] == transport["report_sha256"]
    assert transport["report_sha256"] != transport["report_artifact_sha256"]
    assert all(value is False for value in report["authority"].values())
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["metadata_validation"]["table_bytes_read"] is False
    assert report["metadata_validation"]["Arrow_loaded"] is False
    assert report["source_join"]["status"] == "unresolved_not_attempted"
    raw = wire(request)
    assert inventory.validate_paired_manifest_inventory_v2(wire(report), raw, blobs,
        expected_request_sha256=sha(raw), expected_report_sha256=inventory.paired_manifest_inventory_sha256(report)) == report


def test_legacy_metadata_still_refuses_coordinate_namespace(monkeypatch):
    request, blobs = coordinate_inputs()
    request["schema"] = inventory.REQUEST_SCHEMA
    request["manifests"][0].pop("source_coordinate_report_sha256")
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError, match="manifest path"):
        prepare(request, blobs)


@pytest.mark.parametrize("version", [1, 2])
def test_v2_metadata_refuses_legacy_namespaces_before_owner_load(monkeypatch, version):
    request, blobs = inputs(manifest(version))
    request["schema"] = inventory.REQUEST_SCHEMA_V2
    request["manifests"][0]["source_coordinate_report_sha256"] = sha(b"report")
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError, match="manifest path"):
        prepare_coordinate(request, blobs)


@pytest.mark.parametrize("damage", ["missing", "uppercase", "bool", "short", "extra"])
def test_v2_metadata_requires_closed_independent_report_pin_before_owners(monkeypatch, damage):
    request, blobs = coordinate_inputs()
    entry = request["manifests"][0]
    if damage == "missing": entry.pop("source_coordinate_report_sha256")
    elif damage == "uppercase": entry["source_coordinate_report_sha256"] = "A" * 64
    elif damage == "bool": entry["source_coordinate_report_sha256"] = True
    elif damage == "short": entry["source_coordinate_report_sha256"] = "a" * 63
    else: entry["report"] = {}
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError):
        prepare_coordinate(request, blobs)


@pytest.mark.parametrize("damage", ["missing", "extra", "schema", "report_artifact", "index_artifact", "pin"])
def test_v2_metadata_rejects_resealed_coordinate_declaration_changes(damage):
    value = coordinate_manifest()
    original_pin = value["coordinate_transport"]["report_sha256"]
    transport = value["coordinate_transport"]
    if damage == "missing": transport.pop("index_artifact_sha256")
    elif damage == "extra": transport["authority"] = True
    elif damage == "schema": transport["schema"] = "other/v1"
    elif damage == "report_artifact": transport["report_artifact_sha256"] = True
    elif damage == "index_artifact": transport["index_artifact_sha256"] = "A" * 64
    else: transport["report_sha256"] = sha(b"different complete report")
    request, blobs = coordinate_inputs(seal(value))
    request["manifests"][0]["source_coordinate_report_sha256"] = original_pin
    with pytest.raises(ValueError):
        prepare_coordinate(request, blobs)


@pytest.mark.parametrize("damage", ["drop", "pin", "bank", "authority"])
def test_rehashed_v2_metadata_cannot_replace_original_selection(damage):
    request, blobs = coordinate_inputs()
    report = prepare_coordinate(request, blobs)
    if damage == "drop": report["manifests"] = []
    elif damage == "pin": report["manifests"][0]["source_coordinate_report_sha256"] = sha(b"changed")
    elif damage == "bank": report["analysis"]["banks"] = {}
    else: report["authority"]["source_occurrences_bound"] = True
    raw = wire(request)
    with pytest.raises(ValueError, match="full authoritative replay"):
        inventory.validate_paired_manifest_inventory_v2(report, raw, blobs,
            expected_request_sha256=sha(raw), expected_report_sha256=inventory.paired_manifest_inventory_sha256(report))


def test_mixed_versions_exact_raw_custody_and_no_authority():
    request, blobs = inputs(manifest(2), manifest(1))
    before_request, before_blobs = deepcopy(request), dict(blobs)
    report = prepare(request, blobs)
    assert validate(report, request, blobs) == report
    raw = wire(request)
    assert inventory.validate_paired_manifest_inventory(wire(report), raw, blobs,
        expected_request_sha256=sha(raw), expected_report_sha256=inventory.paired_manifest_inventory_sha256(report)) == report
    assert request == before_request and blobs == before_blobs
    assert report["request"] == request and report["request_raw_utf8"].encode() == raw
    assert [row["path_in_repo"] for row in report["manifests"]] == list(blobs)
    assert [row["selection_ordinal"] for row in report["manifests"]] == [0, 1]
    for row in report["manifests"]:
        assert row["raw_utf8"].encode() == blobs[row["path_in_repo"]]
        assert row["sha256"] == sha(blobs[row["path_in_repo"]])
        assert row["manifest"] == json.loads(blobs[row["path_in_repo"]])
    for bank in ("paired-v1", "paired-v2"):
        for index, kind in enumerate(inventory.TABLES):
            assert report["analysis"]["banks"][bank][kind] == {
                "manifest_reference_count": 1, "declared_row_sum": 2 + index,
                "distinct_physical_path_count": 1, "distinct_path_declared_row_sum": 2 + index,
                "declared_bytes_references": 100 + index, "distinct_path_declared_bytes": 100 + index,
                "distinct_declared_sha256_count": 1}
    assert report["analysis"]["distinct_physical_table_path_count"] == 6
    assert report["source_join"]["source_occurrences"] is None
    assert report["source_join"]["formalization_attempts"] is None
    assert report["source_join"]["bindings"] == []
    assert not any(report["authority"].values())
    assert all(type(value) is bool for value in report["authority"].values())
    assert report["migration_eligibility"].startswith("unknown_")
    for field in ("human_reviews", "signatures_constructed", "admissions", "graph_admissions", "training_mask", "evaluation_gold_mask"):
        assert type(report[field]) is int and report[field] == 0
    assert report["metadata_validation"]["manifest_content_fingerprints_verified"]
    assert not report["metadata_validation"]["remote_revision_authenticated_by_this_operation"]
    assert len(report["producer_pins"]) == 6
    assert all(sha(Path(path).read_bytes()) == digest for path, digest in report["producer_pins"].items())


def test_identical_references_are_retained_without_double_counting_physical_paths():
    first = manifest()
    second = manifest(marker="other", shared=first["tables"])
    request, blobs = inputs(first, second)
    report = prepare(request, blobs)
    for index, kind in enumerate(inventory.TABLES):
        counts = report["analysis"]["banks"]["paired-v2"][kind]
        assert counts["manifest_reference_count"] == 2
        assert counts["declared_row_sum"] == 2 * (2 + index)
        assert counts["declared_bytes_references"] == 2 * (100 + index)
        assert counts["distinct_physical_path_count"] == 1
        assert counts["distinct_path_declared_row_sum"] == 2 + index
        assert counts["distinct_path_declared_bytes"] == 100 + index
    assert len(report["analysis"]["descriptor_references"]) == 6
    assert report["analysis"]["distinct_physical_table_path_count"] == 3


def test_same_declared_content_at_different_paths_is_not_a_source_or_attempt_merge():
    first, second = manifest(marker="a"), manifest(marker="b")
    for kind in inventory.TABLES:
        descriptor = second["tables"][kind]
        digest = first["tables"][kind]["sha256"]
        name = kind + "-" + "f" * 64 + "-" + digest + ".parquet"
        descriptor.update(filename=name, sha256=digest,
            path_in_repo=f"autoformal/uscode/paired-v2/{kind}/agent/{name}")
    second = seal(second)
    request, blobs = inputs(first, second)
    report = prepare(request, blobs)
    counts = report["analysis"]["banks"]["paired-v2"]["paired_spans"]
    assert counts["distinct_physical_path_count"] == 2 and counts["distinct_declared_sha256_count"] == 1
    assert counts["distinct_path_declared_row_sum"] == counts["declared_row_sum"] == 4
    assert report["analysis"]["unique_source_occurrence_count"] is None
    assert report["analysis"]["unique_formalization_attempt_count"] is None


def test_analysis_is_sorted_but_request_order_and_raw_spelling_are_retained():
    a, b = manifest(marker="a"), manifest(marker="b")
    r1, blobs = inputs(a, b)
    r2, _ = inputs(b, a)
    assert prepare(r1, blobs)["analysis"] == prepare(r2, blobs)["analysis"]
    raw = json.dumps(r1, indent=2).encode()
    report = inventory.prepare_paired_manifest_inventory(raw, blobs, expected_request_sha256=sha(raw))
    assert report["request_raw_utf8"].encode() == raw
    assert report["request"] == r1


def test_empty_selection_is_only_no_evidence_for_the_explicit_selection():
    request, blobs = inputs()
    report = prepare(request, blobs)
    assert report["status"] == "empty_explicit_selection_no_evidence"
    assert report["selection_complete"] and not report["authority"]["remote_inventory_exhaustive"]
    assert report["manifests"] == [] and report["analysis"]["selected_manifest_count"] == 0
    assert report["source_join"]["source_occurrences"] is None
    assert all(count == 0 for bank in report["analysis"]["banks"].values() for counts in bank.values() for count in counts.values())


@pytest.mark.parametrize("field", ["schema", "repository_id", "revision", "selection_scope", "manifests"])
def test_missing_request_fields_fail_before_owner_load(monkeypatch, field):
    request, blobs = inputs(manifest())
    del request[field]
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError): prepare(request, blobs)


@pytest.mark.parametrize("field,value", [("schema", "other"), ("repository_id", "other/repo"),
    ("revision", "main"), ("revision", "A" * 40), ("revision", "a" * 39),
    ("selection_scope", "complete_remote_tree"), ("manifests", {}), ("extra", None)])
def test_bad_request_fields_fail_before_owner_load(monkeypatch, field, value):
    request, blobs = inputs(manifest())
    request[field] = value
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError): prepare(request, blobs)


@pytest.mark.parametrize("field,value", [("path_in_repo", "/tmp/offered"), ("path_in_repo", "autoformal/uscode/paired-v3/manifests/a/manifest-" + "a" * 64 + ".json"),
    ("path_in_repo", "autoformal/uscode/paired-v2/../weights/model.bin"), ("bytes", True),
    ("bytes", 1.0), ("bytes", 0), ("bytes", 65537), ("sha256", "A" * 64), ("extra", None)])
def test_bad_selected_descriptor_fails_before_owner_load(monkeypatch, field, value):
    request, blobs = inputs(manifest())
    request["manifests"][0][field] = value
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError): prepare(request, blobs)


@pytest.mark.parametrize("field", ["path_in_repo", "bytes", "sha256"])
def test_missing_selected_descriptor_field_fails_before_owner_load(monkeypatch, field):
    request, blobs = inputs(manifest())
    del request["manifests"][0][field]
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError): prepare(request, blobs)


def test_total_manifest_byte_bound_fails_before_owner_load(monkeypatch):
    request, blobs = inputs(*(manifest(marker=str(index)) for index in range(9)))
    for entry in request["manifests"]: entry["bytes"] = inventory.MAX_MANIFEST_BYTES
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError, match="total byte bound"): prepare(request, blobs)


@pytest.mark.parametrize("mutation", ["duplicate", "too_many", "map_missing", "map_extra", "map_type", "map_key_type", "value_type", "value_hash", "value_size"])
def test_exact_mapping_and_population_preflight(monkeypatch, mutation):
    request, blobs = inputs(manifest())
    path = request["manifests"][0]["path_in_repo"]
    if mutation == "duplicate": request["manifests"] *= 2
    elif mutation == "too_many": request["manifests"] *= 17
    elif mutation == "map_missing": blobs = {}
    elif mutation == "map_extra": blobs["extra"] = b"{}"
    elif mutation == "map_type": blobs = list(blobs.items())
    elif mutation == "map_key_type": blobs[3] = b"{}"
    elif mutation == "value_type": blobs[path] = bytearray(blobs[path])
    elif mutation == "value_hash": blobs[path] = blobs[path].replace(b"agent", b"AGENT", 1)
    elif mutation == "value_size": blobs[path] += b" "
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError): prepare(request, blobs)


@pytest.mark.parametrize("raw", [b"", b"\xff", b"[]", b'{"a":1,"a":2}', b'{"x":NaN}', b"{" * 400, b" " * (128 * 1024 + 1)])
def test_bad_raw_request_fails_before_owner_load(monkeypatch, raw):
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError): inventory.prepare_paired_manifest_inventory(raw, {}, expected_request_sha256=sha(raw))


def test_raw_request_type_and_independent_hash_are_required(monkeypatch):
    request, blobs = inputs(manifest())
    raw = wire(request)
    owner_must_not_load(monkeypatch)
    for value, pin in ((raw.decode(), sha(raw)), (bytearray(raw), sha(raw)), (raw, "0" * 64), (raw, None)):
        with pytest.raises(ValueError): inventory.prepare_paired_manifest_inventory(value, blobs, expected_request_sha256=pin)


@pytest.mark.parametrize("raw", [b'{}\n{"b":1}', b'{"x":1,"x":2}', b'{"x":Infinity}', b"[]", b"\xff"])
def test_malformed_manifest_json_fails_before_owner_load(monkeypatch, raw):
    request, blobs = inputs(manifest())
    path = request["manifests"][0]["path_in_repo"]
    blobs[path] = raw
    request["manifests"][0].update(bytes=len(raw), sha256=sha(raw))
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError): prepare(request, blobs)


@pytest.mark.parametrize("mutation", ["fingerprint", "repository", "path", "version", "agent", "authority", "extra_table", "wrong_table_kind", "table_hash", "row_bool", "row_negative", "size_bool", "filename", "foreign_path"])
def test_existing_transport_owner_rejects_altered_manifest(mutation):
    value = manifest()
    if mutation == "fingerprint": value["fingerprint"] = "f" * 64
    elif mutation == "repository": value["repository_id"] = "other/repo"
    elif mutation == "path": value["path_in_repo"] = "offered/path"
    elif mutation == "version": value["schema"] = "uscode-paired-span-bundle/v1"
    elif mutation == "agent": value["agent_id"] = "other"
    elif mutation == "authority": value["admitted"] = True
    elif mutation == "extra_table": value["tables"]["extra"] = {}
    elif mutation == "wrong_table_kind": value["tables"]["paired_spans"] = deepcopy(value["tables"]["goals"])
    elif mutation == "table_hash": value["tables"]["paired_spans"]["sha256"] = "f" * 64
    elif mutation == "row_bool": value["tables"]["paired_spans"]["row_count"] = True
    elif mutation == "row_negative": value["tables"]["paired_spans"]["row_count"] = -1
    elif mutation == "size_bool": value["tables"]["paired_spans"]["bytes"] = True
    elif mutation == "filename": value["tables"]["paired_spans"]["filename"] = "other.parquet"
    elif mutation == "foreign_path": value["tables"]["paired_spans"]["path_in_repo"] = "/tmp/offered"
    if mutation not in {"fingerprint", "path", "version", "agent"}: value = seal(value)
    # Preserve the original selected namespace when altering its internal declaration.
    selected_path = manifest()["path_in_repo"] if mutation in {"path", "version", "agent"} else value["path_in_repo"]
    raw = wire(value)
    request, _ = inputs(manifest())
    request["manifests"] = [{"path_in_repo": selected_path, "bytes": len(raw), "sha256": sha(raw)}]
    with pytest.raises(ValueError): prepare(request, {selected_path: raw})


@pytest.mark.parametrize("field,value", [("row_count", 9), ("bytes", 999), ("extra", "contradicting_reference")])
def test_same_physical_path_with_conflicting_descriptor_is_rejected(field, value):
    first = manifest()
    second = manifest(marker="second", shared=first["tables"])
    second["tables"]["paired_spans"][field] = value
    second = seal(second)
    request, blobs = inputs(first, second)
    with pytest.raises(ValueError, match="conflicting descriptors"): prepare(request, blobs)


@pytest.mark.parametrize("field,value", [("status", "admitted"), ("revision", "b" * 40),
    ("selection_complete", False), ("source_join", {"status": "bound"}), ("training_mask", 1),
    ("migration_eligibility", "eligible"), ("analysis", {}), ("authority", {"admitted": True}),
    ("manifests", []), ("request_raw_utf8", "{}")])
def test_rehashed_report_mutations_fail_complete_regeneration(field, value):
    request, blobs = inputs(manifest())
    report = prepare(request, blobs)
    report[field] = value
    with pytest.raises(ValueError, match="full authoritative replay"): validate(report, request, blobs)


def test_report_validation_never_opens_offered_producer_or_descriptor_paths(monkeypatch):
    request, blobs = inputs(manifest())
    report = prepare(request, blobs)
    report["producer_pins"]["/tmp/offered-secret"] = "0" * 64
    report["manifests"][0]["manifest"]["tables"]["paired_spans"]["path_in_repo"] = "/tmp/offered-table"
    original = Path.read_bytes
    def guarded(path):
        assert not str(path).startswith("/tmp/offered")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    with pytest.raises(ValueError, match="full authoritative replay"): validate(report, request, blobs)


def test_report_hash_bounds_and_duplicate_report_json_fail_without_owners(monkeypatch):
    owner_must_not_load(monkeypatch)
    for value in ({"x": float("nan")}, {"x": object()}, {"x": "x" * inventory.MAX_REPORT_BYTES}):
        with pytest.raises(ValueError): inventory.paired_manifest_inventory_sha256(value)
    request, blobs = inputs()
    raw = wire(request)
    with pytest.raises(ValueError): inventory.validate_paired_manifest_inventory(b'{"x":1,"x":2}', raw, blobs,
        expected_request_sha256=sha(raw), expected_report_sha256="0" * 64)


def test_wrong_report_pin_is_rejected_before_regeneration(monkeypatch):
    request, blobs = inputs(manifest())
    report = prepare(request, blobs)
    raw = wire(request)
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError, match="report SHA256 mismatch"):
        inventory.validate_paired_manifest_inventory(report, raw, blobs,
            expected_request_sha256=sha(raw), expected_report_sha256="0" * 64)


def test_manifest_mapping_is_captured_before_owner_operations(monkeypatch):
    request, blobs = inputs(manifest())
    original = inventory._owners
    calls = 0
    def changed():
        nonlocal calls
        calls += 1
        if calls == 1: blobs.clear()
        return original()
    monkeypatch.setattr(inventory, "_owners", changed)
    report = prepare(request, blobs)
    assert report["manifests"][0]["sha256"] == request["manifests"][0]["sha256"]


@pytest.mark.parametrize("when", ["before", "during", "serialization"])
def test_trusted_owner_freshness_before_during_and_after_serialization(monkeypatch, when):
    request, blobs = inputs(manifest())
    report = prepare(request, blobs)
    target = next(path for path in report["producer_pins"] if path.endswith("/span_cache_feed.py"))
    original_read, original_analysis, original_wire = Path.read_bytes, inventory._analysis, inventory._wire
    drift = when == "before"
    def read(path):
        raw = original_read(path)
        return raw + b"\n" if drift and str(path.resolve()) == target else raw
    def analysis(rows):
        nonlocal drift
        result = original_analysis(rows)
        if when == "during": drift = True
        return result
    def encoded(value, maximum):
        nonlocal drift
        result = original_wire(value, maximum)
        if when == "serialization" and type(value) is dict and value.get("schema") == inventory.SCHEMA:
            drift = True
        return result
    monkeypatch.setattr(Path, "read_bytes", read)
    monkeypatch.setattr(inventory, "_analysis", analysis)
    monkeypatch.setattr(inventory, "_wire", encoded)
    with pytest.raises(ValueError, match="owner changed|owners changed"): prepare(request, blobs)


def test_self_producer_pin_cannot_be_supplied_or_bypassed(monkeypatch):
    request, blobs = inputs(manifest())
    monkeypatch.setattr(inventory, "_SELF_PIN", "0" * 64)
    with pytest.raises(ValueError, match="producer changed since import"): prepare(request, blobs)


def test_prepare_and_replay_read_only_known_producers_without_external_operations(monkeypatch):
    request, blobs = inputs(manifest(1), manifest(2))
    report = prepare(request, blobs)
    allowed = set(report["producer_pins"])
    original_read = Path.read_bytes
    original_open, original_import = Path.open, builtins.__import__
    def read(path):
        assert str(path.resolve()) in allowed
        return original_read(path)
    def denied(*args, **kwargs): pytest.fail("external operation or table loader invoked")
    def opened(path, mode="r", *args, **kwargs):
        assert mode == "rb" and str(path.resolve()) in allowed
        return original_open(path, mode, *args, **kwargs)
    def imported(name, *args, **kwargs):
        assert name.split(".", 1)[0] not in {"pyarrow", "duckdb", "torch", "transformers", "huggingface_hub"}
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(Path, "read_bytes", read)
    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(builtins, "__import__", imported)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    feed, _ = inventory._owners()
    monkeypatch.setattr(feed, "SpanCacheFeed", denied)
    monkeypatch.setattr(feed, "HubExchangeClient", denied)
    monkeypatch.setattr(feed, "load_exchange_bundle", denied)
    assert validate(report, request, blobs) == report
