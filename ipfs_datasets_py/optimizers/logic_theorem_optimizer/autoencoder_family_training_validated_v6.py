"""Strict, source-bound numerical training on live validated native projections.

The four-tensor structural feature model and macro-family objective are the
existing prepared implementation. This separate entry requires complete native
parser/operator lowering/Lake evidence for every emitted input projection and
the fixed modality floor, including on tuning data. These checks do not prove
source semantics or teach a source-text/formula decoder. There is no checkpoint
promotion, weight download, implicit family omission or checkpoint migration.
"""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import time

from . import autoencoder_family_training as codec
from . import autoencoder_family_training_prepared as prepared
from . import autoencoder_family_decoder_refinement as decoder_refinement
from ...logic.formalization.autoencoder import family_training_v7 as native
from ...logic.formalization.autoencoder import projection_validation_contract_v6 as policy

SCHEMA = "validated-native-family-autoencoder/v6"
FALSE = dict(codec.FALSE)
EPS = prepared.EPS
_require, _raw, _sha, _digest = codec._require, codec._raw, codec._sha, codec._digest
_forward = prepared._forward


def _implementation():
    from ...logic.formalization.autoencoder import native_family_lake_v6 as native_family_lake
    return {name: _sha(Path(module.__file__).read_bytes()) for name, module in (
        ("feature_codec", codec), ("prepared_math", prepared),
        ("decoder_refinement", decoder_refinement), ("target_adapter", native),
        ("projection_policy", policy), ("native_lake_issuer", native_family_lake))} | {
            "trainer": _sha(Path(__file__).read_bytes())}


_IMPORTED_IMPLEMENTATION = _implementation()


def _verify_implementation():
    _require(_implementation() == _IMPORTED_IMPLEMENTATION,
             "validated numerical producer changed since import")
    prepared._verify_implementation()
    return dict(_IMPORTED_IMPLEMENTATION)


def _reports(reports, *, atoms):
    """All validated projections participate; no structural-ready filtering."""
    rows = []
    for report in reports:
        policy._validate_report(report)
        projections = {}
        for target in report["projections"]:
            _require(target["ready_for_training"] is True, "blocked native projection cannot enter training")
            name = target["projection_id"]
            _require(name not in projections, "duplicate native projection")
            descriptor = {key: target.get(key) for key in
                ("logic_family", "profile", "representation_kind", "producer_id")}
            projections[name] = descriptor, Counter(atoms(target["payload"]))
        _require(projections, "native source requires at least one projection")
        rows.append(projections)
    return rows


def _panel(observations, domain_id):
    _require(type(observations) in (list, tuple) and observations,
             "nonempty live validation observations required")
    _require(all(type(row) is policy.ProjectionValidationObservation for row in observations),
             "live validation observations required; stored receipts are not training authority")
    reports = [row.native_report() for row in observations]
    gate = policy.require_projection_training_batch(observations, domain_id=domain_id, target_reports=reports)
    return reports, gate


def _loss_coverage(rows, coverage, metrics=None):
    expected = {(index, name) for index, row in enumerate(rows) for name in row}
    observed = {(row["row"], row["projection_id"]) for row in coverage["projections"] if row["has_coverage"]}
    _require(not coverage["untrained_projection_ids"] and observed == expected,
             "every emitted projection requires fitted numerical loss coverage")
    counts = Counter(name for _, name in expected)
    if metrics is not None:
        _require(set(metrics["projections"]) == set(counts) and all(
            metrics["projections"][name]["rows"] == count for name, count in counts.items()),
            "loss metrics omit a validated projection")
    return {"all_emitted_projections_have_loss": True, "projection_occurrences": len(expected),
        "rows_per_projection": dict(sorted(counts.items())), "scope": "retained_structural_features_only",
        "unknown_atoms_are_not_reconstructed": True}


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
    _require(type(columns) is list and 1 <= len(columns) <= codec.MAX_FEATURES
        and columns == sorted(columns) and len({tuple(c) for c in columns}) == len(columns)
        and all(type(c) is list and len(c) == 2 and c[0] in space["projections"] and type(c[1]) is str for c in columns),
        "invalid fitted feature columns")
    width, latent = len(columns), report["latent_width"]
    _require(type(latent) is int and 1 <= latent <= 64, "invalid latent width")
    parameters = [torch.tensor(p, dtype=torch.float64) for p in saved["parameters"]]
    _require(len(parameters) == 4 and [tuple(p.shape) for p in parameters] ==
        [(width, latent), (latent,), (latent, width), (width,)]
        and all(bool(torch.isfinite(p).all()) for p in parameters), "invalid numerical tensors")
    _require(report["selected_parameters_sha256"] == _digest(saved["parameters"]),
             "saved training parameter identity differs")
    return saved, parameters


@codec._single_threaded
def train_validated_family_projection_autoencoder(training_observations, validation_observations, *,
        domain_id, output_dir, epochs=12, latent_width=16, learning_rate=.001,
        minibatch_size=32, denoising=.05, ridge=.001, patience=4, seed=1729, max_seconds=120,
        refinement_strategy="joint_adam"):
    """Train a fresh structural head after live input gates; never grant admission.

    No parent/resume conversion is supported by this first strict artifact.
    The deadline covers numerical initialization, calibration and refinement;
    native evidence validation/feature preparation are separately timed. A late
    or partial epoch is never selected. Tuning selects; no heldout input is read.
    ``decoder_blocks`` freezes the shared encoder and selects complete decoder
    families independently; the default keeps the existing joint Adam path.
    """
    import torch
    _require(refinement_strategy in ("joint_adam", "decoder_blocks"),
             "unknown native refinement strategy")
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
    space = codec._space(domain, training_reports, training_rows)
    space["producer_pins"] = codec._producer_pins(training_reports + validation_reports)
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
    refinement_diagnostics = None
    if refinement_strategy == "decoder_blocks":
        refinement = decoder_refinement.refine_decoder_blocks(torch, best, training, masks,
            validation, validation_mask, spans, space["projections"], epochs=epochs,
            learning_rate=learning_rate, minibatch_size=minibatch_size, denoising=denoising,
            patience=patience, seed=seed, deadline=started + max_seconds)
        best, best_loss, after = refinement["parameters"], refinement["loss"], refinement["metrics"]
        history, steps = refinement["history"], refinement["steps"]
        selected_epoch, stopped = refinement["selected_epoch"], refinement["stopped"]
        refinement_diagnostics = refinement["selection_diagnostics"]
    else:
        parameters = [p.detach().clone().requires_grad_() for p in best]
        optimizer = torch.optim.Adam(parameters, lr=learning_rate)
        generator = torch.Generator(device="cpu").manual_seed(seed)
        population = (len(training), masks.sum(dim=0).tolist())
        history, steps, selected_epoch, stale, stopped = [], 0, 0, 0, "epoch_budget"
        for epoch in range(epochs):
            if time.monotonic() - started >= max_seconds:
                stopped = "deadline"
                break
            order = torch.randperm(len(training), generator=generator)
            weighted, seen, aborted = 0., 0, False
            for offset in range(0, len(training), minibatch_size):
                if time.monotonic() - started >= max_seconds:
                    aborted = True
                    break
                indices = order[offset:offset + minibatch_size]
                clean = training[indices]
                optimizer.zero_grad(set_to_none=True)
                objective = prepared._PreparedObjective(torch, clean, masks[indices], spans, space["projections"], population)
                clean_loss = objective(_forward(torch, clean, parameters))
                loss = clean_loss
                if denoising:
                    corrupted = clean * (torch.rand(clean.shape, generator=generator) >= denoising)
                    noisy_loss = objective(_forward(torch, corrupted, parameters))
                    loss = .75 * clean_loss + .25 * noisy_loss
                _require(bool(torch.isfinite(loss)), "nonfinite native training loss")
                loss.backward()
                norm = float(torch.nn.utils.clip_grad_norm_(parameters, 1.))
                _require(math.isfinite(norm), "nonfinite native training gradient")
                progress = (epoch + offset / len(training)) / epochs
                rate = learning_rate * min(1., (steps + 1) / 5) * (.1 + .9 * (1 + math.cos(math.pi * progress)) / 2)
                optimizer.param_groups[0]["lr"] = rate
                optimizer.step()
                steps += 1
                weighted += float(loss.detach()) * len(indices)
                seen += len(indices)
            if aborted:
                stopped = "deadline_partial_epoch_not_selected"
                break
            with torch.no_grad():
                score, metrics = codec._objective(torch, _forward(torch, validation, parameters), validation,
                    validation_mask, spans, space["projections"])
            _require(bool(torch.isfinite(score)), "nonfinite native validation loss")
            selected = time.monotonic() - started < max_seconds and float(score) < best_loss - EPS and all(
                value <= after["families"][family] + EPS for family, value in metrics["families"].items())
            if selected:
                best, best_loss, after = [p.detach().clone() for p in parameters], float(score), metrics
                selected_epoch, stale = epoch + 1, 0
            else:
                stale += 1
            history.append({"epoch": epoch + 1, "training_objective": weighted / seen,
                "validation_objective": float(score), "validation_families": metrics["families"], "selected": selected})
            if stale >= patience:
                stopped = "validation_patience"
                break
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
        "selection": ("validation_family_block_calibration_then_independent_decoder_refinement"
            if refinement_strategy == "decoder_blocks" else
            "validation_family_block_calibration_then_monotone_joint_refinement"),
        "refinement_strategy": refinement_strategy, "refinement_diagnostics": refinement_diagnostics,
        "before": {"objective": float(initial_loss), **initial_metrics},
        "after": {"objective": best_loss, **after}, "improved": best_loss < float(initial_loss) - EPS,
        "history": history, "stopping": stopped, "elapsed_seconds": time.monotonic() - started,
        "settings": {"learning_rate": learning_rate, "denoising": denoising, "ridge": ridge,
            "minibatch_size": minibatch_size, "patience": patience, "seed": seed, "max_seconds": max_seconds,
            "refinement_strategy": refinement_strategy},
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
        "semantics": "same_masked_macro_family_objective_with_declared_refinement_strategy",
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
def infer_validated_family_projection_autoencoder(descriptor, observations):
    """Infer from a fresh live-gated panel; stored checkpoint receipts are not authority."""
    import torch
    saved, parameters = _read(descriptor)
    domain = saved["space"]["domain_id"]
    reports, gate = _panel(observations, domain)
    rows = _reports(reports, atoms=prepared._atom_encoder()[0])
    codec._bind_producers(saved["space"], reports)
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
    return {"schema": SCHEMA, "domain_id": domain, "checkpoint_sha256": descriptor["sha256"],
        "latent": latent.tolist(), "reconstructed_features": prediction.tolist(), "objective": float(objective),
        **metrics, "coverage": coverage, "loss_coverage": loss_coverage, "validation_policy": gate,
        "formulas_generated": False, "source_text_decoded": False, "lake_build_executed": False,
        "lake_evidence_scope": "input projections, not reconstructed features", **FALSE}


__all__ = ["train_validated_family_projection_autoencoder", "infer_validated_family_projection_autoencoder", "SCHEMA"]
