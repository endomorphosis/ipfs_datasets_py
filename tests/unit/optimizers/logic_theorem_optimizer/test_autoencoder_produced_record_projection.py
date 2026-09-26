"""Selected multi-receipt projections, using synthetic vectors only.

Declared native profiles here exercise an artifact contract. They are not
runtime production attestations, model inference, training or Lean admission.
"""
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_index as ci
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_manifest as cm
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as ep
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_receipt_set as ers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_produced_record_projection as prp
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
    CODEX_TODO_PROJECTION_OPERATION, HPARAM_SELECTION_OPERATION,
    REPRESENTATION_PROMOTION_OPERATION, TRAINING_OPERATION,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_embedding_production import declared_native_receipt
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_embedding_receipt_set import _case
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_uscode_inventory import _row


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _ref(artifact):
    return {"sha256": artifact.sha256, "bytes": len(artifact.to_bytes())}


def _summary(record):
    # Independent construction of the public summary contract.
    payload = record.to_dict()
    return {"record_id": record.record_id, "source": payload["source"],
            "sample_payload_sha256": _sha(_json(payload["sample"])),
            "embedding_provenance": payload["embedding_provenance"],
            "normalized_content_sha256": _sha(" ".join(record.sample.text.split()).casefold().encode())}


@dataclass
class ProjectionCase:
    case: object
    receipt_set: object
    records_by_entry: dict
    manifest: object
    entry_cids: tuple

    def build(self, **kwargs):
        return prp.build_produced_record_projection(self.receipt_set, self.manifest,
            entry_cids=self.entry_cids, receipt_resolver=self.case.receipt_resolver,
            source_resolver=self.case.source_resolver, **kwargs)


def _manifest(records_by_entry, training_entries, validation_entries, *, mode="corpus"):
    entries = [*training_entries, *validation_entries]
    records = [records_by_entry[entry] for entry in entries]
    manifest = cm.build_corpus_manifest(records,
        training_record_ids=[records_by_entry[entry].record_id for entry in training_entries],
        validation_record_ids=[records_by_entry[entry].record_id for entry in validation_entries], mode=mode)
    entry_by_record = {records_by_entry[entry].record_id: entry for entry in entries}
    return manifest, tuple(entry_by_record[record.record_id] for record in manifest.records)


def _prepared(tmp_path, *, native=True, policy=None, alias=False, groups=None):
    rows = [_row(index) for index in range(1, 33)]
    if alias:
        rows.append({**rows[0], "entry_cid": _row(99)["entry_cid"], "document_index": 99})
    case = _case(tmp_path, rows=rows, groups=groups or [[index] for index in range(32)], native=native,
        policy=policy or ci.SplitPolicy("fixed-produced-record-projection-fixture-v1",
            train=5000, validation=5000, canary=0, holdout=0))
    receipt_set = case.build()
    by_input = {}
    for leaf in case.leaves:
        # A declared-native copy is deliberately NOT added to a fixture root.
        # This lets quarantine checks reject claimed records without inference.
        claimed = leaf if native else declared_native_receipt(leaf)
        for record in claimed.to_corpus_records(resolver=case.source_resolver):
            by_input[ep.EmbeddingInput.from_source_record(record).input_id] = record
    records_by_entry = {row["entry_cid"]: by_input[item.input_id]
                       for row, (item, _) in zip(rows, case.entries)}
    if policy is None:
        train = case.partitions.entry_cids_for("train")[:2]
        validation = case.partitions.entry_cids_for("validation")[:2]
        assert len(train) == len(validation) == 2
    else:
        # Deliberately wrong batch claims used to test protected partition I/O.
        train = (rows[0]["entry_cid"],)
        validation = (rows[1]["entry_cid"],)
    manifest, entries = _manifest(records_by_entry, train, validation)
    return ProjectionCase(case, receipt_set, records_by_entry, manifest, entries)


def _forbidden(_):
    pytest.fail("invalid metadata and split permissions must fail before artifact I/O")


def test_projection_binds_canonical_manifest_order_and_original_leaf_provenance(tmp_path):
    fixture = _prepared(tmp_path)
    projection = fixture.build()
    data = projection.to_dict()
    assert set(data) == {"schema_version", "receipt_set", "source_partitions", "corpus_manifest",
                         "dataset_snapshot_id", "split_snapshot_id", "records",
                         "training_record_ids", "validation_record_ids"}
    assert data["receipt_set"] == _ref(fixture.receipt_set)
    assert data["source_partitions"] == _ref(fixture.case.partitions)
    assert data["corpus_manifest"] == _ref(fixture.manifest)
    assert data["dataset_snapshot_id"] == fixture.manifest.dataset_snapshot_id
    assert data["split_snapshot_id"] == fixture.manifest.split_snapshot_id
    assert data["training_record_ids"] == fixture.manifest.to_dict()["split"]["training_record_ids"]
    assert data["validation_record_ids"] == fixture.manifest.to_dict()["split"]["validation_record_ids"]
    assert data["records"] == [{"record_summary": _summary(record),
        **fixture.receipt_set.binding_for(entry)} for record, entry in zip(fixture.manifest.records, fixture.entry_cids)]
    assert [row["record_summary"]["record_id"] for row in data["records"]] == sorted(
        record.record_id for record in fixture.manifest.records)
    for row in data["records"]:
        assert row["record_summary"]["embedding_provenance"]["artifact_sha256"] == row["receipt_sha256"]
        assert row["receipt_sha256"] != fixture.receipt_set.sha256
    assert b'"embedding_vector"' not in projection.to_bytes()
    assert b"The agency shall retain" not in projection.to_bytes()
    assert projection.to_bytes() == _json(data)
    assert projection.sha256 == _sha(projection.to_bytes())
    assert fixture.build().to_bytes() == projection.to_bytes()
    summary = projection.summary()
    assert summary["record_count"] == summary["selected_leaf_count"] == summary["source_count"] == 4
    assert summary["training_record_count"] == summary["validation_record_count"] == 2
    for key in ("current_selected_leaf_bytes_verified", "current_selected_source_bytes_verified",
                "training_eligible", "admitted"):
        assert summary[key] is False


def test_selected_closure_excludes_unrelated_receipts_and_sources(tmp_path):
    fixture = _prepared(tmp_path)
    projection = fixture.build()
    selected = projection.selected_artifacts()
    leaf_digests = {record.embedding_provenance.artifact_sha256 for record in fixture.manifest.records}
    expected_leaves = sorted([ref for ref in fixture.case.descriptors if ref["sha256"] in leaf_digests],
                             key=lambda ref: ref["sha256"])
    expected_sources = sorted(fixture.manifest.source_refs, key=lambda ref: ref["sha256"])
    assert selected == {"leaf_receipts": expected_leaves, "source_artifacts": expected_sources}
    for digest, path in fixture.case.leaf_paths.items():
        if digest not in leaf_digests:
            path.unlink()
    source_digests = {ref["sha256"] for ref in expected_sources}
    for digest, path in fixture.case.source_paths.items():
        if digest not in source_digests:
            path.unlink()
    read_leaves, read_sources = [], []
    def receipt_resolver(ref):
        read_leaves.append(ref)
        assert ref in expected_leaves
        return fixture.case.receipt_resolver(ref)
    def source_resolver(ref):
        read_sources.append(ref)
        assert ref in expected_sources
        return fixture.case.source_resolver(ref)
    result = projection.verify_batch(fixture.manifest, receipt_resolver=receipt_resolver,
                                     source_resolver=source_resolver)
    assert result["supplied_records_verified"] == result["selected_leaf_count"] == 4
    for key in ("supplied_manifest_verified", "current_selected_leaf_bytes_verified",
                "current_selected_source_bytes_verified"):
        assert result[key] is True
    for key in ("unselected_leaf_bytes_reverified", "unselected_source_bytes_reverified", "training_eligible", "admitted"):
        assert result[key] is False
    assert {ref["sha256"] for ref in read_leaves} == leaf_digests
    assert {ref["sha256"] for ref in read_sources} == source_digests


def test_shared_leaf_is_deduplicated_without_requiring_unselected_source_inputs(tmp_path):
    fixture = _prepared(tmp_path, groups=[list(range(32))])
    projection = fixture.build()
    assert projection.summary()["selected_leaf_count"] == 1
    assert projection.selected_artifacts()["leaf_receipts"] == fixture.case.descriptors
    selected_sources = {record.source.artifact.sha256 for record in fixture.manifest.records}
    for digest, path in fixture.case.source_paths.items():
        if digest not in selected_sources:
            path.unlink()
    result = projection.verify_batch(fixture.manifest, receipt_resolver=fixture.case.receipt_resolver,
                                     source_resolver=fixture.case.source_resolver)
    assert result["supplied_records_verified"] == 4
    assert result["selected_leaf_count"] == 1
    assert result["unselected_source_bytes_reverified"] is False


def test_operation_groups_and_final_closure_reuse_captured_paths_not_resolver_callbacks(tmp_path):
    fixture = _prepared(tmp_path, groups=[list(range(32))])
    projection = fixture.build()
    seen_leaves, seen_sources = set(), set()

    def once(resolver, seen):
        def resolve(ref):
            assert ref["sha256"] not in seen, "final closure must not reinvoke arbitrary resolver callbacks"
            seen.add(ref["sha256"])
            return resolver(ref)
        return resolve

    verified = projection.verify_batch(fixture.manifest,
        receipt_resolver=once(fixture.case.receipt_resolver, seen_leaves),
        source_resolver=once(fixture.case.source_resolver, seen_sources))
    assert verified["supplied_records_verified"] == 4
    assert seen_leaves == {fixture.case.leaves[0].sha256}
    assert seen_sources == {record.source.artifact.sha256 for record in fixture.manifest.records}


def test_explicit_source_alias_changes_projection_identity_without_reembedding(tmp_path):
    fixture = _prepared(tmp_path, alias=True)
    original, alias = fixture.case.rows[0]["entry_cid"], fixture.case.rows[-1]["entry_cid"]
    source_split = fixture.case.partitions.binding_for(original)["split"]
    other_split = "validation" if source_split == "train" else "train"
    other = fixture.case.partitions.entry_cids_for(other_split)[0]
    selected = {source_split: [original], other_split: [other]}
    fixture.manifest, fixture.entry_cids = _manifest(fixture.records_by_entry, selected["train"], selected["validation"])
    first = fixture.build()
    fixture.entry_cids = tuple(alias if entry == original else entry for entry in fixture.entry_cids)
    second = fixture.build()
    assert first.sha256 != second.sha256
    assert first.to_dict()["corpus_manifest"] == second.to_dict()["corpus_manifest"]
    assert first.selected_artifacts() == second.selected_artifacts()
    before = next(row for row in first.to_dict()["records"] if row["entry_cid"] == original)
    after = next(row for row in second.to_dict()["records"] if row["entry_cid"] == alias)
    assert before["source_row_id"] != after["source_row_id"]
    for field in ("input_id", "record_summary", "receipt_sha256", "result_index", "split", "group_id"):
        assert before[field] == after[field]


@pytest.mark.parametrize("split", ["canary", "holdout"])
def test_protected_partitions_cannot_enter_either_batch_split_before_io(tmp_path, split):
    policy = ci.SplitPolicy("protected-projection-fixture", **{
        name: 10000 if name == split else 0 for name in ("train", "validation", "canary", "holdout")})
    fixture = _prepared(tmp_path, policy=policy)
    with pytest.raises(prp.ProjectionError):
        prp.build_produced_record_projection(fixture.receipt_set, fixture.manifest,
            entry_cids=fixture.entry_cids, receipt_resolver=_forbidden, source_resolver=_forbidden)


def test_invalid_validation_split_is_rejected_before_valid_training_reads(tmp_path):
    fixture = _prepared(tmp_path)
    train = fixture.case.partitions.entry_cids_for("train")
    fixture.manifest, fixture.entry_cids = _manifest(fixture.records_by_entry, train[:1], train[1:2])
    with pytest.raises(prp.ProjectionError):
        prp.build_produced_record_projection(fixture.receipt_set, fixture.manifest,
            entry_cids=fixture.entry_cids, receipt_resolver=_forbidden, source_resolver=_forbidden)


def test_fixture_execution_is_quarantined_even_with_declared_native_records(tmp_path):
    fixture = _prepared(tmp_path, native=False)
    with pytest.raises(prp.ProjectionError):
        prp.build_produced_record_projection(fixture.receipt_set, fixture.manifest,
            entry_cids=fixture.entry_cids, receipt_resolver=_forbidden, source_resolver=_forbidden)


def test_diagnostic_manifest_does_not_grant_corpus_consumption(tmp_path):
    fixture = _prepared(tmp_path)
    split = fixture.manifest.to_dict()["split"]
    diagnostic = cm.build_corpus_manifest(list(fixture.manifest.records),
        training_record_ids=split["training_record_ids"], validation_record_ids=split["validation_record_ids"],
        mode="diagnostic")
    with pytest.raises(prp.ProjectionError):
        prp.build_produced_record_projection(fixture.receipt_set, diagnostic,
            entry_cids=fixture.entry_cids, receipt_resolver=_forbidden, source_resolver=_forbidden)


@pytest.mark.parametrize("change", ["reverse", "missing", "duplicate", "foreign", "generator"])
def test_entry_selectors_are_explicit_complete_and_canonical_ordered_before_io(tmp_path, change):
    fixture = _prepared(tmp_path)
    entries = list(fixture.entry_cids)
    if change == "reverse":
        entries.reverse()
    elif change == "missing":
        entries.pop()
    elif change == "duplicate":
        entries[-1] = entries[0]
    elif change == "foreign":
        entries[-1] = "sha256:" + "f" * 64
    else:
        entries = iter(entries)
    with pytest.raises(prp.ProjectionError):
        prp.build_produced_record_projection(fixture.receipt_set, fixture.manifest,
            entry_cids=entries, receipt_resolver=_forbidden, source_resolver=_forbidden)


@pytest.mark.parametrize("change", ["signed_zero", "root_provenance", "source_release"])
def test_exact_manifest_cannot_consume_drifted_produced_record(tmp_path, change):
    fixture = _prepared(tmp_path)
    old = fixture.manifest.records[0]
    if change == "signed_zero":
        assert old.sample.embedding_vector[1] == 0.0
        new = replace(old, sample=replace(old.sample,
            embedding_vector=(1.0, 0.0) + tuple(old.sample.embedding_vector[2:])))
    elif change == "root_provenance":
        new = replace(old, embedding_provenance=replace(old.embedding_provenance,
                                                       artifact_sha256=fixture.receipt_set.sha256))
    else:
        new = replace(old, source=replace(old.source, release_id="different-release"))
    assert new.record_id != old.record_id
    split = fixture.manifest.to_dict()["split"]
    altered = cm.build_corpus_manifest([new if record.record_id == old.record_id else record
                                       for record in fixture.manifest.records],
        training_record_ids=[new.record_id if item == old.record_id else item for item in split["training_record_ids"]],
        validation_record_ids=[new.record_id if item == old.record_id else item for item in split["validation_record_ids"]])
    entry_by_record = {record.record_id: entry for record, entry in zip(fixture.manifest.records, fixture.entry_cids)}
    entry_by_record[new.record_id] = entry_by_record[old.record_id]
    with pytest.raises(prp.ProjectionError):
        prp.build_produced_record_projection(fixture.receipt_set, altered,
            entry_cids=[entry_by_record[record.record_id] for record in altered.records],
            receipt_resolver=fixture.case.receipt_resolver, source_resolver=fixture.case.source_resolver)


@pytest.mark.parametrize("change", ["dataset", "split_order", "summary"])
def test_verify_batch_requires_exact_manifest_and_summaries_before_io(tmp_path, change):
    fixture = _prepared(tmp_path)
    projection = fixture.build()
    split = fixture.manifest.to_dict()["split"]
    if change == "split_order":
        altered = cm.build_corpus_manifest(list(fixture.manifest.records),
            training_record_ids=split["training_record_ids"][::-1], validation_record_ids=split["validation_record_ids"])
    elif change == "dataset":
        train = fixture.case.partitions.entry_cids_for("train")[2:3]
        validation = fixture.case.partitions.entry_cids_for("validation")[:1]
        altered, _ = _manifest(fixture.records_by_entry, train, validation)
    else:
        payload = projection.to_dict()
        payload["records"][0]["record_summary"]["sample_payload_sha256"] = "f" * 64
        projection = prp.ProducedRecordProjection(_json(payload), fixture.receipt_set)
        altered = fixture.manifest
    with pytest.raises(prp.ProjectionError):
        projection.verify_batch(altered, receipt_resolver=_forbidden, source_resolver=_forbidden)


@pytest.mark.parametrize("kind", ["leaf", "source"])
def test_validation_read_cannot_hide_mutation_of_already_verified_training_bytes(tmp_path, kind):
    fixture = _prepared(tmp_path)
    projection = fixture.build()
    by_id = {record.record_id: record for record in fixture.manifest.records}
    split = fixture.manifest.to_dict()["split"]
    training = by_id[split["training_record_ids"][0]]
    validation_digests = {by_id[item].embedding_provenance.artifact_sha256
                          for item in split["validation_record_ids"]}
    target = (fixture.case.leaf_paths[training.embedding_provenance.artifact_sha256] if kind == "leaf"
              else fixture.case.source_paths[training.source.artifact.sha256])
    mutated = []
    def receipt_resolver(ref):
        if ref["sha256"] in validation_digests and not mutated:
            target.write_bytes(b"changed after the training operation completed")
            mutated.append(True)
        return fixture.case.receipt_resolver(ref)
    with pytest.raises(prp.ProjectionError):
        projection.verify_batch(fixture.manifest, receipt_resolver=receipt_resolver,
                                 source_resolver=fixture.case.source_resolver)
    assert mutated


@pytest.mark.parametrize("kind", ["leaf", "source"])
def test_changed_selected_artifact_is_not_hidden_by_previous_build_verification(tmp_path, kind):
    fixture = _prepared(tmp_path)
    projection = fixture.build()
    selected = fixture.manifest.records[0]
    target = (fixture.case.leaf_paths[selected.embedding_provenance.artifact_sha256] if kind == "leaf"
              else fixture.case.source_paths[selected.source.artifact.sha256])
    target.write_bytes(b"changed selected artifact")
    with pytest.raises(prp.ProjectionError):
        projection.verify_batch(fixture.manifest, receipt_resolver=fixture.case.receipt_resolver,
                                 source_resolver=fixture.case.source_resolver)


def test_authorization_reuses_frozen_source_splits_and_explicit_membership(tmp_path):
    fixture = _prepared(tmp_path)
    projection = fixture.build()
    split = fixture.manifest.to_dict()["split"]
    training, validation = split["training_record_ids"], split["validation_record_ids"]
    projection.authorize(TRAINING_OPERATION, training)
    projection.authorize(HPARAM_SELECTION_OPERATION, validation)
    projection.authorize(CODEX_TODO_PROJECTION_OPERATION, training + validation)
    for operation, ids in ((TRAINING_OPERATION, validation), (HPARAM_SELECTION_OPERATION, training),
                           (REPRESENTATION_PROMOTION_OPERATION, training), ("unknown", training),
                           (TRAINING_OPERATION, []), (TRAINING_OPERATION, training * 2),
                           (TRAINING_OPERATION, ["sha256:" + "f" * 64])):
        with pytest.raises(prp.ProjectionError):
            projection.authorize(operation, ids)


def test_serialization_is_immutable_and_detached_from_all_returned_views(tmp_path):
    fixture = _prepared(tmp_path)
    projection = fixture.build()
    expected = projection.to_bytes()
    projection.to_dict()["records"][0]["record_summary"]["source"]["document_id"] = "changed"
    projection.selected_artifacts()["leaf_receipts"][0]["bytes"] = 1
    projection.selected_artifacts()["source_artifacts"].clear()
    projection.summary()["record_count"] = 999
    assert projection.to_bytes() == expected
    with pytest.raises((AttributeError, TypeError)):
        projection._raw = b"{}"
    artifact = projection.save(tmp_path / "projection.json")
    assert {name: artifact[name] for name in ("sha256", "bytes")} == _ref(projection)
    loaded = prp.load_produced_record_projection(artifact["path"], expected_sha256=artifact["sha256"],
        expected_size_bytes=artifact["bytes"], receipt_set=fixture.receipt_set)
    assert loaded.to_bytes() == expected
    for path in fixture.case.leaf_paths.values():
        path.unlink()
    # Reopen is metadata-only and does not imply current closure verification.
    reopened = prp.load_produced_record_projection(artifact["path"], expected_sha256=artifact["sha256"],
                                                  receipt_set=fixture.receipt_set)
    assert reopened.summary()["current_selected_leaf_bytes_verified"] is False
    with pytest.raises((FileExistsError, prp.ProjectionError)):
        projection.save(artifact["path"])
    with pytest.raises(prp.ProjectionError):
        reopened.verify_batch(fixture.manifest, receipt_resolver=fixture.case.receipt_resolver,
                               source_resolver=fixture.case.source_resolver)


@pytest.mark.parametrize("change", ["sha", "size", "bytes", "symlink"])
def test_reopen_requires_exact_regular_file_bytes(tmp_path, change):
    fixture = _prepared(tmp_path)
    projection = fixture.build()
    artifact = projection.save(tmp_path / "projection.json")
    digest, size, path = artifact["sha256"], artifact["bytes"], Path(artifact["path"])
    if change == "sha":
        digest = "f" * 64
    elif change == "size":
        size += 1
    elif change == "bytes":
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    with pytest.raises(prp.ProjectionError):
        prp.load_produced_record_projection(path, expected_sha256=digest, expected_size_bytes=size,
                                             receipt_set=fixture.receipt_set)


@pytest.mark.parametrize("change", [
    lambda data: data.update(extra=True),
    lambda data: data.update(schema_version="other"),
    lambda data: data["receipt_set"].update(sha256="f" * 64),
    lambda data: data["receipt_set"].update(bytes=True),
    lambda data: data["source_partitions"].update(sha256="f" * 64),
    lambda data: data["corpus_manifest"].update(bytes=True),
    lambda data: data.update(dataset_snapshot_id="invalid"),
    lambda data: data["records"].reverse(),
    lambda data: data["records"].append(data["records"][0]),
    lambda data: data["records"].pop(),
    lambda data: data["records"][0].update(entry_cid="sha256:" + "f" * 64),
    lambda data: data["records"][0].update(input_id="sha256:" + "f" * 64),
    lambda data: data["records"][0].update(source_row_id="sha256:" + "f" * 64),
    lambda data: data["records"][0].update(group_id="sha256:" + "f" * 64),
    lambda data: data["records"][0].update(split="holdout"),
    lambda data: data["records"][0].update(status="missing_input"),
    lambda data: data["records"][0].update(receipt_sha256="f" * 64),
    lambda data: data["records"][0].update(result_index=True),
    lambda data: data["records"][0]["record_summary"]["embedding_provenance"].update(artifact_sha256="f" * 64),
    lambda data: data["training_record_ids"].clear(),
    lambda data: data["validation_record_ids"].clear(),
    lambda data: data["training_record_ids"].append(data["validation_record_ids"][0]),
    lambda data: data["validation_record_ids"].append(data["validation_record_ids"][0]),
])
def test_resealed_projection_cannot_change_exact_membership_contract(tmp_path, change):
    fixture = _prepared(tmp_path)
    data = fixture.build().to_dict()
    change(data)
    with pytest.raises(prp.ProjectionError):
        prp.ProducedRecordProjection(_json(data), fixture.receipt_set)


@pytest.mark.parametrize("raw", [b"{}", b"[]", b"null", b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff"])
def test_malformed_or_ambiguous_projection_bytes_are_rejected(tmp_path, raw):
    fixture = _prepared(tmp_path)
    with pytest.raises(prp.ProjectionError):
        prp.ProducedRecordProjection(raw, fixture.receipt_set)


def test_noncanonical_encoding_and_tight_root_limit_are_rejected(tmp_path):
    fixture = _prepared(tmp_path)
    projection = fixture.build()
    with pytest.raises(prp.ProjectionError):
        prp.ProducedRecordProjection(projection.to_bytes() + b"\n", fixture.receipt_set)
    with pytest.raises(prp.ProjectionError):
        prp.ProducedRecordProjection(projection.to_bytes(), fixture.receipt_set,
            limits=prp.ProjectionLimits(max_bytes=len(projection.to_bytes()) - 1))


@pytest.mark.parametrize("field,maximum", [("max_records", 256), ("max_bytes", 4 * 1024**2),
    ("max_leaf_bytes", 64 * 1024**2), ("max_source_bytes", 64 * 1024**2)])
@pytest.mark.parametrize("kind", ["zero", "bool", "float", "above"])
def test_limits_cannot_expand_hard_bounds(field, maximum, kind):
    value = {"zero": 0, "bool": True, "float": 1.0, "above": maximum + 1}[kind]
    with pytest.raises(prp.ProjectionError):
        prp.ProjectionLimits(**{field: value})


@pytest.mark.parametrize("kind", ["records", "root_bytes", "leaf_bytes", "source_bytes"])
def test_all_selected_work_budgets_are_enforced_before_any_resolver(tmp_path, kind):
    fixture = _prepared(tmp_path)
    limits = {
        "records": prp.ProjectionLimits(max_records=3),
        "root_bytes": prp.ProjectionLimits(max_bytes=1),
        "leaf_bytes": prp.ProjectionLimits(max_leaf_bytes=1),
        "source_bytes": prp.ProjectionLimits(max_source_bytes=1),
    }[kind]
    with pytest.raises(prp.ProjectionError):
        prp.build_produced_record_projection(fixture.receipt_set, fixture.manifest,
            entry_cids=fixture.entry_cids, receipt_resolver=_forbidden, source_resolver=_forbidden, limits=limits)


@pytest.mark.parametrize("kind", ["leaves", "sources"])
def test_aggregate_selected_budget_applies_even_when_every_single_file_fits(tmp_path, kind):
    fixture = _prepared(tmp_path)
    selected = fixture.build().selected_artifacts()
    refs = selected["leaf_receipts" if kind == "leaves" else "source_artifacts"]
    bound = sum(ref["bytes"] for ref in refs) - 1
    assert max(ref["bytes"] for ref in refs) < bound
    limits = prp.ProjectionLimits(**{"max_leaf_bytes" if kind == "leaves" else "max_source_bytes": bound})
    with pytest.raises(prp.ProjectionError):
        prp.build_produced_record_projection(fixture.receipt_set, fixture.manifest,
            entry_cids=fixture.entry_cids, receipt_resolver=_forbidden, source_resolver=_forbidden, limits=limits)


def test_receipt_set_selected_leaf_refs_are_detached_bounded_and_unique(tmp_path):
    fixture = _prepared(tmp_path)
    root = fixture.receipt_set
    refs = root.selected_leaf_artifacts(fixture.entry_cids)
    expected = fixture.build().selected_artifacts()["leaf_receipts"]
    assert list(refs) == expected
    assert list(root.selected_leaf_artifacts(fixture.entry_cids[::-1])) == expected
    refs[0]["bytes"] = 1
    assert list(root.selected_leaf_artifacts(fixture.entry_cids)) == expected
    for invalid in ([], list(fixture.entry_cids) * 2, ["sha256:" + "f" * 64],
                    iter(fixture.entry_cids), list(fixture.entry_cids) * 65):
        with pytest.raises(ers.ReceiptSetError):
            root.selected_leaf_artifacts(invalid)


@pytest.mark.parametrize("status", ["unattempted", "missing_input", "token_limit_exceeded"])
def test_selected_leaf_refs_require_successful_embedding_membership(tmp_path, status):
    case = _case(tmp_path, groups=[[0]] if status == "unattempted" else [[0], [1]],
                 statuses={} if status == "unattempted" else {1: status}, native=True)
    root = case.build()
    with pytest.raises(ers.ReceiptSetError):
        root.selected_leaf_artifacts([case.rows[1]["entry_cid"]])
