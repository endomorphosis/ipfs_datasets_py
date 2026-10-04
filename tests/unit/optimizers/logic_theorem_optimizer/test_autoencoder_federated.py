"""Same-base federated updates combine parameters without promoting authority."""
from dataclasses import FrozenInstanceError, replace
import copy
import hashlib
import json
import math
import struct

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import (
    AggregateCandidate, ClientSpec, ClientUpdate, FederatedRound, ParameterSpec,
    aggregate_round, make_client_update, parameter_digest,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_federated as federated


def setup_round(dimension=8, *, dtype="float64", counts=(1, 3), base=None):
    specs = [ParameterSpec("projection.weight", (dimension,), dtype),
             ParameterSpec("output.bias", (), dtype)]
    if base is None:
        base = {"projection.weight": [10.0] * dimension, "output.bias": [-0.0]}
    clients = [ClientSpec("worker-a", counts[0], "c" * 64),
               ClientSpec("worker-b", counts[1], "d" * 64)]
    round_spec = FederatedRound(round_id="round-1", model_id="legal-ir",
        lineage_id="legacy_hub_v1" if dimension == 8 else "current_legal_v2",
        dimension=dimension, architecture="authored-projection/v1", runtime_profile="federated-test/v1",
        base_sha256="a" * 64, base_parameters_sha256=parameter_digest(specs, base),
        embedding_producer_sha256="b" * 64, parameters=specs, clients=clients, max_local_steps=5)
    return round_spec, base


def update(round_spec, client_id, deltas, *, local_steps=2):
    client = next(client for client in round_spec.clients if client.client_id == client_id)
    return make_client_update(round_spec, client_id, deltas, local_steps=local_steps,
                              local_data_sha256=client.local_data_sha256)


@pytest.mark.parametrize("dimension", [8, 384])
@pytest.mark.parametrize("dtype", ["float32", "float64"])
def test_real_weighted_fedavg_uses_one_shared_model_per_lineage(dimension, dtype):
    round_spec, base = setup_round(dimension, dtype=dtype)
    updates = [update(round_spec, "worker-a", {"projection.weight": [4.0] * dimension}),
               update(round_spec, "worker-b", {"projection.weight": [-2.0] * dimension,
                                              "output.bias": [8.0]})]
    candidate = aggregate_round(round_spec, base, updates)
    assert candidate.parameters == {"projection.weight": [9.5] * dimension, "output.bias": [6.0]}
    assert candidate.provenance["total_sample_count"] == 4
    assert candidate.provenance["round"]["dimension"] == dimension
    assert candidate.provenance["parent_checkpoint_sha256"] == round_spec.base_sha256
    for field in ("qualified", "admitted", "formalized", "owner_verified", "promotion_performed",
                  "publication_performed"):
        assert candidate.provenance[field] is False


def test_sparse_omission_uses_all_clients_denominator_and_preserves_untouched_signed_zero():
    round_spec, base = setup_round()
    candidate = aggregate_round(round_spec, base, [
        update(round_spec, "worker-a", {"projection.weight": {0: 4.0}}),
        update(round_spec, "worker-b", {"projection.weight": {1: -2.0}})])
    assert candidate.parameters["projection.weight"] == [11.0, 8.5] + [10.0] * 6
    assert math.copysign(1.0, candidate.parameters["output.bias"][0]) == -1.0


def test_empty_updates_are_valid_and_are_not_silently_dropped():
    round_spec, base = setup_round()
    candidate = aggregate_round(round_spec, base, [
        update(round_spec, "worker-a", {"projection.weight": {0: 4.0}}),
        update(round_spec, "worker-b", {})])
    assert candidate.parameters["projection.weight"][0] == 11.0
    assert len(candidate.provenance["updates"]) == 2


def test_count_sum_exceeding_signed_int64_does_not_overflow():
    maximum = 2**63 - 1
    round_spec, base = setup_round(counts=(maximum, maximum))
    candidate = aggregate_round(round_spec, base, [
        update(round_spec, "worker-a", {"projection.weight": {0: 4.0}}),
        update(round_spec, "worker-b", {"projection.weight": {0: -2.0}})])
    assert candidate.parameters["projection.weight"][0] == 11.0
    assert candidate.provenance["total_sample_count"] == 2 * maximum


def test_cancellation_with_overflowing_intermediate_has_finite_result():
    # base + first contribution exceeds float64, but the final answer fits.
    round_spec, base = setup_round(counts=(3, 1),
        base={"projection.weight": [1.4e308] * 8, "output.bias": [0.0]})
    candidate = aggregate_round(round_spec, base, [
        update(round_spec, "worker-a", {"projection.weight": {0: 0.8e308}}),
        update(round_spec, "worker-b", {"projection.weight": {0: -1.4e308}})])
    assert candidate.parameters["projection.weight"][0] == pytest.approx(1.65e308)
    assert math.isfinite(candidate.parameters["projection.weight"][0])


@pytest.mark.parametrize("dtype,base_value,delta", [("float64", 1.7e308, 1.7e308),
                                                   ("float32", 3e38, 3e38)])
def test_genuine_aggregate_overflow_is_rejected(dtype, base_value, delta):
    round_spec, base = setup_round(dtype=dtype,
        base={"projection.weight": [base_value] * 8, "output.bias": [0.0]})
    with pytest.raises(ValueError, match="overflow|finite"):
        aggregate_round(round_spec, base, [
            update(round_spec, "worker-a", {"projection.weight": {0: delta}}),
            update(round_spec, "worker-b", {"projection.weight": {0: delta}})])


def test_deterministic_order_and_fresh_snapshots_do_not_mutate_inputs():
    round_spec, base = setup_round()
    original_base = copy.deepcopy(base)
    deltas = {"projection.weight": {3: 1.25, 0: 4.0}, "output.bias": [2.0]}
    first = update(round_spec, "worker-a", deltas)
    second = update(round_spec, "worker-b", {"projection.weight": {2: -3.0}})
    candidate = aggregate_round(round_spec, base, [first, second])
    assert aggregate_round(round_spec, dict(reversed(list(base.items()))), [second, first]) == candidate
    reversed_round = replace(round_spec, parameters=list(reversed(round_spec.parameters)),
                             clients=list(reversed(round_spec.clients)))
    assert reversed_round.round_sha256 == round_spec.round_sha256
    assert aggregate_round(reversed_round, base, [second, first]) == candidate
    assert base == original_base and deltas["projection.weight"][0] == 4.0
    deltas["projection.weight"][0] = 9000.0
    first.deltas["projection.weight"][0] = 8000.0
    candidate.parameters["projection.weight"][0] = 7000.0
    candidate.provenance["updates"][0]["sample_count"] = 6000
    assert candidate.parameters["projection.weight"][0] == 11.0
    assert first.deltas["projection.weight"][0] == 4.0
    assert candidate.provenance["updates"][0]["sample_count"] == 1
    with pytest.raises(FrozenInstanceError):
        round_spec.dimension = 384


@pytest.mark.parametrize("base_change", ["value", "sign", "missing", "extra", "shape", "bool"])
def test_changed_base_is_rejected(base_change):
    round_spec, base = setup_round()
    changed = copy.deepcopy(base)
    if base_change == "value":
        changed["projection.weight"][0] += 1
    elif base_change == "sign":
        changed["output.bias"][0] = 0.0
    elif base_change == "missing":
        del changed["output.bias"]
    elif base_change == "extra":
        changed["optimizer_state"] = [0.0]
    elif base_change == "shape":
        changed["projection.weight"].pop()
    else:
        changed["projection.weight"][0] = True
    with pytest.raises(ValueError):
        aggregate_round(round_spec, changed, [update(round_spec, "worker-a", {}),
                                              update(round_spec, "worker-b", {})])


def test_parameter_digest_commits_dtype_shape_and_signed_zero():
    values = {"weight": [0.0]}
    digest64 = parameter_digest([ParameterSpec("weight", (1,), "float64")], values)
    assert digest64 != parameter_digest([ParameterSpec("weight", (1,), "float32")], values)
    assert digest64 != parameter_digest([ParameterSpec("weight", (), "float64")], values)
    assert digest64 != parameter_digest([ParameterSpec("weight", (1,), "float64")], {"weight": [-0.0]})


@pytest.mark.parametrize("field,new", [("base_sha256", "f" * 64), ("round_id", "other-round"),
    ("dimension", 384), ("lineage_id", "another-lineage"), ("model_id", "other-model"),
    ("architecture", "other/v1"), ("runtime_profile", "other/v1"),
    ("embedding_producer_sha256", "e" * 64)])
def test_update_bound_to_exact_model_lineage_round_and_base(field, new):
    round_spec, base = setup_round()
    other = replace(round_spec, **{field: new})
    foreign = update(other, "worker-a", {})
    with pytest.raises(ValueError, match="another round"):
        aggregate_round(round_spec, base, [foreign, update(round_spec, "worker-b", {})])


def test_layout_and_dtype_changes_are_rejected_even_with_same_numeric_values():
    round_spec, base = setup_round()
    changed = replace(round_spec, parameters=[replace(spec, dtype="float32") for spec in round_spec.parameters],
                      base_parameters_sha256=parameter_digest(
                          [replace(spec, dtype="float32") for spec in round_spec.parameters], base))
    with pytest.raises(ValueError, match="another round"):
        aggregate_round(round_spec, base, [update(changed, "worker-a", {}),
                                          update(round_spec, "worker-b", {})])


def test_duplicate_missing_unknown_clients_and_changed_counts_are_rejected():
    round_spec, base = setup_round()
    first = update(round_spec, "worker-a", {})
    with pytest.raises(ValueError, match="duplicate client"):
        aggregate_round(round_spec, base, [first, first])
    with pytest.raises(ValueError, match="every approved"):
        aggregate_round(round_spec, base, [first])
    with pytest.raises(ValueError, match="not approved"):
        make_client_update(round_spec, "unknown", {}, local_steps=1, local_data_sha256="e" * 64)
    changed = replace(round_spec, clients=[replace(client, sample_count=9) for client in round_spec.clients])
    with pytest.raises(ValueError, match="another round"):
        aggregate_round(round_spec, base, [update(changed, "worker-a", {}),
                                          update(round_spec, "worker-b", {})])


@pytest.mark.parametrize("deltas", [
    {"new.weight": [1.0]}, {"optimizer_state": [1.0]}, {"projection.weight": [1.0]},
    {"projection.weight": {-1: 1.0}}, {"projection.weight": {8: 1.0}},
    {"projection.weight": {True: 1.0}}, {"projection.weight": {"0": 1.0}},
    {"projection.weight": {0: math.inf}}, {"projection.weight": {0: math.nan}},
    {"projection.weight": {0: True}}, {"projection.weight": {0: "1.0"}},
    {"projection.weight": {0: 10**400}},
])
def test_invalid_delta_names_coordinates_types_shapes_and_values_are_rejected(deltas):
    round_spec, _ = setup_round()
    with pytest.raises(ValueError):
        update(round_spec, "worker-a", deltas)


@pytest.mark.parametrize("name", ["optimizer_state", "optimizer.exp_avg", "adam.weight", "progress",
    "provenance", "metadata.bias", "qualified", "applied_proof_feedback_ids", "decoded_embeddings"])
def test_nonparameter_state_cannot_be_whitelisted(name):
    with pytest.raises(ValueError, match="cannot be parameters"):
        ParameterSpec(name, (1,), "float64")


@pytest.mark.parametrize("steps", [0, -1, 6, True, 1.5])
def test_local_step_bounds_and_local_dataset_identity_are_checked(steps):
    round_spec, _ = setup_round()
    with pytest.raises(ValueError, match="local_steps"):
        update(round_spec, "worker-a", {}, local_steps=steps)
    with pytest.raises(ValueError, match="local-data"):
        make_client_update(round_spec, "worker-a", {}, local_steps=1, local_data_sha256="e" * 64)


def test_round_input_lists_and_client_update_constructor_have_no_mutable_aliases():
    shape = [8]
    spec = ParameterSpec("weight", shape, "float64")
    shape[0] = 384
    assert spec.shape == (8,)
    round_spec, base = setup_round()
    first = update(round_spec, "worker-a", {"projection.weight": {0: 2.0}})
    raw = [["projection.weight", [[0, 2.0]]]]
    direct = replace(first, _delta_rows=raw)
    raw[0][1][0][1] = 42.0
    assert direct.deltas["projection.weight"][0] == 2.0
    assert direct == first


def test_unsafe_mutated_update_values_and_duplicate_coordinates_are_revalidated():
    round_spec, base = setup_round()
    bad = update(round_spec, "worker-a", {"projection.weight": {0: 2.0}})
    object.__setattr__(bad, "_delta_rows", (("projection.weight", ((0, math.nan),)),))
    with pytest.raises(ValueError, match="finite"):
        aggregate_round(round_spec, base, [bad, update(round_spec, "worker-b", {})])
    bad = update(round_spec, "worker-a", {})
    object.__setattr__(bad, "_delta_rows", (("projection.weight", ((0, 2.0), (0, 3.0))),))
    with pytest.raises(ValueError, match="noncanonical"):
        aggregate_round(round_spec, base, [bad, update(round_spec, "worker-b", {})])


def test_float32_rounds_once_to_declared_dtype_and_rejects_nonfinite_casts():
    round_spec, base = setup_round(dtype="float32", counts=(1, 1))
    candidate = aggregate_round(round_spec, base, [
        update(round_spec, "worker-a", {"projection.weight": {0: 0.1}}),
        update(round_spec, "worker-b", {})])
    cast = lambda value: struct.unpack("<f", struct.pack("<f", value))[0]
    assert candidate.parameters["projection.weight"][0] == cast(10.0 + cast(0.1) / 2)
    with pytest.raises(ValueError, match="overflow"):
        update(round_spec, "worker-a", {"projection.weight": {0: 1e100}})


def test_candidate_constructor_owns_rows_and_boundary_validation_checks_numeric_commitment():
    round_spec, base = setup_round()
    candidate = aggregate_round(round_spec, base, [update(round_spec, "worker-a", {}),
                                                  update(round_spec, "worker-b", {})])
    assert replace(candidate) == candidate
    mutable_rows = [[name, list(values)] for name, values in candidate._parameter_rows]
    owned = replace(candidate, _parameter_rows=mutable_rows)
    mutable_rows[0][1][0] = 123.0
    assert owned == candidate
    object.__setattr__(candidate, "_parameter_rows", tuple(
        (name, (123.0,) + values[1:]) for name, values in candidate._parameter_rows))
    with pytest.raises(ValueError, match="parameter commitment"):
        replace(candidate)


@pytest.mark.parametrize("mutation", ["authority", "unknown", "parent", "counts", "round", "updates"])
def test_closed_candidate_provenance_rejects_forged_authority_and_inconsistent_evidence(mutation):
    round_spec, base = setup_round()
    candidate = aggregate_round(round_spec, base, [update(round_spec, "worker-a", {}),
                                                  update(round_spec, "worker-b", {})])
    forged = candidate.provenance
    if mutation == "authority":
        forged["qualified"] = True
    elif mutation == "unknown":
        forged["optimizer_state"] = {}
    elif mutation == "parent":
        forged["parent_checkpoint_sha256"] = "e" * 64
    elif mutation == "counts":
        forged["updates"][0]["sample_count"] = 100
    elif mutation == "round":
        forged["round"]["parameters"][0]["dtype"] = "float32"
    else:
        forged["updates"].reverse()
    raw = json.dumps(forged, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                     allow_nan=False).encode("ascii")
    with pytest.raises(ValueError):
        AggregateCandidate(candidate._parameter_rows, raw, hashlib.sha256(raw).hexdigest())


def test_candidate_rejects_noncanonical_json_even_with_matching_file_hash():
    round_spec, base = setup_round()
    candidate = aggregate_round(round_spec, base, [update(round_spec, "worker-a", {}),
                                                  update(round_spec, "worker-b", {})])
    raw = json.dumps(candidate.provenance, indent=2).encode()
    with pytest.raises(ValueError, match="bytes or digest"):
        AggregateCandidate(candidate._parameter_rows, raw, hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("dtype,expected", [
    ("float32", "62cdab024fa7ae3fe8963a9f5dd5edf0994ad26de43ba4841965d5933b6b9bc1"),
    ("float64", "6dcd95ba31ad4aa5275bd7b1bcae594cc6f61e7577cae8367af57b85173408cc"),
])
def test_binary_parameter_commitment_v1_known_vectors(dtype, expected):
    assert parameter_digest([ParameterSpec("weight", (2,), dtype)], {"weight": [-0.0, 1.5]}) == expected


def test_binary_update_commitment_v1_known_vector_and_signed_zero():
    item = ClientUpdate("a" * 64, "b" * 64, "c" * 64, "d" * 64, "worker-a", "e" * 64, 2,
                        (("weight", ((0, -0.0), (2, 1.5))),))
    assert item.update_sha256 == "2c40cb3f7e6a00fd6bd766d2b3102e912a66c27480cc5f9f65480a0a15dea64d"
    assert replace(item, _delta_rows=(("weight", ((0, 0.0), (2, 1.5))),)).update_sha256 != item.update_sha256


def test_large_weight_and_delta_commitments_stream_without_numeric_json(monkeypatch):
    original_raw = federated._raw
    def metadata_only(value):
        def check(item):
            if type(item) is dict:
                assert not {"values_le_hex", "deltas", "coordinates"} & set(item)
                for nested in item.values():
                    check(nested)
            elif type(item) in (list, tuple):
                for nested in item:
                    check(nested)
        check(value)
        return original_raw(value)
    monkeypatch.setattr(federated, "_raw", metadata_only)
    specs = [ParameterSpec("weight", (8201,), "float64")]
    base = {"weight": [float(index) for index in range(8201)]}
    round_spec, _ = setup_round()
    round_spec = replace(round_spec, parameters=specs,
                         base_parameters_sha256=parameter_digest(specs, base))
    updates = [update(round_spec, "worker-a", {"weight": [1.5] * 8201}),
               update(round_spec, "worker-b", {"weight": {8192: -0.5}})]
    expected_parameters_sha = round_spec.base_parameters_sha256
    expected_updates_sha = [item.update_sha256 for item in updates]
    # Chunk boundaries are purely operational and never affect wire identity.
    monkeypatch.setattr(federated, "_HASH_CHUNK_COORDINATES", 31)
    assert parameter_digest(specs, base) == expected_parameters_sha
    assert [item.update_sha256 for item in updates] == expected_updates_sha
    candidate = aggregate_round(round_spec, base, updates)
    assert candidate.parameters["weight"][0] == 0.375
    assert candidate.parameters["weight"][8192] == 8192.0
    assert candidate.parameters["weight"][8200] == 8200.375
