"""Candidate geometry stays separate from original occurrence and inference authority.

Authored controls use genuine paired producers, Arrow transport, source codecs,
cache intake and legacy candidate owners. The optional retained phase replays
both complete historical bundles and original receipt bytes without copying
those large receipts. Only the coordinator's owned child executes this suite.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from ipfs_datasets_py.logic.autoformal import legal_compact_source_candidate_crosswalk_v1 as subject
from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_cache_intake_v1 as cache_owner
from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_inventory_v1 as inventory_owner
from ipfs_datasets_py.logic.autoformal import legal_source_span_entity_join_v1 as join_owner
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_join as legacy_owner
from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes
from tests.unit.logic.autoformal.test_legal_compact_source_context_cache_intake_v1 import source_row
from tests.unit.logic.autoformal.test_legal_compact_source_context_inventory_v1 import (
    case as inventory_case, originals as inventory_raws, resolver as source_resolver,
)


CACHE_REVISION = "e" * 40
SOURCE_REVISION = "a" * 40
HISTORICAL_RELEASE = "authored-historical-release"
TARGET_MARKER = "OPAQUE_FORMULA_MUST_NOT_BECOME_SOURCE_CONTEXT"
LEGACY_INPUTS_SHA256 = "e5e7c379f6aecc08ed1d2e624009ecf77786bf6b3ee067af030e16e7a5d7f2d7"
REAL_REQUEST_SHA256 = "f14e27bc4c79d849eb3d87acd0a866e8e3c4319f5ffe8f9d3591bc2c01a29572"
REAL_COMMITMENTS_SHA256 = "dc5acf8d46e9133a6c23364a81cd0552a633f8b45d61ab14f4c1d4bc9581c49d"


def wire(value, *, ascii_only=False):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=ascii_only, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def retain_reference(path, raw=None):
    path = Path(path)
    if raw is not None:
        path.write_bytes(raw)
    body = path.read_bytes()
    return {"path": str(path.absolute()), "bytes": len(body), "sha256": sha(body)}


def section(text, ordinal):
    return {"repository_id": "justicedao/ipfs_uscode", "revision": SOURCE_REVISION,
        "path_in_repo": "uscode_parquet/laws.parquet", "artifact_sha256": "b" * 64,
        "artifact_bytes": 1000, "release_id": HISTORICAL_RELEASE,
        "parquet_row_index": ordinal, "entry_cid": cid_for_bytes(("authored-parent-" + str(ordinal)).encode()),
        "legal_id": "usc:us:5:" + str(ordinal), "text_sha256": sha(text.encode()), "text": text}


def parent(pin):
    return {"repository_id": pin["repository_id"], "revision": pin["revision"],
        "path_in_repo": pin["path_in_repo"], "sha256": pin["artifact_sha256"],
        "bytes": pin["artifact_bytes"], "release_id": pin["release_id"],
        "path": "/historical/producer/machine/laws.parquet"}


def serialize(root, label, bundle):
    """Keep producer directories exact; custody labels vary bundle filename keys."""
    tables = {}
    for kind in paired.TABLE_NAMES:
        table = pa.Table.from_pylist(bundle[kind], schema=paired.arrow_schemas(paired.SCHEMA)[kind])
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink, compression="zstd", row_group_size=2)
        raw = sink.getvalue().to_pybytes()
        digest = sha(raw)
        filename = kind + "-" + sha(label.encode()) + "-" + digest + ".parquet"
        name = "autoformal/uscode/paired-v2/" + kind + "/" + bundle["agent_id"] + "/" + filename
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        tables[kind] = {"path_in_repo": name, "filename": filename,
            "sha256": digest, "bytes": len(raw), "row_count": len(bundle[kind])}
    manifest = {"schema": "uscode-paired-span-bundle/v2", "repository_id": paired.REPOSITORY,
        "agent_id": bundle["agent_id"], "tables": tables,
        "original_receipt_artifact_sha256": bundle["original_receipt_artifact_sha256"],
        "admitted": False, "formalized": False, "enqueued": False}
    fingerprint = sha(wire(manifest, ascii_only=True))
    name = "autoformal/uscode/paired-v2/manifests/" + bundle["agent_id"] + "/manifest-" + fingerprint + ".json"
    manifest.update(fingerprint=fingerprint, path_in_repo=name)
    raw = wire(manifest, ascii_only=True)
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return manifest, {"path_in_repo": name, "bytes": len(raw), "sha256": sha(raw)}, raw


@pytest.fixture
def material(inventory_case, tmp_path):
    raw, options = inventory_raws(inventory_case)
    inventory_originals = {**dict(zip(("population_raw", "occurrences_raw", "catalog_raw", "access_raw"), raw)),
        **options, "source_resolver": source_resolver(inventory_case)}
    inventory = inventory_owner.prepare_source_context_inventory_v1(*raw,
        **options, source_resolver=source_resolver(inventory_case))
    inventory_originals["expected_report_sha256"] = sha(wire(inventory))
    sections = [section("§ Café Clerk; Clerk.", 17), section("§ Clerk shall file.", 18)]
    observations, producers = [], []
    for pin, span_id, text in zip(sections, ("repeated-span", "unique-span"), ("Clerk", "Clerk shall file.")):
        observation = source_row(span_id, text, TARGET_MARKER)
        observation.update(release_id=HISTORICAL_RELEASE, legal_id=pin["legal_id"],
            logic_target_observation={"opaque_target": TARGET_MARKER})
        observations.append(observation)
        producers.append({"source_span_id": span_id, "source_sha256": sha(text.encode()),
            "text": text, "legal_id": pin["legal_id"], "entry_cid": pin["entry_cid"],
            "source_section_offset": pin["parquet_row_index"], "historical_span_ordinal": 999,
            "historical_document_batch_index": 3, "historical_document_batch_size": 64,
            "source_parent": parent(pin), "logic_target_observation": {"opaque_target": TARGET_MARKER},
            "admitted": True, "formalized": True})
    receipt = {"schema_version": "authored-original-producer/v1", "rows": producers}
    receipt_raw = wire(receipt, ascii_only=True)
    bundle = paired.build_paired_census(observations, agent_id="authored-candidate-producer",
        code_identity="authored-source-candidate-control", model_identity="diagnostic:no-model-execution",
        original_receipt=receipt)
    assert bundle["original_receipt_artifact_sha256"] == sha(receipt_raw)
    root = tmp_path / "authored-repository" / CACHE_REVISION
    manifests, entries, manifest_bytes, bindings, legacy = [], [], {}, [], {}
    for label in ("left-custody-path", "right-custody-path"):
        manifest, entry, encoded = serialize(root, label, bundle)
        manifests.append(manifest)
        entries.append(entry)
        manifest_bytes[entry["path_in_repo"]] = encoded
        expected = []
        for ordinal, row in enumerate(bundle["paired_spans"]):
            digest = sha(wire(row, ascii_only=True))
            bindings.append({"manifest_path_in_repo": entry["path_in_repo"], "row_ordinal": ordinal,
                "row_sha256": digest, "occurrence_ids": []})
            expected.append({"row_sha256": digest, "source_span_id": row["source"]["span_id"],
                "text_sha256": row["source"]["text_sha256"], "source_revision": row["source"]["revision"]})
        legacy[entry["path_in_repo"]] = {"expected_population": expected,
            "producer_receipt_bytes": receipt_raw, "expected_producer_receipt_sha256": sha(receipt_raw),
            "source_sections": deepcopy(sections),
            "expected_source_sections": [{key: value for key, value in pin.items() if key != "text"} for pin in sections]}
    request = {"schema": "legal-paired-manifest-inventory-request/v1", "repository_id": paired.REPOSITORY,
        "revision": CACHE_REVISION, "selection_scope": "explicit_paired_manifest_selection", "manifests": entries}
    binding_document = {"schema": "legal-compact-source-context-cache-bindings/v1",
        "cache_request_sha256": sha(wire(request)), "inventory_report_sha256": sha(wire(inventory)), "rows": bindings}
    cache_originals = {"cache_request_raw": wire(request), "cache_bindings_raw": wire(binding_document),
        "expected_cache_request_sha256": sha(wire(request)), "expected_cache_bindings_sha256": sha(wire(binding_document)),
        "repository_root": str(root), "manifest_bytes": manifest_bytes, "inventory_report": inventory,
        "inventory_originals": inventory_originals}
    return {"cache_originals": cache_originals, "legacy": legacy, "manifests": manifests,
        "bundle": bundle, "root": root, "sections": sections, "inventory_case": inventory_case}


def cache_report(material):
    originals = dict(material["cache_originals"])
    raw = [originals.pop(name) for name in ("cache_request_raw", "cache_bindings_raw")]
    return cache_owner.prepare_source_context_cache_intake_v1(*raw, **originals)


def request(material):
    return {"schema": "legal-compact-source-candidate-crosswalk-request/v1",
        "cache_intake_sha256": cache_owner.source_context_cache_intake_sha256(cache_report(material)),
        "legacy_joins": [{"manifest_path_in_repo": item["path_in_repo"],
            "inputs_sha256": None if material["legacy"][item["path_in_repo"]] is None else
                join_owner.legacy_join_inputs_sha256(material["legacy"][item["path_in_repo"]])}
            for item in json.loads(material["cache_originals"]["cache_request_raw"])["manifests"]]}


def prepare(material, declaration=None, **changes):
    raw = wire(request(material) if declaration is None else declaration)
    return subject.prepare_source_candidate_crosswalk_v1(raw,
        **{"expected_request_sha256": sha(raw), "cache_originals": material["cache_originals"],
           "legacy_join_inputs": material["legacy"], **changes})


def replay(material, report, declaration=None, **changes):
    raw = wire(request(material) if declaration is None else declaration)
    return subject.validate_source_candidate_crosswalk_v1(report, raw,
        **{"expected_report_sha256": subject.source_candidate_crosswalk_sha256(report),
           "expected_request_sha256": sha(raw), "cache_originals": material["cache_originals"],
           "legacy_join_inputs": material["legacy"], **changes})


def no_authority(report):
    for item in [report, *report["records"]]:
        assert item["authority"] and all(flag is False for flag in item["authority"].values())
        assert type(item["training_mask"]) is type(item["evaluation_gold_mask"]) is int
        assert item["training_mask"] == item["evaluation_gold_mask"] == 0
    for row in report["records"]:
        assert row["inference_view"] is row["selected_occurrence"] is None
        assert row["original_producer_occurrence_attested"] is False
        assert row["current_source_release_correspondence"] == "unverified_no_independent_crosswalk"
        candidate = row["source_candidate_record"]
        if candidate is not None:
            assert candidate["selected_occurrence"] is None
            assert candidate["original_producer_occurrence_attested"] is False


def test_genuine_original_bound_replay_preserves_unicode_candidates_and_duplicate_content_at_distinct_paths(material):
    expected_cache = cache_report(material)
    report = prepare(material)
    assert replay(material, report) == report
    assert subject.source_candidate_crosswalk_sha256(report) == sha(wire(report))
    assert report["cache_intake_sha256"] == cache_owner.source_context_cache_intake_sha256(expected_cache)
    assert report["cache_coverage"] == expected_cache["coverage"]
    records = report["records"]
    assert len(records) == 4
    assert [row["source_disposition"] for row in records] == ["ambiguous_exact_candidates", "unique_exact_candidate"] * 2
    assert [row["candidate_count"] for row in records] == [2, 1, 2, 1]
    assert [row["reference_id"] for row in records] == [row["reference_id"] for row in expected_cache["records"]]
    assert [row["physical_record_id"] for row in records] == [row["physical_record_id"] for row in expected_cache["records"]]
    assert len({row["physical_record_id"] for row in records}) == len({row["reference_id"] for row in records}) == 4
    assert records[0]["row_sha256"] == records[2]["row_sha256"]
    assert records[0]["candidate_occurrence_ids"] == records[2]["candidate_occurrence_ids"]
    occurrences = [item["source_occurrence"] for item in records[0]["source_candidate_record"]["candidates"]]
    assert [item["start_char"] for item in occurrences] == [7, 14]
    assert [item["start_utf8"] for item in occurrences] == [9, 16]
    assert [item["end_char"] for item in occurrences] == [12, 19]
    assert [item["end_utf8"] for item in occurrences] == [14, 21]
    for row in records:
        candidate = row["source_candidate_record"]
        producer = candidate["producer_link"]["producer_record"]
        assert producer["historical_metadata"]["historical_span_ordinal"] == 999
        assert producer["source_parent"]["revision"] == SOURCE_REVISION
        assert row["revision"] == CACHE_REVISION
        assert row["candidate_occurrence_ids"] == [item["source_occurrence"]["record_cid"] for item in candidate["candidates"]]
    assert TARGET_MARKER not in wire(report).decode()
    assert all(row["occurrence_ids"] == [] for row in expected_cache["records"])
    assert expected_cache["coverage"]["associated_inventory_occurrences"] == 0
    assert len(expected_cache["occurrences"]) == 5
    no_authority(report)


def test_shared_physical_table_keeps_multiple_manifest_references_without_double_counting_records(material):
    originals = material["cache_originals"]
    cache_request = json.loads(originals["cache_request_raw"])
    bindings = json.loads(originals["cache_bindings_raw"])
    old_path = cache_request["manifests"][1]["path_in_repo"]
    manifest = {key: deepcopy(value) for key, value in material["manifests"][1].items()
        if key not in {"fingerprint", "path_in_repo"}}
    manifest["tables"] = deepcopy(material["manifests"][0]["tables"])
    # The existing paired writer supports this optional exporter-source field;
    # it distinguishes two envelopes over identical tables under one producer.
    manifest["exporter_sha256"] = paired.EXPORTER_SOURCE_SHA256
    fingerprint = sha(wire(manifest, ascii_only=True))
    new_path = str(Path(old_path).parent / ("manifest-" + fingerprint + ".json"))
    manifest.update(fingerprint=fingerprint, path_in_repo=new_path)
    raw = wire(manifest, ascii_only=True)
    (material["root"] / new_path).write_bytes(raw)
    originals["manifest_bytes"].pop(old_path)
    originals["manifest_bytes"][new_path] = raw
    cache_request["manifests"][1] = {"path_in_repo": new_path, "bytes": len(raw), "sha256": sha(raw)}
    for row in bindings["rows"]:
        if row["manifest_path_in_repo"] == old_path:
            row["manifest_path_in_repo"] = new_path
    originals["cache_request_raw"] = wire(cache_request)
    originals["expected_cache_request_sha256"] = sha(originals["cache_request_raw"])
    bindings["cache_request_sha256"] = originals["expected_cache_request_sha256"]
    originals["cache_bindings_raw"] = wire(bindings)
    originals["expected_cache_bindings_sha256"] = sha(originals["cache_bindings_raw"])
    material["legacy"][new_path] = material["legacy"].pop(old_path)
    material["manifests"][1] = manifest
    report = prepare(material)
    assert replay(material, report) == report
    records, coverage = report["records"], report["coverage"]
    assert coverage["declared_reference_rows"] == coverage["distinct_manifest_references"] == 4
    assert coverage["distinct_physical_records"] == 2
    assert coverage["candidate_occurrence_references"] == 6
    assert coverage["distinct_candidate_occurrences"] == 3
    assert records[0]["physical_record_id"] == records[2]["physical_record_id"]
    assert records[0]["reference_id"] != records[2]["reference_id"]
    assert records[0]["candidate_occurrence_ids"] == records[2]["candidate_occurrence_ids"]
    no_authority(report)


@pytest.mark.parametrize("damage", ["extra", "missing", "schema", "cache_pin", "missing_join", "duplicate_join", "order", "foreign_path", "inputs_pin"])
def test_request_exact_population_and_independent_pins_refuse(material, damage):
    declaration = request(material)
    if damage == "extra": declaration["target_formula"] = TARGET_MARKER
    elif damage == "missing": declaration.pop("cache_intake_sha256")
    elif damage == "schema": declaration["schema"] = "other/v1"
    elif damage == "cache_pin": declaration["cache_intake_sha256"] = "0" * 64
    elif damage == "missing_join": declaration["legacy_joins"].pop()
    elif damage == "duplicate_join": declaration["legacy_joins"].append(deepcopy(declaration["legacy_joins"][0]))
    elif damage == "order": declaration["legacy_joins"].reverse()
    elif damage == "foreign_path": declaration["legacy_joins"][0]["manifest_path_in_repo"] = "unselected/manifest.json"
    else: declaration["legacy_joins"][0]["inputs_sha256"] = "0" * 64
    with pytest.raises(ValueError): prepare(material, declaration)


def test_original_request_hash_is_independent(material):
    with pytest.raises(ValueError): prepare(material, expected_request_sha256="0" * 64)


@pytest.mark.parametrize("damage", ["missing", "extra", "uncommitted_none"])
def test_join_mapping_cannot_omit_add_or_substitute_declared_inputs(material, damage):
    declaration = request(material)
    first = next(iter(material["legacy"]))
    if damage == "missing": material["legacy"].pop(first)
    elif damage == "extra": material["legacy"]["unselected/manifest.json"] = deepcopy(material["legacy"][first])
    else: material["legacy"][first] = None
    with pytest.raises(ValueError): prepare(material, declaration)


@pytest.mark.parametrize("damage", ["missing", "duplicate", "order", "wrong_row", "wrong_span", "wrong_text", "wrong_release"])
def test_complete_physical_paired_population_is_bound_before_candidate_replay(material, damage):
    inputs = next(iter(material["legacy"].values()))
    expected = inputs["expected_population"]
    if damage == "missing": expected.pop()
    elif damage == "duplicate": expected.append(deepcopy(expected[0]))
    elif damage == "order": expected.reverse()
    elif damage == "wrong_row": expected[0]["row_sha256"] = "0" * 64
    elif damage == "wrong_span": expected[0]["source_span_id"] = "another-span"
    elif damage == "wrong_text": expected[0]["text_sha256"] = "0" * 64
    else: expected[0]["source_revision"] = "another-source-release"
    with pytest.raises(ValueError): prepare(material)


@pytest.mark.parametrize("damage", ["receipt_hash", "receipt_reference", "receipt_missing_pair", "source_bytes", "source_omission", "source_order"])
def test_original_receipt_and_complete_source_text_are_not_replaceable_with_resealed_join_inputs(material, damage):
    inputs = next(iter(material["legacy"].values()))
    if damage == "receipt_hash": inputs["producer_receipt_bytes"] += b" "
    elif damage == "receipt_reference":
        altered = json.loads(inputs["producer_receipt_bytes"])
        altered["rows"][0]["source_parent"]["revision"] = "c" * 40
        inputs["producer_receipt_bytes"] = wire(altered, ascii_only=True)
        inputs["expected_producer_receipt_sha256"] = sha(inputs["producer_receipt_bytes"])
    elif damage == "receipt_missing_pair": inputs["producer_receipt_bytes"] = None
    elif damage == "source_bytes": inputs["source_sections"][0]["text"] += " changed"
    elif damage == "source_omission": inputs["source_sections"].pop()
    else: inputs["source_sections"].reverse()
    with pytest.raises(ValueError): prepare(material)


@pytest.mark.parametrize("field,value", [("entry_cid", "alternate"), ("legal_id", "usc:us:5:999"),
    ("artifact_bytes", 1001), ("release_id", "another-release")])
def test_same_physical_parent_with_conflicting_metadata_retains_mismatch(material, field, value):
    inputs = next(iter(material["legacy"].values()))
    if field == "entry_cid": value = cid_for_bytes(b"alternate parent")
    for key in ("source_sections", "expected_source_sections"): inputs[key][0][field] = value
    report = prepare(material)
    assert [row["source_disposition"] for row in report["records"]] == [
        "producer_parent_mismatch", "unique_exact_candidate", "ambiguous_exact_candidates", "unique_exact_candidate"]
    assert report["records"][0]["candidate_count"] == 0
    assert len(report["records"]) == 4
    no_authority(report)


@pytest.mark.parametrize("missing", ["join", "receipt", "source", "physical_parent"])
def test_unavailable_source_paths_retain_all_reference_slots_without_text_or_alias_fallback(material, missing):
    path = next(iter(material["legacy"]))
    inputs = material["legacy"][path]
    if missing == "join":
        material["legacy"][path] = None
        expected = "source_join_unavailable"
    elif missing == "receipt":
        inputs.update(producer_receipt_bytes=None, expected_producer_receipt_sha256=None)
        expected = "producer_source_unavailable"
    elif missing == "source":
        inputs.update(source_sections=[], expected_source_sections=[])
        expected = "source_section_unavailable"
    else:
        for key in ("source_sections", "expected_source_sections"): inputs[key][0]["parquet_row_index"] = 77
        expected = "source_section_unavailable"
    report = prepare(material)
    assert len(report["records"]) == 4
    assert report["records"][0]["source_disposition"] == expected
    assert report["records"][0]["candidate_count"] == 0
    assert report["records"][2]["candidate_count"] == 2
    assert report["records"][0]["selected_occurrence"] is None
    no_authority(report)


@pytest.mark.parametrize("failed", ["missing", "corrupt"])
def test_failed_cache_bundle_keeps_declared_slots_and_does_not_borrow_equal_text_candidates(material, failed):
    table = material["root"] / material["manifests"][0]["tables"]["paired_spans"]["path_in_repo"]
    if failed == "missing": table.unlink()
    else: table.write_bytes(b"corrupt authored table")
    report = prepare(material)
    assert len(report["records"]) == 4
    assert [row["source_disposition"] for row in report["records"][:2]] == ["cache_record_unavailable"] * 2
    assert all(row["row_sha256"] is row["source_candidate_record"] is None for row in report["records"][:2])
    assert [row["candidate_count"] for row in report["records"]] == [0, 0, 2, 1]
    no_authority(report)


@pytest.mark.parametrize("damage", ["drop_record", "physical_identity", "candidate_omission", "selector", "selected", "inference", "authority", "mask"])
def test_rehashed_report_cannot_replace_full_original_replay(material, damage):
    report = prepare(material)
    row = report["records"][0]
    if damage == "drop_record": report["records"].pop()
    elif damage == "physical_identity": row["physical_record_id"] = report["records"][2]["physical_record_id"]
    elif damage == "candidate_omission": row["source_candidate_record"]["candidates"].pop()
    elif damage == "selector": row["source_candidate_record"]["candidates"][0]["source_occurrence"]["start_utf8"] = 7
    elif damage == "selected": row["selected_occurrence"] = row["candidate_occurrence_ids"][0]
    elif damage == "inference": row["inference_view"] = {"target_formula": TARGET_MARKER}
    elif damage == "authority": row["authority"]["source_correspondence_verified"] = True
    else: report["training_mask"] = 1
    with pytest.raises(ValueError): replay(material, report)


def test_independent_saved_report_digest_and_detached_replay_are_required(material):
    report = prepare(material)
    before = deepcopy(report)
    with pytest.raises(ValueError): replay(material, report, expected_report_sha256="0" * 64)
    result = replay(material, report)
    result["records"][0]["candidate_occurrence_ids"].clear()
    result["records"][0]["source_candidate_record"]["candidates"].clear()
    assert report == before
    assert prepare(material) == before


@pytest.mark.parametrize("bound", ["text_characters", "text_utf8", "source_rows", "paired_rows",
    "physical_row_bool", "parent_bytes_bool"])
def test_oversized_sections_populations_and_boolean_integer_metadata_refuse_before_cache_or_legacy_work(material, monkeypatch, bound):
    inputs = next(iter(material["legacy"].values()))
    if bound == "text_characters": inputs["source_sections"][0]["text"] = "x" * (128 * 1024 + 1)
    elif bound == "text_utf8": inputs["source_sections"][0]["text"] = "ß" * (64 * 1024 + 1)
    elif bound == "source_rows":
        inputs["source_sections"] = [deepcopy(inputs["source_sections"][0]) for _ in range(65)]
        inputs["expected_source_sections"] = [deepcopy(inputs["expected_source_sections"][0]) for _ in range(65)]
    elif bound == "paired_rows": inputs["expected_population"] = [deepcopy(inputs["expected_population"][0]) for _ in range(65)]
    else:
        field = "parquet_row_index" if bound == "physical_row_bool" else "artifact_bytes"
        for key in ("source_sections", "expected_source_sections"): inputs[key][0][field] = True
    declaration = request(material)
    def forbidden(*args, **kwargs): pytest.fail("unbounded input reached cache or legacy owner work")
    monkeypatch.setattr(cache_owner, "prepare_source_context_cache_intake_v1", forbidden)
    monkeypatch.setattr(legacy_owner, "build_legacy_source_join", forbidden)
    with pytest.raises(ValueError): prepare(material, declaration)


@pytest.mark.parametrize("mutation", ["manifest_bytes", "inventory_report", "inventory_original", "source_partitions", "legacy_metadata"])
def test_closing_fence_rejects_nested_original_mutation_after_real_legacy_candidate_work(material, monkeypatch, mutation):
    """Disclosed fault-injection seam wraps, then executes, the genuine owner."""
    declaration = request(material)
    build = legacy_owner.build_legacy_source_join
    calls = []

    def mutate_after_real_build(*args, **kwargs):
        result = build(*args, **kwargs)
        calls.append(result["counts"]["candidate_occurrences"])
        originals = material["cache_originals"]
        if mutation == "manifest_bytes":
            path = next(iter(originals["manifest_bytes"]))
            originals["manifest_bytes"][path] += b" "
        elif mutation == "inventory_report": originals["inventory_report"]["rows"][0]["id"] = "altered-occurrence"
        elif mutation == "inventory_original": originals["inventory_originals"]["access_raw"] += b" "
        elif mutation == "source_partitions":
            # Typed frozen originals can still be corrupted by hostile Python;
            # retain the owner's exact state check rather than trusting identity.
            object.__setattr__(originals["inventory_originals"]["source_partitions"], "_sha256", "0" * 64)
        else: next(iter(material["legacy"].values()))["source_sections"][0]["text"] += " altered"
        return result

    monkeypatch.setattr(legacy_owner, "build_legacy_source_join", mutate_after_real_build)
    with pytest.raises(ValueError, match="changed"): prepare(material, declaration)
    assert calls == [3]


REAL_ENV = ("LEGAL_COMPACT_SOURCE_CONTEXT_CACHE_REQUEST", "LEGAL_COMPACT_SOURCE_CONTEXT_CACHE_COMMITMENTS",
    "LEGAL_COMPACT_SOURCE_CONTEXT_CACHE_ROOT", "LEGAL_COMPACT_SOURCE_CROSSWALK_INPUTS",
    "LEGAL_COMPACT_SOURCE_CROSSWALK_RECEIPT_V1", "LEGAL_COMPACT_SOURCE_CROSSWALK_RECEIPT_V2")


@pytest.mark.skipif(not all(os.environ.get(name) for name in REAL_ENV), reason="retainedcandidateintegrationnotconfigured")
def test_complete_retained_sixteen_record_crosswalk_replays_all_150_candidates_without_selection(material, tmp_path):
    request_path, commitments_path, real_root, legacy_path, receipt_v1, receipt_v2 = [Path(os.environ[name]) for name in REAL_ENV]
    request_raw, commitments_raw, legacy_raw = request_path.read_bytes(), commitments_path.read_bytes(), legacy_path.read_bytes()
    assert sha(request_raw) == REAL_REQUEST_SHA256
    assert sha(commitments_raw) == REAL_COMMITMENTS_SHA256
    assert sha(legacy_raw) == LEGACY_INPUTS_SHA256
    cache_request, commitments, inputs = json.loads(request_raw), json.loads(commitments_raw), json.loads(legacy_raw)
    assert cache_request["revision"] == commitments["revision"] == "60501f3e920f6c9050cfc452e0d9fcc2b7c184f3"
    assert len(commitments["rows"]) == 16 and all(row["occurrence_ids"] == [] for row in commitments["rows"])
    originals = material["cache_originals"]
    bindings = {"schema": "legal-compact-source-context-cache-bindings/v1",
        "cache_request_sha256": sha(request_raw), "inventory_report_sha256": sha(wire(originals["inventory_report"])),
        "rows": commitments["rows"]}
    originals.update(cache_request_raw=request_raw, cache_bindings_raw=wire(bindings),
        expected_cache_request_sha256=sha(request_raw), expected_cache_bindings_sha256=sha(wire(bindings)),
        repository_root=str(real_root), manifest_bytes={item["path_in_repo"]:
            (real_root / item["path_in_repo"]).read_bytes() for item in cache_request["manifests"]})
    receipt_references, legacy = [], {}
    for path, supplied in inputs.items():
        descriptor = supplied["producer_receipt"]
        receipt_path = receipt_v1 if path.startswith("autoformal/uscode/paired-v1/") else receipt_v2
        assert str(receipt_path) == descriptor["path"]
        receipt = receipt_path.read_bytes()
        assert len(receipt) == descriptor["bytes"] and sha(receipt) == descriptor["sha256"]
        assert descriptor["sha256"] == supplied["expected_producer_receipt_sha256"]
        receipt_references.append(descriptor)
        legacy[path] = {name: supplied[name] for name in ("expected_population", "expected_producer_receipt_sha256",
            "source_sections", "expected_source_sections")}
        legacy[path]["producer_receipt_bytes"] = receipt
    material["legacy"] = legacy
    declaration = request(material)
    regenerated_cache = cache_report(material)
    report = prepare(material, declaration)
    replayed = replay(material, report, declaration)
    assert replayed == report
    records = report["records"]
    assert len(records) == len({row["physical_record_id"] for row in records}) == len({row["reference_id"] for row in records}) == 16
    assert [row["candidate_count"] for row in records] == [33, 1, 1, 57, 1, 1, 1, 2, 1, 1, 1, 20, 1, 1, 1, 27]
    assert sum(row["candidate_count"] for row in records) == 150
    assert sum(row["source_disposition"] == "unique_exact_candidate" for row in records) == 11
    assert sum(row["source_disposition"] == "ambiguous_exact_candidates" for row in records) == 5
    expected_parent_rows = [2722, 2724, 2720, 2721, 2720, 2726, 2721, 2727, 3358, 3352, 3353, 3355, 3357, 3345, 3353, 3354]
    assert [row["source_candidate_record"]["producer_link"]["producer_record"]["source_section_offset"] for row in records] == expected_parent_rows
    full_sections = {pin["parquet_row_index"]: pin for supplied in legacy.values() for pin in supplied["source_sections"]}
    assert len(full_sections) == 13
    for row, parent_row in zip(records, expected_parent_rows):
        candidate = row["source_candidate_record"]
        producer = candidate["producer_link"]["producer_record"]
        assert producer["source_parent"]["revision"] == "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e"
        assert row["revision"] == "60501f3e920f6c9050cfc452e0d9fcc2b7c184f3"
        text = full_sections[parent_row]["text"]
        for item in candidate["candidates"]:
            occurrence = item["source_occurrence"]
            char_slice = text[occurrence["start_char"]:occurrence["end_char"]]
            byte_slice = text.encode()[occurrence["start_utf8"]:occurrence["end_utf8"]]
            assert byte_slice == char_slice.encode() == producer["text"].encode()
            assert sha(byte_slice) == candidate["text_sha256"]
    no_authority(report)
    destination = tmp_path / "real-candidate-originals"
    destination.mkdir()
    references = {"request": retain_reference(destination / "request.json", wire(declaration)),
        "report": retain_reference(destination / "report.json", wire(report)),
        "replayed-report": retain_reference(destination / "replayed-report.json", wire(replayed)),
        "cache-request": retain_reference(destination / "cache-request.json", request_raw),
        "cache-bindings": retain_reference(destination / "cache-bindings.json", originals["cache_bindings_raw"]),
        "cache-report": retain_reference(destination / "cache-report.json", wire(regenerated_cache)),
        "inventory-report": retain_reference(destination / "inventory-report.json", wire(originals["inventory_report"]))}
    for name in ("population", "occurrences", "catalog", "access"):
        references[name] = retain_reference(destination / (name + ".json"),
            originals["inventory_originals"][name + "_raw"])
    inventory = material["inventory_case"]
    references["source-inventory"] = retain_reference(destination / "source-inventory.json", inventory["inventory"].to_bytes())
    references["source-partitions"] = retain_reference(destination / "source-partitions.json", inventory["partitions"].to_bytes())
    source_artifacts = [{"artifact": {"sha256": digest, "bytes": len(body)},
        "file": retain_reference(destination / ("source-" + digest + ".txt"), body)}
        for digest, body in sorted(inventory["artifacts"].items())]
    cache_paths = set(originals["manifest_bytes"])
    for encoded in originals["manifest_bytes"].values():
        cache_paths.update(descriptor["path_in_repo"] for descriptor in json.loads(encoded)["tables"].values())
    evidence = {"schema": "legal-compact-source-candidate-crosswalk-engineering-evidence/v1",
        "scope": "selected_retained_historical_bundles", "cache_request": {"path": str(request_path), "bytes": len(request_raw), "sha256": sha(request_raw)},
        "cache_row_commitments": {"path": str(commitments_path), "bytes": len(commitments_raw), "sha256": sha(commitments_raw)},
        "legacy_join_inputs": {"path": str(legacy_path), "bytes": len(legacy_raw), "sha256": sha(legacy_raw)},
        "producer_receipts": receipt_references,
        "originals": references, "request": references["request"], "report": references["report"],
        "crosswalk_report": references["report"], "cache_report": references["cache-report"],
        "regenerated_cache_report": references["cache-report"], "cache_bindings": references["cache-bindings"],
        "cache_files": [retain_reference(real_root / path) for path in sorted(cache_paths)],
        "source_artifacts": source_artifacts,
        "missing_source_artifacts": [inventory["inputs"]["missing"]["source"]["artifact"]],
        "physical_cache_records": 16, "complete_historical_sections": 13, "candidate_occurrence_references": 150,
        "unique_candidate_records": 11, "ambiguous_candidate_records": 5, "original_occurrences_selected": 0,
        "parent_parquet_rehashed_or_decoded": False, "remote_revision_authenticated": False,
        "model_executed": False, "training_executed": False, "database_executed": False, "prover_executed": False,
        "training_mask": 0, "evaluation_gold_mask": 0}
    (tmp_path / "source-candidate-crosswalk-engineering-evidence.json").write_bytes(wire(evidence))
