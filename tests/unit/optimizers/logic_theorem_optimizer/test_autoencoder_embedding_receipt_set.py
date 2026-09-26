"""Independent multi-leaf receipt integrity checks; no model executes here.

All vectors are injected fixtures. Explicit declared-native codec claims in a
few consumption tests exercise validation, not runtime production attestation.
"""
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_index as ci
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as ep
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_receipt_set as ers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_partitions as sp
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import TRAINING_OPERATION
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_embedding_production import (
    declared_native_receipt, fixture_receipt,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_uscode_inventory import (
    _build, _release, _row,
)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@dataclass
class Case:
    partitions: object
    rows: list
    entries: list
    leaves: list
    descriptors: list
    leaf_paths: dict
    source_paths: dict

    def receipt_resolver(self, descriptor):
        return self.leaf_paths[descriptor["sha256"]]

    def source_resolver(self, descriptor):
        return self.source_paths[descriptor["sha256"]]

    def build(self, **kwargs):
        return ers.build_embedding_receipt_set(self.partitions, self.descriptors,
            receipt_resolver=self.receipt_resolver, source_resolver=self.source_resolver, **kwargs)


def _case(tmp_path, *, rows=None, groups=None, statuses=None, native=False, profile_changes=None, policy=None):
    rows = rows if rows is not None else [_row(index) for index in (1, 2, 3)]
    fixture = _release(tmp_path / "release", [rows])
    inventory = _build(fixture)
    partitions = sp.build_source_partitions(inventory, policy=policy or ci.SplitPolicy(
        "explicit-receipt-set-fixture", train=10000, validation=0, canary=0, holdout=0))
    sources = tmp_path / "sources"
    sources.mkdir()
    entries, source_paths = [], {}
    for row in rows:
        raw = row["text"].encode()
        digest = _sha(raw)
        path = sources / f"{digest}.txt"
        if not path.exists():
            path.write_bytes(raw)
        source_paths[digest] = path
        citation = f"{row['title']} U.S.C. § {row['section']}"
        span = SourceSpan(SourceArtifact(digest, len(raw)), "us_code", fixture.release.release_id,
                          row["legal_id"], "en", citation, 0, len(raw))
        entries.append((ep.EmbeddingInput(span, row["title"], row["section"], row["text"], citation), path))
    groups = groups if groups is not None else [[0, 1], [2]]
    statuses = statuses or {}
    leaves, descriptors, leaf_paths = [], [], {}
    for group_number, group in enumerate(groups):
        selected = [entries[index] for index in group]
        results = []
        for index in group:
            item = entries[index][0]
            status = statuses.get(index, "embedded")
            if status == "embedded":
                tokens = {"input_ids": [101, 2000, 102], "attention_mask": [1, 1, 1],
                          "token_type_ids": [0, 0, 0]}
                vector = [1.0, -0.0] + [0.0] * 382
            elif status == "token_limit_exceeded":
                tokens = ep.token_input_digest({"input_ids": [100] * 513,
                                               "attention_mask": [1] * 513, "token_type_ids": None})
                vector = None
            else:
                tokens = vector = None
            results.append({"input_id": item.input_id, "status": status, "tokens": tokens, "vector": vector})
        leaf = fixture_receipt(selected, results=results)
        if native:
            leaf = declared_native_receipt(leaf)
        if profile_changes and group_number in profile_changes:
            data = leaf.to_dict()
            profile_changes[group_number](data)
            leaf = ep.EmbeddingProductionReceipt(_json(data))
        path = tmp_path / f"leaf-{group_number}.json"
        artifact = leaf.save(path, resolver=lambda ref: source_paths[ref["sha256"]])
        descriptor = {name: artifact[name] for name in ("sha256", "bytes")}
        leaves.append(leaf)
        descriptors.append(descriptor)
        leaf_paths[leaf.sha256] = path
    return Case(partitions, rows, entries, leaves, descriptors, leaf_paths, source_paths)


def _coverage(receipt_set):
    return {row["input_id"]: row for row in receipt_set.to_dict()["inputs"]}


def test_two_leaves_cover_more_than_single_producer_limit_without_expanding_it(tmp_path):
    case = _case(tmp_path, rows=[_row(index) for index in range(1, 259)],
                 groups=[list(range(129)), list(range(129, 258))])
    receipt_set = case.build()
    data, summary = receipt_set.to_dict(), receipt_set.summary()
    assert ep.MAX_RECORDS == 256
    assert summary["eligible_unique_input_count"] == summary["eligible_row_count"] == 258
    assert summary["unique_status_counts"]["embedded"] == summary["physical_status_counts"]["embedded"] == 258
    assert summary["leaf_count"] == 2
    assert summary["all_inputs_attempted"] is summary["all_inputs_embedded"] is True
    assert summary["native_execution_profile"] is False
    assert [member["artifact"]["sha256"] for member in data["members"]] == sorted(leaf.sha256 for leaf in case.leaves)
    assert [row["input_id"] for row in data["inputs"]] == sorted(item.input_id for item, _ in case.entries)
    assert data["source_partitions"] == {"sha256": case.partitions.sha256, "bytes": len(case.partitions.to_bytes())}
    assert b"embedding_vector" not in receipt_set.to_bytes() and b"The agency shall retain" not in receipt_set.to_bytes()
    assert receipt_set.sha256 == _sha(receipt_set.to_bytes())
    assert case.build().to_bytes() == receipt_set.to_bytes()
    reversed_set = ers.build_embedding_receipt_set(case.partitions, case.descriptors[::-1],
        receipt_resolver=case.receipt_resolver, source_resolver=case.source_resolver)
    assert reversed_set.to_bytes() == receipt_set.to_bytes()
    assert receipt_set.verify_all(receipt_resolver=case.receipt_resolver,
                                  source_resolver=case.source_resolver)["all_leaf_bytes_verified"] is True


def test_partial_set_preserves_unattempted_population_and_leaf_ordinals(tmp_path):
    case = _case(tmp_path, groups=[[2, 0]])
    receipt_set = case.build()
    coverage, summary = _coverage(receipt_set), receipt_set.summary()
    pending = coverage[case.entries[1][0].input_id]
    assert pending == {"input_id": case.entries[1][0].input_id, "receipt_sha256": None,
                       "result_index": None, "status": "unattempted"}
    assert summary["eligible_unique_input_count"] == 3
    assert summary["unique_status_counts"]["embedded"] == 2
    assert summary["unique_status_counts"]["unattempted"] == 1
    assert summary["all_inputs_attempted"] is summary["all_inputs_embedded"] is False
    for ordinal, index in enumerate((2, 0)):
        assert coverage[case.entries[index][0].input_id]["result_index"] == ordinal
    assert receipt_set.binding_for(case.rows[1]["entry_cid"]) == {
        **case.partitions.binding_for(case.rows[1]["entry_cid"]), **pending}


def test_aliases_account_for_physical_occurrences_without_duplicate_production(tmp_path):
    a, b = _row(1), _row(2)
    alias = {**a, "entry_cid": _row(3)["entry_cid"], "document_index": 3}
    case = _case(tmp_path, rows=[a, b, alias], groups=[[0]], statuses={0: "token_limit_exceeded"})
    receipt_set = case.build()
    summary = receipt_set.summary()
    assert summary["physical_row_count"] == summary["eligible_row_count"] == 3
    assert summary["eligible_unique_input_count"] == 2
    assert summary["unique_status_counts"]["token_limit_exceeded"] == 1
    assert summary["physical_status_counts"]["token_limit_exceeded"] == 2
    left, right = [receipt_set.binding_for(row["entry_cid"]) for row in (a, alias)]
    assert left["input_id"] == right["input_id"]
    assert left["source_row_id"] != right["source_row_id"]
    assert left["receipt_sha256"] == right["receipt_sha256"] == case.leaves[0].sha256
    assert left["result_index"] == right["result_index"] == 0


def test_same_exact_text_can_have_distinct_legal_inputs_in_separate_leaves(tmp_path):
    rows = [_row(1, text="The agency shall retain records."), _row(2, text="The agency shall retain records.")]
    case = _case(tmp_path, rows=rows, groups=[[0], [1]])
    assert case.entries[0][0].source.artifact == case.entries[1][0].source.artifact
    assert case.entries[0][0].input_id != case.entries[1][0].input_id
    receipt_set = case.build()
    assert receipt_set.summary()["unique_status_counts"]["embedded"] == 2
    assert receipt_set.binding_for(rows[0]["entry_cid"])["group_id"] == receipt_set.binding_for(rows[1]["entry_cid"])["group_id"]


def test_missing_and_oversized_dispositions_remain_distinct_from_success(tmp_path):
    case = _case(tmp_path, statuses={1: "token_limit_exceeded", 2: "missing_input"})
    case.entries[2][1].unlink()
    receipt_set = case.build()
    summary = receipt_set.summary()
    assert summary["unique_status_counts"] == {"unattempted": 0, "embedded": 1,
                                               "token_limit_exceeded": 1, "missing_input": 1}
    assert summary["all_inputs_attempted"] is True and summary["all_inputs_embedded"] is False
    assert receipt_set.verify_all(receipt_resolver=case.receipt_resolver,
                                  source_resolver=case.source_resolver)["all_leaf_bytes_verified"] is True


def test_excluded_source_rows_are_not_a_smaller_eligible_denominator(tmp_path):
    rows = [_row(1), _row(2, admission_status="excluded"), _row(3)]
    case = _case(tmp_path, rows=rows, groups=[[0]])
    summary = case.build().summary()
    assert summary["physical_row_count"] == 3
    assert summary["eligible_row_count"] == 2 and summary["excluded_row_count"] == 1
    assert summary["unique_status_counts"]["unattempted"] == 1
    excluded = _case(tmp_path / "excluded", rows=rows, groups=[[1]])
    with pytest.raises(ers.ReceiptSetError):
        excluded.build()


def test_same_input_cannot_be_owned_by_multiple_receipts(tmp_path):
    case = _case(tmp_path, groups=[[0, 1], [1, 2]])
    with pytest.raises(ers.ReceiptSetError):
        case.build()


def test_foreign_release_input_cannot_enter_existing_partition_root(tmp_path):
    case, other = _case(tmp_path / "first"), _case(tmp_path / "other", rows=[_row(1, text="Different source."), _row(2), _row(3)])
    with pytest.raises(ers.ReceiptSetError):
        ers.build_embedding_receipt_set(case.partitions, other.descriptors,
            receipt_resolver=other.receipt_resolver, source_resolver=other.source_resolver)


@pytest.mark.parametrize("change", [
    lambda data: data["execution"].update(batch_size=1),
    lambda data: data["execution"].update(kind="native"),
    lambda data: data["producer"].update(code_sha256="b" * 64),
    lambda data: data["producer"]["runtime_versions"].update(python="different-runtime"),
    lambda data: data["model_assets"][0].update(sha256="f" * 64),
    lambda data: data["model_assets"][0].update(bytes=2),
])
def test_leaf_profiles_must_match_exactly_without_fixture_upgrade(tmp_path, change):
    case = _case(tmp_path, profile_changes={1: change})
    with pytest.raises(ers.ReceiptSetError):
        case.build()


def test_fixture_set_cannot_verify_records_even_if_supplied_claim_is_native(tmp_path):
    case = _case(tmp_path)
    receipt_set = case.build()
    claimed = declared_native_receipt(case.leaves[0]).to_corpus_records(resolver=case.source_resolver)
    with pytest.raises(ers.ReceiptSetError):
        receipt_set.verify_records(claimed[:1], entry_cids=[case.rows[0]["entry_cid"]], operation=TRAINING_OPERATION,
            receipt_resolver=case.receipt_resolver, source_resolver=case.source_resolver)
    for key in ("training_eligible", "admitted", "source_authority_authenticated", "current_leaf_bytes_verified"):
        assert receipt_set.summary()[key] is False
    receipt_set.to_dict()["profile"]["execution"]["kind"] = "native"
    assert receipt_set.summary()["native_execution_profile"] is False


def test_immutable_save_reopen_is_metadata_only_until_explicit_leaf_verification(tmp_path):
    case = _case(tmp_path)
    receipt_set = case.build()
    artifact = receipt_set.save(tmp_path / "set.json")
    loaded = ers.load_embedding_receipt_set(artifact["path"], expected_sha256=artifact["sha256"],
        expected_size_bytes=artifact["bytes"], partitions=case.partitions)
    assert loaded.to_bytes() == receipt_set.to_bytes() == _json(receipt_set.to_dict())
    assert loaded.summary()["current_leaf_bytes_verified"] is False
    loaded.summary()["unique_status_counts"]["embedded"] = 999
    loaded.binding_for(case.rows[0]["entry_cid"])["status"] = "forged"
    assert loaded.to_bytes() == receipt_set.to_bytes()
    with pytest.raises((AttributeError, TypeError)):
        loaded._raw = b"{}"
    with pytest.raises((FileExistsError, ers.ReceiptSetError)):
        receipt_set.save(artifact["path"])
    for digest, size in (("0" * 64, artifact["bytes"]), (artifact["sha256"], artifact["bytes"] + 1)):
        with pytest.raises(ers.ReceiptSetError):
            ers.load_embedding_receipt_set(artifact["path"], expected_sha256=digest,
                expected_size_bytes=size, partitions=case.partitions)
    case.leaf_paths[case.leaves[0].sha256].write_bytes(b"corrupt leaf")
    assert ers.load_embedding_receipt_set(artifact["path"], expected_sha256=artifact["sha256"],
        partitions=case.partitions).sha256 == receipt_set.sha256
    with pytest.raises(ers.ReceiptSetError):
        loaded.verify_all(receipt_resolver=case.receipt_resolver, source_resolver=case.source_resolver)


@pytest.mark.parametrize("kind", ["root", "leaf", "source"])
def test_symlink_inputs_are_not_accepted_as_pinned_regular_files(tmp_path, kind):
    case = _case(tmp_path)
    receipt_set = case.build()
    artifact = receipt_set.save(tmp_path / "set.json")
    target = (Path(artifact["path"]) if kind == "root" else
              case.leaf_paths[case.leaves[0].sha256] if kind == "leaf" else case.entries[0][1])
    original = target.with_suffix(".original")
    target.rename(original)
    target.symlink_to(original)
    with pytest.raises(ers.ReceiptSetError):
        if kind == "root":
            ers.load_embedding_receipt_set(target, expected_sha256=artifact["sha256"], partitions=case.partitions)
        else:
            receipt_set.verify_all(receipt_resolver=case.receipt_resolver, source_resolver=case.source_resolver)


@pytest.mark.parametrize("change", [
    lambda data: data.update(extra=True),
    lambda data: data["source_partitions"].update(sha256="0" * 64),
    lambda data: data["source_partitions"].update(bytes=True),
    lambda data: data["members"].reverse(),
    lambda data: data["members"][0].update(input_count=True),
    lambda data: data["members"][0].update(input_count=257),
    lambda data: data["inputs"].reverse(),
    lambda data: data["inputs"].pop(),
    lambda data: data["inputs"].append(data["inputs"][0]),
    lambda data: data["inputs"][0].update(input_id="sha256:" + "0" * 64),
    lambda data: data["inputs"][0].update(status="truncated"),
    lambda data: data["inputs"][0].update(receipt_sha256="0" * 64),
    lambda data: data["inputs"][0].update(result_index=True),
    lambda data: data["inputs"][0].update(result_index=257),
    lambda data: data["inputs"][0].update(status="unattempted"),
    lambda data: data["profile"]["execution"].update(truncation=True),
])
def test_resealed_root_cannot_change_closed_membership_contract(tmp_path, change):
    case = _case(tmp_path)
    data = case.build().to_dict()
    change(data)
    with pytest.raises(ers.ReceiptSetError):
        ers.EmbeddingReceiptSet(_json(data), case.partitions)


def test_root_result_claims_are_checked_against_actual_leaf_bytes(tmp_path):
    case = _case(tmp_path)
    data = case.build().to_dict()
    data["inputs"][0]["status"] = "missing_input"
    resealed = ers.EmbeddingReceiptSet(_json(data), case.partitions)
    with pytest.raises(ers.ReceiptSetError):
        resealed.verify_all(receipt_resolver=case.receipt_resolver, source_resolver=case.source_resolver)


@pytest.mark.parametrize("raw", [b"{}", b"[]", b"null", b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff"])
def test_ambiguous_or_malformed_root_json_is_rejected(tmp_path, raw):
    case = _case(tmp_path)
    with pytest.raises(ers.ReceiptSetError):
        ers.EmbeddingReceiptSet(raw, case.partitions)


def test_root_byte_budget_and_canonical_encoding_are_enforced(tmp_path):
    case = _case(tmp_path)
    receipt_set = case.build()
    with pytest.raises(ers.ReceiptSetError):
        ers.EmbeddingReceiptSet(receipt_set.to_bytes() + b"\n", case.partitions)
    with pytest.raises(ers.ReceiptSetError):
        ers.EmbeddingReceiptSet(receipt_set.to_bytes(), case.partitions,
            ers.ReceiptSetLimits(max_root_bytes=len(receipt_set.to_bytes()) - 1))


def test_root_identity_cannot_move_to_another_partition_policy(tmp_path):
    case = _case(tmp_path)
    receipt_set = case.build()
    other = sp.build_source_partitions(case.partitions.inventory, policy=ci.SplitPolicy("other-policy"))
    with pytest.raises(ers.ReceiptSetError):
        ers.EmbeddingReceiptSet(receipt_set.to_bytes(), other)


@pytest.mark.parametrize("field,maximum", [("max_receipts", 1024), ("max_inputs", 65536),
    ("max_root_bytes", 64 * 1024**2), ("max_total_receipt_bytes", 4 * 1024**3)])
@pytest.mark.parametrize("which", ["zero", "bool", "float", "above"])
def test_configured_limits_cannot_expand_hard_bounds(field, maximum, which):
    value = {"zero": 0, "bool": True, "float": 1.0, "above": maximum + 1}[which]
    with pytest.raises(ers.ReceiptSetError):
        ers.ReceiptSetLimits(**{field: value})


@pytest.mark.parametrize("kind", ["receipts", "inputs", "bytes", "descriptor", "duplicate"])
def test_build_preflights_aggregate_work_before_calling_resolvers(tmp_path, kind):
    case = _case(tmp_path)
    kwargs, artifacts = {}, list(case.descriptors)
    if kind == "receipts":
        kwargs["limits"] = ers.ReceiptSetLimits(max_receipts=1)
    elif kind == "inputs":
        kwargs["limits"] = ers.ReceiptSetLimits(max_inputs=2)
    elif kind == "bytes":
        kwargs["limits"] = ers.ReceiptSetLimits(max_total_receipt_bytes=sum(ref["bytes"] for ref in artifacts) - 1)
    elif kind == "descriptor":
        artifacts[0] = {**artifacts[0], "path": "/untrusted/local/path"}
    else:
        artifacts.append(artifacts[0])
    def forbidden(_):
        pytest.fail("receipt/source resolution must follow complete preflight")
    with pytest.raises(ers.ReceiptSetError):
        ers.build_embedding_receipt_set(case.partitions, artifacts,
            receipt_resolver=forbidden, source_resolver=forbidden, **kwargs)


@pytest.mark.parametrize("kind", ["leaf", "source"])
def test_later_leaf_cannot_hide_mutation_of_earlier_verified_bytes(tmp_path, kind):
    case = _case(tmp_path, groups=[[0], [1]])
    first, second = sorted(case.leaves, key=lambda leaf: leaf.sha256)
    seen = []
    def resolver(ref):
        seen.append(ref["sha256"])
        if ref["sha256"] == second.sha256 and second.sha256 not in seen[:-1]:
            target = (case.leaf_paths[first.sha256] if kind == "leaf" else
                      case.source_paths[first.inputs[0].source.artifact.sha256])
            target.write_bytes(b"changed after verification")
        return case.receipt_resolver(ref)
    with pytest.raises(ers.ReceiptSetError):
        ers.build_embedding_receipt_set(case.partitions, case.descriptors,
            receipt_resolver=resolver, source_resolver=case.source_resolver)


def test_selected_record_verification_preserves_leaf_provenance_and_source_membership(tmp_path):
    case = _case(tmp_path, native=True)
    receipt_set = case.build()
    record = case.leaves[0].to_corpus_records(resolver=case.source_resolver)[0]
    # Neither the other source in the selected leaf nor the other leaf's source
    # is needed for this bounded selection. Their absence must stay explicit.
    case.entries[1][1].unlink()
    case.entries[2][1].unlink()
    case.leaf_paths[case.leaves[1].sha256].unlink()
    read_leaves, read_sources = [], []
    def leaf_resolver(ref):
        read_leaves.append(ref["sha256"])
        assert ref["sha256"] == case.leaves[0].sha256
        return case.receipt_resolver(ref)
    def source_resolver(ref):
        read_sources.append(ref["sha256"])
        assert ref["sha256"] == record.source.artifact.sha256
        return case.source_resolver(ref)
    verified = receipt_set.verify_records([record], entry_cids=[case.rows[0]["entry_cid"]],
        operation=TRAINING_OPERATION, receipt_resolver=leaf_resolver, source_resolver=source_resolver)
    assert verified["supplied_records_verified"] == verified["selected_leaf_count"] == 1
    assert verified["unselected_leaf_bytes_reverified"] is verified["unselected_source_bytes_reverified"] is False
    assert verified["training_eligible"] is verified["admitted"] is False
    assert read_leaves and read_sources
    projection = verified["source_projection"]
    assert projection["source_partitions"]["sha256"] == case.partitions.sha256
    assert projection["records"][0]["input_id"] == case.entries[0][0].input_id
    assert record.embedding_provenance.artifact_sha256 == case.leaves[0].sha256 != receipt_set.sha256


@pytest.mark.parametrize("kind", ["leaf", "source"])
def test_later_selected_leaf_cannot_hide_mutation_of_previously_verified_selected_bytes(tmp_path, kind):
    case = _case(tmp_path, groups=[[0], [1]], native=True)
    receipt_set = case.build()
    first, second = sorted(case.leaves, key=lambda leaf: leaf.sha256)
    records = [leaf.to_corpus_records(resolver=case.source_resolver)[0] for leaf in (first, second)]
    entry_by_input = {item.input_id: row["entry_cid"] for (item, _), row in zip(case.entries, case.rows)}
    entries = [entry_by_input[leaf.inputs[0].input_id] for leaf in (first, second)]
    seen = []
    def receipt_resolver(ref):
        seen.append(ref["sha256"])
        if ref["sha256"] == second.sha256 and second.sha256 not in seen[:-1]:
            target = (case.leaf_paths[first.sha256] if kind == "leaf" else
                      case.source_paths[first.inputs[0].source.artifact.sha256])
            target.write_bytes(b"changed after selected record verification")
        return case.receipt_resolver(ref)
    with pytest.raises(ers.ReceiptSetError):
        receipt_set.verify_records(records, entry_cids=entries, operation=TRAINING_OPERATION,
            receipt_resolver=receipt_resolver, source_resolver=case.source_resolver)


def test_selected_record_may_bind_an_exact_source_alias_without_reembedding(tmp_path):
    original = _row(1)
    alias = {**original, "entry_cid": _row(2)["entry_cid"], "document_index": 2}
    case = _case(tmp_path, rows=[original, alias], groups=[[0]], native=True)
    receipt_set = case.build()
    record = case.leaves[0].to_corpus_records(resolver=case.source_resolver)[0]
    verified = receipt_set.verify_records([record], entry_cids=[alias["entry_cid"]],
        operation=TRAINING_OPERATION, receipt_resolver=case.receipt_resolver, source_resolver=case.source_resolver)
    binding = verified["source_projection"]["records"][0]
    assert binding["entry_cid"] == alias["entry_cid"]
    assert binding["source_row_id"] == case.partitions.binding_for(alias["entry_cid"])["source_row_id"]
    assert binding["input_id"] == case.entries[0][0].input_id
    assert receipt_set.summary()["physical_status_counts"]["embedded"] == 2


def test_record_from_unlisted_leaf_cannot_silently_fill_unattempted_membership(tmp_path):
    case = _case(tmp_path, native=True)
    receipt_set = ers.build_embedding_receipt_set(case.partitions, case.descriptors[:1],
        receipt_resolver=case.receipt_resolver, source_resolver=case.source_resolver)
    record = case.leaves[1].to_corpus_records(resolver=case.source_resolver)[0]
    assert receipt_set.binding_for(case.rows[2]["entry_cid"])["status"] == "unattempted"
    with pytest.raises(ers.ReceiptSetError):
        receipt_set.verify_records([record], entry_cids=[case.rows[2]["entry_cid"]],
            operation=TRAINING_OPERATION, receipt_resolver=case.receipt_resolver, source_resolver=case.source_resolver)


@pytest.mark.parametrize("change", ["vector", "root_provenance", "foreign_entry", "duplicate", "source"])
def test_selected_record_consumption_rejects_vector_provenance_selector_or_source_drift(tmp_path, change):
    case = _case(tmp_path, native=True)
    receipt_set = case.build()
    record = case.leaves[0].to_corpus_records(resolver=case.source_resolver)[0]
    records, entries = [record], [case.rows[0]["entry_cid"]]
    if change == "vector":
        records = [replace(record, sample=replace(record.sample,
                   embedding_vector=(1.0, 0.0) + record.sample.embedding_vector[2:]))]
    elif change == "root_provenance":
        records = [replace(record, embedding_provenance=replace(record.embedding_provenance,
                                                               artifact_sha256=receipt_set.sha256))]
    elif change == "foreign_entry":
        entries = [case.rows[1]["entry_cid"]]
    elif change == "duplicate":
        records, entries = records * 2, entries * 2
    else:
        case.entries[0][1].write_bytes(b"changed source")
    with pytest.raises(ers.ReceiptSetError):
        receipt_set.verify_records(records, entry_cids=entries, operation=TRAINING_OPERATION,
            receipt_resolver=case.receipt_resolver, source_resolver=case.source_resolver)


def test_protected_source_split_is_rejected_before_receipt_or_source_io(tmp_path):
    case = _case(tmp_path, native=True, policy=ci.SplitPolicy(
        "holdout-only", train=0, validation=0, canary=0, holdout=10000))
    receipt_set = case.build()
    record = case.leaves[0].to_corpus_records(resolver=case.source_resolver)[0]
    def forbidden(_):
        pytest.fail("operation protection must precede receipt/source I/O")
    with pytest.raises(ers.ReceiptSetError):
        receipt_set.verify_records([record], entry_cids=[case.rows[0]["entry_cid"]],
            operation=TRAINING_OPERATION, receipt_resolver=forbidden, source_resolver=forbidden)


@pytest.mark.parametrize("operation", ["build", "all", "selected"])
def test_closure_resolves_each_reference_once_then_rechecks_exact_captured_paths(tmp_path, operation):
    case = _case(tmp_path, native=True)
    receipt_set = case.build()
    records = case.leaves[0].to_corpus_records(resolver=case.source_resolver)[:1]
    seen_leaves, seen_sources = set(), set()

    def once(resolver, seen):
        def resolve(ref):
            assert ref["sha256"] not in seen, "final rehash must not invoke a mutable resolver again"
            seen.add(ref["sha256"])
            return resolver(ref)
        return resolve

    resolvers = {"receipt_resolver": once(case.receipt_resolver, seen_leaves),
                 "source_resolver": once(case.source_resolver, seen_sources)}
    if operation == "build":
        ers.build_embedding_receipt_set(case.partitions, case.descriptors, **resolvers)
    elif operation == "all":
        receipt_set.verify_all(**resolvers)
    else:
        receipt_set.verify_records(records, entry_cids=[case.rows[0]["entry_cid"]],
            operation=TRAINING_OPERATION, **resolvers)
    assert seen_leaves and seen_sources
