"""Pure protocol, bound and matrix controls; native evidence has its own fixture."""
import builtins
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_inventory_scan as scanner
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_feature_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features


@pytest.mark.parametrize("name", tuple(scanner.CodebaseInventoryScanLimits.__dataclass_fields__))
@pytest.mark.parametrize("value", [0, -1, True, 1.0])
def test_coordinator_limits_are_positive_exact_integers(name, value):
    with pytest.raises(scanner.CodebaseInventoryScanError, match="bounded"):
        replace(scanner.CodebaseInventoryScanLimits(), **{name: value})


@pytest.mark.parametrize("name", tuple(scanner.CodebaseInventoryScanLimits.__dataclass_fields__))
def test_coordinator_limits_do_not_widen_profile(name):
    original = scanner.CodebaseInventoryScanLimits()
    with pytest.raises(scanner.CodebaseInventoryScanError, match="bounded"):
        replace(original, **{name: getattr(original, name) + 1})


@pytest.fixture
def prohibit_torch(monkeypatch):
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            pytest.fail("invalid finite protocol reached a numerical import")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)


def request():
    return {"schema": worker.SCHEMA, "optimized": True, "contract": {}, "feature_space": {}, "state": {},
            "shared_inventory": {}, "shards": [{"shard_index": 0, "targets": [{}]}],
            "limits": {"max_shards": 16, "max_rows_per_shard": 16, "max_target_bytes": 4 * 1024 * 1024,
                       "max_input_bytes": 32 * 1024 * 1024, "max_output_bytes": 16 * 1024 * 1024},
            "max_seconds": 120}


@pytest.mark.parametrize("mutation", ["extra", "missing", "foreign", "sequence"])
def test_worker_closed_request_refuses_before_torch(prohibit_torch, mutation):
    value = request()
    if mutation == "extra":
        value["training_executed"] = True
    elif mutation == "missing":
        del value["state"]
    elif mutation == "foreign":
        value["schema"] = "unrelated-profile@1"
    else:
        value = [value]
    with pytest.raises(ValueError, match="closed"):
        worker.execute(value)


@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_optimization_switch_requires_boolean(prohibit_torch, value):
    payload = request()
    payload["optimized"] = value
    with pytest.raises(ValueError, match="boolean"):
        worker.execute(payload)


@pytest.mark.parametrize("value", [0, -1, True, float("inf"), 600.01])
def test_worker_deadline_is_closed_and_finite(prohibit_torch, value):
    payload = request()
    payload["max_seconds"] = value
    with pytest.raises(ValueError, match="duration|JSON compliant"):
        worker.execute(payload)


@pytest.mark.parametrize("mutation", ["empty", "too_many", "index", "empty_rows", "too_many_rows", "extra"])
def test_finite_shards_are_ordered_and_bounded_before_torch(prohibit_torch, mutation):
    payload = request()
    if mutation == "empty":
        payload["shards"] = []
    elif mutation == "too_many":
        payload["shards"] *= 17
    elif mutation == "index":
        payload["shards"][0]["shard_index"] = 1
    elif mutation == "empty_rows":
        payload["shards"][0]["targets"] = []
    elif mutation == "too_many_rows":
        payload["shards"][0]["targets"] *= 17
    else:
        payload["shards"][0]["fit"] = True
    with pytest.raises(ValueError, match="bounded|canonical"):
        worker.execute(payload)


def test_request_byte_bound_precedes_numerical_import(prohibit_torch):
    payload = request()
    payload["limits"]["max_input_bytes"] = 1
    with pytest.raises(ValueError, match="input.*bound"):
        worker.execute(payload)


def test_duplicate_and_nonfinite_native_json_are_refused():
    with pytest.raises(ValueError, match="duplicate"):
        json.loads('{"optimized":true,"optimized":false}', object_pairs_hook=worker._json_pairs)
    with pytest.raises(ValueError, match="nonfinite"):
        json.loads('{"duration":NaN}', parse_constant=worker._json_constant)


def targets():
    from ipfs_datasets_py.logic.formalization.autoencoder import codebase_targets
    from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
    result = []
    for number in range(3):
        path, name = f"unit_{number}.py", f"step_{number}"
        body = f"def {name}(n: int) -> int:\n    return n + {number + 1}\n".encode()
        result.append(codebase_targets.prepare_codebase_targets(body,
            IntegerOffsetContract(path, name, "n", number + 1), revision="snapshot:matrix-unit-control").to_dict())
    return result


def test_prepared_vocabulary_preserves_reference_matrix_ids_and_coverage():
    values = targets()
    ids = [row["projection_id"] for row in values[0]["projections"]]
    space = features.build_feature_space("codebase_ir", ids, values[:2])
    vocabulary = worker.prepare_inventory_vocabulary(space)
    for batch in (values[:1], values[1:], values):
        assert worker._matrix(vocabulary, batch) == features._matrix(space, batch)
        for target in batch:
            coverage = worker.inventory_target_coverage(vocabulary, target)
            assert coverage["compatible"]
            assert coverage["coverage"] == features._matrix(space, [target])[2]


def test_zero_vocabulary_coverage_is_an_explicit_incompatible_result():
    values = targets()
    ids = [row["projection_id"] for row in values[0]["projections"]]
    space = features.build_feature_space("codebase_ir", ids, values[:1])
    vocabulary = worker.prepare_inventory_vocabulary(space)
    foreign_atoms = deepcopy(values[1])
    for projection in foreign_atoms["projections"]:
        projection["expression"] = {"wholly_unknown_unit_control": "unknown-value"}
    coverage = worker.inventory_target_coverage(vocabulary, foreign_atoms)
    assert not coverage["compatible"]
    assert all(row["known_atoms"] == 0 and row["unknown_atoms"] > 0 for row in coverage["coverage"])
    with pytest.raises(ValueError, match="coverage"):
        worker._matrix(vocabulary, [foreign_atoms])
    with pytest.raises(ValueError, match="coverage"):
        features._matrix(space, [foreign_atoms])


def record_value():
    ordered = [{"source_key": "raw:61612e7079", "entry_cid": cid_for_structured({"fixture": "entry"})}]
    return {"schema": scanner.SCHEMA, "profile": scanner.PROFILE,
            "codec": "canonical-finite-native-json/raw-cidv1", "head": {}, "model": {},
            "membership": {"cid": cid_for_structured(ordered), "ordered": ordered},
            "entries": [{**ordered[0], "disposition": "inferred", "inference": {"latent": [.25]}}],
            "shards": [], "worker_receipt": None, "counters": {}, "timings": {}, "limits": {},
            "implementation": {}, "authority": dict(scanner._FALSE)}


def test_finite_numerical_record_binds_raw_cid_and_detaches_readers():
    value = record_value()
    raw = scanner._wire(value)
    record = scanner.CodebaseInventoryScanRecord(cid_for_bytes(raw), raw)
    reader = record.to_dict()
    reader["entries"][0]["inference"]["latent"][0] = 999
    assert record.to_dict() == value
    with pytest.raises(scanner.CodebaseInventoryScanError, match="identity"):
        scanner.CodebaseInventoryScanRecord(cid_for_bytes(raw + b"\n"), raw)
    with pytest.raises(scanner.CodebaseInventoryScanError, match="identity"):
        scanner.CodebaseInventoryScanRecord(cid_for_bytes(raw + b"\n"), raw + b"\n")


@pytest.mark.parametrize("mutation", ["authority", "numeric_authority", "membership", "duplicate", "disposition"])
def test_record_refuses_authority_or_incomplete_membership(mutation):
    value = record_value()
    if mutation == "authority":
        value["authority"]["proof_authority"] = True
    elif mutation == "numeric_authority":
        value["authority"]["proof_authority"] = 0
    elif mutation == "membership":
        value["membership"]["ordered"] = []
    elif mutation == "duplicate":
        value["entries"] *= 2
        ordered = [{"source_key": row["source_key"], "entry_cid": row["entry_cid"]} for row in value["entries"]]
        value["membership"] = {"cid": cid_for_structured(ordered), "ordered": ordered}
    else:
        value["entries"][0]["disposition"] = "proved"
    raw = scanner._wire(value)
    with pytest.raises(scanner.CodebaseInventoryScanError):
        scanner.CodebaseInventoryScanRecord(cid_for_bytes(raw), raw)
