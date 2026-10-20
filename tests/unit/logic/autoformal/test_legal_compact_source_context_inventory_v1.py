"""Finite source/context inventory controls over authored diagnostic metadata.

The source inventory is constructed directly through its real canonical codec;
no Parquet shard, Hub, database, model, training, solver or prover is invoked.
Declared source/access metadata and lexical nominations grant no permission.
All execution belongs to the coordinator's owned no-model qualification child.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_v1 as lexical
from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_inventory_v1 as subject
from ipfs_datasets_py.logic.syntax_core import signatures
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_index as index
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_partitions as partitions_owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_import as importer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_inventory as inventory_owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_production import EmbeddingInput


def wire(value, *, ascii_only=False):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=ascii_only, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def authored_catalog():
    obj = signatures.LogicSort("Object")
    entries = [("Inspect", ("inspector", "record"), ("inspect",)),
        ("Retain", ("holder", "record"), ("retain",)),
        ("ActOne", ("actor",), ("act",)), ("ActTwo", ("actor",), ("act",))]
    signature = signatures.LogicSignature("authored-source-inventory-catalog", family="tdfol",
        profile="tdfol_default", sorts=(obj,), symbols=tuple(
            signatures.declare_predicate(name, (obj,) * len(roles)) for name, roles, _ in entries))
    return {"schema": "legal-compact-source-catalog/v1", "signature": signature.to_dict(),
        "argument_roles": [{"symbol": name, "roles": list(roles)} for name, roles, _ in entries],
        "aliases": [{"symbol": name, "forms": list(forms)} for name, _, forms in entries]}


def physical_id(inventory, ordinal):
    return "sha256:" + sha(wire({"schema": "source-inventory-row-v1",
        "inventory_sha256": inventory.sha256, "relative_path": "data/corpus/authored.parquet",
        "row_index": ordinal}, ascii_only=True))


def expected_group(rows):
    """Independent component keys, including the otherwise excluded connector."""
    keys = set()
    for row in rows:
        meta = row["metadata"]
        for key in (["document", "us_code", meta["canonical_identity"]["document_id"]],
                ["source_artifact", meta["text_sha256"]],
                ["normalized_content", meta["normalized_content_sha256"]]):
            keys.add(wire(key, ascii_only=True).decode())
    return "sha256:" + sha(wire({"schema": "document-source-content-connected-groups-v1",
        "keys": sorted(keys)}, ascii_only=True))


@pytest.fixture
def case():
    """Six physical metadata rows, five selected, one excluded group connector.

    The authored Parquet descriptor is metadata only: no file is constructed,
    parsed, or claimed to have been independently authenticated. Source text
    byte checks are separate and use the in-memory descriptor resolver below.
    """
    revision = "a" * 40
    manifest_raw = b"Authored metadata-only release declaration; no Parquet bytes."
    manifest_ref = {"sha256": sha(manifest_raw), "bytes": len(manifest_raw)}
    release_id = "hf:fixture/source-context@" + revision + "#manifest-sha256:" + manifest_ref["sha256"]
    release = {"repo_id": "fixture/source-context", "revision": revision,
        "manifest": manifest_ref, "release_id": release_id,
        "manifest_digest": sha(b"authored manifest digest"), "release_point": "authored-diagnostic",
        "source_revision": "b" * 40, "default_excludes_recovery": True,
        "import_limits": asdict(importer.USCodeImportLimits()), "other_artifacts": []}
    specs = [("same-left", "1", "inspect records.", False),
        ("connector", "1", "UNRELATED   BRIDGE TEXT.", True),
        ("same-right", "2", "inspect records.", False),
        ("no-match", "3", "unrelated bridge text.", False),
        ("ambiguous", "4", "act", False),
        ("missing", "5", "retain note.", False)]
    metadata_rows, inputs, artifacts = [], {}, {}
    for ordinal, (name, section, text, excluded) in enumerate(specs):
        raw = text.encode("utf-8")
        citation = "10 U.S.C. § " + section
        identity = {"document_id": "usc:us:10:" + section, "title": "10",
            "section": section, "citation": citation}
        source = SourceSpan(SourceArtifact(sha(raw), len(raw)), "us_code", release_id,
            identity["document_id"], "en", citation, 0, len(raw), "identity")
        item = EmbeddingInput(source, "10", section, text, citation)
        inputs[name] = item.to_dict()
        if name != "missing":
            artifacts[sha(raw)] = raw
        status = "retrieval_disposition_excluded" if excluded else "ready_published_text"
        metadata_rows.append({"row_index": ordinal, "entry_cid": "authored-entry:" + name,
            "legal_id": identity["document_id"], "original_status": status, "status": status,
            "duplicate_entry_cid": False, "wrapper_verified": True,
            "metadata": {"record_sha256": sha(wire({"authored_diagnostic": name, "text": text})),
                "text_sha256": sha(raw), "text_bytes": len(raw),
                "normalized_content_sha256": sha(" ".join(text.split()).casefold().encode()),
                "canonical_identity": identity, "input_id": item.input_id}})
    descriptor = b"Authored metadata-only shard descriptor; no persisted Parquet."
    inventory_raw = wire({"schema_version": "autoencoder-uscode-source-inventory-v1",
        "scope": "declared_corpus_family_only", "release": release, "shards": [{
            "artifact": {"relative_path": "data/corpus/authored.parquet", "family": "corpus",
                "sha256": sha(descriptor), "bytes": len(descriptor), "row_count": len(metadata_rows),
                "schema_id": "uscode-corpus-row/v1", "media_type": "application/vnd.apache.parquet"},
            "status": "verified", "rows_scanned": len(metadata_rows), "rows": metadata_rows}]})
    inventory = inventory_owner.USCodeSourceInventory(inventory_raw)
    policy = index.SplitPolicy("authored-source-before-context", train=10000, validation=0, canary=0, holdout=0)
    partitions = partitions_owner.build_source_partitions(inventory, policy=policy)
    selected = [name for name, _, _, excluded in specs if not excluded]
    catalog = authored_catalog()
    population = {"schema": "legal-relational-batch-population/v1", "partition": "train",
        "selection_sha256": sha(b"all five authored selected occurrences before any context resolution"),
        "rows": [{"id": name, "source_sha256": sha(inputs[name]["text"].encode()),
            "context_sha256": sha(("preexisting-source-context:" + name).encode())} for name in selected]}
    population_raw, catalog_raw = wire(population), wire(catalog)
    occurrences = {"schema": "legal-compact-source-context-occurrences/v1",
        "population_sha256": sha(population_raw), "source_partitions_sha256": partitions.sha256,
        "cache_revision": {"repo_id": "fixture/source-context-cache", "revision": "c" * 40,
            "catalog_sha256": sha(catalog_raw)},
        "rows": [{"id": name, "entry_cid": "authored-entry:" + name,
            "source_row_id": partitions.binding_for("authored-entry:" + name)["source_row_id"],
            "source_request": {"occurrence_id": name, "input": inputs[name]}} for name in selected]}
    occurrences_raw = wire(occurrences)
    access = {"schema": "legal-compact-source-context-access/v1",
        "population_sha256": sha(population_raw), "occurrences_sha256": sha(occurrences_raw),
        "catalog_sha256": sha(catalog_raw), "rows": [{"id": name, "operation": "inference",
            "origin": "source_derived", "disposition": "allow",
            "review_record_sha256": sha(("caller-declared-review:" + name).encode())} for name in selected]}
    return {"population": population, "occurrences": occurrences, "catalog": catalog, "access": access,
        "inventory": inventory, "partitions": partitions, "metadata_rows": metadata_rows,
        "artifacts": artifacts, "inputs": inputs, "selected": selected}


def originals(case):
    raw = tuple(wire(case[name]) for name in ("population", "occurrences", "catalog", "access"))
    options = {"expected_" + name + "_sha256": sha(value)
        for name, value in zip(("population", "occurrences", "catalog", "access"), raw)}
    options.update(source_partitions=case["partitions"],
        expected_source_partitions_sha256=case["partitions"].sha256)
    return raw, options


def repin(case):
    case["occurrences"]["population_sha256"] = sha(wire(case["population"]))
    case["occurrences"]["source_partitions_sha256"] = case["partitions"].sha256
    case["occurrences"]["cache_revision"]["catalog_sha256"] = sha(wire(case["catalog"]))
    case["access"].update(population_sha256=sha(wire(case["population"])),
        occurrences_sha256=sha(wire(case["occurrences"])), catalog_sha256=sha(wire(case["catalog"])))


def resolver(case, calls=None):
    def resolve(reference):
        if calls is not None:
            calls.append(deepcopy(reference))
        return case["artifacts"].get(reference["sha256"])
    return resolve


def prepare(case, **changes):
    raw, options = originals(case)
    return subject.prepare_source_context_inventory_v1(*raw,
        **{**options, "source_resolver": resolver(case), **changes})


def validate(case, report, **changes):
    raw, options = originals(case)
    return subject.validate_source_context_inventory_v1(report, *raw,
        **{**options, "expected_report_sha256": sha(wire(report)),
           "source_resolver": resolver(case), **changes})


def no_authority(report):
    assert report["authority"] and all(flag is False for flag in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    for row in report["rows"]:
        assert row["authority"] and all(flag is False for flag in row["authority"].values())
        assert row["inference_view"] is None and row["encoder_status"] == "not_supplied"
        assert type(row["training_mask"]) is int and row["training_mask"] == 0
        assert type(row["evaluation_gold_mask"]) is int and row["evaluation_gold_mask"] == 0


def retained_reference(path, raw):
    path.write_bytes(raw)
    return {"path": str(path.absolute()), "bytes": len(raw), "sha256": sha(raw)}


def test_complete_population_replays_and_persists_all_originals_without_permission(case, tmp_path, record_property):
    report = prepare(case)
    replayed = validate(case, report)
    assert replayed == report and replayed is not report
    assert subject.source_context_inventory_sha256(report) == sha(wire(report))
    assert report["schema"] == "legal-compact-source-context-inventory/v1"
    assert report["profile"] == "declared-source-cache-access-consistency/v1"
    assert report["status"] == "complete_declared_inventory"
    assert report["population"]["ordered_ids"] == case["selected"]
    assert report["population"]["denominator"] == 5
    assert [row["id"] for row in report["rows"]] == case["selected"]
    assert [row["context_status"] for row in report["rows"]] == [
        "nominated_for_inspection", "nominated_for_inspection", "no_match", "ambiguous", "source_unavailable"]
    assert report["coverage"]["population_rows"] == report["coverage"]["inventory_rows"] == 5
    assert report["coverage"]["source_available_rows"] == 4
    assert report["coverage"]["source_unavailable_rows"] == 1
    assert report["coverage"]["nominated_rows"] == 2
    assert report["coverage"]["inference_view_rows"] == 0
    assert sum(report["coverage"]["context_status_counts"].values()) == 5
    assert report["coverage"]["full_population_retained"] is True
    assert report["catalog_validated"] is True
    assert report["catalog_validation"]["role"] == "fixed_diagnostic_probe_not_population"
    for row in report["rows"]:
        original = next(item for item in case["population"]["rows"] if item["id"] == row["id"])
        assert row["population_context_sha256"] == original["context_sha256"]
        if row["context_status"] == "nominated_for_inspection":
            candidate = row["candidate_context"]
            assert row["compact_context_raw_sha256"] == sha(wire(candidate))
            assert row["compact_context_sha256"] == sha(wire(candidate))
            assert row["population_context_sha256"] != row["compact_context_sha256"]
            assert row["symbol_role_derivations"]
            assert row["lexical_report"]["status"] == "nominated"
        else:
            assert row["candidate_context"] is None
            assert row["compact_context_raw_sha256"] is row["compact_context_sha256"] is None
    assert report["rows"][-1]["source_bytes_verified"] is False
    assert report["rows"][-1]["lexical_report"] is None
    no_authority(report)
    root = tmp_path / "source-context-inventory-originals"
    root.mkdir()
    raw, _ = originals(case)
    saved = {name: retained_reference(root / (name + ".json"), value)
        for name, value in zip(("population", "occurrences", "catalog", "access"), raw)}
    saved["inventory"] = retained_reference(root / "inventory.json", case["inventory"].to_bytes())
    saved["partitions"] = retained_reference(root / "partitions.json", case["partitions"].to_bytes())
    sources = [{"artifact": {"sha256": digest, "bytes": len(body)},
        "file": retained_reference(root / ("source-" + digest + ".txt"), body)}
        for digest, body in sorted(case["artifacts"].items())]
    evidence = {"schema": "legal-compact-source-context-inventory-engineering-evidence/v1",
        "fixture_scope": "authored_metadata_only_no_parquet_or_external_review",
        "originals": saved, "source_artifacts": sources,
        "missing_source_artifacts": [case["inputs"]["missing"]["source"]["artifact"]],
        "report": retained_reference(root / "report.json", wire(report)),
        "replayed_report": retained_reference(root / "replayed-report.json", wire(replayed)),
        "physical_row_count": 6, "selected_row_count": 5, "excluded_connector_row_index": 1,
        "excluded_connector_in_grouping": True, "parquet_materialized_or_read": False,
        "model_executed": False, "training_executed": False, "database_executed": False,
        "prover_executed": False, "inference_permission_verified": False,
        "source_authority_authenticated": False, "training_mask": 0, "evaluation_gold_mask": 0}
    evidence_path = tmp_path / "source-context-inventory-engineering-evidence.json"
    evidence_path.write_bytes(wire(evidence))
    record_property("source_context_inventory_evidence", str(evidence_path))


def test_physical_occurrences_and_excluded_transitive_connector_keep_full_component(case):
    report = prepare(case)
    physical = case["metadata_rows"]
    expected = expected_group([physical[number] for number in (0, 1, 2, 3)])
    first, second, third = report["rows"][:3]
    assert first["source_request"]["input"]["text"] == second["source_request"]["input"]["text"]
    assert first["source_row_id"] != second["source_row_id"]
    assert first["source_row_id"] == physical_id(case["inventory"], 0)
    assert second["source_row_id"] == physical_id(case["inventory"], 2)
    assert first["source_request"]["input"]["input_id"] != second["source_request"]["input"]["input_id"]
    assert all(row["partition_binding"]["group_id"] == expected for row in (first, second, third))
    assert expected != expected_group([physical[number] for number in (0, 2)])
    assert expected != expected_group([physical[3]])
    assert report["source_partitions"]["verification_summary"]["physical_row_count"] == 6
    assert report["source_partitions"]["verification_summary"]["eligible_row_count"] == 5
    assert report["source_partitions"]["inventory_sha256"] == case["inventory"].sha256
    assert first["partition_binding"] == case["partitions"].binding_for(first["entry_cid"])
    no_authority(report)


@pytest.mark.parametrize("pin", ["population", "occurrences", "catalog", "access", "source_partitions"])
def test_independent_original_pins_refuse_before_callbacks_or_nomination(case, monkeypatch, pin):
    def forbidden(*args, **kwargs):
        pytest.fail("an invalid independent original pin reached source resolution or lexical nomination")
    monkeypatch.setattr(lexical, "prepare_source_context_v1", forbidden)
    with pytest.raises(ValueError):
        prepare(case, **{"expected_" + pin + "_sha256": "0" * 64, "source_resolver": forbidden})


@pytest.mark.parametrize("location,mutation", [
    ("occurrences", "missing"), ("occurrences", "duplicate"), ("occurrences", "orphan"), ("occurrences", "order"),
    ("access", "missing"), ("access", "duplicate"), ("access", "orphan"), ("access", "order")])
def test_population_join_requires_exact_complete_ordered_occurrence_and_access_rows(case, location, mutation):
    rows = case[location]["rows"]
    if mutation == "missing": rows.pop()
    elif mutation == "duplicate": rows.append(deepcopy(rows[0]))
    elif mutation == "orphan": rows[-1]["id"] = "unselected-orphan"
    else: rows.reverse()
    repin(case)
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("mutation", ["physical_row", "entry", "same_text_origin", "release"])
def test_matching_text_cannot_substitute_physical_membership_or_source_release(case, mutation):
    rows = case["occurrences"]["rows"]
    if mutation == "physical_row": rows[0]["source_row_id"] = rows[1]["source_row_id"]
    elif mutation == "entry": rows[0]["entry_cid"] = rows[1]["entry_cid"]
    elif mutation == "same_text_origin": rows[0]["source_request"]["input"] = deepcopy(rows[1]["source_request"]["input"])
    else:
        data = deepcopy(rows[0]["source_request"]["input"])
        data["source"]["release_id"] += ":different-release"
        rows[0]["source_request"]["input"] = EmbeddingInput(
            SourceSpan.from_dict(data["source"]), data["title"], data["section"], data["text"], data["citation"]).to_dict()
    repin(case)
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("origin", ["target_derived", "teacher_target", "identity_sidecar", "unknown"])
def test_declared_allow_or_review_digest_never_promotes_target_or_unknown_origins(case, origin):
    case["access"]["rows"][0]["origin"] = origin
    report = prepare(case)
    row = report["rows"][0]
    assert row["context_status"] == "origin_not_allowed"
    assert row["candidate_context"] is row["lexical_report"] is None
    assert report["coverage"]["population_rows"] == 5
    assert row["access"]["disposition"] == "allow" and row["access"]["review_record_sha256"] is not None
    no_authority(report)


@pytest.mark.parametrize("disposition,status", [("deny", "access_denied"), ("unavailable", "access_unavailable")])
def test_source_available_but_access_blocked_never_yields_candidate_context(case, disposition, status):
    case["access"]["rows"][0]["disposition"] = disposition
    report = prepare(case)
    row = report["rows"][0]
    assert row["source_bytes_verified"] is True and row["context_status"] == status
    assert row["candidate_context"] is row["lexical_report"] is None
    assert report["coverage"]["population_rows"] == 5
    no_authority(report)


def test_authored_diagnostic_nomination_still_has_no_effective_inference_view(case):
    case["access"]["rows"][0].update(origin="authored_diagnostic", review_record_sha256=None)
    report = prepare(case)
    assert report["rows"][0]["context_status"] == "nominated_for_inspection"
    assert report["rows"][0]["candidate_context"] is not None
    no_authority(report)


def test_entire_catalog_is_validated_when_every_access_row_is_denied(case):
    for row in case["access"]["rows"]: row["disposition"] = "deny"
    case["catalog"]["signature"]["symbols"][-1]["metadata"] = {"target_derived": True}
    repin(case)
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("change", ["roles", "cache_revision", "access_policy"])
def test_existing_report_cannot_be_replayed_against_new_self_consistent_originals(case, change):
    report = prepare(case)
    if change == "roles": case["catalog"]["argument_roles"][0]["roles"].reverse()
    elif change == "cache_revision": case["occurrences"]["cache_revision"]["revision"] = "d" * 40
    else: case["access"]["rows"][0]["disposition"] = "deny"
    repin(case)
    with pytest.raises(ValueError):
        validate(case, report)


@pytest.mark.parametrize("kind", ["wrong_bytes", "short_bytes", "bytearray", "text"])
def test_source_resolver_must_return_exact_immutable_artifact_bytes(case, kind):
    original = resolver(case)
    def changed(reference):
        raw = original(reference)
        if raw is None: return None
        return b"X" * len(raw) if kind == "wrong_bytes" else raw[:-1] if kind == "short_bytes" else bytearray(raw) if kind == "bytearray" else raw.decode()
    with pytest.raises(ValueError):
        prepare(case, source_resolver=changed)


def test_resolver_descriptor_mutation_refuses_instead_of_returning_partial_report(case):
    original = resolver(case)
    def changed(reference):
        result = original(reference)
        reference["bytes"] += 1
        return result
    with pytest.raises(ValueError):
        prepare(case, source_resolver=changed)


def test_partition_mutation_during_source_callback_is_refused_and_restored(case):
    partition = case["partitions"]
    before = partition.to_bytes()
    original = resolver(case)
    def changed(reference):
        object.__setattr__(partition, "_raw", before + b" ")
        return original(reference)
    try:
        with pytest.raises(ValueError):
            prepare(case, source_resolver=changed)
    finally:
        object.__setattr__(partition, "_raw", before)
    assert partition.to_bytes() == before


@pytest.mark.parametrize("damage", ["drop_missing", "group", "permission", "training_mask", "role", "population_context"])
def test_resealed_output_cannot_change_original_population_groups_or_no_credit(case, damage):
    report = prepare(case)
    if damage == "drop_missing": report["rows"].pop()
    elif damage == "group": report["rows"][0]["partition_binding"]["group_id"] = "sha256:" + "0" * 64
    elif damage == "permission": report["rows"][0]["inference_view"] = deepcopy(report["rows"][0]["candidate_context"])
    elif damage == "training_mask": report["training_mask"] = 1
    elif damage == "role": report["rows"][0]["candidate_context"]["argument_roles"][0]["roles"].reverse()
    else: report["rows"][0]["population_context_sha256"] = report["rows"][0]["compact_context_sha256"]
    with pytest.raises(ValueError):
        validate(case, report)


def test_returned_reports_and_replay_are_detached_from_originals_and_prior_mutations(case):
    raw, _ = originals(case)
    report = prepare(case)
    expected = deepcopy(report)
    replayed = validate(case, report)
    replayed["rows"][0]["source_request"]["input"]["text"] = "changed returned view"
    replayed["rows"][0]["access"]["disposition"] = "deny"
    assert report == expected
    assert originals(case)[0] == raw
    assert prepare(case) == expected


@pytest.mark.parametrize("location", ["population", "occurrences", "catalog", "access"])
def test_target_and_prediction_payloads_are_not_accepted_by_closed_original_schemas(case, location):
    case[location]["expected_formula"] = {"schema": "authored-target", "tree": ["predicate", 0]}
    repin(case)
    with pytest.raises(ValueError):
        prepare(case)


def test_population_split_must_match_original_source_partition_membership(case):
    case["population"]["partition"] = "holdout"
    repin(case)
    with pytest.raises(ValueError):
        prepare(case)


def test_non_scalar_access_origins_are_bounded_value_errors(case):
    for origin in ([], {}):
        case["access"]["rows"][0]["origin"] = origin
        with pytest.raises(ValueError):
            prepare(case)
