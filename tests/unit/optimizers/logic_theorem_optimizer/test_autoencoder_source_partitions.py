"""Freeze source membership before embedding exclusions; fixtures never run a model."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_index as ci
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_partitions as sp
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_import as imp
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_inventory as inv
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import (
    EmbeddingProvenance, SourceArtifact, SourceSampleRecord, SourceSpan,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_production import EmbeddingInput
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
    CODEX_TODO_PROJECTION_OPERATION, HPARAM_SELECTION_OPERATION,
    REPRESENTATION_PROMOTION_OPERATION, TRAINING_OPERATION,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_uscode_inventory import (
    _build, _release, _row, _rows,
)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _parts(inventory, **kwargs):
    return sp.build_source_partitions(inventory,
        policy=kwargs.pop("policy", ci.SplitPolicy("source-before-embedding")), **kwargs)


def _only_split(split):
    return ci.SplitPolicy("explicit-test-partition", **{name: 10000 if name == split else 0 for name in ci.SPLITS})


def _physical_id(inventory, path, index):
    return "sha256:" + _sha(_json({"schema": "source-inventory-row-v1", "inventory_sha256": inventory.sha256,
                                 "relative_path": path, "row_index": index}))


def _expected_group(rows):
    # Independent, explicit expected component keys. Neither a shard SHA nor a
    # release root nor an embedding model belongs in this grouping domain.
    keys = set()
    for row in rows:
        meta = row["metadata"]
        keys.update(_json(key).decode() for key in (
            ["document", "us_code", meta["canonical_identity"]["document_id"]],
            ["source_artifact", meta["text_sha256"]],
            ["normalized_content", meta["normalized_content_sha256"]],
        ))
    return "sha256:" + _sha(_json({"schema": "document-source-content-connected-groups-v1", "keys": sorted(keys)}))


def _record(row, fixture, *, vector=(1.0, -0.0)):
    """Explicit synthetic record solely for codec/projection assertions."""
    raw = row["text"].encode()
    citation = f"{row['title']} U.S.C. § {row['section']}"
    source = SourceSpan(SourceArtifact(_sha(raw), len(raw)), "us_code", fixture.release.release_id,
                        row["legal_id"], "en", citation, 0, len(raw))
    sample = SampleRecord(row["title"], row["section"], row["text"], citation,
                          "unit-fixture-only", vector)
    return SourceSampleRecord(source, sample, EmbeddingProvenance("unit-fixture-only", "a" * 40, "b" * 64))


def _connector_fixture(tmp_path, *, oversized=False):
    a = _row(1, text="Alpha retained.")
    b = _row(2, legal_id=a["legal_id"], section=a["section"], text="  Béta\t retained.  ")
    c = _row(3, text="bÉTA retained.")
    if oversized:
        b["text"] = " " * 100 + b["text"]
    else:
        b["admission_status"] = "excluded"
    fixture = _release(tmp_path, [[a, b], [c]],
                       import_limits=imp.USCodeImportLimits(max_text_bytes=80) if oversized else None)
    return fixture, (a, b, c)


def test_freeze_preserves_physical_rows_and_never_constructs_embedding_records(tmp_path, monkeypatch):
    fixture = _release(tmp_path)
    inventory = _build(fixture)
    monkeypatch.setattr(EmbeddingInput, "from_source_record", classmethod(
        lambda cls, record: pytest.fail("freezing source partitions must not need embedding-bearing records")))
    partitions = _parts(inventory)
    data = partitions.to_dict()
    assert data["inventory"] == {"sha256": inventory.sha256, "bytes": len(inventory.to_bytes())}
    assert sum(partitions.partition_counts.values()) == sum(partitions.eligible_partition_counts.values()) == 3
    assert len(data["rows"]) == 3
    expected_ids = [_physical_id(inventory, shard["artifact"]["relative_path"], row["row_index"])
                    for shard in inventory.to_dict()["shards"] for row in shard["rows"]]
    assert [row["source_row_id"] for row in data["rows"]] == expected_ids
    assert all(set(row) == {"source_row_id", "group_id", "split"} for row in data["rows"])
    assert b"embedding_vector" not in partitions.to_bytes() and b"The agency shall" not in partitions.to_bytes()
    assert partitions.sha256 == _sha(partitions.to_bytes())


@pytest.mark.parametrize("oversized", [False, True])
def test_excluded_rows_preserve_transitive_groups_before_any_selection(tmp_path, oversized):
    fixture, originals = _connector_fixture(tmp_path, oversized=oversized)
    inventory = _build(fixture)
    partitions = _parts(inventory)
    rows = _rows(inventory)
    assert rows[1]["status"] == ("text_exceeds_bound" if oversized else "retrieval_disposition_excluded")
    assert {row["group_id"] for row in partitions.to_dict()["rows"]} == {_expected_group(rows)}
    assert sum(partitions.partition_counts.values()) == 3
    assert sum(partitions.eligible_partition_counts.values()) == 2
    split = partitions.binding_for(originals[0]["entry_cid"])["split"]
    assert partitions.entry_cids_for(split) == (originals[0]["entry_cid"], originals[2]["entry_cid"])
    with pytest.raises(sp.SourcePartitionError):
        partitions.binding_for(originals[1]["entry_cid"])
    assert _expected_group(rows) != _expected_group([rows[0], rows[2]])


def test_group_keys_and_assignments_match_existing_index_on_full_eligible_population(tmp_path):
    originals = [_row(i) for i in range(1, 61)]
    fixture = _release(tmp_path, [originals[:30], originals[30:]])
    inventory = _build(fixture)
    policy = ci.SplitPolicy("cross-codec-parity", train=2500, validation=2500, canary=2500, holdout=2500)
    partitions = _parts(inventory, policy=policy)
    records = [_record(row, fixture) for row in originals]
    index = ci.build_corpus_index(records, policy=policy,
        scope=ci.IndexScope(inventory.sha256, (fixture.root["sha256"],)))
    assert all(partitions.partition_counts.values())
    for original, record, metadata in zip(originals, records, _rows(inventory)):
        binding = partitions.binding_for(original["entry_cid"])
        assert binding["group_id"] == index.record_groups[record.record_id] == _expected_group([metadata])
        assert binding["split"] == index.assignments[record.record_id]
    assert len({row["group_id"] for row in partitions.to_dict()["rows"]}) == 60


def test_duplicate_input_ids_do_not_collapse_physical_occurrences(tmp_path):
    a = _row(1)
    b = {**a, "entry_cid": _row(2)["entry_cid"], "document_index": 2}
    fixture = _release(tmp_path, [[a], [b]])
    inventory = _build(fixture)
    partitions = _parts(inventory, policy=_only_split("train"))
    left, right = [partitions.binding_for(row["entry_cid"]) for row in (a, b)]
    assert left["input_id"] == right["input_id"]
    assert left["source_row_id"] != right["source_row_id"]
    assert left["group_id"] == right["group_id"]
    assert partitions.partition_counts["train"] == partitions.eligible_partition_counts["train"] == 2
    assert partitions.verification_summary()["physical_row_count"] == 2
    assert partitions.verification_summary()["eligible_unique_input_count"] == 1
    assert partitions.entry_cids_for("train") == (a["entry_cid"], b["entry_cid"])
    with pytest.raises(ValueError):
        sp.materialize_partition_inputs(partitions, [a["entry_cid"], b["entry_cid"]], tmp_path / "aliases",
            operation=TRAINING_OPERATION, release=fixture.release, resolver=fixture.resolve)
    assert not (tmp_path / "aliases").exists()


def test_duplicate_cid_rows_remain_connectors_but_cannot_be_selected(tmp_path):
    fixture, originals = _connector_fixture(tmp_path)
    a, b, c = originals
    b = {**b, "admission_status": "admitted", "entry_cid": a["entry_cid"]}
    fixture = _release(tmp_path / "duplicate", [[a, b], [c]])
    inventory = _build(fixture)
    partitions = _parts(inventory, policy=_only_split("train"))
    assert sum(partitions.partition_counts.values()) == 3
    assert partitions.entry_cids_for("train") == (c["entry_cid"],)
    assert {row["group_id"] for row in partitions.to_dict()["rows"]} == {_expected_group(_rows(inventory))}
    with pytest.raises(sp.SourcePartitionError):
        partitions.binding_for(a["entry_cid"])


@pytest.mark.parametrize("text", ["", " \t\n"])
def test_verified_empty_text_can_contribute_source_keys_without_embedding_input(tmp_path, text):
    a = _row(1)
    b = _row(2, legal_id=a["legal_id"], section=a["section"], text=text)
    fixture = _release(tmp_path, [[a, b]])
    inventory = _build(fixture)
    assert inventory.summary()["grouping_metadata_complete"] is True
    partitions = _parts(inventory, policy=_only_split("train"))
    assert partitions.partition_counts["train"] == 2
    assert partitions.eligible_partition_counts["train"] == 1
    assert {row["group_id"] for row in partitions.to_dict()["rows"]} == {_expected_group(_rows(inventory))}


@pytest.mark.parametrize("mode", ["missing", "corrupt", "invalid_wrapper", "identity", "missing_text"])
def test_incomplete_grouping_metadata_cannot_be_hidden_by_healthy_selected_rows(tmp_path, mode):
    changed = _row(2, **({"title": "7"} if mode == "identity" else {"text": None} if mode == "missing_text" else {}))
    fixture = _release(tmp_path, [[_row(1)], [changed]], wrapper_change=(
        lambda index, rows: rows[0].update(record_sha256="0" * 64) if index == 1 else None
    ) if mode == "invalid_wrapper" else None)
    if mode == "missing":
        fixture.shards[1].unlink()
    elif mode == "corrupt":
        fixture.shards[1].write_bytes(b"broken source")
    inventory = _build(fixture)
    assert inventory.summary()["grouping_metadata_complete"] is False
    with pytest.raises(sp.SourcePartitionError):
        _parts(inventory)


def test_partition_bytes_are_deterministic_and_loaded_state_is_detached(tmp_path):
    fixture = _release(tmp_path)
    inventory = _build(fixture, batch_size=1)
    partitions = _parts(inventory)
    assert _parts(_build(fixture, batch_size=2)).to_bytes() == partitions.to_bytes()
    restored = sp.SourcePartitions(partitions.to_bytes(), inventory)
    assert restored.to_bytes() == partitions.to_bytes()
    copy = restored.to_dict()
    copy["rows"][0]["split"] = "forged"
    counts = restored.partition_counts
    counts["train"] = 999
    binding = restored.binding_for(_row(1)["entry_cid"])
    binding["input_id"] = "forged"
    assert restored.to_bytes() == partitions.to_bytes()
    assert sum(restored.partition_counts.values()) == 3
    assert restored.binding_for(_row(1)["entry_cid"])["input_id"] != "forged"


def test_partition_cannot_be_rebound_to_another_self_consistent_inventory(tmp_path):
    fixture = _release(tmp_path / "old")
    inventory = _build(fixture)
    partitions = _parts(inventory)
    altered = _release(tmp_path / "new", [[_row(1, text="Changed legal text."), _row(2)], [_row(3)]])
    other_inventory = _build(altered)
    with pytest.raises(sp.SourcePartitionError):
        sp.SourcePartitions(partitions.to_bytes(), other_inventory)


@pytest.mark.parametrize("mutation", [
    lambda data: data.update(unknown=True),
    lambda data: data["inventory"].update(sha256="0" * 64),
    lambda data: data["inventory"].update(bytes=True),
    lambda data: data["rows"].pop(),
    lambda data: data["rows"].reverse(),
    lambda data: data["rows"][0].update(source_row_id="sha256:" + "0" * 64),
    lambda data: data["rows"][0].update(group_id="sha256:" + "0" * 64),
    lambda data: data["rows"][0].update(split="holdout"),
    lambda data: data.update(content_normalization="lowercase-only"),
])
def test_resealed_partition_metadata_cannot_override_frozen_derivation(tmp_path, mutation):
    inventory = _build(_release(tmp_path))
    partitions = _parts(inventory, policy=_only_split("train"))
    data = partitions.to_dict()
    mutation(data)
    with pytest.raises(sp.SourcePartitionError):
        sp.SourcePartitions(_json(data), inventory)


@pytest.mark.parametrize("raw", [b"{}", b"[]", b"null", b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff"])
def test_partition_decoder_rejects_noncanonical_and_ambiguous_json(tmp_path, raw):
    inventory = _build(_release(tmp_path))
    with pytest.raises(sp.SourcePartitionError):
        sp.SourcePartitions(raw, inventory)


def test_save_and_load_require_expected_content_identity_and_exclusive_output(tmp_path):
    inventory = _build(_release(tmp_path))
    partitions = _parts(inventory)
    saved = partitions.save(tmp_path / "partitions.json")
    assert saved["sha256"] == partitions.sha256 and saved["bytes"] == len(partitions.to_bytes())
    restored = sp.load_source_partitions(saved["path"], expected_sha256=saved["sha256"],
        expected_size_bytes=saved["bytes"], inventory=inventory)
    assert restored.to_bytes() == partitions.to_bytes()
    with pytest.raises((FileExistsError, sp.SourcePartitionError)):
        partitions.save(saved["path"])
    for digest, size in (("0" * 64, saved["bytes"]), (saved["sha256"], saved["bytes"] + 1)):
        with pytest.raises(sp.SourcePartitionError):
            sp.load_source_partitions(saved["path"], expected_sha256=digest,
                expected_size_bytes=size, inventory=inventory)
    Path(saved["path"]).write_bytes(partitions.to_bytes() + b"\n")
    with pytest.raises(sp.SourcePartitionError):
        sp.SourcePartitions(Path(saved["path"]).read_bytes(), inventory)


def test_loader_rejects_missing_symlink_directory_and_untrusted_inventory(tmp_path):
    inventory = _build(_release(tmp_path))
    partitions = _parts(inventory)
    path = tmp_path / "partitions.json"
    partitions.save(path)
    link = tmp_path / "link"
    link.symlink_to(path)
    for candidate in (tmp_path / "absent", link, tmp_path):
        with pytest.raises(sp.SourcePartitionError):
            sp.load_source_partitions(candidate, expected_sha256=partitions.sha256, inventory=inventory)
    with pytest.raises(sp.SourcePartitionError):
        sp.SourcePartitions(partitions.to_bytes(), inventory.to_dict())


@pytest.mark.parametrize("field,value", [("max_rows", 0), ("max_rows", True), ("max_rows", 65537),
    ("max_bytes", 0), ("max_bytes", 1.5), ("max_bytes", 64 * 1024**2 + 1)])
def test_limits_are_strict_and_cannot_expand_bounded_contract(field, value):
    with pytest.raises(sp.SourcePartitionError):
        sp.SourcePartitionLimits(**{field: value})


def test_partition_population_and_serialized_byte_budgets_are_enforced(tmp_path):
    inventory = _build(_release(tmp_path))
    for limits in (sp.SourcePartitionLimits(max_rows=2), sp.SourcePartitionLimits(max_bytes=20)):
        with pytest.raises(sp.SourcePartitionError):
            _parts(inventory, limits=limits)


def test_empty_partitions_fail_selection_without_policy_resampling(tmp_path):
    inventory = _build(_release(tmp_path))
    partitions = _parts(inventory, policy=_only_split("train"))
    before = partitions.to_bytes()
    with pytest.raises(sp.SourcePartitionError):
        partitions.entry_cids_for("holdout")
    assert partitions.entry_cids_for("holdout", require_nonempty=False) == ()
    assert partitions.to_bytes() == before
    for split, nonempty in (("external_test", True), ("train", 1)):
        with pytest.raises(sp.SourcePartitionError):
            partitions.entry_cids_for(split, require_nonempty=nonempty)


@pytest.mark.parametrize("split", ci.SPLITS)
@pytest.mark.parametrize("operation,allowed", [
    (TRAINING_OPERATION, {"train"}), (HPARAM_SELECTION_OPERATION, {"validation"}),
    (REPRESENTATION_PROMOTION_OPERATION, {"canary"}),
    (CODEX_TODO_PROJECTION_OPERATION, {"train", "validation"}),
])
def test_explicit_source_selections_reuse_protected_operation_matrix(tmp_path, split, operation, allowed):
    partitions = _parts(_build(_release(tmp_path)), policy=_only_split(split))
    entry_cids = [_row(1)["entry_cid"]]
    if split in allowed:
        assert partitions.authorize(operation, entry_cids) is None
    else:
        with pytest.raises(sp.SourcePartitionError):
            partitions.authorize(operation, entry_cids)


@pytest.mark.parametrize("entries", [[], [_row(1)["entry_cid"]] * 2,
    ["unknown"], [True], _row(1)["entry_cid"], None])
def test_authorization_requires_explicit_bounded_unique_known_entries(tmp_path, entries):
    partitions = _parts(_build(_release(tmp_path)), policy=_only_split("train"))
    with pytest.raises(sp.SourcePartitionError):
        partitions.authorize(TRAINING_OPERATION, entries)
    with pytest.raises(sp.SourcePartitionError):
        partitions.authorize("unrestricted-training", [_row(1)["entry_cid"]])


def test_projection_retains_full_source_component_after_connector_exclusion(tmp_path):
    fixture, originals = _connector_fixture(tmp_path)
    inventory = _build(fixture)
    partitions = _parts(inventory)
    records = [_record(originals[i], fixture) for i in (2, 0)]
    ids = [originals[i]["entry_cid"] for i in (2, 0)]
    result = partitions.project_records(records, entry_cids=ids)
    assert result["source_partitions"] == {"sha256": partitions.sha256, "bytes": len(partitions.to_bytes())}
    assert result["training_eligible"] is result["admitted"] is False
    assert [row["entry_cid"] for row in result["records"]] == ids
    assert [row["record_summary"]["record_id"] for row in result["records"]] == [r.record_id for r in records]
    for record, entry_cid, row in zip(records, ids, result["records"]):
        assert row == {"record_summary": ci._summary(record), **partitions.binding_for(entry_cid)}
        assert row["group_id"] == _expected_group(_rows(inventory))
    subset_index = ci.build_corpus_index(records, policy=ci.SplitPolicy("source-before-embedding"),
        scope=ci.IndexScope(inventory.sha256, (fixture.root["sha256"],)))
    assert len(set(subset_index.record_groups.values())) == 2
    assert all(row["group_id"] != subset_index.record_groups[record.record_id]
               for row, record in zip(result["records"], records))


def test_projection_binds_exact_record_variants_without_changing_source_membership(tmp_path):
    fixture = _release(tmp_path)
    partitions = _parts(_build(fixture))
    record = _record(_row(1), fixture)
    changed_vector = replace(record, sample=replace(record.sample, embedding_vector=(1.0, 0.0)))
    changed_producer = replace(record, embedding_provenance=replace(record.embedding_provenance, revision="c" * 40))
    results = [partitions.project_records([variant], entry_cids=[_row(1)["entry_cid"]])["records"][0]
               for variant in (record, changed_vector, changed_producer)]
    assert len({row["record_summary"]["record_id"] for row in results}) == 3
    assert len({row["input_id"] for row in results}) == len({row["group_id"] for row in results}) == 1
    assert len({row["split"] for row in results}) == 1


@pytest.mark.parametrize("bound", ["per_vector", "aggregate_values"])
def test_projection_checks_all_numeric_budgets_before_serializing_any_record(tmp_path, monkeypatch, bound):
    originals = [_row(i) for i in range(1, 3 if bound == "per_vector" else 26)]
    fixture = _release(tmp_path, [originals])
    partitions = _parts(_build(fixture))
    if bound == "per_vector":
        records = [_record(originals[0], fixture), _record(originals[1], fixture, vector=(1.0,) * 4097)]
    else:
        records = [_record(row, fixture, vector=(1.0,) * 4096) for row in originals]
        assert sum(len(record.sample.embedding_vector) for record in records) > 98304
    monkeypatch.setattr(SourceSampleRecord, "to_dict", lambda self: pytest.fail(
        "all projection budgets must be checked before serializing even the first record"))
    with pytest.raises(sp.SourcePartitionError):
        partitions.project_records(records, entry_cids=[row["entry_cid"] for row in originals])


def test_projection_rejects_record_without_embedding_before_serialization(tmp_path, monkeypatch):
    fixture = _release(tmp_path)
    partitions = _parts(_build(fixture))
    record = _record(_row(1), fixture)
    missing = replace(record, sample=replace(record.sample, embedding_model="mock:stable-sha256",
                                            embedding_vector=None), embedding_provenance=None)
    monkeypatch.setattr(SourceSampleRecord, "to_dict", lambda self: pytest.fail(
        "missing embeddings must be rejected before record serialization"))
    with pytest.raises(sp.SourcePartitionError):
        partitions.project_records([missing], entry_cids=[_row(1)["entry_cid"]])


@pytest.mark.parametrize("mutation", [
    lambda r: replace(r, sample=replace(r.sample, text=r.sample.text + " ")),
    lambda r: replace(r, sample=replace(r.sample, title="7")),
    lambda r: replace(r, sample=replace(r.sample, section="999")),
    lambda r: replace(r, source=replace(r.source, release_id="other-release")),
    lambda r: replace(r, source=replace(r.source, document_id="usc:us:5:999")),
    lambda r: replace(r, source=replace(r.source, artifact=replace(r.source.artifact, sha256="f" * 64))),
    lambda r: replace(r, source=replace(r.source, language="fr")),
    lambda r: replace(r, source=replace(r.source, byte_start=1)),
    lambda r: replace(r, source=replace(r.source, citation="different citation"),
                      sample=replace(r.sample, citation="different citation")),
])
def test_projection_rejects_changed_input_identity_even_with_same_normalized_text(tmp_path, mutation):
    fixture = _release(tmp_path)
    partitions = _parts(_build(fixture))
    record = mutation(_record(_row(1), fixture))
    with pytest.raises(sp.SourcePartitionError):
        partitions.project_records([record], entry_cids=[_row(1)["entry_cid"]])


@pytest.mark.parametrize("mode", ["empty", "mismatched_lengths", "duplicate_selection", "unknown", "wrong_record", "over_limit"])
def test_projection_requires_bounded_exact_explicit_occurrence_membership(tmp_path, mode):
    fixture = _release(tmp_path)
    partitions = _parts(_build(fixture))
    records, ids = [_record(_row(1), fixture)], [_row(1)["entry_cid"]]
    if mode == "empty":
        records, ids = [], []
    elif mode == "mismatched_lengths":
        ids = []
    elif mode == "duplicate_selection":
        records, ids = records * 2, ids * 2
    elif mode == "unknown":
        ids = [_row(99)["entry_cid"]]
    elif mode == "wrong_record":
        ids = [_row(2)["entry_cid"]]
    else:
        records, ids = records * 257, [_row(i)["entry_cid"] for i in range(257)]
    with pytest.raises(sp.SourcePartitionError):
        partitions.project_records(records, entry_cids=ids)


def test_materialization_authorizes_before_any_source_read_or_output(tmp_path):
    fixture = _release(tmp_path)
    partitions = _parts(_build(fixture), policy=_only_split("holdout"))
    def forbidden(reference):
        pytest.fail("protected source selection must fail before source reads")
    with pytest.raises(sp.SourcePartitionError):
        sp.materialize_partition_inputs(partitions, [_row(1)["entry_cid"]], tmp_path / "protected",
            operation=TRAINING_OPERATION, release=fixture.release, resolver=forbidden)
    assert not (tmp_path / "protected").exists()


def test_materialization_preserves_order_exact_inputs_and_durable_partition_receipt(tmp_path):
    fixture = _release(tmp_path)
    inventory = _build(fixture)
    partitions = _parts(inventory, policy=_only_split("train"))
    ids = [_row(3)["entry_cid"], _row(1)["entry_cid"]]
    result = sp.materialize_partition_inputs(partitions, ids, tmp_path / "selected",
        operation=TRAINING_OPERATION, release=fixture.release, resolver=fixture.resolve)
    assert result.inputs == result.materialization.inputs
    assert [item.input_id for item in result.inputs] == [partitions.binding_for(key)["input_id"] for key in ids]
    assert [item.text for item in result.inputs] == [_row(3)["text"], _row(1)["text"]]
    receipt = result.selection_receipt
    assert receipt["source_partitions"] == {"sha256": partitions.sha256, "bytes": len(partitions.to_bytes())}
    assert receipt["operation"] == TRAINING_OPERATION
    assert receipt["bindings"] == [partitions.binding_for(key) for key in ids]
    assert receipt["inventory_selection"] == {name: result.materialization.selection_receipt_artifact[name]
                                               for name in ("sha256", "bytes")}
    reference = result.selection_receipt_artifact
    raw = Path(reference["path"]).read_bytes()
    assert Path(reference["path"]).name == "source-partition-selection.json"
    assert reference["sha256"] == _sha(raw) and reference["bytes"] == len(raw)
    assert json.loads(raw) == receipt
    assert receipt["admitted"] is False and receipt["training_eligible"] is False
    with pytest.raises((ValueError, FileExistsError)):
        sp.materialize_partition_inputs(partitions, ids, tmp_path / "selected",
            operation=TRAINING_OPERATION, release=fixture.release, resolver=fixture.resolve)
    assert Path(reference["path"]).read_bytes() == raw


def test_materialization_still_rechecks_selected_source_bytes_and_release(tmp_path):
    fixture = _release(tmp_path)
    partitions = _parts(_build(fixture), policy=_only_split("train"))
    fixture.shards[0].write_bytes(b"changed after freezing")
    with pytest.raises(ValueError):
        sp.materialize_partition_inputs(partitions, [_row(1)["entry_cid"]], tmp_path / "changed",
            operation=TRAINING_OPERATION, release=fixture.release, resolver=fixture.resolve)
    assert not (tmp_path / "changed").exists()


def test_source_partition_integrity_does_not_claim_training_proof_or_global_holdout(tmp_path):
    partitions = _parts(_build(_release(tmp_path)))
    summary = partitions.verification_summary()
    for key in ("global_holdout_verified", "source_authority_authenticated", "training_eligible", "admitted"):
        assert summary[key] is False
    assert summary["inventory_sha256"] == partitions.to_dict()["inventory"]["sha256"]
    assert summary["current_source_bytes_verified"] is False
    assert summary["embedding_producer_authenticated"] is False


def test_offline_cli_materialization_preserves_frozen_nondefault_import_limits(tmp_path):
    source_root = tmp_path / "sources"
    fixture = _release(source_root, [[_row(i) for i in range(1, 7)]],
                       import_limits=imp.USCodeImportLimits(max_text_bytes=80))
    for shard, descriptor in zip(fixture.shards, fixture.descriptors):
        destination = source_root / descriptor["relative_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(shard, destination)
    inventory = _build(fixture)
    saved = inventory.save(tmp_path / "inventory.json")
    expected = _parts(inventory).entry_cids_for("train")[0]
    root = Path(__file__).resolve().parents[4]
    output = tmp_path / "cli-output"
    completed = subprocess.run([
        sys.executable, "-B", str(root / "scripts/ops/legal_ir/freeze_uscode_source_partitions.py"),
        "--inventory", saved["path"], "--inventory-sha256", saved["sha256"],
        "--seed", "source-before-embedding", "--output-directory", str(output),
        "--source-root", str(source_root), "--materialize-training-count", "1",
    ], cwd=root, capture_output=True, text=True, timeout=30, check=False)
    assert completed.returncode == 0, completed.stdout[-4000:] + completed.stderr[-4000:]
    report = json.loads((output / "source-partitions-report.json").read_bytes())
    assert report["passed"] is True
    assert report["selected_entry_cids"] == [expected]
    assert len(report["selected_input_ids"]) == 1
    receipt = json.loads(Path(report["selection_receipt"]["path"]).read_bytes())
    assert len(receipt["bindings"]) == 1
    assert receipt["bindings"][0]["input_id"] == report["selected_input_ids"][0]
    assert receipt["bindings"][0]["entry_cid"] == expected
    assert receipt["admitted"] is receipt["training_eligible"] is False
