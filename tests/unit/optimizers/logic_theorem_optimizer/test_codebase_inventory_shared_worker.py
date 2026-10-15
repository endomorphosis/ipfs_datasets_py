"""Shared resume inference with real native lowering and frozen CPU weights.

These captured-record fixtures do not open a catalog, scheduler or registry,
fit a model, download weights, or execute repository code. Deterministic valid
epoch-zero parameters exercise the actual Torch engine and unchanged numerical
worker. Byte limits, late native refusal, exact root joins and live restored
object retention are separate controls, not inference success substitutes.
"""
import builtins
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import gc
import types

import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebasePublicationReceipt, _request
from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_resume as resume
from ipfs_datasets_py.logic.software_contracts import codebase_ir_targets as native
from ipfs_datasets_py.logic.software_contracts import codebase_resume_shared_targets as transport
from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseIRManifest, CodebaseUnit
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import ArtifactRecord, RepositoryState
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot, SnapshotEntry
from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_feature_worker as numerical
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_resume_worker as legacy
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_shared_worker as worker


@pytest.fixture(scope="module")
def captured():
    records = [(f"unit{index:02d}.py",
                f"def step{index}(n: int) -> int:\n    return n + {index + 1}\n".encode())
               for index in range(3)]
    entries = tuple(SnapshotEntry(path, "file", len(raw), cid_for_bytes(raw), disposition="filesystem")
                    for path, raw in records)
    snapshot = RepositorySnapshot("fixture-native-shared-worker", entries, "filesystem",
                                  max_entries=512, max_file_bytes=64 * 1024)
    asts = tuple(PythonASTExtractor().extract_from_source(raw, path=path,
        repository_id=snapshot.repository_id, revision="snapshot:" + snapshot.snapshot_cid,
        repository_tree_cid=snapshot.snapshot_cid) for path, raw in records)
    repository_state = RepositoryState(snapshot.repository_id, artifacts=(ArtifactRecord(
        "artifact:snapshot-evidence", "snapshot", ".snapshot", snapshot.snapshot_cid,
        metadata={"snapshot": snapshot.to_dict()}),))
    units = tuple(CodebaseUnit(entry.source_key, entry.entry_cid, cid_for_structured(ast.to_dict()), "ok")
                  for entry, ast in zip(entries, asts))
    manifest = CodebaseIRManifest(snapshot, repository_state,
        "rev:" + snapshot.repository_id + ":snapshot:" + snapshot.snapshot_cid, units)
    receipt = CodebasePublicationReceipt("shared-worker-fixture",
        _request(snapshot.repository_id, manifest.cid, None), None, snapshot.repository_id,
        1, manifest.cid, snapshot.snapshot_cid, manifest.ast_revision_id)
    targets = tuple(native._prepare_bound(binding=native._binding(receipt.head, manifest, entry, unit, raw),
        manifest=manifest, receipt=receipt, ast_record=ast, raw=raw,
        specs=(ContractSpec(f"step{index}", (), (f"result == n + {index + 1}",), f"post-{index}"),),
        limits=native.CodebaseTargetLimits())
        for index, ((_, raw), entry, unit, ast) in enumerate(zip(records, entries, units, asts)))
    assert all(target.ready_for_training is True for target in targets)
    ids = [native.CODEBASE_PROGRAM_PROJECTION, native.CODEBASE_CONTRACTS_PROJECTION]
    space = features.build_feature_space("codebase_ir", ids, targets)
    contract = features.build_native_feature_contract(space, ir_schema=native.CODEBASE_TARGET_SCHEMA,
        adapter_sha256=hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(), latent_width=8)
    width, latent = len(space["columns"]), 8
    parameters = [
        [[((row + column) % 7 + 1) / 1000 for column in range(latent)] for row in range(width)],
        [index / 100 for index in range(latent)],
        [[((row + column) % 5 + 1) / 1000 for column in range(width)] for row in range(latent)],
        [index / 10000 for index in range(width)],
    ]
    def zero_like(value):
        return [zero_like(child) if type(child) is list else 0.0 for child in value]
    state = {"schema": features.STATE_SCHEMA, "contract_sha256": contract.sha256,
        "feature_space_sha256": features.digest(space), "latent_width": latent, "parameters": parameters,
        "adam": [{"step": 0, "exp_avg": zero_like(value), "exp_avg_sq": zero_like(value)}
                 for value in parameters], "completed_epochs": 0,
        "optimizer_config": {"name": "Adam", "learning_rate": .002, "betas": [.9, .999], "eps": 1e-8},
        "tuning_targets_sha256": features.digest([]), **features.FALSE}
    shared = transport.create_resume_shared_inventory(receipt.head, manifest, receipt)
    token = transport.validate_resume_shared_inventory(shared)
    compact = [transport.compact_resume_target(target, token) for target in targets]
    checkpoint_bytes = worker._wire({"contract": contract.to_dict(), "feature_space": space, "state": state})
    artifact = {"sha256": hashlib.sha256(checkpoint_bytes).hexdigest(), "bytes": len(checkpoint_bytes)}
    model = {"version_id": "deterministic-epoch-zero", "variant_id": contract.variant_id,
        "artifact": artifact, "artifact_cid": cid_for_bytes(checkpoint_bytes),
        "contract_sha256": contract.sha256, "state_sha256": features.digest(state),
        "feature_space_sha256": features.digest(space), "latent_width": latent,
        "feature_columns": width, "projection_ids": space["projection_ids"],
        "projection_widths": {name: sum(row[0] == name for row in space["columns"]) for name in space["projection_ids"]},
        "ancestry": [{"version_id": "deterministic-epoch-zero", "artifact": artifact}]}
    files = {"shared-worker-fixture": hashlib.sha256(Path(worker.__file__).read_bytes()).hexdigest()}
    root = {"schema": resume.ROOT_SCHEMA, "head": receipt.head.to_dict(),
        "head_cid": cid_for_structured(receipt.head.to_dict()), "members": resume._members(manifest),
        "membership_cid": cid_for_structured(resume._members(manifest)), "model": model,
        "limits": resume.CodebaseScanResumeLimits(max_inventory_entries=512, page_entries=3).to_dict(), "optimized": True,
        "implementation": {"files": files, "sha256": features.digest(files),
            "scope": "listed_local_files_only_not_execution_attestation"}, "authority": dict(resume._FALSE)}
    return {"root": root, "contract": contract.to_dict(), "feature_space": space, "state": state,
            "targets": targets, "compact": compact, "shared": shared}


def request_for(captured, *, optimized=True, page_entries=3, indices=None):
    value = {"schema": worker.SCHEMA, "root": deepcopy(captured["root"]), "optimized": optimized,
        "contract": deepcopy(captured["contract"]), "feature_space": deepcopy(captured["feature_space"]),
        "state": deepcopy(captured["state"]), "shared_inventory": deepcopy(captured["shared"]),
        "targets": deepcopy(captured["compact"]), "member_indices": list(range(3)), "max_seconds": 30,
        "limits": {"max_rows": page_entries, "max_target_bytes": worker.MAX_TARGET_BYTES,
            "max_input_bytes": worker.MAX_BYTES, "max_output_bytes": worker.MAX_OUTPUT_BYTES,
            "max_feature_cells": worker.MAX_FEATURE_CELLS, "max_retained_restored_targets": 1}}
    value["root"]["optimized"] = optimized
    value["root"]["limits"]["page_entries"] = page_entries
    if indices is not None:
        value["member_indices"] = list(indices)
        value["targets"] = [deepcopy(captured["compact"][index]) for index in indices]
    value["root_cid"] = cid_for_structured(value["root"])
    return value


def guard_torch_import(monkeypatch):
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            pytest.fail("Torch imported before all shared/root/native target checks completed")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)


@pytest.fixture
def torch_process_controls(monkeypatch):
    torch = pytest.importorskip("torch")
    torch.set_num_threads(1)
    # A pytest process evaluates several independent worker invocations; Torch
    # permits the interop setter only once. Actual tensor construction, forward
    # arithmetic and no-grad execution remain unchanged and use one CPU thread.
    def require_one(value):
        assert value == 1
    monkeypatch.setattr(torch, "set_num_interop_threads", require_one)
    return torch


@pytest.mark.parametrize("optimized", [True, False])
def test_shared_streamed_native_inference_equals_unchanged_full_worker(captured, optimized, torch_process_controls):
    request = request_for(captured, optimized=optimized)
    frozen = worker._wire(request)
    actual = worker.execute(request)
    old_request = deepcopy(request)
    old_request["schema"] = legacy.SCHEMA
    del old_request["shared_inventory"]
    for key in ("max_feature_cells", "max_retained_restored_targets"):
        del old_request["limits"][key]
    old_request["targets"] = [target.to_dict() for target in captured["targets"]]
    expected = legacy.execute(old_request)
    assert actual["inference"] == expected["inference"]
    assert actual["worker"] == expected["worker"]
    assert set(actual) == {"schema", "optimized", "inference", "counters", "worker"}
    assert actual["counters"] == {"shared_inventory_validations": 1, "shared_manifest_parses": 1,
        "shared_receipt_parses": 1, "shared_replay_preparations": int(optimized), "target_restorations": 3,
        "native_target_replays": (1 if optimized else 2) * 3,
        "native_lowering_replays": (1 if optimized else 2) * 3,
        "full_target_comparisons": (1 if optimized else 2) * 3, "streamed_feature_rows": 3,
        "matrix_builds": 1, "vocabulary_builds": 1, "weight_tensor_builds": 4, "input_tensor_builds": 1,
        "contract_validations": 1 if optimized else 2, "state_validations": 1 if optimized else 2,
        "rows": 3, "training_calls": 0, "max_retained_restored_targets": 1,
        "gc_collections": 0 if optimized else 3}
    assert all(actual["inference"][flag] is False for flag in features.FALSE)
    assert worker._wire(request) == frozen
    assert request["state"]["completed_epochs"] == 0


@pytest.mark.parametrize("optimized", [True, False])
def test_previous_restored_target_is_destroyed_before_next_row(captured, optimized, monkeypatch, torch_process_controls):
    original_restore, original_matrix = transport.restore_resume_target, numerical._matrix
    restored_inputs, validated_inputs, row_calls = [], [], []
    original_collect, collection_calls = gc.collect, []
    def collect(*args, **kwargs):
        collection_calls.append(1)
        return original_collect(*args, **kwargs)
    def retained():
        return [id(value) for value in gc.get_objects()
                if type(value) is DomainTargetEnvelope and any(
                    id(value) == identity and value.canonical_bytes is payload
                    for identity, payload in restored_inputs + validated_inputs)]
    def restore(*args, **kwargs):
        remaining = retained()
        if remaining:
            owners = []
            for value in gc.get_objects():
                if type(value) is DomainTargetEnvelope and id(value) in remaining:
                    for owner in gc.get_referrers(value):
                        if type(owner) is types.FrameType:
                            owners.append(("frame", owner.f_code.co_name))
                        elif type(owner) is dict:
                            owners.append(("mapping", sorted(key for key, child in owner.items()
                                if child is value and type(key) is str)))
                        else:
                            owners.append((type(owner).__name__, None))
            assert not remaining, owners
        target = original_restore(*args, **kwargs)
        assert gc.is_tracked(target)
        # Holding only bytes permits envelope destruction and disambiguates
        # CPython reuse of a freed envelope's numeric object address.
        restored_inputs.append((id(target), target.canonical_bytes))
        return target
    def matrix(vocabulary, targets):
        assert len(targets) == 1
        validated_inputs.append((id(targets[0]), targets[0].canonical_bytes))
        row_calls.append(targets[0].source_digest)
        return original_matrix(vocabulary, targets)
    monkeypatch.setattr(transport, "restore_resume_target", restore)
    monkeypatch.setattr(numerical, "_matrix", matrix)
    monkeypatch.setattr(gc, "collect", collect)
    actual = worker.execute(request_for(captured, optimized=optimized))
    assert len(restored_inputs) == len(validated_inputs) == len(row_calls) == 3
    assert not retained()
    assert row_calls == [row["source_digest"] for row in actual["inference"]["rows"]]
    assert len(collection_calls) == actual["counters"]["gc_collections"] == (0 if optimized else 3)


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("mutation", ["projection", "source_bytes", "ast_provenance"])
def test_late_rehashed_malformed_native_target_refuses_before_torch_or_engine(captured, optimized, mutation, monkeypatch):
    request = request_for(captured, optimized=optimized)
    value = captured["targets"][1].to_dict()
    if mutation == "projection":
        value["projections"][0]["expression"]["changed_native_expression"] = True
    elif mutation == "source_bytes":
        value["validation"][0]["details"]["source_bytes_hex"] = (
            b"def step1(n: int) -> int:\n    return n + 9\n").hex()
    else:
        value["validation"][0]["details"]["captured_ast"]["provenance"]["path"] = "different.py"
    bad = DomainTargetEnvelope.from_dict(value)
    token = transport.validate_resume_shared_inventory(request["shared_inventory"])
    request["targets"][1] = transport.compact_resume_target(bad, token)
    original = numerical._matrix
    completed_rows = []
    def matrix(vocabulary, targets):
        result = original(vocabulary, targets)
        completed_rows.append(result[1])
        return result
    monkeypatch.setattr(numerical, "_matrix", matrix)
    guard_torch_import(monkeypatch)
    with pytest.raises(ValueError):
        worker.execute(request)
    assert completed_rows == [[captured["targets"][0].source_digest]]


@pytest.mark.parametrize("mutation", ["source_order", "root_member", "root_head", "model_sha", "state",
    "state_authority", "old_shared_schema", "shared_hash", "compact_hash", "target_hash", "page_boundary",
    "old_root_profile"])
def test_native_source_global_membership_and_model_joins_refuse_before_torch(captured, mutation, monkeypatch):
    request = request_for(captured)
    if mutation == "source_order":
        request["targets"][0], request["targets"][1] = request["targets"][1], request["targets"][0]
    elif mutation == "root_member":
        request["root"]["members"][0]["ast_cid"] = cid_for_structured({"foreign_ast": True})
        request["root"]["membership_cid"] = cid_for_structured(request["root"]["members"])
    elif mutation == "root_head":
        request["root"]["head"]["generation"] += 1
        request["root"]["head_cid"] = cid_for_structured(request["root"]["head"])
    elif mutation == "model_sha":
        request["root"]["model"]["state_sha256"] = "0" * 64
    elif mutation == "state":
        request["state"]["parameters"][0][0][0] += .1
    elif mutation == "state_authority":
        request["state"]["qualified"] = True
    elif mutation == "old_shared_schema":
        request["shared_inventory"]["schema"] = "codebase-ir-shared-target-inventory@1"
    elif mutation == "shared_hash":
        request["shared_inventory"]["shared_sha256"] = "0" * 64
    elif mutation == "compact_hash":
        request["targets"][0]["compact_sha256"] = "0" * 64
    elif mutation == "target_hash":
        compact = request["targets"][0]
        compact["target_sha256"] = "0" * 64
        compact["compact_sha256"] = transport._digest(
            {key: child for key, child in compact.items() if key != "compact_sha256"},
            transport.MAX_TARGET_BYTES, "test-rehashed-target")
    elif mutation == "page_boundary":
        request = request_for(captured, page_entries=2, indices=[1, 2])
    elif mutation == "old_root_profile":
        request["root"]["limits"]["max_inventory_entries"] = 1024
    else:
        raise AssertionError(mutation)
    request["root_cid"] = cid_for_structured(request["root"])
    guard_torch_import(monkeypatch)
    with pytest.raises(ValueError):
        worker.execute(request)


def test_coherently_valid_foreign_publication_cannot_replace_root_inventory(captured, monkeypatch):
    request = request_for(captured)
    original = transport.validate_resume_shared_inventory(request["shared_inventory"])
    foreign_receipt = CodebasePublicationReceipt("different-genuine-publication",
        _request(original.head.repository_id, original.manifest.cid, None), None,
        original.head.repository_id, 1, original.manifest.cid, original.head.snapshot_cid,
        original.head.ast_revision_id)
    foreign = transport.create_resume_shared_inventory(foreign_receipt.head, original.manifest, foreign_receipt)
    assert transport.validate_resume_shared_inventory(foreign).head == foreign_receipt.head
    assert foreign_receipt.head != original.head
    request["shared_inventory"] = foreign
    guard_torch_import(monkeypatch)
    with pytest.raises(ValueError, match="shared native head/global membership differs"):
        worker.execute(request)


@pytest.mark.parametrize("name,value", [("max_rows", 65), ("max_rows", True),
    ("max_target_bytes", worker.MAX_TARGET_BYTES + 1), ("max_input_bytes", worker.MAX_BYTES + 1),
    ("max_output_bytes", worker.MAX_OUTPUT_BYTES + 1), ("max_feature_cells", worker.MAX_FEATURE_CELLS + 1),
    ("max_feature_cells", 1), ("max_retained_restored_targets", 2), ("max_retained_restored_targets", True)])
def test_closed_fixed_request_caps_reject_widening_or_boolean_aliases(captured, name, value, monkeypatch):
    request = request_for(captured)
    request["limits"][name] = value
    guard_torch_import(monkeypatch)
    with pytest.raises(ValueError):
        worker.execute(request)


@pytest.mark.parametrize("mutation", ["old_worker", "missing_shared", "extra", "bool_index", "duplicate_index",
    "reversed_indices", "empty", "too_many_rows", "duration_bool", "duration_nan", "duration_large",
    "input_bytes", "input_bytes_bool", "compact_bytes"])
def test_inert_request_protocol_rejects_before_dependency_import(captured, mutation, monkeypatch):
    request = request_for(captured)
    input_bytes = None
    if mutation == "old_worker":
        request["schema"] = legacy.SCHEMA
    elif mutation == "missing_shared":
        del request["shared_inventory"]
    elif mutation == "extra":
        request["proof_authority"] = False
    elif mutation == "bool_index":
        request["member_indices"][0] = False
    elif mutation == "duplicate_index":
        request["member_indices"] = [0, 0, 2]
    elif mutation == "reversed_indices":
        request["member_indices"].reverse()
    elif mutation == "empty":
        request["targets"] = request["member_indices"] = []
    elif mutation == "too_many_rows":
        request["targets"].append(deepcopy(request["targets"][0]))
        request["member_indices"].append(3)
    elif mutation == "duration_bool":
        request["max_seconds"] = True
    elif mutation == "duration_nan":
        request["max_seconds"] = float("nan")
        input_bytes = 0
    elif mutation == "duration_large":
        request["max_seconds"] = worker.MAX_SECONDS + 1
    elif mutation == "input_bytes":
        input_bytes = worker.MAX_BYTES + 1
    elif mutation == "input_bytes_bool":
        input_bytes = False
    elif mutation == "compact_bytes":
        request["targets"][0]["too_large"] = "x" * worker.MAX_TARGET_BYTES
    else:
        raise AssertionError(mutation)
    guard_torch_import(monkeypatch)
    with pytest.raises(ValueError):
        worker.execute(request, _input_bytes=input_bytes)


def test_json_entrypoint_refuses_duplicate_and_nonfinite_raw_values():
    with pytest.raises(ValueError, match="duplicate"):
        json.loads('{"optimized":true,"optimized":false}', object_pairs_hook=worker._json_pairs)
    with pytest.raises(ValueError, match="nonfinite"):
        json.loads('{"seconds":NaN}', parse_constant=worker._json_constant)


def test_restored_full_target_cap_remains_independent_of_small_compact_size(captured, monkeypatch):
    request = request_for(captured, indices=[0])
    compact_size = len(worker._wire(request["targets"][0]))
    full_size = len(captured["targets"][0].canonical_bytes)
    assert compact_size < full_size
    request["limits"]["max_target_bytes"] = compact_size
    request["root"]["limits"]["max_target_bytes"] = compact_size
    request["root_cid"] = cid_for_structured(request["root"])
    guard_torch_import(monkeypatch)
    with pytest.raises(ValueError, match="restored native target exceeds byte bound"):
        worker.execute(request)


def test_reference_replays_each_row_twice_and_revalidates_state_without_shared_replay(captured, monkeypatch,
                                                                                    torch_process_controls):
    original_replay, original_contract, original_state = legacy._replay_target, features._contract, features._validate_state
    original_native = native.validate_codebase_targets
    calls = {"legacy": [], "native": 0, "contract": 0, "state": 0}
    def legacy_replay(value, optimized):
        assert optimized is False
        calls["legacy"].append(value["source_digest"])
        return original_replay(value, optimized)
    def contract(*args, **kwargs):
        calls["contract"] += 1
        return original_contract(*args, **kwargs)
    def state(*args, **kwargs):
        calls["state"] += 1
        return original_state(*args, **kwargs)
    def native_replay(*args, **kwargs):
        calls["native"] += 1
        return original_native(*args, **kwargs)
    def prohibited(*args, **kwargs):
        pytest.fail("reference path prepared or used an optimized shared replay")
    monkeypatch.setattr(legacy, "_replay_target", legacy_replay)
    monkeypatch.setattr(features, "_contract", contract)
    monkeypatch.setattr(features, "_validate_state", state)
    monkeypatch.setattr(native, "validate_codebase_targets", native_replay)
    monkeypatch.setattr(transport, "prepare_resume_replay", prohibited)
    monkeypatch.setattr(transport, "validate_resume_target", prohibited)
    result = worker.execute(request_for(captured, optimized=False))
    assert calls == {"legacy": [target.source_digest for target in captured["targets"]],
                     "native": 6, "contract": 2, "state": 2}
    assert result["counters"]["native_target_replays"] == 6


@pytest.mark.parametrize("bound", ["entries", "files", "manifest"])
def test_coherently_rehashed_root_cannot_narrow_captured_profile(captured, bound, monkeypatch):
    request = request_for(captured)
    limits = request["root"]["limits"]
    if bound == "entries":
        limits["max_inventory_entries"] = len(request["root"]["members"])
    elif bound == "files":
        limits["max_file_bytes"] = max(row["source_size_bytes"] for row in request["root"]["members"])
    else:
        limits["max_manifest_bytes"] = len(resume.canonical_dag_json_bytes(request["shared_inventory"]["manifest"])) - 1
    request["root_cid"] = cid_for_structured(request["root"])
    # Shape, raw root CID and actual listed rows still agree. Refusal must come
    # from the captured declaration, before dependency loading or inference.
    resume.CodebaseScanResumeRoot.from_dict(request["root_cid"], request["root"])
    guard_torch_import(monkeypatch)
    with pytest.raises(ValueError, match="capture exceeds root profile"):
        worker.execute(request)
