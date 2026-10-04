"""Frozen source384 projection endpoints, excluding target-assisted readouts.

The residual branch needs the original input skip connection. Its narrow
activation is not a complete compressed representation of that input. This
profile loads the original thirteen tensors through the preserved replay
architecture; it does not admit the current full source-decoder runtime.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from .alignment_baseline import _digest, _raw
from .alignment_study import _bounded_bytes, _observed_binding

PLAN_SCHEMA = "alignment-source384-representation-plan/v1"
SCHEMA = "alignment-source384-representations/v1"
PROFILE = "frozen-source384-projection-endpoints/cpu-float32/v1"
ENDPOINTS = {"residual_branch_8": 8, "residual_projection_384": 384, "formula_condition_32": 32}
FALSE = dict.fromkeys(("qualified", "proof_authority", "source_fidelity_established",
    "context_semantics_applied", "context_resolution_executed", "training_executed",
    "query_reference_consumed", "sample_memory_used", "target_safety_projection_used",
    "formula_generation_executed", "parser_features_consumed", "runtime_cryptographically_attested"), False)
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_checkpoint_representations.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/gte_bridge_teacher.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/gte_worker_contract.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/gte_migration_inventory.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_transfer_replay.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_latent_formula.py",
)
_LOADED_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _seal(value):
    value["payload_sha256"] = _digest(value)
    return value


def _integrity(value):
    _require(type(value) is dict and value.get("payload_sha256") == _digest(
        {k: v for k, v in value.items() if k != "payload_sha256"}), "representation payload digest differs")
    _require(all(value.get(key) is False for key in FALSE), "representation cannot acquire authority or target access")


def _repository():
    return Path(__file__).resolve().parents[4]


def _sources():
    root = _repository()
    return [_observed_binding(root, {"path": name, "sha256": hashlib.sha256(
        _bounded_bytes(root / name, 8 * 1024 * 1024)).hexdigest()}) for name in _SOURCE_FILES]


def _owner_inputs(inputs, lane):
    from .alignment_richer_embeddings import (
        validate_embedding_lane,
        validate_richer_embedding_inputs,
    )

    validate_richer_embedding_inputs(inputs)
    validate_embedding_lane(lane, inputs)
    _require(len(inputs["rows"]) == 34 and lane["lane_id"] == "native384"
             and lane["dimension"] == 384, "fixed 34-row native384 source lane required")
    _require(lane["status"] in ("produced", "diagnostic_fixture", "unavailable"), "complete, fixture or unavailable lane required")


def _checkpoint(path, expected, preserved):
    from .gte_bridge_teacher import _IO, inspect_teacher

    teacher = inspect_teacher(path, expected_sha256=expected, repository_root=preserved)
    checkpoint, _ = _IO.read_pinned_json(Path(path), expected_sha256=expected,
                                         max_bytes=48 * 1024 * 1024)
    _require(checkpoint["config"]["projection_width"] == 8
             and checkpoint["config"]["hidden_size"] == 32, "selected endpoint geometry differs")
    return checkpoint, teacher


def prepare_source384_representation_plan(inputs, raw_lane, *, checkpoint_path,
        expected_checkpoint_sha256, preserved_repository_root):
    """Admit original serialized weights and listed archived sources before Torch."""
    from .gte_bridge_teacher import _source_pins

    _owner_inputs(inputs, raw_lane)
    checkpoint, teacher = _checkpoint(checkpoint_path, expected_checkpoint_sha256, preserved_repository_root)
    if raw_lane["status"] == "produced":
        _require(raw_lane["backend_evidence"]["profile_id"] == teacher["source_representation_id"],
                 "checkpoint and observed source backbone profiles differ")
    current = _repository()
    drift = []
    for name, expected in sorted(_source_pins(checkpoint).items()):
        actual = hashlib.sha256(_bounded_bytes(current / name, 8 * 1024 * 1024)).hexdigest()
        if actual != expected:
            drift.append({"path": name, "checkpoint_sha256": expected, "current_sha256": actual})
    vectors = {r["id"]: r for r in raw_lane["receipts"]}
    source_hashes = {r["source_sha256"] for r in inputs["rows"]}
    normalized_hashes = {hashlib.sha256(" ".join(r["source_text"].casefold().split()).encode()).hexdigest()
                         for r in inputs["rows"]}
    overlap = {}
    for split in ("training_manifest", "validation_manifest"):
        overlap[split] = {"source_sha256_overlap_count": len(source_hashes & {r["source_sha256"] for r in checkpoint[split]}),
            "normalized_source_sha256_overlap_count": len(normalized_hashes & {r["normalized_source_sha256"] for r in checkpoint[split]}),
            "embedding_sha256_overlap_count": len({r["embedding_sha256"] for r in vectors.values()} &
                                                    {r["embedding_sha256"] for r in checkpoint[split]}),
            "declared_manifest_rows": len(checkpoint[split])}
    return _seal({"schema": PLAN_SCHEMA, "profile_id": PROFILE, "native_input_dimension": 384,
        "endpoint_dimensions": dict(ENDPOINTS), "input_manifest_sha256": inputs["payload_sha256"],
        "raw_lane_sha256": raw_lane["payload_sha256"], "checkpoint_path": str(Path(checkpoint_path).absolute()),
        "expected_checkpoint_sha256": expected_checkpoint_sha256,
        "preserved_repository_root": str(Path(preserved_repository_root).absolute()), "teacher_binding": teacher,
        "executing_source_bindings": _sources(), "current_full_decoder_source_drift": drift,
        "current_full_decoder_admitted": False, "full_decoder_loader_attempted": False,
        "input_recipe": "saved_exact_source_gte384_vector_without_context_or_parser",
        "endpoint_recipe": "x=(raw-mean)/scale;b=tanh(down(x));p=x+up(b);c=tanh(condition(p))",
        "branch_is_complete_compressed_input": False, "split_overlap": overlap,
        "split_independence_authenticated": False, "original_training_corpus_read": False, **FALSE})


def validate_source384_representation_plan(plan, inputs, raw_lane):
    _integrity(plan)
    expected = prepare_source384_representation_plan(inputs, raw_lane,
        checkpoint_path=plan["checkpoint_path"], expected_checkpoint_sha256=plan["expected_checkpoint_sha256"],
        preserved_repository_root=plan["preserved_repository_root"])
    _require(_raw(plan) == _raw(expected), "representation plan differs from exact source/checkpoint replay")
    return {"status": "validated_integrity_only", "plan_sha256": plan["payload_sha256"], **FALSE}


def _endpoint(values, dimension):
    _require(type(values) is list and len(values) == dimension
             and all(type(v) is float and math.isfinite(v) for v in values), "finite declared endpoint vector required")
    return {"dimension": dimension, "values": values, "values_sha256": _digest(values), "norm": math.hypot(*values)}


def _receipt(row, native, endpoints):
    return {"id": row["id"], "input_sha256": row["input_sha256"], "source_sha256": row["source_sha256"],
        "context_role": row["context_role"], "context_forwarded": False,
        "input_embedding_sha256": native["embedding_sha256"], "status": "represented",
        "endpoints": {key: _endpoint(endpoints[key], dimension) for key, dimension in ENDPOINTS.items()}}


def _result(plan, raw_lane, rows, evidence, status):
    return _seal({"schema": SCHEMA, "profile_id": PROFILE, "native_input_dimension": 384,
        "endpoint_dimensions": dict(ENDPOINTS), "status": status, "plan": plan, "raw_lane": raw_lane,
        "rows": rows, "row_count": len(rows), "execution_evidence": evidence,
        "model_inference_executed": status == "produced", "endpoint_inference_executed": status == "produced",
        "diagnostic_fixture": status == "diagnostic_fixture", **FALSE})


def diagnostic_source384_representations(plan, inputs, raw_lane, endpoint_values):
    """Pure marked fixtures; never claim numerical model execution."""
    validate_source384_representation_plan(plan, inputs, raw_lane)
    _require(raw_lane["status"] == "diagnostic_fixture", "only explicit diagnostic owner receipts accepted")
    native = {r["id"]: r for r in raw_lane["receipts"]}
    _require(set(endpoint_values) == set(native), "fixture endpoints must cover all inputs")
    rows = [_receipt(row, native[row["id"]], endpoint_values[row["id"]]) for row in inputs["rows"]]
    result = _result(plan, raw_lane, rows, {"kind": "injected_fixture", "model_loaded": False}, "diagnostic_fixture")
    validate_source384_representations(result, inputs)
    return result


def extract_source384_representations(plan, inputs, raw_lane):
    """Execute only projection/conditioning layers; no prefixes, GRU or targets."""
    validate_source384_representation_plan(plan, inputs, raw_lane)
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _LOADED_SHA,
             "representation implementation changed after import")
    if raw_lane["status"] == "unavailable":
        return _result(plan, raw_lane, [], {"kind": "not_executed", "model_loaded": False}, "unavailable")
    _require(raw_lane["status"] == "produced", "actual extraction requires observed native source vectors")
    from ....optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
    from .gte_decoder_transfer_replay import (
        _exact_float32,
        _numerical_context,
        _original_primary_model,
        digest,
    )

    checkpoint, _ = _checkpoint(plan["checkpoint_path"], plan["expected_checkpoint_sha256"], plan["preserved_repository_root"])
    for tensor in checkpoint["model_state"].values():
        _exact_float32(tensor)
    # Only the numerical module's unchanged checkpoint pin governs this
    # projection-only route; the mismatched UI decoder is never executed.
    from .gte_bridge_teacher import _source_pins

    numerical_path = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_latent_formula.py"
    _require(hashlib.sha256(Path(numerical.__file__).read_bytes()).hexdigest() == _source_pins(checkpoint)[numerical_path],
             "numerical projection source differs from preserved donor")
    import torch

    with _numerical_context(torch), torch.inference_mode():
        _require(torch.get_default_device().type == "cpu" and torch.get_default_dtype() == torch.float32,
                 "CPU float32 construction defaults required")
        model = _original_primary_model(torch, checkpoint)
        parity = numerical._model({"dimension": 384}, checkpoint["codec"], checkpoint["config"])
        parity.to(device="cpu", dtype=torch.float32)
        parity.load_state_dict({name: torch.tensor(value, dtype=torch.float32)
                               for name, value in checkpoint["model_state"].items()}, strict=True)
        parity.eval()
        for parameter in parity.parameters():
            parameter.requires_grad_(False)
        before = digest({name: value.tolist() for name, value in model.state_dict().items()})
        _require(before == checkpoint["weights_sha256"], "loaded tensors differ from donor")
        native = {row["id"]: row for row in raw_lane["receipts"]}
        rows, parity_max_error = [], 0.0
        for row in inputs["rows"]:
            receipt = native[row["id"]]
            raw = torch.tensor([receipt["embedding"]], dtype=torch.float32)
            x = (raw - model.input_mean) / model.input_scale
            branch = torch.tanh(model.projection_down(x))
            projected = x + model.projection_up(branch)
            condition = torch.tanh(model.condition(projected))
            expected_projected = parity.project(x)
            expected_condition = parity.start(expected_projected)[0]
            _require(torch.equal(projected, expected_projected) and torch.equal(condition, expected_condition),
                     "independent original/numerical layer equations differ")
            values = {"residual_branch_8": branch[0].tolist(), "residual_projection_384": projected[0].tolist(),
                      "formula_condition_32": condition[0].tolist()}
            rows.append(_receipt(row, receipt, values))
        after = digest({name: value.tolist() for name, value in model.state_dict().items()})
        _require(before == after and all(p.grad is None for m in (model, parity) for p in m.parameters()),
                 "extraction changed donor tensors or created gradients")
        evidence = {"kind": "observed_checkpoint_projection", "model_loaded": True, "device": "cpu",
            "dtype": "float32", "cpu_threads": 1, "row_batch_size": 1, "eval_mode": True,
            "gradient_mode": "inference_mode", "tensor_count": len(model.state_dict()),
            "parameter_count": sum(p.numel() for p in model.parameters()), "before_weights_sha256": before,
            "after_weights_sha256": after, "projection_condition_parity_bitwise_equal": True,
            "parity_rows": len(rows), "parity_max_abs_error": parity_max_error,
            "gru_calls": 0, "formula_token_calls": 0, "source_encoder_calls": 0}
    validate_source384_representation_plan(plan, inputs, raw_lane)
    result = _result(plan, raw_lane, rows, evidence, "produced")
    validate_source384_representations(result, inputs)
    return result


def validate_source384_representations(result, inputs, raw_lane=None, *, plan=None):
    """Check unchanged receipt linkage and scope without executing a model."""
    _integrity(result)
    plan = result["plan"] if plan is None else plan
    raw_lane = result["raw_lane"] if raw_lane is None else raw_lane
    validate_source384_representation_plan(plan, inputs, raw_lane)
    _require(_raw(result["plan"]) == _raw(plan) and _raw(result["raw_lane"]) == _raw(raw_lane),
             "representation result binds another input generation")
    _require(result["schema"] == SCHEMA and result["profile_id"] == PROFILE
             and type(result["native_input_dimension"]) is int and result["native_input_dimension"] == 384
             and _raw(result["endpoint_dimensions"]) == _raw(ENDPOINTS), "representation profile or widths differ")
    status = result["status"]
    _require(status in ("produced", "diagnostic_fixture", "unavailable"), "invalid representation availability")
    _require(result["model_inference_executed"] is (status == "produced")
             and result["endpoint_inference_executed"] is (status == "produced")
             and result["diagnostic_fixture"] is (status == "diagnostic_fixture"), "representation execution flags differ")
    evidence = result["execution_evidence"]
    if status == "produced":
        required = {"kind": "observed_checkpoint_projection", "model_loaded": True, "device": "cpu",
            "dtype": "float32", "cpu_threads": 1, "row_batch_size": 1, "eval_mode": True,
            "gradient_mode": "inference_mode", "tensor_count": 13, "parameter_count": 25224,
            "before_weights_sha256": plan["teacher_binding"]["weights_sha256"],
            "after_weights_sha256": plan["teacher_binding"]["weights_sha256"],
            "projection_condition_parity_bitwise_equal": True, "parity_rows": 34, "parity_max_abs_error": 0.0,
            "gru_calls": 0, "formula_token_calls": 0, "source_encoder_calls": 0}
        _require(raw_lane["status"] == "produced" and _raw(evidence) == _raw(required), "native extraction evidence differs")
    else:
        expected = {"kind": "injected_fixture" if status == "diagnostic_fixture" else "not_executed", "model_loaded": False}
        _require(raw_lane["status"] == status and _raw(evidence) == _raw(expected), "fixture/unavailable cannot claim model evidence")
    _require(type(result["rows"]) is list and type(result["row_count"]) is int
             and result["row_count"] == len(result["rows"]) == (0 if status == "unavailable" else 34), "representation row count differs")
    lookup = {r["id"]: r for r in raw_lane["receipts"]}
    for receipt, row in zip(result["rows"], inputs["rows"], strict=status != "unavailable"):
        _require(set(receipt["endpoints"]) == set(ENDPOINTS), "exact endpoint set required")
        values = {}
        for key, dimension in ENDPOINTS.items():
            endpoint = receipt["endpoints"][key]
            values[key] = endpoint["values"]
            _require(_raw(endpoint) == _raw(_endpoint(endpoint["values"], dimension)), "endpoint geometry/digest/norm differs")
            if dimension in (8, 32):
                _require(all(abs(v) <= 1. for v in endpoint["values"]), "tanh endpoint exceeds declared range")
        _require(_raw(receipt) == _raw(_receipt(row, lookup[row["id"]], values)), "source/endpoint receipt differs")
    expected_keys = set(_result(plan, raw_lane, [], evidence, status))
    _require(set(result) == expected_keys, "closed representation result required")
    return {"status": "validated_integrity_only", "payload_sha256": result["payload_sha256"],
        "row_count": result["row_count"], "native_input_dimension": 384, "endpoint_dimensions": dict(ENDPOINTS),
        "independent_output_replay": False, **FALSE}
