"""Complete-vocabulary native structural heads; a separate v6 artifact lineage.

Every original structural atom in training is retained, within explicit feature,
byte and estimated-memory bounds. All live native gates and family nonregression
criteria are inherited unchanged. This does not learn a source-text decoder,
change an older checkpoint, increase context windows or grant proof authority.
"""
from __future__ import annotations

import json
from pathlib import Path
import time

from . import autoencoder_family_training as codec
from . import autoencoder_family_training_prepared as prepared
from . import autoencoder_family_training_validated_v5 as previous
from . import autoencoder_family_complete_vocab as complete
from . import autoencoder_family_adaptive_refinement as adaptive
from ...logic.formalization.autoencoder import family_training_v7 as native
from ...logic.formalization.autoencoder import projection_validation_contract_v5 as policy

SCHEMA = "validated-complete-native-family-autoencoder/v6"
FALSE = dict(codec.FALSE)
EPS = prepared.EPS
_require, _raw, _sha, _digest = codec._require, codec._raw, codec._sha, codec._digest
_forward = prepared._forward
_panel, _reports, _loss_coverage = previous._panel, previous._reports, previous._loss_coverage


def _implementation():
    return {"inherited_live_gates": previous._implementation(),
        "complete_features": _sha(Path(complete.__file__).read_bytes()),
        "adaptive_refinement": _sha(Path(adaptive.__file__).read_bytes()),
        "trainer": _sha(Path(__file__).read_bytes())}


_IMPORTED_IMPLEMENTATION = _implementation()


def _verify_implementation():
    _require(_implementation() == _IMPORTED_IMPLEMENTATION,
             "complete numerical producer changed since import")
    previous._verify_implementation()
    return dict(_IMPORTED_IMPLEMENTATION)


def _read(descriptor):
    import torch
    _require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"}
             and descriptor["schema"] == SCHEMA, "closed validated checkpoint descriptor required")
    _verify_implementation()
    path = Path(descriptor["path"])
    _require(path.is_absolute() and path.is_file() and not path.is_symlink()
             and path.stat().st_size <= codec.MAX_BYTES, "bounded regular checkpoint required")
    raw = path.read_bytes()
    _require(_sha(raw) == descriptor["sha256"], "validated checkpoint digest differs")
    saved = json.loads(raw)
    _require(type(saved) is dict and set(saved) ==
        {"schema", "implementation", "space", "parameters", "report", *FALSE}
        and saved["schema"] == SCHEMA and saved["implementation"] == _implementation(),
        "validated checkpoint schema or source producer differs")
    _require(all(saved[key] is False and saved["space"][key] is False
        and saved["report"][key] is False for key in FALSE), "feature checkpoints cannot grant authority")
    space, report = saved["space"], saved["report"]
    _require(report["schema"] == SCHEMA and report["domain_id"] == space["domain_id"],
             "checkpoint report domain differs")
    _require(report["policy_sha256"] == _digest(policy.domain_projection_policy(space["domain_id"])),
             "projection policy changed")
    codec._validate_producer_pins(space["producer_pins"])
    columns = space["columns"]
    _require(type(columns) is list and 1 <= len(columns) <= adaptive.MAX_FEATURES
        and columns == sorted(columns) and len({tuple(c) for c in columns}) == len(columns)
        and all(type(c) is list and len(c) == 2 and c[0] in space["projections"] and type(c[1]) is str for c in columns),
        "invalid fitted feature columns")
    width, latent = len(columns), report["latent_width"]
    _require(type(latent) is int and 1 <= latent <= 64, "invalid latent width")
    selection = space["feature_selection"]
    counts = {name: sum(column[0] == name for column in columns) for name in space["projections"]}
    _require(selection["method"] == "complete_training_only_original_atoms"
        and selection["available_atoms"] == selection["retained_atoms"] == counts,
        "complete checkpoint feature accounting differs")
    adaptive.validate_settings(epochs=report["epochs_requested"], latent_width=latent, **report["settings"])
    _require(width <= report["settings"]["max_features"], "checkpoint exceeds declared feature capacity")
    complete.guard_inference_memory(features=width, rows=1, projections=len(space["projections"]),
        latent_width=latent, max_estimated_bytes=report["settings"]["memory_budget_bytes"])
    parameters = [torch.tensor(p, dtype=torch.float64) for p in saved["parameters"]]
    _require(len(parameters) == 4 and [tuple(p.shape) for p in parameters] ==
        [(width, latent), (latent,), (latent, width), (width,)]
        and all(bool(torch.isfinite(p).all()) for p in parameters), "invalid numerical tensors")
    _require(report["selected_parameters_sha256"] == _digest(saved["parameters"]),
             "saved training parameter identity differs")
    return saved, parameters


@codec._single_threaded
def train_complete_family_projection_autoencoder(training_observations, validation_observations, *,
        domain_id, output_dir, epochs=12, latent_width=16, learning_rate=.001,
        minibatch_size=32, denoising=.05, ridge=.001, patience=4, seed=1729, max_seconds=120,
        adaptive_learning_rate=False, plateau_patience=3, plateau_factor=.5,
        min_learning_rate_ratio=.05, max_features=65536,
        memory_budget_bytes=512 * 1024 * 1024):
    """Fit a complete training vocabulary after all existing live native gates.

    No projection atoms are pruned. Bounds fail before numerical allocation.
    Tuning selects independent decoder blocks; heldout targets cannot fit.
    The source-text decoder and context-window limits are unchanged.
    """
    import torch
    adaptive.validate_settings(epochs=epochs, latent_width=latent_width,
        minibatch_size=minibatch_size, patience=patience, learning_rate=learning_rate,
        denoising=denoising, ridge=ridge, seed=seed, max_seconds=max_seconds,
        memory_budget_bytes=memory_budget_bytes, max_features=max_features,
        adaptive_learning_rate=adaptive_learning_rate, plateau_patience=plateau_patience,
        plateau_factor=plateau_factor, min_learning_rate_ratio=min_learning_rate_ratio)
    call_started = time.monotonic()
    producer = _verify_implementation()
    training_reports, training_gate = _panel(training_observations, domain_id)
    validation_reports, validation_gate = _panel(validation_observations, domain_id)
    input_digest = _digest([training_reports, validation_reports])
    atoms, cache_info = prepared._atom_encoder()
    prepared._settings(epochs, latent_width, minibatch_size, patience, learning_rate, denoising, ridge, seed, max_seconds)
    output = Path(output_dir).absolute()
    _require(not output.exists() and not output.is_symlink(), "fresh validated family output required")
    domain = domain_id
    training_rows = _reports(training_reports, atoms=atoms)
    validation_rows = _reports(validation_reports, atoms=atoms)
    train_keys = set().union(*(codec._split_keys(r) for r in training_reports))
    valid_keys = set().union(*(codec._split_keys(r) for r in validation_reports))
    _require(not train_keys & valid_keys, "training/validation source leakage")
    space = complete.build_complete_space(domain, training_reports, training_rows,
        validation_rows=len(validation_rows), latent_width=latent_width, minibatch_size=minibatch_size,
        max_features=max_features, max_estimated_bytes=memory_budget_bytes)
    space["producer_pins"] = codec._producer_pins(training_reports + validation_reports)
    tensor_plan = adaptive.estimate_numerical_memory(training_rows=len(training_rows),
        validation_rows=len(validation_rows), feature_count=len(space["columns"]),
        projection_count=len(space["projections"]), latent_width=latent_width,
        minibatch_size=minibatch_size, memory_budget_bytes=memory_budget_bytes,
        max_features=max_features)
    parameter_count = 2 * len(space["columns"]) * latent_width + latent_width + len(space["columns"])
    artifact_estimate = len(_raw(space)) + 32 * parameter_count + len(_raw(training_gate)) + len(_raw(validation_gate)) + 4 * 1024 * 1024
    _require(artifact_estimate <= codec.MAX_BYTES, "complete artifact estimate exceeds serialization bound")
    parameters = None
    codec._bind_producers(space, list(training_reports) + list(validation_reports))
    training, masks, spans, train_coverage = codec._matrix(space, training_rows)
    validation, validation_mask, _, validation_coverage = codec._matrix(space, validation_rows)
    training_loss_coverage = _loss_coverage(training_rows, train_coverage)
    validation_loss_coverage = _loss_coverage(validation_rows, validation_coverage)
    _require(bool(masks.any(dim=0).all()) and bool(validation_mask.any(dim=0).all()),
             "every fitted projection requires both training and tuning observations")
    codec._validate_producer_pins(space["producer_pins"])
    started = time.monotonic()
    if parameters is None:
        mean = training.mean(dim=0)
        _, _, vectors = torch.linalg.svd(training - mean, full_matrices=False)
        basis = torch.zeros((training.shape[1], latent_width), dtype=torch.float64)
        rank = min(latent_width, len(vectors))
        basis[:, :rank] = vectors[:rank].T
        parameters = [basis, -(mean @ basis), basis.T.clone(), mean.clone()]
    initial = [p.detach().clone() for p in parameters]
    with torch.no_grad():
        initial_loss, initial_metrics = codec._objective(torch, _forward(torch, validation, initial),
            validation, validation_mask, spans, space["projections"])
    best, best_loss, after = initial, float(initial_loss), initial_metrics
    calibration = {"status": "not_run_deadline", "selected_families": [], "training_projections": []}
    if time.monotonic() - started < max_seconds:
        proposal, calibration_rows = prepared._calibrate_decoder(torch, initial, training, masks, spans, ridge)
        calibration.update(status="discarded_due_deadline", training_projections=calibration_rows, ridge=ridge,
            proposal_parameters_sha256=_digest([p.tolist() for p in proposal]))
        if time.monotonic() - started < max_seconds:
            candidate, candidate_loss, candidate_metrics, selection = prepared._select_decoder_families(torch, initial, proposal,
                validation, validation_mask, spans, space["projections"])
            if time.monotonic() - started < max_seconds:
                best, best_loss, after, calibration = candidate, candidate_loss, candidate_metrics, selection
                calibration.update(status="executed", training_projections=calibration_rows, ridge=ridge,
                    proposal_parameters_sha256=_digest([p.tolist() for p in proposal]))
            else:
                calibration["selection_discarded_due_deadline"] = True
    calibration_loss = best_loss
    preparation_seconds = time.monotonic() - call_started
    optimization_started = time.monotonic()
    refinement = adaptive.refine_decoder_blocks_adaptive(torch, best, training, masks,
        validation, validation_mask, spans, space["projections"], epochs=epochs,
        learning_rate=learning_rate, minibatch_size=minibatch_size, denoising=denoising,
        patience=patience, seed=seed, deadline=started + max_seconds,
        memory_budget_bytes=memory_budget_bytes, max_features=max_features,
        adaptive_learning_rate=adaptive_learning_rate, plateau_patience=plateau_patience,
        plateau_factor=plateau_factor, min_learning_rate_ratio=min_learning_rate_ratio)
    best, best_loss, after = refinement["parameters"], refinement["loss"], refinement["metrics"]
    history, steps = refinement["history"], refinement["steps"]
    selected_epoch, stopped = refinement["selected_epoch"], refinement["stopped"]
    refinement_diagnostics = refinement["selection_diagnostics"]
    optimization_seconds = time.monotonic() - optimization_started
    _loss_coverage(validation_rows, validation_coverage, after)
    _require(all(after["families"][family] <= value + EPS for family, value in initial_metrics["families"].items()),
             "selected family regressed against initialization")
    observed = sorted({p["logic_family"] for p in space["projections"].values()})
    state = [p.tolist() for p in best]
    report = {"schema": SCHEMA, "domain_id": domain, "latent_width": latent_width,
        "training_rows": len(training), "validation_rows": len(validation), "epochs_requested": epochs,
        "epochs_completed": len(history), "optimizer_steps": steps, "selected_epoch": selected_epoch,
        "decoder_calibration": calibration, "calibrated_validation_objective": calibration_loss,
        "training_executed": calibration["status"] in ("executed", "discarded_due_deadline") or steps > 0,
        "initialization": "training_only_deterministic_svd",
        "initial_parameters_sha256": _digest([p.tolist() for p in initial]),
        "selected_parameters_sha256": _digest(state), "parent_descriptor": None,
        "parent_modified": False, "vocabulary_scope": "original_training_only", "optimizer_state": "fresh_adam",
        "objective": "masked_macro_family_native_projection_reconstruction",
        "training_objective": "0.75_clean_plus_0.25_denoising_mse_plus_0.1_cosine" if denoising else "clean_mse_plus_0.1_cosine",
        "selection": "validation_family_block_calibration_then_complete_decoder_refinement",
        "refinement_strategy": "complete_decoder_blocks", "refinement_diagnostics": refinement_diagnostics,
        "numerical_memory_estimate": tensor_plan,
        "artifact_size_preflight": {"estimated_bytes": artifact_estimate, "maximum_bytes": codec.MAX_BYTES,
            "scope": "conservative_json_tensor_space_and_metadata_estimate; actual artifact rechecked"},
        "before": {"objective": float(initial_loss), **initial_metrics},
        "after": {"objective": best_loss, **after}, "improved": best_loss < float(initial_loss) - EPS,
        "history": history, "stopping": stopped, "elapsed_seconds": time.monotonic() - started,
        "settings": {"learning_rate": learning_rate, "denoising": denoising, "ridge": ridge,
            "minibatch_size": minibatch_size, "patience": patience, "seed": seed, "max_seconds": max_seconds,
            "adaptive_learning_rate": adaptive_learning_rate, "plateau_patience": plateau_patience,
            "plateau_factor": plateau_factor, "min_learning_rate_ratio": min_learning_rate_ratio,
            "max_features": max_features, "memory_budget_bytes": memory_budget_bytes},
        "trained_logic_families": observed if steps or calibration["status"] == "executed" else [],
        "loss_target_logic_families": observed,
        "families_without_validation": sorted(set(observed) - set(after["families"])),
        "training_coverage": train_coverage, "validation_coverage": validation_coverage,
        "effective_feature_panels": {"training": prepared._feature_panel(training, masks),
            "validation": prepared._feature_panel(validation, validation_mask)},
        "training_reports_sha256": _digest(training_reports), "validation_reports_sha256": _digest(validation_reports),
        "feature_selection": space["feature_selection"],
        "frontier": [r["frontier"] for r in list(training_reports) + list(validation_reports)],
        "source_text_decoder_trained": False, "lake_build_executed": False,
        "provider_calls": 0, "download_calls": 0, **FALSE}
    report["prepared_execution"] = {"producer": producer, "reference_schema": prepared.SCHEMA,
        "semantics": "same_masked_macro_family_objective_on_complete_training_vocabulary",
        "atom_cache": cache_info()._asdict(), "preparation_seconds": preparation_seconds,
        "optimization_seconds": optimization_seconds}
    _require(_verify_implementation() == producer, "validated producer drift during fitting")
    _require(_digest([training_reports, validation_reports]) == input_digest,
             "validated family inputs changed during fitting")
    codec._validate_producer_pins(space["producer_pins"])
    # Reauthenticate every live execution after fitting, before any artifact is written.
    final_training_gate = policy.require_projection_training_batch(training_observations,
        domain_id=domain, target_reports=training_reports)
    final_validation_gate = policy.require_projection_training_batch(validation_observations,
        domain_id=domain, target_reports=validation_reports)
    _require(final_training_gate == training_gate and final_validation_gate == validation_gate,
             "live validation evidence changed during training")
    _verify_implementation()
    report.update(policy_sha256=_digest(policy.domain_projection_policy(domain)),
        validation_policy={"training": final_training_gate, "tuning": final_validation_gate},
        loss_coverage={"training": training_loss_coverage, "tuning": validation_loss_coverage},
        training_gate_passed=True, admission_granted=False, source_semantics_verified=False,
        roundtrip_ok=False, constitution_formalized=False,
        lake_evidence_scope="all input projections; not learned reconstruction or source meaning",
        checkpoint_live_evidence_reusable=False, source_group_independence_verified=False,
        numerical_deadline_scope="initialization_calibration_refinement_excludes_input_validation_and_feature_preparation",
        whole_call_elapsed_seconds=time.monotonic() - call_started)
    package = {"schema": SCHEMA, "implementation": producer, "space": space,
        "parameters": state, "report": report, **FALSE}
    raw = _raw(package)
    _require(len(raw) <= codec.MAX_BYTES, "validated family artifact exceeds byte bound")
    output.mkdir(parents=True)
    path = output / "family_checkpoint.json"
    with path.open("xb") as stream:
        stream.write(raw)
    descriptor = {"schema": SCHEMA, "path": str(path), "sha256": _sha(raw)}
    _read(descriptor)
    return {"descriptor": descriptor, "report": report}


@codec._single_threaded
def infer_complete_family_projection_autoencoder(descriptor, observations):
    """Infer from a fresh live-gated panel; stored checkpoint receipts are not authority."""
    import torch
    saved, parameters = _read(descriptor)
    domain = saved["space"]["domain_id"]
    reports, gate = _panel(observations, domain)
    rows = _reports(reports, atoms=prepared._atom_encoder()[0])
    codec._bind_producers(saved["space"], reports)
    inference_memory = complete.guard_inference_memory(features=len(saved["space"]["columns"]),
        rows=len(rows), projections=len(saved["space"]["projections"]),
        latent_width=saved["report"]["latent_width"],
        max_estimated_bytes=saved["report"]["settings"]["memory_budget_bytes"])
    values, mask, spans, coverage = codec._matrix(saved["space"], rows)
    _loss_coverage(rows, coverage)
    with torch.no_grad():
        latent = torch.tanh(values @ parameters[0] + parameters[1])
        prediction = latent @ parameters[2] + parameters[3]
        objective, metrics = codec._objective(torch, prediction, values, mask, spans, saved["space"]["projections"])
    loss_coverage = _loss_coverage(rows, coverage, metrics)
    _require(bool(torch.isfinite(objective)) and bool(torch.isfinite(prediction).all()), "nonfinite inference")
    current_gate = policy.require_projection_training_batch(observations, domain_id=domain, target_reports=reports)
    _require(current_gate == gate, "live validation evidence changed during inference")
    _verify_implementation()
    full_support = complete.common_support_metrics(saved["space"], prediction, rows,
        reference_space=saved["space"])
    _verify_implementation()
    return {"schema": SCHEMA, "domain_id": domain, "checkpoint_sha256": descriptor["sha256"],
        "complete_support_metrics": full_support, "inference_memory_estimate": inference_memory,
        "latent": latent.tolist(), "reconstructed_features": prediction.tolist(), "objective": float(objective),
        **metrics, "coverage": coverage, "loss_coverage": loss_coverage, "validation_policy": gate,
        "formulas_generated": False, "source_text_decoded": False, "lake_build_executed": False,
        "lake_evidence_scope": "input projections, not reconstructed features", **FALSE}


def train_complete_prepared_projection_corpus(handle, *, output_dir, **options):
    """Replay the issued corpus around complete-vocabulary training."""
    from ...logic.formalization.autoencoder import training_readiness as readiness
    manifest = readiness.validate_prepared_projection_corpus(handle)
    if not manifest["strict_structural_training_allowed"]:
        raise readiness.CorpusReadinessError(manifest)
    domain, rows = readiness._ISSUED[handle]
    observations = {split: [row["observation"] for row in rows if row["split"] == split]
                    for split in ("train", "validation")}
    fitted = train_complete_family_projection_autoencoder(
        observations["train"], observations["validation"], domain_id=domain,
        output_dir=output_dir, **options)
    final = readiness.validate_prepared_projection_corpus(handle)
    _require(final == manifest, "corpus changed during complete training")
    return {**fitted, "corpus_manifest": final, "corpus_manifest_sha256": final["manifest_sha256"]}


__all__ = ["train_complete_family_projection_autoencoder", "infer_complete_family_projection_autoencoder",
    "train_complete_prepared_projection_corpus", "SCHEMA"]
