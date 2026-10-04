"""Independent native replay equivalence and corruption controls.

Fixtures construct immutable captured records without a catalog, fitting,
resource admission, repository execution or an inference worker.  The unchanged
single-target validator is the comparison owner; rehashed transports exercise
native replay rather than only digest checking.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import (
    CodebasePublicationReceipt, _request,
)
from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseIRManifest, CodebaseUnit
from ipfs_datasets_py.logic.software_contracts import codebase_ir_targets as native
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_replay as replay_module
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_targets as transport
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import ArtifactRecord, RepositoryState
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot, SnapshotEntry
from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec


@pytest.fixture(scope="module")
def captured():
    sources = (
        ("good.py", b"def step(n: int) -> int:\n    return n + 1\n", True),
        ("unsupported.py", b"LIMIT = 3\ndef step(n: int) -> int:\n    return n + LIMIT\n", True),
        ("unindexed.py", b"def step(n: int) -> int:\n    return n + 2\n", False),
    )
    entries = tuple(SnapshotEntry(path, "file", len(raw), cid_for_bytes(raw),
                                  disposition="filesystem") for path, raw, _ in sources)
    snapshot = RepositorySnapshot("fixture-native-inventory-replay", entries, "filesystem",
                                  max_entries=4, max_file_bytes=64 * 1024)
    ast_records = tuple(PythonASTExtractor().extract_from_source(
        raw, path=path, repository_id=snapshot.repository_id,
        revision="snapshot:" + snapshot.snapshot_cid,
        repository_tree_cid=snapshot.snapshot_cid,
    ) if indexed else None for path, raw, indexed in sources)
    state = RepositoryState(snapshot.repository_id, artifacts=(ArtifactRecord(
        "artifact:snapshot-evidence", "snapshot", ".snapshot", snapshot.snapshot_cid,
        metadata={"snapshot": snapshot.to_dict()},
    ),))
    units = tuple(CodebaseUnit(entry.source_key, entry.entry_cid,
        None if ast is None else cid_for_structured(ast.to_dict()), "unindexed" if ast is None else "ok"
    ) for entry, ast in zip(entries, ast_records))
    manifest = CodebaseIRManifest(snapshot, state,
        "rev:" + snapshot.repository_id + ":snapshot:" + snapshot.snapshot_cid, units)
    receipt = CodebasePublicationReceipt("native-replay-fixture",
        _request(snapshot.repository_id, manifest.cid, None), None,
        snapshot.repository_id, 1, manifest.cid, snapshot.snapshot_cid, manifest.ast_revision_id)
    head = receipt.head
    targets = tuple(native._prepare_bound(
        binding=native._binding(head, manifest, entry, unit, raw), manifest=manifest,
        receipt=receipt, ast_record=ast, raw=raw,
        specs=(ContractSpec("step", (), ("result == n + 1",), "step-post"),)
              if path == "good.py" else (), limits=native.CodebaseTargetLimits(),
    ) for (path, raw, _), entry, unit, ast in zip(sources, entries, units, ast_records))
    shared = {"schema": transport.SHARED_INVENTORY_SCHEMA, "head": head.to_dict(),
              "manifest": manifest.to_dict(), "publication_receipt": receipt.to_dict()}
    shared["shared_sha256"] = transport._digest(shared, 16 * 1024 * 1024, "fixture")
    return targets, shared


def prepared(captured, counters=None):
    return replay_module.prepare_inventory_replay(
        transport.validate_shared_inventory_envelope(deepcopy(captured[1])), counters=counters)


@pytest.mark.parametrize("position", [0, 1, 2])
def test_complete_supported_and_frontier_targets_equal_unchanged_native(captured, position):
    target = captured[0][position]
    counts = replay_module.InventoryReplayCounters()
    replay = prepared(captured, counts)
    result = replay_module.validate_inventory_codebase_target(target, replay, counters=counts)
    assert result.canonical_bytes == native.validate_codebase_targets(target).canonical_bytes
    assert result.to_dict() == target.to_dict()
    assert result.ready_for_training is (position == 0)
    assert replay.membership_count == 3
    assert counts.to_dict() == {
        "shared_replay_preparations": 1, "target_replay_attempts": 1, "target_replays": 1,
        "source_digest_checks": 1, "ast_digest_checks": int(position != 2),
        "authored_contract_replays": 1, "native_lowering_replays": 1,
        "full_target_comparisons": 1, "shared_manifest_parses_avoided": 1,
        "shared_receipt_parses_avoided": 1,
    }


def test_one_preparation_replays_many_targets_without_native_manifest_reparse(captured, monkeypatch):
    counts = replay_module.InventoryReplayCounters()
    replay = prepared(captured, counts)
    def prohibited(*args, **kwargs):
        pytest.fail("a target reparsed the already independently validated shared native record")
    monkeypatch.setattr(CodebaseIRManifest, "from_dict", prohibited)
    monkeypatch.setattr(CodebasePublicationReceipt, "from_dict", prohibited)
    for target in captured[0] * 2:
        assert replay_module.validate_inventory_codebase_target(target, replay, counters=counts) == target
    assert counts.shared_replay_preparations == 1
    assert counts.target_replays == counts.native_lowering_replays == counts.full_target_comparisons == 6
    assert counts.shared_manifest_parses_avoided == counts.shared_receipt_parses_avoided == 6


def test_replay_snapshot_ignores_mutable_detached_transport_readers(captured):
    shared = deepcopy(captured[1])
    token = transport.validate_shared_inventory_envelope(shared)
    replay = replay_module.prepare_inventory_replay(token)
    shared["manifest"]["coverage"]["inventory_entries"] = 999
    token._manifest_value["coverage"]["inventory_entries"] = 999
    token._receipt_value["operation_id"] = "altered-detached-reader"
    detached = token.to_dict()
    detached["head"]["generation"] = 999
    assert replay_module.validate_inventory_codebase_target(captured[0][0], replay) == captured[0][0]
    assert replay_module.prepare_inventory_replay(token).membership_count == 3
    with pytest.raises(TypeError):
        replay._manifest_value["coverage"]["inventory_entries"] = 999


@pytest.mark.parametrize("mutation", ["token", "canonical", "digest", "native", "rehashed_native"])
def test_factory_refuses_forged_or_changed_validated_tokens(captured, mutation):
    token = transport.validate_shared_inventory_envelope(deepcopy(captured[1]))
    if mutation == "token":
        token = replace(token, _token=object())
    elif mutation == "canonical":
        value = token.to_dict()
        value["manifest"]["coverage"]["inventory_entries"] = 999
        token = replace(token, canonical_bytes=native._wire(value))
    elif mutation == "digest":
        token = replace(token, shared_sha256="0" * 64)
    elif mutation == "native":
        token = replace(token, head=replace(token.head, generation=2))
    else:
        altered_head = replace(token.head, generation=2)
        value = token.to_dict()
        value["head"] = altered_head.to_dict()
        del value["shared_sha256"]
        value["shared_sha256"] = transport._digest(value, 16 * 1024 * 1024, "rehash-control")
        token = replace(token, head=altered_head, canonical_bytes=native._wire(value),
                        shared_sha256=value["shared_sha256"])
    with pytest.raises(native.CodebaseTargetError):
        replay_module.prepare_inventory_replay(token)


def test_only_boundary_validated_tokens_and_native_envelopes_are_accepted(captured):
    with pytest.raises(native.CodebaseTargetError, match="ValidatedInventoryEnvelope"):
        replay_module.prepare_inventory_replay(captured[1])
    replay = prepared(captured)
    with pytest.raises(native.CodebaseTargetError, match="native immutable"):
        replay_module.validate_inventory_codebase_target(captured[0][0].to_dict(), replay)
    with pytest.raises(native.CodebaseTargetError, match="token"):
        replay_module.validate_inventory_codebase_target(captured[0][0], replace(replay, _token=object()))


def mutated_target(target, mutation):
    value = target.to_dict()
    details = value["validation"][0]["details"]
    if mutation == "source_bytes":
        details["source_bytes_hex"] = b"def step(n: int) -> int:\n    return n + 9\n".hex()
    elif mutation == "source_hex_case":
        details["source_bytes_hex"] = details["source_bytes_hex"].upper()
    elif mutation == "source_path":
        details["source_binding"]["path"] = "different.py"
    elif mutation == "source_key":
        details["source_binding"]["source_key"] = "raw:666f726569676e2e7079"
    elif mutation == "entry":
        details["source_binding"]["entry"]["size_bytes"] += 1
    elif mutation == "unit":
        details["source_binding"]["unit"]["parse_status"] = "partial"
    elif mutation == "head":
        details["source_binding"]["head"]["generation"] += 1
    elif mutation == "manifest":
        details["manifest"]["coverage"]["formalized_properties"] = 1
    elif mutation == "receipt":
        details["publication_receipt"]["operation_id"] = "different-publication"
    elif mutation == "ast_provenance":
        details["captured_ast"]["provenance"]["path"] = "different.py"
    elif mutation == "missing_ast":
        details["captured_ast"] = None
    elif mutation == "authored_contract":
        details["authored_contracts"][0]["postconditions"] = ["result == n + 9"]
    elif mutation == "projection":
        value["projections"][0]["expression"]["changed_native_expression"] = True
    elif mutation == "native_program":
        details["native_program"]["metadata"]["changed_native_program"] = True
    elif mutation == "bridge":
        details["native_bridge_results"] = []
    elif mutation == "correspondence":
        details["correspondence"]["is_runtime_equivalence_proof"] = True
    elif mutation == "frontier":
        value["qualification_gaps"] = []
    elif mutation == "numeric_authority":
        details["proof_authority"] = 0
    elif mutation == "shared_bool_alias":
        details["manifest"]["coverage"]["formalized_properties"] = False
    elif mutation == "shared_float_alias":
        details["manifest"]["coverage"]["inventory_entries"] = 3.0
    elif mutation == "unknown_detail":
        details["foreign_extension"] = "unknown-owner"
    elif mutation == "limit_bool":
        details["limits"]["max_functions"] = True
    elif mutation == "limit_widen":
        details["limits"]["max_source_bytes"] += 1
    elif mutation == "limit_source":
        details["limits"]["max_source_bytes"] = 1
    else:
        raise AssertionError(mutation)
    return DomainTargetEnvelope.from_dict(value)


@pytest.mark.parametrize("mutation", [
    "source_bytes", "source_hex_case", "source_path", "source_key", "entry", "unit", "head",
    "manifest", "receipt", "ast_provenance", "missing_ast", "authored_contract", "projection",
    "native_program", "bridge", "correspondence", "frontier", "numeric_authority",
    "shared_bool_alias", "shared_float_alias", "unknown_detail", "limit_bool", "limit_widen", "limit_source",
])
def test_rehashed_native_declarations_refused_by_both_replay_owners(captured, mutation):
    target = mutated_target(captured[0][0], mutation)
    counts = replay_module.InventoryReplayCounters()
    with pytest.raises(native.CodebaseTargetError):
        native.validate_codebase_targets(target)
    with pytest.raises(native.CodebaseTargetError):
        replay_module.validate_inventory_codebase_target(target, prepared(captured), counters=counts)
    assert counts.target_replay_attempts == 1
    assert counts.target_replays == counts.shared_manifest_parses_avoided == counts.shared_receipt_parses_avoided == 0


@pytest.mark.parametrize("mutation", ["source_bytes", "ast_provenance", "authored_contract", "projection", "frontier"])
def test_lossless_compact_transport_cannot_grant_native_validity(captured, mutation):
    shared = transport.validate_shared_inventory_envelope(deepcopy(captured[1]))
    bad_target = mutated_target(captured[0][0], mutation)
    compact = transport.compact_inventory_target(bad_target, shared)
    restored = transport.restore_inventory_target(shared, compact)
    assert restored.canonical_bytes == bad_target.canonical_bytes
    with pytest.raises(native.CodebaseTargetError):
        native.validate_codebase_targets(restored)
    with pytest.raises(native.CodebaseTargetError):
        replay_module.validate_inventory_codebase_target(restored, replay_module.prepare_inventory_replay(shared))


@pytest.mark.parametrize("mutation", ["shared", "compact", "target_sha", "missing", "extra"])
def test_corrupt_compact_or_shared_transport_refuses_before_replay(captured, mutation):
    shared_value = deepcopy(captured[1])
    shared = transport.validate_shared_inventory_envelope(shared_value)
    compact = transport.compact_inventory_target(captured[0][0], shared)
    if mutation == "shared":
        shared_value["manifest"]["coverage"]["inventory_entries"] = 999
        with pytest.raises(native.CodebaseTargetError):
            transport.validate_shared_inventory_envelope(shared_value)
        return
    if mutation == "compact":
        compact["detached_target"]["qualification_gaps"] = []
    elif mutation == "target_sha":
        compact["target_sha256"] = "0" * 64
        payload = {key: value for key, value in compact.items() if key != "compact_sha256"}
        compact["compact_sha256"] = hashlib.sha256(native._wire(payload)).hexdigest()
    elif mutation == "missing":
        del compact["source_digest"]
    else:
        compact["proof_authority"] = True
    with pytest.raises(native.CodebaseTargetError):
        transport.restore_inventory_target(shared, compact)


def test_counter_booleans_and_foreign_counter_owners_are_refused(captured):
    counts = replay_module.InventoryReplayCounters(target_replays=True)
    with pytest.raises(native.CodebaseTargetError, match="exact"):
        replay_module.prepare_inventory_replay(
            transport.validate_shared_inventory_envelope(deepcopy(captured[1])), counters=counts)
    with pytest.raises(native.CodebaseTargetError, match="exact"):
        replay_module.validate_inventory_codebase_target(captured[0][0], prepared(captured), counters={})


def test_closed_native_byte_and_ast_limits_remain_enforced(captured):
    target = captured[0][0]
    value = target.to_dict()
    value["validation"][0]["details"]["limits"]["max_ast_nodes"] = 1
    constrained = DomainTargetEnvelope.from_dict(value)
    with pytest.raises(native.CodebaseTargetError, match="AST"):
        native.validate_codebase_targets(constrained)
    with pytest.raises(native.CodebaseTargetError, match="AST"):
        replay_module.validate_inventory_codebase_target(constrained, prepared(captured))
    value = target.to_dict()
    value["qualification_gaps"].append("x" * (4 * 1024 * 1024))
    oversized = DomainTargetEnvelope.from_dict(value)
    with pytest.raises(native.CodebaseTargetError, match="byte bound"):
        native.validate_codebase_targets(oversized)
    with pytest.raises(native.CodebaseTargetError, match="byte bound"):
        replay_module.validate_inventory_codebase_target(oversized, prepared(captured))
