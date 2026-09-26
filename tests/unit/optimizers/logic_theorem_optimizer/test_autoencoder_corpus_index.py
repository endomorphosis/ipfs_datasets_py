"""Frozen cross-batch grouping and exact membership without holdout overclaims."""

from dataclasses import replace
import hashlib
import json
import os

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_index as ci
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import (
    EmbeddingProvenance, SourceArtifact, SourceSampleRecord, SourceSpan, build_corpus_manifest,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
    HPARAM_SELECTION_OPERATION, REPRESENTATION_PROMOTION_OPERATION, TRAINING_OPERATION,
)


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _scope(**kwargs):
    values = {"selection_sha256": _sha("selected-rows"), "release_manifest_sha256s": (_sha("release-root"),)}
    values.update(kwargs)
    return ci.IndexScope(**values)


def _record(index, *, text=None, document=None, release="release-1", artifact=None, vector=None):
    text = text or f"The agency shall retain record number {index} for at least {index + 3} days."
    source = SourceSpan(SourceArtifact(artifact or _sha(f"source-{index}-{release}"), len(text.encode())),
                        "us_code", release, document or f"/us/usc/t5/s{index}", "en", f"5 U.S.C. {index}",
                        0, len(text.encode()))
    sample = SampleRecord("5", str(index), text, source.citation, "declared-external-encoder",
                          vector if vector is not None else (float(index), -0.0))
    return SourceSampleRecord(source, sample, EmbeddingProvenance(sample.embedding_model, "a" * 40, "b" * 64))


def _index(records, **kwargs):
    return ci.build_corpus_index(records, scope=kwargs.pop("scope", _scope()),
                                 policy=kwargs.pop("policy", ci.SplitPolicy("frozen-before-training")), **kwargs)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _population(count=80):
    return [_record(i) for i in range(count)]


def _batch(index, records, *, train_count=2, validation_count=2):
    lookup = {record.record_id: record for record in records}
    train = list(reversed(index.record_ids_for("train")[:train_count]))
    validation = list(reversed(index.record_ids_for("validation")[:validation_count]))
    return build_corpus_manifest([lookup[key] for key in train + validation],
                                training_record_ids=train, validation_record_ids=validation, mode="corpus")


def test_index_is_deterministic_independent_of_input_order_and_contains_no_text_or_vectors():
    records = _population()
    left, right = _index(records), _index(list(reversed(records)))
    assert left.to_bytes() == right.to_bytes()
    assert left.index_id == "sha256:" + left.sha256
    assert left.sha256 == hashlib.sha256(left.to_bytes()).hexdigest()
    assert all(count > 0 for count in left.partition_counts.values())
    assert records[0].sample.text.encode() not in left.to_bytes()
    assert b"embedding_vector" not in left.to_bytes()
    assert len(set(left.record_groups.values())) == len(records)


def test_document_source_and_content_keys_group_transitively_across_releases():
    first = _record(1, document="same-law", release="old")
    second = _record(2, document="same-law", release="new")
    third = _record(3, text="  " + second.sample.text.upper() + "\n", document="other-law")
    fourth = _record(4, artifact=third.source.artifact.sha256)
    # A physical artifact has one exact size, independent of selectors.
    common_size = max(third.source.artifact.bytes, fourth.source.artifact.bytes)
    third = replace(third, source=replace(third.source, artifact=SourceArtifact(third.source.artifact.sha256, common_size)))
    fourth = replace(fourth, source=replace(fourth.source, artifact=SourceArtifact(fourth.source.artifact.sha256, common_size)))
    index = _index([first, second, third, fourth])
    assert len(set(index.record_groups.values())) == 1
    assert len(set(index.assignments.values())) == 1
    assert {row["source"]["release_id"] for row in index.to_dict()["records"]} == {"old", "new", "release-1"}


def test_same_embedding_producer_and_release_do_not_merge_unrelated_documents():
    records = _population()
    assert len({record.embedding_provenance for record in records}) == 1
    assert len({record.source.release_id for record in records}) == 1
    index = _index(records)
    assert len(set(index.record_groups.values())) == len(records)
    assert len(set(index.assignments.values())) == 4


def test_embedding_variants_keep_source_partition_but_change_exact_record_identity():
    first = _record(1)
    second = replace(first, sample=replace(first.sample, embedding_vector=(1.0, 0.0)))
    third = replace(first, embedding_provenance=replace(first.embedding_provenance, revision="c" * 40))
    indexes = [_index([record]) for record in (first, second, third)]
    assert len({record.record_id for record in (first, second, third)}) == 3
    assert len({next(iter(index.record_groups.values())) for index in indexes}) == 1
    assert len({next(iter(index.assignments.values())) for index in indexes}) == 1
    together = _index([first, second, third])
    assert len(set(together.record_groups.values())) == 1


def test_index_reuses_exact_ordered_batch_membership_and_preserves_batch_identities():
    records = _population()
    index = _index(records)
    manifest = _batch(index, records)
    before = manifest.to_bytes()
    summary = index.verify_batch(manifest)
    split = manifest.to_dict()["split"]
    assert summary["training_record_ids"] == split["training_record_ids"]
    assert summary["validation_record_ids"] == split["validation_record_ids"]
    assert summary["dataset_snapshot_id"] == manifest.dataset_snapshot_id
    assert summary["split_snapshot_id"] == manifest.split_snapshot_id
    assert manifest.to_bytes() == before
    assert summary["batch_index_membership_verified"] is True
    assert summary["indexed_partition_disjoint_verified"] is True
    assert summary["global_holdout_verified"] is summary["corpus_complete"] is summary["admitted"] is False


@pytest.mark.parametrize("protected", ["validation", "canary", "holdout"])
def test_protected_records_cannot_enter_training(protected):
    records = _population()
    index = _index(records)
    lookup = {record.record_id: record for record in records}
    key = index.record_ids_for(protected)[0]
    manifest = build_corpus_manifest([lookup[key]], training_record_ids=[key], validation_record_ids=[], mode="diagnostic")
    with pytest.raises(ci.CorpusIndexError, match="protected from training"):
        index.verify_batch(manifest)


@pytest.mark.parametrize("protected", ["train", "canary", "holdout"])
def test_nonvalidation_records_cannot_enter_line_search_validation(protected):
    records = _population()
    index = _index(records)
    lookup = {record.record_id: record for record in records}
    train = index.record_ids_for("train")[0]
    validation = index.record_ids_for(protected)[-1]
    keys = list(dict.fromkeys([train, validation]))
    manifest = build_corpus_manifest([lookup[key] for key in keys], training_record_ids=[train],
                                     validation_record_ids=[validation], mode="diagnostic")
    with pytest.raises(ci.CorpusIndexError, match="protected from hparam_selection"):
        index.verify_batch(manifest)


def test_operations_reuse_existing_split_vocabulary():
    index = _index(_population())
    index.authorize(TRAINING_OPERATION, [index.record_ids_for("train")[0]])
    index.authorize(HPARAM_SELECTION_OPERATION, [index.record_ids_for("validation")[0]])
    index.authorize(REPRESENTATION_PROMOTION_OPERATION, [index.record_ids_for("canary")[0]])
    with pytest.raises(ci.CorpusIndexError, match="unknown split operation"):
        index.authorize("unrestricted_training", [])
    with pytest.raises(ci.CorpusIndexError, match="outside the frozen"):
        index.authorize(TRAINING_OPERATION, ["sha256:" + "0" * 64])


@pytest.mark.parametrize("mutation", [
    lambda record: replace(record, sample=replace(record.sample, embedding_vector=(1.0, 0.0))),
    lambda record: replace(record, source=replace(record.source, release_id="different-release")),
    lambda record: replace(record, source=replace(record.source, citation="different-citation")),
    lambda record: replace(record, embedding_provenance=replace(record.embedding_provenance, revision="f" * 40)),
])
def test_changed_record_payload_or_provenance_cannot_join_frozen_index(mutation):
    original = _record(1)
    index = _index([original], policy=ci.SplitPolicy("all-train", train=10000, validation=0, canary=0, holdout=0))
    changed = mutation(original)
    batch = build_corpus_manifest([changed], training_record_ids=[changed.record_id], validation_record_ids=[], mode="diagnostic")
    with pytest.raises(ci.CorpusIndexError, match="exact frozen index summary"):
        index.verify_batch(batch)


def test_forged_summary_is_detected_when_exact_batch_record_is_present():
    record = _record(1)
    index = _index([record], policy=ci.SplitPolicy("all-train", train=10000, validation=0, canary=0, holdout=0))
    data = index.to_dict()
    data["records"][0]["sample_payload_sha256"] = "0" * 64
    forged = ci.CorpusIndex(_json(data))
    batch = build_corpus_manifest([record], training_record_ids=[record.record_id], validation_record_ids=[], mode="diagnostic")
    with pytest.raises(ci.CorpusIndexError, match="exact frozen index summary"):
        forged.verify_batch(batch)


def test_empty_frozen_partition_fails_selection_without_reassigning():
    index = _index([_record(1)], policy=ci.SplitPolicy("all-train", train=10000, validation=0, canary=0, holdout=0))
    before = index.to_bytes()
    with pytest.raises(ci.CorpusIndexError, match="empty; no automatic resampling"):
        index.record_ids_for("validation")
    assert index.record_ids_for("validation", require_nonempty=False) == ()
    assert index.to_bytes() == before


def test_cached_metadata_is_immutable_and_external_copies_cannot_change_index():
    index = _index(_population())
    raw = index.to_bytes()
    assignments = index.assignments
    assignments.clear()
    index.record_groups.clear()
    index.partition_counts.clear()
    data = index.to_dict()
    data["records"][0]["source"]["release_id"] = "mutated"
    with pytest.raises(TypeError):
        index._summaries[next(iter(index._summaries))]["source"]["release_id"] = "mutated"
    assert index.to_bytes() == raw
    assert index.assignments


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(unknown=True),
    lambda value: value.update(schema_version="unknown"),
    lambda value: value["records"][0].update(text="must not be here"),
    lambda value: value["records"][0]["source"].update(path="/arbitrary"),
    lambda value: value["assignments"].update({value["records"][0]["record_id"]: "holdout"}),
    lambda value: value["record_groups"].update({value["records"][0]["record_id"]: "sha256:" + "0" * 64}),
    lambda value: value["records"].reverse(),
    lambda value: value["records"].append(value["records"][0]),
])
def test_closed_schema_and_deterministic_assignments_reject_tampering(mutation):
    index = _index(_population(), policy=ci.SplitPolicy("all-train", train=10000, validation=0, canary=0, holdout=0))
    value = index.to_dict()
    mutation(value)
    with pytest.raises(ci.CorpusIndexError):
        ci.CorpusIndex(_json(value))


def test_canonical_json_and_duplicate_field_rules():
    index = _index([_record(1)])
    with pytest.raises(ci.CorpusIndexError, match="noncanonical"):
        ci.CorpusIndex(json.dumps(index.to_dict(), indent=2).encode())
    with pytest.raises(ci.CorpusIndexError, match="invalid index JSON"):
        ci.CorpusIndex(b'{"x":1,"x":2}')
    with pytest.raises(ci.CorpusIndexError, match="invalid index JSON"):
        ci.CorpusIndex(b'{"x":NaN}')


def test_exclusive_save_and_bounded_hash_verified_load(tmp_path):
    index = _index(_population())
    path = tmp_path / "index.json"
    descriptor = index.save(path)
    loaded = ci.load_corpus_index(path, expected_sha256=descriptor["sha256"], expected_size_bytes=descriptor["bytes"])
    assert loaded.to_bytes() == index.to_bytes()
    assert loaded.assignments == index.assignments
    with pytest.raises(FileExistsError):
        index.save(path)
    with pytest.raises(ci.CorpusIndexError, match="SHA-256 mismatch"):
        ci.load_corpus_index(path, expected_sha256="0" * 64)
    with pytest.raises(ci.CorpusIndexError, match="expected size"):
        ci.load_corpus_index(path, expected_sha256=index.sha256, expected_size_bytes=descriptor["bytes"] + 1)
    path.write_bytes(path.read_bytes()[:-1] + b" ")
    with pytest.raises(ci.CorpusIndexError, match="SHA-256 mismatch"):
        ci.load_corpus_index(path, expected_sha256=index.sha256)


def test_missing_symlink_and_nonregular_files_are_rejected(tmp_path):
    index = _index([_record(1)])
    path = tmp_path / "index.json"
    index.save(path)
    link = tmp_path / "link"
    link.symlink_to(path)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    for invalid in (tmp_path / "missing", link, fifo):
        with pytest.raises(ci.CorpusIndexError):
            ci.load_corpus_index(invalid, expected_sha256=index.sha256)


def test_record_byte_and_release_bounds_are_enforced():
    records = [_record(1), _record(2)]
    with pytest.raises(ci.CorpusIndexError, match="record count"):
        _index(records, limits=ci.IndexLimits(max_records=1))
    with pytest.raises(ci.CorpusIndexError, match="byte bound"):
        _index(records, limits=ci.IndexLimits(max_index_bytes=1))
    with pytest.raises(ci.CorpusIndexError, match="release manifest count"):
        _index(records, scope=_scope(release_manifest_sha256s=(_sha("r1"), _sha("r2"))),
               limits=ci.IndexLimits(max_release_manifests=1))
    with pytest.raises(ci.CorpusIndexError, match="duplicate indexed"):
        _index([records[0], records[0]])


@pytest.mark.parametrize("kwargs", [{"max_records": 65537}, {"max_records": True}, {"max_records": 0},
                                  {"max_index_bytes": 64 * 1024 * 1024 + 1}, {"max_release_manifests": 129}])
def test_limits_cannot_exceed_contract(kwargs):
    with pytest.raises(ci.CorpusIndexError, match="bound"):
        ci.IndexLimits(**kwargs)


@pytest.mark.parametrize("kwargs", [{"train": True}, {"train": 8000.0}, {"train": -1}, {"train": 8001}, {"seed": ""}])
def test_split_policy_is_explicit_and_integer_bounded(kwargs):
    values = {"seed": "frozen"}
    values.update(kwargs)
    with pytest.raises(ci.CorpusIndexError):
        ci.SplitPolicy(**values)


def test_scope_never_claims_whole_corpus_or_global_holdout():
    with pytest.raises(ci.CorpusIndexError, match="selected_subset"):
        _scope(completeness="all_federal_laws")
    with pytest.raises(ci.CorpusIndexError, match="duplicate release"):
        _scope(release_manifest_sha256s=(_sha("root"), _sha("root")))
    with pytest.raises(ci.CorpusIndexError, match="release manifest"):
        _scope(release_manifest_sha256s=())
    index = _index(_population())
    summary = index.verification_summary()
    assert summary["scope"]["completeness"] == "selected_subset"
    for field in ("global_holdout_verified", "corpus_complete", "source_bytes_verified",
                  "source_authority_authenticated", "embedding_producer_authenticated",
                  "semantic_duplicate_isolation_verified", "unseen_checkpoint_lineage_verified", "admitted"):
        assert summary[field] is False
