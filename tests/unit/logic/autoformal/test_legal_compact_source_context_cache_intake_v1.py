"""Lossless selected cache records remain observations, never inference inputs.

Authored bundles use the real paired producer, typed Arrow tables and public
intake. Their legacy diagnostic vectors are fixture data, not model execution.
The separate real phase reads both complete retained60501 bundles in place.
No network, database, model, training, prover or Lean call belongs to this suite.
Execution is restricted to the coordinator's owned qualification child.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_cache_intake_v1 as subject
from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_inventory_v1 as inventory_owner
from ipfs_datasets_py.logic.autoformal import legal_paired_payload_intake_v1 as payload_owner
from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
from tests.unit.logic.autoformal.test_legal_compact_source_context_inventory_v1 import (
    case as inventory_case, originals as inventory_raws, resolver as source_resolver,
)


REVISION = "e" * 40
TARGET_MARKER = "OPAQUE_TARGET_MUST_NOT_ENTER_LEXICAL_CONTEXT"


def wire(value, *, ascii_only=False):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=ascii_only, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def source_row(span, text, marker):
    rule = {"modality": "Obligation", "actor": marker, "action": "retain", "object": "record"}
    return {"source_span_id": span, "text": text, "legal_id": "usc:us:10:1",
        "release_id": "authored-cached-source-release",
        "compiler_result": {"compiler_status": "compiled", "rules": [rule], "components": [],
            "compilation_complete": True, "decompiled": text, "roundtrip": True},
        "autoencoder_observation": {"raw_decoder": {"embedding": [0.125] * 8},
            "embedding_representation": {"embedding_model": "mock:authored-cache-diagnostic/8",
                "semantic_embeddings": False}}}


def serialize_bundle(root, label, observations):
    """Encode real producer outputs; no alternate cache decoder is supplied."""
    receipt = {"rows": [{"source_span_id": row["source_span_id"], "text": row["text"]}
        for row in observations], "authored_diagnostic": True}
    bundle = paired.build_paired_census(observations, agent_id=label,
        code_identity="authored-cache-intake-control", model_identity="diagnostic:no-model-execution",
        original_receipt=receipt)
    tables, files = {}, {}
    for kind in paired.TABLE_NAMES:
        table = pa.Table.from_pylist(bundle[kind], schema=paired.arrow_schemas(paired.SCHEMA)[kind])
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink, compression="zstd", row_group_size=2)
        raw = sink.getvalue().to_pybytes()
        digest = sha(raw)
        filename = kind + "-" + "1" * 64 + "-" + digest + ".parquet"
        name = "autoformal/uscode/paired-v2/" + kind + "/" + label + "/" + filename
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        files[name] = path
        tables[kind] = {"path_in_repo": name, "filename": filename,
            "sha256": digest, "bytes": len(raw), "row_count": len(bundle[kind])}
    manifest = {"schema": "uscode-paired-span-bundle/v2", "repository_id": paired.REPOSITORY,
        "agent_id": label, "tables": tables,
        "original_receipt_artifact_sha256": bundle["original_receipt_artifact_sha256"],
        "admitted": False, "formalized": False, "enqueued": False}
    fingerprint = sha(wire(manifest, ascii_only=True))
    name = "autoformal/uscode/paired-v2/manifests/" + label + "/manifest-" + fingerprint + ".json"
    manifest.update(fingerprint=fingerprint, path_in_repo=name)
    raw = wire(manifest, ascii_only=True)
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    files[name] = path
    return bundle, manifest, {"path_in_repo": name, "bytes": len(raw), "sha256": sha(raw)}, files


@pytest.fixture
def material(inventory_case, tmp_path):
    raw, options = inventory_raws(inventory_case)
    original_inputs = {**dict(zip(("population_raw", "occurrences_raw", "catalog_raw", "access_raw"), raw)),
        **options, "source_resolver": source_resolver(inventory_case)}
    report = inventory_owner.prepare_source_context_inventory_v1(*raw,
        **options, source_resolver=source_resolver(inventory_case))
    original_inputs["expected_report_sha256"] = sha(wire(report))
    root = tmp_path / "authored-repository" / REVISION
    text = inventory_case["inputs"]["same-left"]["text"]
    definitions = [
        ("authored-left", [source_row("competing-span", text, TARGET_MARKER + "_ONE"),
            source_row("ambiguous-span", text, TARGET_MARKER + "_TWO")], [["same-left"], ["same-left", "same-right"]]),
        ("authored-right", [source_row("competing-span", text, TARGET_MARKER + "_RIVAL"),
            source_row("unmatched-span", "Cache source with no inventory counterpart.", TARGET_MARKER + "_UNMATCHED")],
            [["same-left"], []]),
    ]
    bundles, manifest_bytes, entries, files, bindings = [], {}, [], {}, []
    for label, observations, associations in definitions:
        bundle, manifest, entry, paths = serialize_bundle(root, label, observations)
        bundles.append((bundle, manifest))
        entries.append(entry)
        files.update(paths)
        manifest_bytes[entry["path_in_repo"]] = paths[entry["path_in_repo"]].read_bytes()
        for ordinal, (row, occurrence_ids) in enumerate(zip(bundle["paired_spans"], associations)):
            bindings.append({"manifest_path_in_repo": entry["path_in_repo"], "row_ordinal": ordinal,
                "row_sha256": sha(wire(row, ascii_only=True)), "occurrence_ids": occurrence_ids})
    request = {"schema": "legal-paired-manifest-inventory-request/v1", "repository_id": paired.REPOSITORY,
        "revision": REVISION, "selection_scope": "explicit_paired_manifest_selection", "manifests": entries}
    association_document = {"schema": "legal-compact-source-context-cache-bindings/v1",
        "cache_request_sha256": sha(wire(request)), "inventory_report_sha256": sha(wire(report)), "rows": bindings}
    return {"request": request, "bindings": association_document, "manifest_bytes": manifest_bytes,
        "root": root, "inventory_report": report, "inventory_originals": original_inputs,
        "inventory_case": inventory_case, "bundles": bundles, "files": files}


def arguments(material):
    request_raw, bindings_raw = wire(material["request"]), wire(material["bindings"])
    return (request_raw, bindings_raw), {"expected_cache_request_sha256": sha(request_raw),
        "expected_cache_bindings_sha256": sha(bindings_raw), "repository_root": str(material["root"]),
        "manifest_bytes": material["manifest_bytes"], "inventory_report": material["inventory_report"],
        "inventory_originals": material["inventory_originals"]}


def prepare(material, **changes):
    raw, options = arguments(material)
    return subject.prepare_source_context_cache_intake_v1(*raw, **{**options, **changes})


def replay(material, report, **changes):
    raw, options = arguments(material)
    return subject.validate_source_context_cache_intake_v1(report, *raw,
        **{**options, "expected_report_sha256": sha(wire(report)), **changes})


def no_authority(report):
    assert report["authority"] and all(flag is False for flag in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert report["entity_definition_intake"] == "not_scanned"
    for record in report["records"]:
        assert record["inference_view"] is None
        assert record["authority"] and all(flag is False for flag in record["authority"].values())
        assert type(record["training_mask"]) is int and record["training_mask"] == 0
        assert type(record["evaluation_gold_mask"]) is int and record["evaluation_gold_mask"] == 0
    assert all(row["inference_view"] is None for row in report["occurrences"])
    assert all(row["inference_view"] is None for row in report["inventory_report"]["rows"])


def file_reference(path, raw=None):
    path = Path(path)
    if raw is not None: path.write_bytes(raw)
    body = path.read_bytes()
    return {"path": str(path.absolute()), "bytes": len(body), "sha256": sha(body)}


def retain(material, report, replayed, destination, *, real):
    destination.mkdir()
    raw, _ = arguments(material)
    inventory = material["inventory_case"]
    originals = {name: file_reference(destination / (name + ".json"), body)
        for name, body in zip(("cache-request", "cache-bindings"), raw)}
    for name in ("population", "occurrences", "catalog", "access"):
        originals[name] = file_reference(destination / (name + ".json"),
            material["inventory_originals"][name + "_raw"])
    originals["source-inventory"] = file_reference(destination / "source-inventory.json", inventory["inventory"].to_bytes())
    originals["source-partitions"] = file_reference(destination / "source-partitions.json", inventory["partitions"].to_bytes())
    originals["inventory-report"] = file_reference(destination / "inventory-report.json", wire(material["inventory_report"]))
    sources = [{"artifact": {"sha256": digest, "bytes": len(body)},
        "file": file_reference(destination / ("source-" + digest + ".txt"), body)}
        for digest, body in sorted(inventory["artifacts"].items())]
    return {"schema": "legal-compact-source-context-cache-intake-" + ("engineering" if real else "authored") + "-evidence/v1",
        "scope": "selected_retained_historical_bundles" if real else "authored_cache_codec_controls",
        "originals": originals, "source_artifacts": sources,
        "missing_source_artifacts": [inventory["inputs"]["missing"]["source"]["artifact"]],
        "cache_files": [file_reference(path) for _, path in sorted(material["files"].items())],
        "report": file_reference(destination / "report.json", wire(report)),
        "replayed_report": file_reference(destination / "replayed-report.json", wire(replayed)),
        "cache_revision": material["request"]["revision"], "physical_record_count": len(report["records"]),
        "inventory_occurrence_count": len(report["occurrences"]), "model_executed": False,
        "training_executed": False, "database_executed": False, "prover_executed": False,
        "inference_permission_verified": False, "remote_revision_authenticated": False,
        "training_mask": 0, "evaluation_gold_mask": 0}


def test_real_public_authored_intake_preserves_competing_physical_records_without_context_leak(material, tmp_path):
    original_inventory = deepcopy(material["inventory_report"])
    report = prepare(material)
    replayed = replay(material, report)
    assert replayed == report and replayed is not report
    assert subject.source_context_cache_intake_sha256(report) == sha(wire(report))
    assert report["inventory_report"] == original_inventory
    assert len(report["bundles"]) == 2 and len(report["records"]) == 4
    assert report["coverage"]["declared_reference_rows"] == report["coverage"]["verified_reference_rows"] == 4
    assert report["coverage"]["full_declared_population_retained"] is True
    assert report["coverage"]["inventory_occurrences"] == 5
    assert [record["association_status"] for record in report["records"]] == [
        "declared_single_association", "ambiguous_source_occurrences", "declared_single_association", "unresolved_source_occurrence"]
    assert [record["row_ordinal"] for record in report["records"]] == [0, 1, 0, 1]
    for record, original in zip(report["records"], [row for bundle, _ in material["bundles"] for row in bundle["paired_spans"]]):
        assert record["record_status"] == "verified"
        assert record["derived_row_json"].encode() == wire(original, ascii_only=True)
        assert record["row_sha256"] == sha(wire(original, ascii_only=True))
        assert record["source_observation"] == original["source"]
        assert record["revision"] == REVISION and record["source_observation"]["revision"] != REVISION
        assert all(item["source_correspondence_verified"] is False for item in record["association_results"])
    first, _, rival, _ = report["records"]
    assert first["source_observation"]["span_id"] == rival["source_observation"]["span_id"]
    assert first["physical_record_id"] != rival["physical_record_id"]
    assert first["row_sha256"] != rival["row_sha256"]
    assert TARGET_MARKER in first["derived_row_json"] and TARGET_MARKER in rival["derived_row_json"]
    assert TARGET_MARKER not in wire(report["inventory_report"]).decode()
    assert [row["id"] for row in report["occurrences"]] == material["inventory_case"]["selected"]
    assert len(report["occurrences"][0]["cache_reference_ids"]) == 3
    assert report["occurrences"][2]["association_status"] == "no_cache_association"
    no_authority(report)
    evidence = retain(material, report, replayed, tmp_path / "authored-originals", real=False)
    (tmp_path / "source-context-cache-intake-authored-evidence.json").write_bytes(wire(evidence))


@pytest.mark.skipif(not all(os.environ.get(name) for name in (
    "LEGAL_COMPACT_SOURCE_CONTEXT_CACHE_REQUEST", "LEGAL_COMPACT_SOURCE_CONTEXT_CACHE_COMMITMENTS",
    "LEGAL_COMPACT_SOURCE_CONTEXT_CACHE_ROOT")), reason="retainedcacheintegrationnotconfigured")
def test_complete_two_retained_real_bundles_keep_all_sixteen_rows_unassociated(material, tmp_path):
    request_path = Path(os.environ["LEGAL_COMPACT_SOURCE_CONTEXT_CACHE_REQUEST"])
    commitments_path = Path(os.environ["LEGAL_COMPACT_SOURCE_CONTEXT_CACHE_COMMITMENTS"])
    real_root = Path(os.environ["LEGAL_COMPACT_SOURCE_CONTEXT_CACHE_ROOT"])
    request_raw = request_path.read_bytes()
    commitments = json.loads(commitments_path.read_bytes())
    request = json.loads(request_raw)
    assert request["revision"] == commitments["revision"] == "60501f3e920f6c9050cfc452e0d9fcc2b7c184f3"
    assert len(commitments["rows"]) == 16 and all(row["occurrence_ids"] == [] for row in commitments["rows"])
    material["root"], material["request"] = real_root, request
    material["manifest_bytes"] = {entry["path_in_repo"]: (real_root / entry["path_in_repo"]).read_bytes()
        for entry in request["manifests"]}
    material["bindings"] = {"schema": "legal-compact-source-context-cache-bindings/v1",
        "cache_request_sha256": sha(wire(request)),
        "inventory_report_sha256": sha(wire(material["inventory_report"])), "rows": commitments["rows"]}
    files = {}
    for entry in request["manifests"]:
        path = entry["path_in_repo"]
        files[path] = real_root / path
        manifest = json.loads(material["manifest_bytes"][path])
        for descriptor in manifest["tables"].values(): files[descriptor["path_in_repo"]] = real_root / descriptor["path_in_repo"]
    material["files"] = files
    report = prepare(material)
    replayed = replay(material, report)
    assert report == replayed
    assert len(report["records"]) == report["coverage"]["declared_reference_rows"] == 16
    assert [bundle["declared_rows"] for bundle in report["bundles"]] == [8, 8]
    assert all(record["record_status"] == "verified" for record in report["records"])
    assert all(record["association_status"] == "unresolved_source_occurrence" for record in report["records"])
    assert all(record["occurrence_ids"] == [] for record in report["records"])
    assert len({record["physical_record_id"] for record in report["records"]}) == 16
    assert report["coverage"]["associated_inventory_occurrences"] == 0
    assert report["coverage"]["unassociated_inventory_occurrences"] == 5
    assert all(record["revision"] != record["source_observation"]["revision"] for record in report["records"])
    assert all(record["derived_row_json"] is not None for record in report["records"])
    no_authority(report)
    evidence = retain(material, report, replayed, tmp_path / "real-originals", real=True)
    evidence["request_declaration"] = file_reference(request_path)
    evidence["row_commitments"] = file_reference(commitments_path)
    (tmp_path / "source-context-cache-intake-engineering-evidence.json").write_bytes(wire(evidence))


@pytest.mark.parametrize("pin", ["cache_request", "cache_bindings", "inventory_report"])
def test_wrong_original_pins_refuse_before_paired_payload_use(material, monkeypatch, pin):
    def forbidden(**kwargs): pytest.fail("wrong original pin reached paired payload")
    monkeypatch.setattr(payload_owner, "prepare_paired_payload_intake", forbidden)
    changes = {}
    if pin == "inventory_report":
        material["inventory_originals"]["expected_report_sha256"] = "0" * 64
    else: changes["expected_" + pin + "_sha256"] = "0" * 64
    with pytest.raises(ValueError): prepare(material, **changes)


@pytest.mark.parametrize("damage", ["mutable_revision", "repository", "duplicate_manifest", "target_field"])
def test_closed_immutable_request_refuses_invalid_selection(material, damage):
    if damage == "mutable_revision": material["request"]["revision"] = "main"
    elif damage == "repository": material["request"]["repository_id"] = "other/cache"
    elif damage == "duplicate_manifest": material["request"]["manifests"].append(deepcopy(material["request"]["manifests"][0]))
    else: material["request"]["expected_formula"] = {"tree": ["predicate", 0]}
    material["bindings"]["cache_request_sha256"] = sha(wire(material["request"]))
    with pytest.raises(ValueError): prepare(material)


def test_huge_declared_row_population_refuses_before_file_scan_or_payload_allocation(material, monkeypatch):
    entry = material["request"]["manifests"][0]
    previous = entry["path_in_repo"]
    manifest = deepcopy(material["bundles"][0][1])
    manifest.pop("fingerprint")
    manifest.pop("path_in_repo")
    manifest["tables"]["paired_spans"]["row_count"] = 10 ** 9
    fingerprint = sha(wire(manifest, ascii_only=True))
    path = str(Path(previous).parent / ("manifest-" + fingerprint + ".json"))
    manifest.update(fingerprint=fingerprint, path_in_repo=path)
    raw = wire(manifest, ascii_only=True)
    material["manifest_bytes"].pop(previous)
    material["manifest_bytes"][path] = raw
    destination = material["root"] / path
    destination.write_bytes(raw)
    entry.update(path_in_repo=path, bytes=len(raw), sha256=sha(raw))
    for row in material["bindings"]["rows"]:
        if row["manifest_path_in_repo"] == previous: row["manifest_path_in_repo"] = path
    material["bindings"]["cache_request_sha256"] = sha(wire(material["request"]))
    def forbidden(*args, **kwargs): pytest.fail("unbounded declared population reached file scan or payload allocation")
    monkeypatch.setattr(subject, "_files", forbidden)
    monkeypatch.setattr(payload_owner, "prepare_paired_payload_intake", forbidden)
    with pytest.raises(ValueError): prepare(material)


@pytest.mark.parametrize("damage", ["missing", "duplicate", "order", "orphan"])
def test_bindings_cover_exact_ordered_manifest_declared_slots(material, damage):
    rows = material["bindings"]["rows"]
    if damage == "missing": rows.pop()
    elif damage == "duplicate": rows.append(deepcopy(rows[0]))
    elif damage == "order": rows.reverse()
    else: rows[0]["manifest_path_in_repo"] = "unselected/manifest.json"
    with pytest.raises(ValueError): prepare(material)


@pytest.mark.parametrize("damage", ["hash", "ordinal", "unknown_occurrence", "duplicate_occurrence", "origin_payload"])
def test_resealed_association_declarations_cannot_change_slots_or_inventory_membership(material, damage):
    row = material["bindings"]["rows"][0]
    if damage == "hash": row["row_sha256"] = "0" * 64
    elif damage == "ordinal": row["row_ordinal"] = True
    elif damage == "unknown_occurrence": row["occurrence_ids"] = ["not-in-inventory"]
    elif damage == "duplicate_occurrence": row["occurrence_ids"] = ["same-left", "same-left"]
    else: row["target_ast"] = ["predicate", 0]
    with pytest.raises(ValueError): prepare(material)


def test_explicit_text_mismatch_is_retained_as_failed_association_not_a_dropped_record(material):
    material["bindings"]["rows"][0]["occurrence_ids"] = ["no-match"]
    report = prepare(material)
    row = report["records"][0]
    assert row["association_status"] == "association_source_mismatch"
    assert row["association_results"][0]["exact_text_sha256_match"] is False
    assert len(report["records"]) == 4 and report["coverage"]["declared_reference_rows"] == 4
    assert row["derived_row_json"] is not None
    no_authority(report)


def test_equal_text_never_creates_an_undeclared_source_occurrence_association(material):
    material["bindings"]["rows"][0]["occurrence_ids"] = []
    report = prepare(material)
    assert report["records"][0]["association_status"] == "unresolved_source_occurrence"
    assert report["records"][0]["association_results"] == []
    no_authority(report)


def test_null_row_pin_is_derived_only_from_verified_table_and_stays_null_after_corruption(material):
    material["bindings"]["rows"][0]["row_sha256"] = None
    report = prepare(material)
    record = report["records"][0]
    assert record["expected_row_sha256"] is None
    assert record["row_sha256"] == sha(wire(material["bundles"][0][0]["paired_spans"][0], ascii_only=True))
    descriptor = material["bundles"][0][1]["tables"]["paired_spans"]
    (material["root"] / descriptor["path_in_repo"]).write_bytes(b"corrupt authored table")
    failed = prepare(material)
    assert failed["records"][0]["expected_row_sha256"] is None
    assert failed["records"][0]["row_sha256"] is failed["records"][0]["record_sha256"] is None
    assert len(failed["records"]) == 4
    no_authority(failed)


@pytest.mark.parametrize("kind", ["paired_spans", "goals", "artifacts", "missing"])
def test_failed_public_bundle_keeps_every_declared_record_slot(material, kind):
    table_kind = "paired_spans" if kind == "missing" else kind
    manifest = material["bundles"][0][1]
    path = material["root"] / manifest["tables"][table_kind]["path_in_repo"]
    if kind == "missing": path.unlink()
    else: path.write_bytes(b"corrupt authored table")
    report = prepare(material)
    assert len(report["records"]) == report["coverage"]["declared_reference_rows"] == 4
    assert report["coverage"]["verified_reference_rows"] == 2
    assert report["coverage"]["unavailable_reference_rows"] == 2
    assert all(record["record_status"] in {"bundle_unavailable", "bundle_corrupt"} for record in report["records"][:2])
    assert all(record["row_sha256"] is record["record_sha256"] is record["derived_row_json"] is None for record in report["records"][:2])
    assert all(record["association_status"] == "cache_record_unavailable" for record in report["records"][:2])
    assert all(record["record_status"] == "verified" for record in report["records"][2:])
    assert report["coverage"]["full_declared_population_retained"] is True
    no_authority(report)


@pytest.mark.parametrize("damage", ["missing", "extra", "changed"])
def test_original_manifest_bytes_mapping_cannot_be_substituted(material, damage):
    mapping = material["manifest_bytes"]
    first = next(iter(mapping))
    if damage == "missing": mapping.pop(first)
    elif damage == "extra": mapping["unselected.json"] = b"{}"
    else: mapping[first] += b" "
    with pytest.raises(ValueError): prepare(material)


@pytest.mark.parametrize("damage", ["drop_record", "physical_identity", "cache_revision", "inference_view", "mask"])
def test_rehashed_report_cannot_replace_complete_cache_and_inventory_replay(material, damage):
    report = prepare(material)
    if damage == "drop_record": report["records"].pop()
    elif damage == "physical_identity": report["records"][0]["physical_record_id"] = report["records"][1]["physical_record_id"]
    elif damage == "cache_revision": report["records"][0]["revision"] = "f" * 40
    elif damage == "inference_view": report["records"][0]["inference_view"] = {"target": TARGET_MARKER}
    else: report["training_mask"] = 1
    with pytest.raises(ValueError): replay(material, report)


def test_mutated_parent_inventory_cannot_be_accepted_through_its_new_self_hash(material):
    material["inventory_report"]["rows"].pop()
    digest = sha(wire(material["inventory_report"]))
    material["inventory_originals"]["expected_report_sha256"] = digest
    material["bindings"]["inventory_report_sha256"] = digest
    with pytest.raises(ValueError): prepare(material)


def test_prepared_values_are_detached_and_source_context_report_is_preserved(material):
    report = prepare(material)
    before = deepcopy(report)
    result = replay(material, report)
    result["records"][0]["occurrence_ids"].clear()
    result["inventory_report"]["rows"][0]["access"]["disposition"] = "deny"
    assert report == before
    assert prepare(material) == before
