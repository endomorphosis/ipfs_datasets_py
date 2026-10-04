"""One-factorization ridge path for the unchanged fixed-schema source decoder.

Only the fitting algorithm changes: one symmetric eigendecomposition of the
smaller primal/dual Gram matrix serves every ridge and every scalar class.
Target schemas, frozen Legal projections, validation selection and inference
remain owned by structured_source_384. Grouped fitting reuses the existing
closed-row, source, embedding and caller-declared leakage-group audit.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path
import time

from . import grouped_source_training_384 as grouped
from . import structured_source_384 as structured

SCHEMA = "grouped-structured-source-ridge-path-384/v1"
TRAINER_ID = "structured-source-shared-eigen-ridge-path-384/v1"
shared, native, legal = structured.shared, structured.native, structured.legal
_require, _raw, digest = structured._require, structured._raw, structured.digest


def _pins():
    return {"trainer_id": TRAINER_ID,
        "trainer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "inherited_grouped_recipe": grouped._pins()}


def _ridge_path(np, data, targets):
    """Factor once; return coefficients for W=(X'X+ridge I)^-1 X'Y.

    Inputs are already normalized/centered by the original training helpers.
    This operation has no validation inputs. Small negative eigenvalues from
    floating point roundoff are clipped with a dimension/spectrum-scaled
    tolerance; materially negative or nonfinite spectra are rejected.
    """
    _require(isinstance(data, np.ndarray) and isinstance(targets, np.ndarray)
        and data.ndim == targets.ndim == 2 and 1 <= len(data) <= 2048
        and data.shape[1] == structured.DIMENSION and targets.shape[0] == len(data)
        and 1 <= targets.shape[1] <= 4096
        and data.dtype == targets.dtype == np.dtype("float64")
        and bool(np.isfinite(data).all()) and bool(np.isfinite(targets).all()),
        "finite bounded float64 ridge matrices required")
    started = time.monotonic()
    primal = len(data) >= data.shape[1]
    gram = data.T @ data if primal else data @ data.T
    _require(bool(np.isfinite(gram).all()), "nonfinite ridge Gram matrix")
    gram_seconds = time.monotonic() - started
    started = time.monotonic()
    values, vectors = np.linalg.eigh(gram)
    factorization_seconds = time.monotonic() - started
    dimension = len(gram)
    _require(values.shape == (dimension,) and vectors.shape == gram.shape
        and bool(np.isfinite(values).all()) and bool(np.isfinite(vectors).all()),
        "nonfinite or invalid ridge eigendecomposition")
    spectral_scale = max(1., float(np.max(np.abs(values))))
    tolerance = 64. * np.finfo(np.float64).eps * dimension * spectral_scale
    minimum = float(values.min())
    _require(minimum >= -tolerance, "materially negative eigenvalue in positive semidefinite Gram matrix")
    clipped = int((values < 0).sum())
    values = np.maximum(values, 0.)
    started = time.monotonic()
    left = vectors if primal else data.T @ vectors
    right = vectors.T @ (data.T @ targets) if primal else vectors.T @ targets
    _require(bool(np.isfinite(left).all()) and bool(np.isfinite(right).all()),
        "nonfinite ridge path transform")
    preparation_seconds = time.monotonic() - started
    return (left, values, right), {"factorizations": 1,
        "factorization_method": "symmetric_eigendecomposition",
        "factorization_form": "primal" if primal else "dual",
        "factorization_dimension": dimension, "training_matrix_shape": list(data.shape),
        "scalar_class_count": targets.shape[1], "gram_seconds": gram_seconds,
        "factorization_seconds": factorization_seconds,
        "ridge_path_preparation_seconds": preparation_seconds,
        "minimum_raw_eigenvalue": minimum, "negative_eigenvalue_tolerance": tolerance,
        "roundoff_negative_eigenvalues_clipped": clipped,
        "minimum_supported_ridge": 16. * tolerance,
        "ridge_stability_policy": "ridge_must_exceed_16_times_Gram_eigenvalue_roundoff_tolerance",
        "factorization_reused_across_ridges_and_classes": True,
        "objective": "sum_squared_centered_class_residuals_plus_ridge_times_squared_weight_norm"}


def _weights(np, path, ridge):
    _require(type(ridge) in (int, float) and math.isfinite(ridge) and 0 < ridge <= 100,
        "finite positive bounded ridge required")
    left, values, right = path
    # The original ridge grid permits values arbitrarily close to zero. Such
    # values can amplify the numerically nonzero Gram nullspace into finite
    # but meaningless weights. Reject this unsupported conditioning regime;
    # clipping negative roundoff alone is insufficient. The normal default
    # grid remains comfortably above this dimension/spectrum-scaled bound.
    floor = 1024. * np.finfo(np.float64).eps * len(values) * max(1., float(values.max()))
    _require(ridge > floor, "ridge is too small for stable Gram eigenvalue resolution")
    weights = (left / (values + float(ridge))[None, :]) @ right
    _require(bool(np.isfinite(weights).all()), "nonfinite learned decoder weights")
    return weights


def _config(config):
    options = {"ridges": list(structured.RIDGES),
        "embedding_provenance": {"model_id": "caller_supplied", "verified_by_runtime": False}}
    _require(config is None or type(config) is dict and set(config) <= set(options),
        "unknown structured training option")
    options.update(deepcopy(config or {}))
    _require(type(options["ridges"]) is list and 1 <= len(options["ridges"]) <= 16
        and all(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 100 for value in options["ridges"])
        and options["ridges"] == sorted(set(options["ridges"])), "finite increasing positive ridge grid required")
    _require(type(options["embedding_provenance"]) is dict and len(_raw(options["embedding_provenance"])) <= 16384,
        "bounded embedding provenance required")
    return options


def train(domain, training_rows, validation_rows, *, parent_projection, config=None):
    """Fit all scalar classes with one training-only factorization.

    Returns the original checkpoint schema, so existing runtime loaders and
    inference paths consume it unchanged. This trainer's identity is explicit
    in training metadata; inference implementation pins retain their meaning.
    """
    started, pins = time.monotonic(), _pins()
    options = _config(config)
    def direct_rows(rows, split):
        _require(type(rows) is list and all(type(row) is dict and set(row) == set(grouped.DECODER_FIELDS) for row in rows),
            "closed domain row schema required")
        # Direct callers have no declared semantic groups. Use one internal
        # audit group per split solely to reuse exact source/numeric identity
        # checks (including int/float and signed-zero aliases). These labels
        # are discarded before fitting and make no semantic grouping claim.
        augmented = [{**row, "group_id": "direct-" + split, "split": split} for row in rows]
        prepared, _, inventory = grouped._prepare(domain, augmented, split)
        return prepared, inventory
    training, training_inventory = direct_rows(training_rows, "train")
    validation, validation_inventory = direct_rows(validation_rows, "validation")
    grouped._exclude(training_inventory, validation_inventory)
    return _train_prepared(domain, training, validation, parent_projection=parent_projection,
        options=options, pins=pins, started=started)


def _train_prepared(domain, training, validation, *, parent_projection, options, pins, started):
    """Internal numerical core; both public entry points audit before dispatch.

    Prepared rows contain only original decoder fields. This is deliberately
    private: callers have no public parameter for bypassing identity audits.
    Native semantic, parent, target-schema and numerical checks remain here.
    """
    grouped.api._preflight_source_targets(domain, training, validation)
    parent, parent_sha, parent_file = shared._parent(parent_projection)
    with native._cpu():
        legal.validate_checkpoint(parent)
    _require(parent["binding"]["dimension"] == structured.DIMENSION and parent["progress"]["optimizer_steps"] > 0,
        "trained 384D Legal parent required")
    projection, schema = structured._projection(parent), structured._fit_schema(training)
    with structured._numeric() as np:
        train_targets, _ = structured._targets(np, training, schema)
        _, validation_ids = structured._targets(np, validation, schema)
        train_x, transform = structured._normalize(np, structured._project(np, training, projection))
        validation_x, _ = structured._normalize(np, structured._project(np, validation, projection), transform)
        bias = train_targets.mean(0)
        centered_targets = train_targets - bias
        initial = structured._score(domain, np.zeros((len(validation), train_targets.shape[1])), validation, validation_ids, schema)
        fit_started = time.monotonic()
        path, diagnostics = _ridge_path(np, train_x, centered_targets)
        selected, best_rank, history = None, None, []
        validation_seconds = solve_seconds = 0.
        for ridge in options["ridges"]:
            tick = time.monotonic()
            weights = _weights(np, path, ridge)
            solve_seconds += time.monotonic() - tick
            tick = time.monotonic()
            observed = structured._score(domain, validation_x @ weights + bias, validation, validation_ids, schema)
            validation_seconds += time.monotonic() - tick
            rank = (observed["exact_targets"], observed["semantic_leaf_correct"])
            chosen = best_rank is None or rank > best_rank
            history.append({"ridge": ridge, **observed, "selected_at_step": chosen})
            if chosen:
                selected, best_rank, best_weights, best = ridge, rank, weights.copy(), observed
        elapsed = time.monotonic() - fit_started
        state = {"weights": best_weights.tolist(), "bias": bias.tolist()}
        metrics = {"trainer_id": TRAINER_ID, "trainer_sha256": pins["trainer_sha256"],
            "selected_ridge": selected, "selected_validation": best, "initial_zero_head_validation": initial,
            "history": history, **diagnostics, "ridge_candidates": len(options["ridges"]),
            "ridge_path_solve_seconds": solve_seconds, "validation_seconds": validation_seconds,
            "fit_seconds": elapsed, "fit_seconds_scope": "Gram_factorization_all_ridge_weights_and_validation",
            "unique_training_examples": len(training), "fit_unique_examples_per_second": len(training) / max(elapsed, 1e-9),
            "pre_checkpoint_seconds": time.monotonic() - started, "test_used_for_selection": False,
            "selection": "free_running_exact_then_variable_leaf_accuracy_first_ridge_on_ties",
            "optimizer_steps": 0, "gradient_training_used": False}
    checkpoint = {"schema": structured.SCHEMA, "domain_id": domain, "dimension": structured.DIMENSION,
        "implementation": structured._implementation(), "config": options, "parent_sha256": parent_sha,
        "parent_binding": deepcopy(parent["binding"]), "projection_width": parent["config"]["projection_width"],
        "projection_state": projection, "projection_sha256": digest(projection), "input_transform": transform,
        "target_schema": schema, "head_state": state, "head_sha256": digest(state),
        "training_manifest": structured._manifest(training), "validation_manifest": structured._manifest(validation),
        "training": metrics, "lineage": {"parent_encoder_frozen": True,
            "projection_tensors_inherited_exactly": list(structured.PROJECTION_KEYS), "parent_modified": False,
            "random_parameters_used": False}, **structured.FALSE}
    _require(len(_raw(checkpoint)) <= structured.MAX_BYTES, "checkpoint exceeds bound")
    if parent_file:
        _require(parent_file[0].read_bytes() == parent_file[1], "parent changed during training")
    structured.Runtime(checkpoint)
    _require(pins == _pins(), "ridge path producer changed during fitting")
    metrics.update(full_fit_seconds=time.monotonic() - started,
        full_fit_seconds_scope="native_preflight_parent_validation_feature_preparation_ridge_path_selection_checkpoint_runtime_validation")
    _require(len(_raw(checkpoint)) <= structured.MAX_BYTES, "checkpoint exceeds bound")
    return {"checkpoint": checkpoint, "metrics": deepcopy(metrics)}


def train_grouped_source_decoder_384(domain, training_rows, validation_rows, *, parent_projection, config=None):
    """Audit original grouped rows, then fit the unchanged decoder format."""
    started, pins = time.monotonic(), _pins()
    audit_started = time.monotonic()
    training, train_bindings, train_inventory = grouped._prepare(domain, training_rows, "train")
    validation, validation_bindings, validation_inventory = grouped._prepare(domain, validation_rows, "validation")
    grouped._exclude(train_inventory, validation_inventory)
    audit_seconds = time.monotonic() - audit_started
    fit_started = time.monotonic()
    result = _train_prepared(domain, training, validation, parent_projection=parent_projection,
        options=_config(config), pins=pins, started=fit_started)
    fit_seconds = time.monotonic() - fit_started
    _require(pins == _pins(), "ridge path producer changed during grouped fitting")
    checkpoint, metrics = result["checkpoint"], result["metrics"]
    recipe = {"schema": SCHEMA, "domain_id": domain, "producer": pins,
        "checkpoint_schema": checkpoint["schema"], "checkpoint_sha256": digest(checkpoint),
        "parent_sha256": checkpoint["parent_sha256"], "config_sha256": digest(checkpoint["config"]),
        "training_bindings": train_bindings, "validation_bindings": validation_bindings,
        "training_inventory": train_inventory, "validation_inventory": validation_inventory,
        "bindings_sha256": digest({"train": train_bindings, "validation": validation_bindings}),
        "grouping_policy": "caller_declared_indivisible_leakage_groups_not_target_equivalence",
        "automatic_semantic_grouping_performed": False,
        "normalization_policy": "casefold_and_whitespace_for_conservative_leakage_exclusion",
        "group_or_split_metadata_used_as_features": False, "test_used_for_selection": False, **shared.FALSE}
    group_count = len(train_inventory["group_id"])
    report = {"schema": SCHEMA, "recipe": recipe, "recipe_sha256": digest(recipe),
        "training_variant_count": len(training), "training_unique_group_count": group_count,
        "validation_variant_count": len(validation), "validation_unique_group_count": len(validation_inventory["group_id"]),
        "public_fit_seconds": fit_seconds, "recipe_pre_report_seconds": time.monotonic() - started,
        "training_variants_per_public_fit_second": len(training) / max(fit_seconds, 1e-9),
        "training_groups_per_public_fit_second": group_count / max(fit_seconds, 1e-9),
        "throughput_scope": "post_group_audit_fit_including_native_preflight_parent_validation_tuning_and_checkpoint",
        "training_validation_audit_seconds": audit_seconds, "input_audit_passes_per_split": 1,
        "includes_embedding_generation": False, "independent_semantic_examples_estimated": False,
        "checkpoint_format_modified": False, **shared.FALSE}
    complete_seconds = time.monotonic() - started
    report.update(complete_recipe_seconds=complete_seconds,
        complete_recipe_training_variants_per_second=len(training) / max(complete_seconds, 1e-9),
        complete_recipe_training_groups_per_second=group_count / max(complete_seconds, 1e-9),
        complete_recipe_seconds_scope="entry_through_input_audit_fitting_runtime_validation_and_sidecar_construction")
    return {"checkpoint": checkpoint, "metrics": metrics, "report": report}


__all__ = ["SCHEMA", "TRAINER_ID", "train", "train_grouped_source_decoder_384"]
