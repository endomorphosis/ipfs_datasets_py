"""Complete, bounded original-atom vocabularies and comparable structural loss.

No field, array index, token position, source digest or projection is filtered.
The vocabulary is fitted to training rows only. Explicit capacity overruns are
errors rather than requests to truncate. This owner does not issue native gate
or source-fidelity authority; callers must use the live validated trainer.

Common-support evaluation retains raw predicted coordinates, pads absent ones
with zero, and normalizes the target over *all* its original atoms. Its support
is the supplied complete training reference plus evaluation-only target atoms.
Those evaluation atoms never enter a fitted vocabulary. This objective differs
from the old retained-coordinate training objective and remains structural.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math

from . import autoencoder_family_training as codec

SCHEMA = "complete-original-atom-vocabulary/v1"
COMMON_SCHEMA = "common-support-native-structural-loss/v1"
DEFAULT_MAX_FEATURES = 65_536
DEFAULT_MAX_ESTIMATED_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_ATOM_BYTES = 64 * 1024 * 1024
MAX_FEATURES = 1_048_576
MAX_EVALUATION_COORDINATES = 8_388_608
MAX_EVALUATION_BYTES = 256 * 1024 * 1024
FALSE = {**codec.FALSE, "source_semantics_verified": False, "roundtrip_ok": False,
         "source_text_decoded": False, "formulas_generated": False}


class FeatureCapacityError(ValueError):
    """An exact requested representation cannot fit the caller's explicit cap."""

    def __init__(self, report):
        self.report = deepcopy(report)
        super().__init__("complete feature capacity exceeded: " + report["reason"])

    def to_dict(self):
        return deepcopy(self.report)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value, label, lower=1, upper=MAX_FEATURES):
    _require(type(value) is int and lower <= value <= upper, "bounded integer required for " + label)
    return value


def _capacity(reason, observed, maximum):
    raise FeatureCapacityError({"schema": SCHEMA, "reason": reason, "observed": observed,
        "maximum": maximum, "truncated": False, "training_permitted": False, **FALSE})


def _validate_rows(rows, *, maximum_rows=codec.MAX_ROWS):
    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= maximum_rows, "bounded nonempty atom rows required")
    for row in rows:
        _require(type(row) is dict and row, "nonempty projection atom row required")
        for name, value in row.items():
            _require(type(name) is str and 0 < len(name) <= 4096, "bounded projection identity required")
            _require(type(value) in (tuple, list) and len(value) == 2, "descriptor/atom-count pair required")
            descriptor, atoms = value
            _require(type(descriptor) is dict and type(descriptor.get("logic_family")) is str
                and descriptor["logic_family"], "explicit projection family descriptor required")
            _require(type(atoms) in (dict, Counter) and atoms, "nonempty exact atom counts required")
            _require(all(type(atom) is str and atom and type(count) is int and 0 < count <= 2**53 - 1
                for atom, count in atoms.items()), "atom counts must be positive integers over exact strings")


def estimate_feature_memory(*, features, training_rows, validation_rows, projections,
        latent_width, minibatch_size, training_nonzero_atoms):
    """Conservative tensor working-set estimate, not a hard process RSS bound.

    Includes float64 matrices, SVD work arrays, parameters, gradients, Adam
    moments, selected/proposed copies, validation predictions and minibatches.
    Python objects, imported libraries, native checker processes and allocator
    overhead require additional host headroom. Sparse figures describe storage
    opportunity only; this API does not silently change the numerical backend.
    """
    for name, value in {"features": features, "training_rows": training_rows,
            "projections": projections, "latent_width": latent_width, "minibatch_size": minibatch_size}.items():
        _integer(value, name)
    _integer(validation_rows, "validation_rows", lower=0)
    _integer(training_nonzero_atoms, "training_nonzero_atoms", lower=0, upper=MAX_EVALUATION_COORDINATES * 1024)
    rank, batch = min(training_rows, features), min(training_rows, minibatch_size)
    parameters = 2 * features * latent_width + latent_width + features
    tensor_parts = {
        "training_and_validation_matrices": 8 * features * (training_rows + validation_rows),
        "projection_masks": (training_rows + validation_rows) * projections,
        "parameters_gradients_moments_and_copies": 8 * 9 * parameters,
        "svd_input_output_and_working_estimate": 8 * (2 * training_rows * features + rank * features + rank * training_rows + rank * rank),
        "minibatch_working_estimate": 8 * 6 * batch * features,
        "validation_prediction_working_estimate": 8 * 2 * validation_rows * features,
    }
    dense_bytes = sum(tensor_parts.values())
    sparse_parts = {
        "training_csr_float64_int64": 16 * training_nonzero_atoms + 8 * (training_rows + 1),
        "validation_csr_worst_case": 16 * validation_rows * features + 8 * (validation_rows + 1),
    }
    return {"schema": "complete-feature-memory-estimate/v1", "dense_estimated_bytes": dense_bytes,
        "dense_components": tensor_parts, "sparse_matrix_estimated_bytes": sum(sparse_parts.values()),
        "sparse_components": sparse_parts, "features": features, "training_rows": training_rows,
        "validation_rows": validation_rows, "projections": projections, "latent_width": latent_width,
        "minibatch_size": minibatch_size, "dtype": "float64", "backend_changed": False,
        "includes_python_or_native_process_rss": False, "hard_rss_bound": False}


def guard_inference_memory(*, features, rows, projections, latent_width,
        max_estimated_bytes=DEFAULT_MAX_ESTIMATED_BYTES):
    """Reject an oversized inference tensor plan before matrix allocation.

    Covers decoded float64 parameters, input/output/temporary dense matrices,
    latent intermediates and masks. It excludes checkpoint JSON/Python objects,
    imports and allocator overhead, and is not a process RSS limit.
    """
    for name, value in {"features": features, "rows": rows, "projections": projections,
            "latent_width": latent_width}.items():
        _integer(value, name)
    _integer(max_estimated_bytes, "max_estimated_bytes", upper=64 * 1024**3)
    parameters = 2 * features * latent_width + latent_width + features
    parts = {"float64_parameters": 8 * parameters,
        "input_output_and_temporary_matrices": 8 * 4 * rows * features,
        "latent_intermediates": 8 * 3 * rows * latent_width,
        "projection_masks": rows * projections}
    total = sum(parts.values())
    if total > max_estimated_bytes:
        _capacity("max_inference_estimated_bytes", total, max_estimated_bytes)
    return {"schema": "complete-feature-inference-memory-estimate/v1",
        "estimated_bytes": total, "components": parts, "max_estimated_bytes": max_estimated_bytes,
        "includes_python_or_native_process_rss": False, "hard_rss_bound": False,
        "backend_changed": False}


def build_complete_space(domain_id, training_reports, training_rows, *, validation_rows,
        latent_width, minibatch_size, max_features=DEFAULT_MAX_FEATURES,
        max_estimated_bytes=DEFAULT_MAX_ESTIMATED_BYTES, max_atom_bytes=DEFAULT_MAX_ATOM_BYTES):
    """Return the existing matrix owner's space shape with every training atom.

    ``training_rows`` must be the original owner's ``_atoms`` counters prepared
    from these reports by the live validated trainer. This numerical boundary
    authenticates their exact correspondence again, without granting native
    validation authority. Validation supplies only a row *count* for budgeting.
    """
    _integer(max_features, "max_features")
    _integer(max_estimated_bytes, "max_estimated_bytes", upper=64 * 1024**3)
    _integer(max_atom_bytes, "max_atom_bytes", upper=1024**3)
    _integer(validation_rows, "validation_rows", lower=0, upper=codec.MAX_ROWS)
    _integer(latent_width, "latent_width", upper=64)
    _integer(minibatch_size, "minibatch_size", upper=codec.MAX_ROWS)
    _require(type(domain_id) is str and domain_id, "explicit domain required")
    _validate_rows(training_rows)
    _require(type(training_reports) in (list, tuple) and len(training_reports) == len(training_rows),
        "training report/atom row count differs")
    descriptors, tokens, unique_count, atom_bytes, nonzero = {}, {}, 0, 0, 0
    for report, row in zip(training_reports, training_rows):
        _require(type(report) is dict and report.get("domain_id") == domain_id,
            "training report domain differs")
        projections = report.get("projections")
        _require(type(projections) is list and len(projections) == len(row), "complete original projection rows required")
        names = [target.get("projection_id") for target in projections]
        _require(len(set(names)) == len(names) and set(names) == set(row), "emitted projection identities differ")
        for target in projections:
            name = target["projection_id"]
            _require(target.get("ready_for_training") is True, "blocked projection cannot enter a complete feature head")
            expected_descriptor = {key: target.get(key) for key in
                ("logic_family", "profile", "representation_kind", "producer_id")}
            descriptor, atoms = row[name]
            _require(descriptor == expected_descriptor, "original projection descriptor differs")
            _require(atoms == Counter(codec._atoms(target["payload"])), "original payload atoms were omitted or altered")
            _require(name not in descriptors or descriptors[name] == descriptor, "native projection semantics changed")
            descriptors[name] = deepcopy(descriptor)
            vocabulary = tokens.setdefault(name, set())
            nonzero += len(atoms)
            for atom in atoms:
                if atom in vocabulary:
                    continue
                unique_count += 1
                if unique_count > max_features:
                    _capacity("max_features", unique_count, max_features)
                atom_bytes += len(codec._raw([name, atom]))
                if atom_bytes > max_atom_bytes:
                    _capacity("max_atom_bytes", atom_bytes, max_atom_bytes)
                vocabulary.add(atom)
    memory = estimate_feature_memory(features=unique_count, training_rows=len(training_rows),
        validation_rows=validation_rows, projections=len(descriptors), latent_width=latent_width,
        minibatch_size=minibatch_size, training_nonzero_atoms=nonzero)
    # Serialized vocabulary bytes are included in this estimate separately from
    # tensor storage; runtime object and allocator overhead still need headroom.
    estimated_total = memory["dense_estimated_bytes"] + atom_bytes
    if estimated_total > max_estimated_bytes:
        _capacity("max_estimated_bytes", estimated_total, max_estimated_bytes)
    columns = [[name, atom] for name in sorted(tokens) for atom in sorted(tokens[name])]
    counts = {name: len(value) for name, value in sorted(tokens.items())}
    result = {"domain_id": domain_id, "projections": descriptors, "columns": columns,
        "training_sources": sorted(report["source_digest"] for report in training_reports),
        "training_split_keys": sorted(set().union(*(codec._split_keys(report) for report in training_reports))),
        "training_reports_sha256": codec._digest(training_reports),
        "feature_selection": {"method": "complete_training_only_original_atoms", "schema": SCHEMA,
            "available_atoms": counts, "retained_atoms": dict(counts), "discarded_atoms": 0,
            "all_original_atom_fields_and_positions_retained": True,
            "validation_or_test_atoms_used_for_fitting": False,
            "limits": {"max_features": max_features, "max_estimated_bytes": max_estimated_bytes,
                "max_atom_bytes": max_atom_bytes}, "serialized_atom_bytes": atom_bytes,
            "estimated_total_bytes": estimated_total, "memory_estimate": memory},
        "normalization": "log1p_l2_per_native_projection", **codec.FALSE}
    return result


def _space_columns(space):
    _require(type(space) is dict and type(space.get("domain_id")) is str
        and type(space.get("projections")) is dict and space["projections"], "explicit structural feature space required")
    columns = space.get("columns")
    _require(type(columns) is list and 1 <= len(columns) <= MAX_FEATURES, "bounded nonempty feature columns required")
    _require(all(type(pair) is list and len(pair) == 2 and all(type(item) is str for item in pair)
        and pair[0] in space["projections"] and pair[1] for pair in columns), "invalid feature columns")
    _require(columns == sorted(columns) and len({tuple(pair) for pair in columns}) == len(columns),
        "feature columns must be unique and canonical")
    by_projection = {name: {} for name in space["projections"]}
    for offset, (name, atom) in enumerate(columns):
        by_projection[name][atom] = offset
    _require(all(by_projection.values()), "each fitted projection requires feature coordinates")
    return by_projection


def common_support_metrics(space, prediction, rows, *, reference_space,
        max_coordinates=MAX_EVALUATION_COORDINATES, max_atom_bytes=MAX_EVALUATION_BYTES):
    """Score untouched predicted coordinates against full target-atom support.

    The mandatory reference is a complete *training-only* space shared by every
    compared model. Evaluation-only atoms enlarge only this scoring support.
    Raw predictions are never rescaled using targets or secretly renormalized.
    Missing coordinates predict zero; model coordinates with zero target remain
    false positives. The full target is log1p/L2 normalized, including OOV atoms.
    Every supplied projection participates in its macro-family loss.
    """
    _integer(max_coordinates, "max_coordinates", upper=MAX_EVALUATION_COORDINATES)
    _integer(max_atom_bytes, "max_atom_bytes", upper=1024**3)
    _validate_rows(rows)
    model = _space_columns(space)
    reference = _space_columns(reference_space)
    _require(space["domain_id"] == reference_space["domain_id"], "reference domain differs")
    _require(set(model) == set(reference) and space["projections"] == reference_space["projections"],
        "compared models require the same complete projection descriptors")
    _require(reference_space.get("feature_selection", {}).get("method") == "complete_training_only_original_atoms",
        "complete training-only reference space required")
    _require(all(set(model[name]) <= set(reference[name]) for name in model),
        "model coordinates are outside the common training reference")
    width = len(space["columns"])
    if len(rows) * width > max_coordinates:
        _capacity("max_prediction_coordinates", len(rows) * width, max_coordinates)
    if type(prediction) not in (list, tuple):
        import torch
        _require(type(prediction) is torch.Tensor and prediction.device.type == "cpu"
            and prediction.ndim == 2 and tuple(prediction.shape) == (len(rows), width),
            "bounded exact-shape CPU prediction tensor required")
        prediction = prediction.detach().tolist()
    _require(type(prediction) in (list, tuple) and len(prediction) == len(rows), "prediction row count differs")
    _require(all(type(values) in (list, tuple) and len(values) == width
        and all(type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1e100 for value in values) for values in prediction),
        "finite bounded exact-width raw predictions required")
    support = {name: set(atoms) for name, atoms in reference.items()}
    for row in rows:
        _require(set(row) <= set(model), "evaluation contains an unexpected projection")
        for name, (descriptor, atoms) in row.items():
            _require(descriptor == space["projections"][name], "evaluation projection descriptor differs")
            support[name].update(atoms)
    coordinates = sum(len(atoms) for atoms in support.values()) * len(rows)
    if coordinates > max_coordinates:
        _capacity("max_evaluation_coordinates", coordinates, max_coordinates)
    atom_bytes = sum(len(codec._raw([name, atom])) for name, atoms in support.items() for atom in atoms)
    if atom_bytes > max_atom_bytes:
        _capacity("max_evaluation_atom_bytes", atom_bytes, max_atom_bytes)
    by_projection, coverage = {}, []
    family_values = {}
    absent_by_row = [{"row": index, "projection_ids": sorted(set(model) - set(row))}
        for index, row in enumerate(rows)]
    absent_entire_batch = []
    for name in sorted(model):
        losses, mses, cosines = [], [], []
        for index, row in enumerate(rows):
            if name not in row:
                continue  # Missing projection is masked, never a zero target.
            _, atoms = row[name]
            target_values = {atom: math.log1p(count) for atom, count in atoms.items()}
            target_norm = math.sqrt(math.fsum(value * value for value in target_values.values()))
            _require(target_norm > 0, "nonzero full target required")
            expected = {atom: value / target_norm for atom, value in target_values.items()}
            predicted = {atom: float(prediction[index][offset]) for atom, offset in model[name].items()}
            prediction_norm = math.sqrt(math.fsum(value * value for value in predicted.values()))
            dot = math.fsum(value * expected.get(atom, 0.) for atom, value in predicted.items())
            squared_error = math.fsum((predicted.get(atom, 0.) - expected.get(atom, 0.)) ** 2 for atom in support[name])
            mse = squared_error / len(support[name])
            cosine = 1. - dot / max(prediction_norm, 1e-8)
            loss = mse + .1 * cosine
            _require(all(math.isfinite(value) for value in (mse, cosine, loss)), "nonfinite common-support loss")
            losses.append(loss); mses.append(mse); cosines.append(cosine)
            known = set(atoms) & set(model[name])
            missing = set(atoms) - set(model[name])
            reference_oov = set(atoms) - set(reference[name])
            coverage.append({"row": index, "projection_id": name,
                "known_atom_occurrences": sum(atoms[atom] for atom in known),
                "missing_atom_occurrences": sum(atoms[atom] for atom in missing),
                "known_distinct_atoms": len(known), "missing_distinct_atoms": len(missing),
                "unseen_training_distinct_atoms": len(reference_oov),
                "unknown_target_squared_mass": math.fsum(expected[atom] ** 2 for atom in missing),
                "target_coordinates": len(atoms), "common_support_coordinates": len(support[name]),
                "all_target_atoms_scored": True, "missing_coordinates_predicted_zero": True,
                "unknown_atoms_claimed_reconstructed": False})
        if not losses:
            absent_entire_batch.append(name)
            continue
        family = space["projections"][name]["logic_family"]
        value = math.fsum(losses) / len(losses)
        by_projection[name] = {"objective": value, "mse": math.fsum(mses) / len(mses),
            "cosine_loss": math.fsum(cosines) / len(cosines), "rows": len(losses),
            "support_coordinates": len(support[name]), "logic_family": family}
        family_values.setdefault(family, []).append(value)
    families = {name: math.fsum(values) / len(values) for name, values in family_values.items()}
    return {"schema": COMMON_SCHEMA, "domain_id": space["domain_id"],
        "objective": math.fsum(families.values()) / len(families), "families": families,
        "projections": by_projection, "coverage": {"projections": coverage,
            "all_emitted_projections_have_loss": True, "all_target_atoms_scored": True,
            "no_unknown_atoms_claimed_reconstructed": True,
            "emitted_projection_occurrences": sum(len(row) for row in rows),
            "absent_projections_by_row": absent_by_row,
            "absent_projection_ids": absent_entire_batch,
            "missing_projections_are_masked_not_zero_targets": True},
        "reference_training_columns_sha256": codec._digest(reference_space["columns"]),
        "evaluation_support_sha256": codec._digest([[name, sorted(atoms)] for name, atoms in sorted(support.items())]),
        "target_normalization": "log1p_l2_over_all_original_target_atoms",
        "prediction_mapping": "raw_coordinates_unchanged_zero_extended_without_target_dependent_scaling",
        "objective_scope": "masked_macro_family_common_support_structural_reconstruction",
        "different_from_retained_coordinate_training_objective": True,
        "evaluation_atoms_added_to_fitted_vocabulary": False, "full_semantic_fidelity_established": False,
        "evaluation_coordinates": coordinates, "evaluation_atom_bytes": atom_bytes, **FALSE}


__all__ = ["SCHEMA", "COMMON_SCHEMA", "FeatureCapacityError", "build_complete_space",
    "estimate_feature_memory", "guard_inference_memory", "common_support_metrics"]
