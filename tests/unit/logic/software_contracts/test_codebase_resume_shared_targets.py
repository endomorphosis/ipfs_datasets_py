"""Native shared512 records, lossless restoration and coherent corruption.

Fixtures use the existing captured source/AST/contract producers and unchanged
native target validator. They never fit a model, launch a worker, run a source
program, scan a checkout or reserve resources. These are protocol/native replay
controls; they do not qualify a live repository or numerical throughput.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import (
    CodebasePublicationReceipt, _request,
)
from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
from ipfs_datasets_py.logic.software_contracts import codebase_ir_targets as native
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_replay as old_replay
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_targets as old_transport
from ipfs_datasets_py.logic.software_contracts import codebase_resume_shared_targets as shared
from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseIRManifest, CodebaseUnit
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import ArtifactRecord, RepositoryState
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot, SnapshotEntry
from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec


def make_records(count=3, max_entries=512, max_file_bytes=64 * 1024):
    source_rows = [
        ("a-good.py", b"def step(n: int) -> int:\n    return n + 1\n", True),
        ("b-unsupported.py", b"LIMIT = 3\ndef step(n: int) -> int:\n    return n + LIMIT\n", True),
        ("c-unindexed.py", b"def step(n: int) -> int:\n    return n + 2\n", False),
    ]
    source_rows += [(f"unit-{number:04d}.py", b"def step(n: int) -> int:\n    return n + 2\n", False)
                    for number in range(max(0, count - 3))]
    entries = tuple(SnapshotEntry(path, "file", len(raw), cid_for_bytes(raw),
                                  disposition="filesystem") for path, raw, _ in source_rows)
    snapshot = RepositorySnapshot(f"fixture-resume-shared-{count}", entries, "filesystem",
                                  max_entries=max_entries, max_file_bytes=max_file_bytes)
    ast_records = tuple(PythonASTExtractor().extract_from_source(
        raw, path=path, repository_id=snapshot.repository_id,
        revision="snapshot:" + snapshot.snapshot_cid,
        repository_tree_cid=snapshot.snapshot_cid,
    ) if indexed else None for path, raw, indexed in source_rows)
    state = RepositoryState(snapshot.repository_id, artifacts=(ArtifactRecord(
        "artifact:snapshot-evidence", "snapshot", ".snapshot", snapshot.snapshot_cid,
        metadata={"snapshot": snapshot.to_dict()},
    ),))
    units = tuple(CodebaseUnit(entry.source_key, entry.entry_cid,
        None if record is None else cid_for_structured(record.to_dict()),
        "unindexed" if record is None else "ok",
    ) for entry, record in zip(entries, ast_records))
    manifest = CodebaseIRManifest(snapshot, state,
        "rev:" + snapshot.repository_id + ":snapshot:" + snapshot.snapshot_cid, units)
    receipt = CodebasePublicationReceipt("resume-shared-fixture",
        _request(snapshot.repository_id, manifest.cid, None), None,
        snapshot.repository_id, 1, manifest.cid, snapshot.snapshot_cid, manifest.ast_revision_id)
    return receipt.head, manifest, receipt, source_rows, entries, units, ast_records


def targets_for(records):
    head, manifest, receipt, sources, entries, units, ast_records = records
    return tuple(native._prepare_bound(
        binding=native._binding(head, manifest, entry, unit, raw), manifest=manifest,
        receipt=receipt, ast_record=record, raw=raw,
        specs=(ContractSpec("step", (), ("result == n + 1",), "step-post"),)
              if path == "a-good.py" else (), limits=native.CodebaseTargetLimits(),
    ) for (path, raw, _), entry, unit, record in zip(sources[:3], entries[:3], units[:3], ast_records[:3]))


@pytest.fixture(scope="module")
def captured():
    records = make_records()
    return records, targets_for(records)


def token_for(records):
    return shared.validate_resume_shared_inventory(shared.create_resume_shared_inventory(*records[:3]))


def rehash(value, digest_field):
    payload = {name: child for name, child in value.items() if name != digest_field}
    value[digest_field] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return value


@pytest.mark.parametrize("count", [300, 512])
def test_new_capture512_profile_is_separate_from_unchanged_capture256(count):
    records = make_records(count)
    token = token_for(records)
    replay = shared.prepare_resume_replay(token)
    assert len(token.manifest.snapshot.entries) == replay.membership_count == count
    target = targets_for(records)[0]
    restored = shared.restore_resume_target(token, shared.compact_resume_target(target, token))
    assert restored.canonical_bytes == target.canonical_bytes
    assert shared.validate_resume_target(restored, replay).canonical_bytes == native.validate_codebase_targets(target).canonical_bytes
    legacy = token.to_dict()
    legacy["schema"] = old_transport.SHARED_INVENTORY_SCHEMA
    rehash(legacy, "shared_sha256")
    with pytest.raises(native.CodebaseTargetError):
        old_transport.validate_shared_inventory_envelope(legacy)
    assert old_transport.CodebaseInventoryLimits().max_entries == 256
    with pytest.raises(native.CodebaseTargetError):
        old_transport.CodebaseInventoryLimits(max_entries=512)


@pytest.mark.parametrize("position", [0, 1, 2])
def test_complete_lossless_target_replay_matches_original_native_owner(captured, position):
    records, targets = captured
    token = token_for(records)
    counts = shared.InventoryReplayCounters()
    replay = shared.prepare_resume_replay(token, counts)
    target = targets[position]
    compact = shared.compact_resume_target(target, token)
    detached = deepcopy(target.to_dict())
    details = detached["validation"][0]["details"]
    del details["manifest"], details["publication_receipt"]
    assert compact["detached_target"] == detached
    assert compact["target_sha256"] == target.digest
    assert compact["source_digest"] == target.source_digest
    restored = shared.restore_resume_target(token, compact)
    result = shared.validate_resume_target(restored, replay, counts)
    assert restored.canonical_bytes == result.canonical_bytes == native.validate_codebase_targets(target).canonical_bytes
    assert result.ready_for_training is (position == 0)
    assert counts.to_dict() == {
        "shared_replay_preparations": 1, "target_replay_attempts": 1, "target_replays": 1,
        "source_digest_checks": 1, "ast_digest_checks": int(position != 2),
        "authored_contract_replays": 1, "native_lowering_replays": 1,
        "full_target_comparisons": 1, "shared_manifest_parses_avoided": 1,
        "shared_receipt_parses_avoided": 1,
    }
    authority = result.to_dict()["validation"][0]["details"]
    assert authority["proof_authority"] is authority["execution_authority"] is False


def test_one_preparation_never_reparses_native_shared_records_per_row(captured, monkeypatch):
    records, targets = captured
    token = token_for(records)
    counts = shared.InventoryReplayCounters()
    replay = shared.prepare_resume_replay(token, counts)

    def prohibited(*args, **kwargs):
        pytest.fail("a row reparsed its receiver-owned native shared records")

    monkeypatch.setattr(CodebaseIRManifest, "from_dict", prohibited)
    monkeypatch.setattr(CodebasePublicationReceipt, "from_dict", prohibited)
    for target in targets * 2:
        restored = shared.restore_resume_target(token, shared.compact_resume_target(target, token))
        assert shared.validate_resume_target(restored, replay, counts) == target
    assert counts.shared_replay_preparations == 1
    assert counts.target_replays == counts.native_lowering_replays == counts.full_target_comparisons == 6


def test_local_tokens_retain_no_mutable_input_aliases(captured):
    records, targets = captured
    declaration = shared.create_resume_shared_inventory(*records[:3])
    token = shared.validate_resume_shared_inventory(declaration)
    replay = shared.prepare_resume_replay(token)
    declaration["manifest"]["coverage"]["inventory_entries"] = 999
    detached = token.to_dict()
    detached["head"]["generation"] = 999
    with pytest.raises(TypeError):
        token._manifest_value["coverage"]["inventory_entries"] = 999
    with pytest.raises(TypeError):
        replay._entry_values[next(iter(replay._entries))]["size_bytes"] = 999
    assert shared.validate_resume_target(targets[0], replay) == targets[0]


@pytest.mark.parametrize("mutation", ["canonical", "digest", "head", "manifest", "receipt", "snapshot", "seal"])
def test_changed_validated_token_refused_at_every_transport_boundary(captured, mutation):
    records, targets = captured
    token = token_for(records)
    compact = shared.compact_resume_target(targets[0], token)
    if mutation == "canonical":
        forged = replace(token, canonical_bytes=token.canonical_bytes + b" ")
    elif mutation == "digest":
        forged = replace(token, shared_sha256="0" * 64)
    elif mutation == "head":
        forged = replace(token, head=replace(token.head, generation=2))
    elif mutation == "manifest":
        forged = replace(token, manifest=make_records(4)[1])
    elif mutation == "receipt":
        forged = replace(token, receipt=replace(token.receipt, operation_id="different"))
    elif mutation == "snapshot":
        forged = replace(token, _manifest_value={})
    else:
        forged = replace(token, _seal=object())
    for operation in (lambda: shared.compact_resume_target(targets[0], forged),
                      lambda: shared.restore_resume_target(forged, compact),
                      lambda: shared.prepare_resume_replay(forged)):
        with pytest.raises(native.CodebaseTargetError):
            operation()


@pytest.mark.parametrize("mutation", ["seal", "digest", "count", "count_bool", "head", "membership", "snapshot"])
def test_changed_receiver_replay_token_is_refused(captured, mutation):
    records, targets = captured
    replay = shared.prepare_resume_replay(token_for(records))
    if mutation == "seal":
        forged = replace(replay, _seal=object())
    elif mutation == "digest":
        forged = replace(replay, shared_sha256="0" * 64)
    elif mutation == "count":
        forged = replace(replay, membership_count=4)
    elif mutation == "count_bool":
        forged = replace(replay, membership_count=True)
    elif mutation == "head":
        forged = replace(replay, _head=replace(replay._head, generation=2))
    elif mutation == "membership":
        forged = replace(replay, _entries={})
    else:
        forged = replace(replay, _manifest_value={})
    with pytest.raises(native.CodebaseTargetError):
        shared.validate_resume_target(targets[0], forged)


def test_old_tokens_dictionaries_and_foreign_counter_owners_are_refused(captured):
    records, targets = captured
    declaration = shared.create_resume_shared_inventory(*records[:3])
    token = shared.validate_resume_shared_inventory(declaration)
    replay = shared.prepare_resume_replay(token)
    old_value = deepcopy(declaration)
    old_value["schema"] = old_transport.SHARED_INVENTORY_SCHEMA
    old_value["manifest"]["snapshot"]["max_entries"] = 3
    # Use an independently valid old inventory; changing its capture declaration
    # alone would also change snapshot/head/publication identities.
    old_records = make_records(max_entries=3)
    old_value = {"schema": old_transport.SHARED_INVENTORY_SCHEMA,
                 "head": old_records[0].to_dict(), "manifest": old_records[1].to_dict(),
                 "publication_receipt": old_records[2].to_dict()}
    old_token = old_transport.validate_shared_inventory_envelope(rehash(old_value, "shared_sha256"))
    old_replay_token = old_replay.prepare_inventory_replay(old_token)
    for foreign in (declaration, old_token, old_replay_token, object()):
        with pytest.raises(native.CodebaseTargetError):
            shared.prepare_resume_replay(foreign)
        with pytest.raises(native.CodebaseTargetError):
            shared.compact_resume_target(targets[0], foreign)
    with pytest.raises(native.CodebaseTargetError):
        shared.validate_resume_target(targets[0].to_dict(), replay)
    with pytest.raises(native.CodebaseTargetError):
        shared.validate_resume_target(targets[0], old_replay_token)
    for counts in ({}, shared.InventoryReplayCounters(target_replays=True),
                   shared.InventoryReplayCounters(target_replays=-1)):
        with pytest.raises(native.CodebaseTargetError):
            shared.prepare_resume_replay(token, counts)
        with pytest.raises(native.CodebaseTargetError):
            shared.validate_resume_target(targets[0], replay, counts)


@pytest.mark.parametrize("mutation", [
    "schema", "unknown", "missing", "digest", "head", "receipt", "coverage_bool",
    "coverage_float", "entries_order", "units_order", "duplicate_unit", "missing_unit",
    "declared513", "source65537", "declared_bool", "entries_tuple", "nonfinite", "receipt_bytes",
])
def test_rehashed_shared_inventory_refuses_noncanonical_or_incomplete_native_records(captured, mutation):
    value = shared.create_resume_shared_inventory(*captured[0][:3])
    if mutation == "schema":
        value["schema"] = old_transport.SHARED_INVENTORY_SCHEMA
    elif mutation == "unknown":
        value["proof_authority"] = False
    elif mutation == "missing":
        del value["publication_receipt"]
    elif mutation == "digest":
        value["shared_sha256"] = "0" * 64
    elif mutation == "head":
        value["head"]["generation"] += 1
    elif mutation == "receipt":
        value["publication_receipt"]["manifest_cid"] = value["head"]["snapshot_cid"]
    elif mutation == "coverage_bool":
        value["manifest"]["coverage"]["formalized_properties"] = False
    elif mutation == "coverage_float":
        value["manifest"]["coverage"]["inventory_entries"] = 3.0
    elif mutation == "entries_order":
        value["manifest"]["snapshot"]["entries"].reverse()
    elif mutation == "units_order":
        value["manifest"]["units"].reverse()
    elif mutation == "duplicate_unit":
        value["manifest"]["units"][1] = deepcopy(value["manifest"]["units"][0])
    elif mutation == "missing_unit":
        value["manifest"]["units"].pop()
    elif mutation == "declared513":
        value["manifest"]["snapshot"]["max_entries"] = 513
    elif mutation == "source65537":
        value["manifest"]["snapshot"]["max_file_bytes"] = 65537
    elif mutation == "declared_bool":
        value["manifest"]["snapshot"]["max_entries"] = True
    elif mutation == "entries_tuple":
        value["manifest"]["snapshot"]["entries"] = tuple(value["manifest"]["snapshot"]["entries"])
    elif mutation == "nonfinite":
        value["manifest"]["coverage"]["formalized_properties"] = float("nan")
    elif mutation == "receipt_bytes":
        value["publication_receipt"]["operation_id"] = "x" * (shared.MAX_RECEIPT_BYTES + 1)
    if mutation not in {"digest", "nonfinite"}:
        rehash(value, "shared_sha256")
    with pytest.raises(native.CodebaseTargetError):
        shared.validate_resume_shared_inventory(value)


def test_capture_and_serialized_hard_bounds_are_preserved(captured):
    with pytest.raises(native.CodebaseTargetError):
        shared.create_resume_shared_inventory(*make_records(513, max_entries=513)[:3])
    with pytest.raises(native.CodebaseTargetError):
        shared.create_resume_shared_inventory(*make_records(max_file_bytes=65537)[:3])
    value = shared.create_resume_shared_inventory(*captured[0][:3])
    value["manifest"]["semantic_state"]["oversized"] = "x" * shared.MAX_SHARED_BYTES
    with pytest.raises(native.CodebaseTargetError):
        shared.validate_resume_shared_inventory(value)
    token = token_for(captured[0])
    compact = shared.compact_resume_target(captured[1][0], token)
    compact["detached_target"]["qualification_gaps"].append("x" * shared.MAX_TARGET_BYTES)
    with pytest.raises(native.CodebaseTargetError):
        shared.restore_resume_target(token, compact)
    oversized = captured[1][0].to_dict()
    oversized["qualification_gaps"].append("x" * shared.MAX_TARGET_BYTES)
    target = DomainTargetEnvelope.from_dict(oversized)
    with pytest.raises(native.CodebaseTargetError):
        shared.compact_resume_target(target, token)
    with pytest.raises(native.CodebaseTargetError):
        shared.validate_resume_target(target, shared.prepare_resume_replay(token))


@pytest.mark.parametrize("mutation", [
    "schema", "unknown", "missing", "shared", "target_sha", "source_digest", "digest",
    "manifest_injection", "receipt_injection", "head", "detached", "nonfinite", "tuple",
])
def test_compact_boundary_rejects_coherent_transport_mutations(captured, mutation):
    token = token_for(captured[0])
    compact = shared.compact_resume_target(captured[1][0], token)
    details = compact["detached_target"]["validation"][0]["details"]
    if mutation == "schema":
        compact["schema"] = old_transport.COMPACT_TARGET_SCHEMA
    elif mutation == "unknown":
        compact["proof_authority"] = False
    elif mutation == "missing":
        del compact["source_digest"]
    elif mutation == "shared":
        compact["shared_sha256"] = "0" * 64
    elif mutation == "target_sha":
        compact["target_sha256"] = "0" * 64
    elif mutation == "source_digest":
        compact["source_digest"] = "0" * 64
    elif mutation == "digest":
        compact["compact_sha256"] = "0" * 64
    elif mutation == "manifest_injection":
        details["manifest"] = token.manifest.to_dict()
    elif mutation == "receipt_injection":
        details["publication_receipt"] = token.receipt.to_dict()
    elif mutation == "head":
        details["source_binding"]["head"]["generation"] += 1
    elif mutation == "detached":
        compact["detached_target"] = []
    elif mutation == "nonfinite":
        details["proof_authority"] = float("inf")
    else:
        compact["detached_target"]["validation"] = tuple(compact["detached_target"]["validation"])
    if mutation not in {"digest", "nonfinite"}:
        rehash(compact, "compact_sha256")
    with pytest.raises(native.CodebaseTargetError):
        shared.restore_resume_target(token, compact)


def test_lossless_rehashed_transport_cannot_grant_native_source_or_proof_validity(captured):
    token = token_for(captured[0])
    replay = shared.prepare_resume_replay(token)
    for mutation in ("source", "ast", "contract", "projection", "frontier", "authority", "limit"):
        value = captured[1][0].to_dict()
        details = value["validation"][0]["details"]
        if mutation == "source":
            details["source_bytes_hex"] = b"def step(n: int) -> int:\n    return n + 9\n".hex()
        elif mutation == "ast":
            details["captured_ast"]["provenance"]["path"] = "foreign.py"
        elif mutation == "contract":
            details["authored_contracts"][0]["postconditions"] = ["result == n + 9"]
        elif mutation == "projection":
            value["projections"][0]["expression"]["foreign"] = True
        elif mutation == "frontier":
            value["qualification_gaps"] = []
        elif mutation == "authority":
            details["proof_authority"] = 0
        else:
            details["limits"]["max_functions"] = True
        bad = DomainTargetEnvelope.from_dict(value)
        restored = shared.restore_resume_target(token, shared.compact_resume_target(bad, token))
        assert restored.canonical_bytes == bad.canonical_bytes
        counts = shared.InventoryReplayCounters()
        with pytest.raises(native.CodebaseTargetError):
            native.validate_codebase_targets(restored)
        with pytest.raises(native.CodebaseTargetError):
            shared.validate_resume_target(restored, replay, counts)
        assert counts.target_replay_attempts == 1
        assert counts.target_replays == counts.shared_manifest_parses_avoided == 0


def test_alternate_coherent_inventory_never_receives_original_rows(captured):
    original = token_for(captured[0])
    alternate = token_for(make_records(4))
    assert original.shared_sha256 != alternate.shared_sha256
    target = captured[1][0]
    compact = shared.compact_resume_target(target, original)
    with pytest.raises(native.CodebaseTargetError):
        shared.compact_resume_target(target, alternate)
    with pytest.raises(native.CodebaseTargetError):
        shared.restore_resume_target(alternate, compact)
    with pytest.raises(native.CodebaseTargetError):
        shared.validate_resume_target(target, shared.prepare_resume_replay(alternate))
