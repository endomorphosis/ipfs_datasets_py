"""Bind a fitted affine boundary to an unchanged dual-donor initialization.

The caller admits all four complete files by their externally supplied byte
hashes before calling this object-level inspector. Content consistency is not
producer authentication, numerical replay, teacher qualification or permission
to distill. Inspection imports only the standard library.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import struct


SCHEMA = "gte-aligned-decoder-handoff/v1"
FILE_PIN_FIELDS = {"initialization_sha256", "bridge_checkpoint_sha256", "plan_sha256", "fit_report_sha256"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TRUE_REPORT = {"analytic_alignment_fit_executed", "primary_input_boundary_fitted",
    "original_initialization_unchanged", "inherited_decoder_weights_unchanged",
    "fitted_bridge_reloaded_exactly", "donor_transform_applied_by_decoder_only"}
_FALSE_REPORT = {"auxiliary_connector_fitted", "validation_used_for_fit",
    "adapter_outputs_normalized", "encoder_numerics_verified", "source_vectors_producer_verified",
    "student_vectors_producer_verified", "source_fidelity_qualified", "teacher_qualified",
    "distillation_executed", "student_decoder_gradient_training_executed", "proof_authority"}
_REPORT_FIELDS = {"schema", "initialization_sha256", "plan_sha256", "bridge_weights_sha256",
    "bridge_checkpoint_sha256", "initialization_representation_id", "aligned_representation_id",
    "donor_pins", "source_profile_id", "train_rows_sha256", "validation_rows_sha256",
    "plan_content_sha256", "pair_coverage_status", "missing_eligible_pair_receipts", "selection",
    "optimizer_steps", *_TRUE_REPORT, *_FALSE_REPORT}
_SELECTION_FIELDS = {"schema", "candidates", "candidate_count", "selected_regularization",
    "selected_weights_sha256", "selection_policy", "tie_break_policy", "train_rows",
    "validation_rows", "validation_used_for_fit", "refit_with_validation", "test_or_canary_used",
    "optimizer_steps"}
_CANDIDATE_FIELDS = {"regularization", "weights_sha256", "train_metrics", "validation_metrics",
    "diagnostics", "objective", "objective_residual_reduction", "exported_training_objective"}
_METRIC_FIELDS = {"schema", "status", "reason", "rows", "input_dimension", "output_dimension",
    "prediction_dtype", "metric_accumulation_dtype", "coordinate_mse", "mean_squared_l2",
    "min_squared_l2", "max_squared_l2", "cosine_error_mean", "cosine_error_max",
    "cosine_available_rows", "cosine_unavailable_rows", "adapter_outputs_normalized"}
_DIAGNOSTIC_FIELDS = {"solver", "solve_dtype", "export_dtype", "device", "numerical_threads",
    "training_rows", "system_dimension", "centered_rank_upper_bound", "exact_rank",
    "rank_estimation_performed", "solve_relative_residual", "max_solve_relative_residual",
    "solver_numerics_passed"}
_OBJECTIVE = "sum_squared_l2_residual_plus_lambda_frobenius_weight_squared"


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_aligned_contract_" + name,
                                                Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the aligned-decoder contract dependency")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_REUSE = _helper("gte_decoder_reuse")
_ALIGNMENT = _helper("gte_alignment_contract")
_BRIDGE = _helper("gte_affine_bridge")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == fields, "closed " + label + " required")


def _hash(value, label):
    _require(type(value) is str and _SHA.fullmatch(value) is not None,
             "full lowercase " + label + " SHA256 required")


def _count(value, label, maximum=4096):
    _require(type(value) is int and 0 <= value <= maximum, "bounded integer " + label + " required")


def _number(value, label, *, minimum=0., maximum=None):
    _require(type(value) in (int, float), "finite numeric " + label + " required")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise ValueError("finite numeric " + label + " required") from None
    _require(math.isfinite(number) and number >= minimum
             and (maximum is None or number <= maximum), "finite bounded " + label + " required")
    return number


def _file_digest_binding(value):
    """Match the previous CLI's *identity* convention, not arbitrary file bytes."""
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


def _exact_float32(value, label):
    if type(value) is list:
        for child in value:
            _exact_float32(child, label)
        return
    # Torch float32 .tolist() emits JSON floats. Integer JSON leaves would
    # round-trip to different serialized content even when numerically exact.
    _require(type(value) is float, label + " must contain serialized float32 values")
    try:
        number = float(value)
        restored = struct.unpack("!f", struct.pack("!f", number))[0]
    except (OverflowError, ValueError, struct.error):
        raise ValueError(label + " exceeds finite float32 range") from None
    _require(math.isfinite(number) and math.isfinite(restored) and restored == number,
             label + " is not exact finite float32 serialization")


def _inspect_bridge(bridge, initialization, pins):
    _closed(bridge, _BRIDGE._FIELDS, "fitted bridge")
    _require(bridge["schema"] == _BRIDGE.SCHEMA and bridge["architecture"] == _BRIDGE.ARCHITECTURE,
             "fitted bridge schema or architecture differs")
    _require(type(bridge["input_dimension"]) is int and bridge["input_dimension"] == 768
             and type(bridge["output_dimension"]) is int and bridge["output_dimension"] == 384,
             "exact fitted bridge dimensions required")
    _BRIDGE._seed(bridge["seed"])
    expected = {"domain_id": "legal_ir", "teacher_runtime_id": "legal_ir:source_training_v2",
        "source_representation_id": _BRIDGE.SOURCE_REPRESENTATION_ID,
        "student_representation_id": _BRIDGE.STUDENT_REPRESENTATION_ID,
        "teacher_checkpoint_sha256": pins["teacher384_checkpoint_sha256"]}
    _BRIDGE._bindings(**expected)
    _require(all(bridge[name] == value for name, value in expected.items()), "fitted bridge donor/profile differs")
    _require(all(bridge[name] is False for name in _BRIDGE.FLAGS), "bridge cannot grant qualification or authority")
    transform = _BRIDGE.validate_input_transform(bridge["input_transform"])
    _require(transform == initialization["primary"]["input_transform"]
             and bridge["input_transform_sha256"] == _BRIDGE.digest(transform),
             "fitted bridge and inherited donor transform differ")
    state = bridge["model_state"]
    _BRIDGE._validate_state(state)
    for values in state.values():
        _exact_float32(values, "fitted bridge state")
    _hash(bridge["weights_sha256"], "bridge weights")
    _require(bridge["weights_sha256"] == _BRIDGE.digest(state), "fitted bridge weights digest differs")
    identity = _BRIDGE.adapted_representation_id(**{name: bridge[name] for name in (
        "weights_sha256", "teacher_checkpoint_sha256", "input_transform_sha256",
        "student_representation_id", "source_representation_id")})
    _require(bridge["adapted_representation_id"] == identity, "fitted bridge derived identity differs")
    _require(len(_BRIDGE._raw(bridge)) <= _BRIDGE.MAX_CHECKPOINT_BYTES, "fitted bridge exceeds byte bound")


def _metrics(value, rows, label):
    _closed(value, _METRIC_FIELDS, label + " metrics")
    _require(value["schema"] == "gte-affine-alignment-metrics/v1", label + " metrics schema differs")
    for name in ("rows", "cosine_available_rows", "cosine_unavailable_rows"):
        _count(value[name], label + " " + name)
    _require(value["rows"] == rows and value["cosine_available_rows"] + value["cosine_unavailable_rows"] == rows,
             label + " metrics row accounting differs")
    _require(type(value["input_dimension"]) is int and value["input_dimension"] == 768
             and type(value["output_dimension"]) is int and value["output_dimension"] == 384
             and value["prediction_dtype"] == "float32" and value["metric_accumulation_dtype"] == "float64"
             and value["adapter_outputs_normalized"] is False, label + " metric convention differs")
    squared = ("coordinate_mse", "mean_squared_l2", "min_squared_l2", "max_squared_l2")
    cosine = ("cosine_error_mean", "cosine_error_max")
    if rows == 0:
        _require(value["status"] == "unavailable" and value["reason"] == "no_rows"
                 and all(value[name] is None for name in (*squared, *cosine)),
                 "empty validation metrics must be unavailable")
        return
    _require(value["status"] == "available" and value["reason"] is None, label + " metrics must be available")
    for name in squared:
        _number(value[name], label + " " + name)
    _require(value["min_squared_l2"] <= value["mean_squared_l2"] <= value["max_squared_l2"]
             and math.isclose(value["coordinate_mse"] * 384, value["mean_squared_l2"], rel_tol=1e-12, abs_tol=1e-12),
             label + " metric reductions differ")
    if value["cosine_available_rows"]:
        for name in cosine:
            _number(value[name], label + " " + name, maximum=2.)
        _require(value["cosine_error_mean"] <= value["cosine_error_max"], label + " cosine reductions differ")
    else:
        _require(all(value[name] is None for name in cosine), label + " zero predictions have unavailable cosine")


def _diagnostics(value, rows):
    _closed(value, _DIAGNOSTIC_FIELDS, "candidate diagnostics")
    for name in ("training_rows", "system_dimension", "centered_rank_upper_bound", "numerical_threads"):
        _count(value[name], "diagnostic " + name)
    dual = rows < 768
    _require(value["solver"] == ("centered_dual" if dual else "centered_primal")
             and value["system_dimension"] == (rows if dual else 768)
             and value["centered_rank_upper_bound"] == min(rows - 1, 768)
             and value["training_rows"] == rows and value["numerical_threads"] == 1,
             "candidate solve geometry or row count differs")
    _require(value["solve_dtype"] == "float64" and value["export_dtype"] == "float32"
             and value["device"] == "cpu" and value["exact_rank"] is None
             and value["rank_estimation_performed"] is False and value["solver_numerics_passed"] is True,
             "candidate solve convention or evidence differs")
    _number(value["solve_relative_residual"], "solve relative residual", maximum=1e-6)
    _require(type(value["max_solve_relative_residual"]) in (int, float)
             and value["max_solve_relative_residual"] == 1e-6, "candidate solve acceptance threshold differs")


def _selection(selection, plan, bridge):
    _closed(selection, _SELECTION_FIELDS, "alignment selection")
    _require(selection["schema"] == "gte-affine-alignment-selection/v1", "alignment selection schema differs")
    for name in ("candidate_count", "train_rows", "validation_rows", "optimizer_steps"):
        _count(selection[name], "selection " + name)
    train_rows, validation_rows = len(plan["train_rows"]), len(plan["validation_rows"])
    candidates = selection["candidates"]
    _require(type(candidates) is list and len(candidates) == len(plan["regularization_candidates"])
             and selection["candidate_count"] == len(candidates)
             and selection["train_rows"] == train_rows and selection["validation_rows"] == validation_rows,
             "selection candidates or row accounting differs")
    _require(selection["selection_policy"] == plan["selection_policy"]
             and selection["tie_break_policy"] == "smaller_regularization"
             and selection["validation_used_for_fit"] is False and selection["refit_with_validation"] is False
             and selection["test_or_canary_used"] is False and selection["optimizer_steps"] == 0,
             "selection must retain train-only fitting and separate validation")
    for entry, regularization in zip(candidates, plan["regularization_candidates"]):
        _closed(entry, _CANDIDATE_FIELDS, "alignment candidate")
        _number(entry["regularization"], "regularization", minimum=1e-8, maximum=1e6)
        _require(entry["regularization"] == regularization, "selection grid differs from plan")
        _hash(entry["weights_sha256"], "candidate weights")
        _require(entry["objective"] == _OBJECTIVE and entry["objective_residual_reduction"] == "sum",
                 "candidate ridge objective differs")
        _number(entry["exported_training_objective"], "exported training objective")
        _metrics(entry["train_metrics"], train_rows, "train")
        _metrics(entry["validation_metrics"], validation_rows, "validation")
        _diagnostics(entry["diagnostics"], train_rows)
    if validation_rows:
        chosen = min(candidates, key=lambda entry: (entry["validation_metrics"]["mean_squared_l2"], entry["regularization"]))
    else:
        _require(len(candidates) == 1 and plan["selection_policy"] == "fixed_candidate_no_validation",
                 "a regularization grid needs separate validation")
        chosen = candidates[0]
    _number(selection["selected_regularization"], "selected regularization", minimum=1e-8, maximum=1e6)
    _require(selection["selected_regularization"] == chosen["regularization"]
             and selection["selected_weights_sha256"] == chosen["weights_sha256"] == bridge["weights_sha256"],
             "selected bridge is not the declared validation winner")
    weight_norm = math.fsum(float(number) ** 2 for row in bridge["model_state"]["weight"] for number in row)
    objective = chosen["train_metrics"]["mean_squared_l2"] * train_rows + chosen["regularization"] * weight_norm
    _require(math.isfinite(objective) and math.isclose(objective, chosen["exported_training_objective"],
             rel_tol=1e-10, abs_tol=1e-10), "selected bridge and exported ridge objective differ")
    return chosen


def inspect_alignment_handoff(initialization, bridge, plan, fit_report, *,
                              expected_file_pins, expected_donor_pins):
    """Inspect pinned file objects without reconstructing their original bytes.

    The external file pins are admitted by the caller, not authenticated here.
    Unavailable preparation runs have no fitted handoff and must not call this
    function with fabricated placeholders. The original initialization remains
    a separate immutable ancestor of the later aligned generation.
    """
    _closed(expected_file_pins, FILE_PIN_FIELDS, "external handoff file pins")
    for name, value in expected_file_pins.items():
        _hash(value, name)
    _REUSE._pins(expected_donor_pins)
    inventory = _REUSE.inspect_dual_decoder(initialization, expected_donor_pins=expected_donor_pins)
    for state in (initialization["primary"]["model_state"], initialization["legacy8"]["model_state"],
                  initialization["connector"]):
        for values in state.values():
            _exact_float32(values, "inherited initialization state")
    plan_inspection = _ALIGNMENT.inspect_alignment_plan(plan)
    _require(plan_inspection["fit_ready"] is True and plan["domain_id"] == "legal_ir",
             "ready Legal paired alignment plan required")
    _require(plan["source_vector_space_id"] == _BRIDGE.SOURCE_REPRESENTATION_ID
             and plan["student_profile_id"] == initialization["source_profile_id"] == _BRIDGE.STUDENT_REPRESENTATION_ID,
             "alignment coordinates differ from inherited donor or student profile")
    _inspect_bridge(bridge, initialization, expected_donor_pins)
    _closed(fit_report, _REPORT_FIELDS, "alignment fit report")
    _require(fit_report["schema"] == "gte-affine-alignment-fit/v1", "alignment fit report schema differs")
    for name in ("initialization_sha256", "plan_sha256", "bridge_checkpoint_sha256"):
        _require(fit_report[name] == expected_file_pins[name], "fit report external file binding differs: " + name)
    _require(fit_report["donor_pins"] == expected_donor_pins
             and fit_report["initialization_representation_id"] == initialization["representation_id"]
             and fit_report["bridge_weights_sha256"] == bridge["weights_sha256"]
             and fit_report["source_profile_id"] == plan["student_profile_id"],
             "fit report initialization, donor, weights or profile binding differs")
    for name in ("train_rows_sha256", "validation_rows_sha256"):
        _require(fit_report[name] == plan[name], "fit report training/validation row binding differs")
    _require(fit_report["plan_content_sha256"] == plan["plan_sha256"], "fit report plan content binding differs")
    for name in _TRUE_REPORT:
        _require(fit_report[name] is True, "fit report lacks required declaration: " + name)
    for name in _FALSE_REPORT:
        _require(fit_report[name] is False, "fit report contains unsupported evidence: " + name)
    _count(fit_report["optimizer_steps"], "fit report optimizer steps")
    _require(fit_report["optimizer_steps"] == 0, "analytic alignment must contain zero optimizer steps")
    _count(fit_report["missing_eligible_pair_receipts"], "missing eligible pair receipts", 100000)
    missing = plan["counts"]["missing_eligible_pair_receipts"]
    coverage = fit_report["pair_coverage_status"]
    _require(fit_report["missing_eligible_pair_receipts"] == missing
             and coverage in ("ready", "partial") and (not missing or coverage == "partial"),
             "fit report pair coverage differs from plan")
    chosen = _selection(fit_report["selection"], plan, bridge)
    identity_binding = {"initialization_sha256": expected_file_pins["initialization_sha256"],
        "plan_sha256": expected_file_pins["plan_sha256"], "bridge_weights_sha256": bridge["weights_sha256"]}
    aligned_id = "legal_ir:aligned_dual_decoder_768:" + _file_digest_binding(identity_binding)
    _require(fit_report["aligned_representation_id"] == aligned_id
             and aligned_id != initialization["representation_id"], "aligned generation identity differs")
    return {"schema": SCHEMA, "status": "fitted_unqualified", "file_pins": deepcopy(expected_file_pins),
        "donor_pins": deepcopy(expected_donor_pins), "initialization_representation_id": initialization["representation_id"],
        "aligned_representation_id": aligned_id, "bridge_weights_sha256": bridge["weights_sha256"],
        "adapted_representation_id": bridge["adapted_representation_id"], "plan_content_sha256": plan["plan_sha256"],
        "train_rows_sha256": plan["train_rows_sha256"], "validation_rows_sha256": plan["validation_rows_sha256"],
        "source_profile_id": plan["student_profile_id"], "train_pair_count": len(plan["train_rows"]),
        "validation_pair_count": len(plan["validation_rows"]), "pair_coverage_status": coverage,
        "pair_coverage_authenticated": False,
        "missing_eligible_pair_receipts": missing, "selected_regularization": chosen["regularization"],
        "candidate_count": len(fit_report["selection"]["candidates"]),
        "copied_parameter_count": inventory["copied_parameter_count"],
        "boundary_alignment_required": True, "primary_input_boundary_fitted": True,
        "auxiliary_connector_fitted": False, "original_initialization_unchanged": True,
        "inherited_decoder_weights_unchanged": True, "encoder_numerics_verified": False,
        "teacher_qualified": False, "source_fidelity_qualified": False, "proof_authority": False,
        "distillation_executed": False, "student_decoder_gradient_training_executed": False,
        "source_vectors_producer_verified": False, "student_vectors_producer_verified": False,
        "optimizer_steps": 0}


__all__ = ["inspect_alignment_handoff", "SCHEMA", "FILE_PIN_FIELDS"]
