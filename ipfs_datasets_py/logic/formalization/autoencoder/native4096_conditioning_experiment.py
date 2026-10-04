"""Matched native4096 source-conditioning diagnostics, never qualification.

Each arm starts from an identical copied token/GRU prior and zero source paths.
The public entry requires the live native-owner capability for every arm. The
old 8D teacher, production loaders, encoder context and target codec are intact.
"""
from copy import deepcopy
import math
import time

from . import native4096_formula_sidecar_experiment as pilot

core = pilot.core
_require = core._require
SCHEMA = "native4096-matched-conditioning/v1"
STEPS = 200
BASE_LR = .001
ARMS = ("joint_unscaled", "joint_source_scaled", "staged_source_scaled_plateau")
SOURCE_WEIGHTS = ("condition.weight", "source_to_embedding.weight")
PRIOR_PREFIXES = ("target_embedding.", "decoder.", "output.")
FALSE = dict(pilot.FALSE, source_encoder_trained=False, holdout_evaluated=False)


def _prepare(rows):
    """Train-only normalization and input geometry; targets never set rates."""
    torch = core._torch()
    vectors = torch.tensor([row["input"] for row in rows], dtype=torch.float32)
    mean64 = vectors.double().mean(0)
    scale = float(((vectors.double()-mean64).square().sum()/len(rows)).sqrt())
    _require(math.isfinite(scale) and scale > 1e-8, "distinct training vectors required")
    mean = mean64.float()
    normalized = (vectors-mean)/scale
    # At zero weights, the first Adam coordinate step has
    # |delta(Wx)| <= lr*||x||_1. This first-step scaling heuristic reduces a
    # sqrt(width)-dependent activation shock; later momentum ratios are not
    # covered by that bound. Actual activations are recorded in every panel.
    source_l1_bound = max(1., float(normalized.abs().sum(1).max()))
    _require(math.isfinite(source_l1_bound), "finite source geometry required")
    length = max(len(row["target_ids"]) for row in rows)
    labels = torch.tensor([row["target_ids"]+[0]*(length-len(row["target_ids"]))
                           for row in rows], dtype=torch.long)
    return normalized, labels, dict(mean=mean.tolist(), scale=scale,
        source_l1_bound=source_l1_bound, statistics_dtype="float64", model_dtype="float32",
        training_ids=[row["id"] for row in rows])


def _groups(model, arm, source_l1_bound):
    _require(arm in ARMS, "closed conditioning arm required")
    groups = {"source_weights": [], "source_bias": [], "copied_prior": []}
    for name, parameter in model.named_parameters():
        _require(parameter.requires_grad, "unfrozen fresh pilot parameters required")
        key = ("source_weights" if name in SOURCE_WEIGHTS else "source_bias"
               if name == "condition.bias" else "copied_prior")
        _require(key != "copied_prior" or name.startswith(PRIOR_PREFIXES),
                 "unexpected pilot parameter")
        groups[key].append(parameter)
    _require(all(groups.values()), "complete disjoint optimizer groups required")
    scaled = arm != "joint_unscaled"
    return [dict(params=parameters, name=name,
                 lr=BASE_LR/source_l1_bound if scaled and name == "source_weights" else BASE_LR)
            for name, parameters in groups.items()]


def _fit_arm(model, rows, *, arm, deadline, steps=STEPS):
    """Numerical implementation; synthetic controls confer no native evidence."""
    torch = core._torch()
    _require(type(steps) is int and 1 <= steps <= STEPS, "bounded optimizer steps required")
    _require(type(deadline) in (int, float) and math.isfinite(deadline)
             and time.monotonic() < deadline <= time.monotonic()+301,
             "live bounded monotonic deadline required")
    sources, labels, normalization = _prepare(rows)
    groups = _groups(model, arm, normalization["source_l1_bound"])
    optimizer = torch.optim.AdamW(groups, weight_decay=.01, foreach=False)
    parameters = list(model.parameters())
    prior = [p for name, p in model.named_parameters() if name.startswith(PRIOR_PREFIXES)]
    staged = arm == "staged_source_scaled_plateau"
    initial_digest = core.tensor_digest(model)
    minimum_lrs = [group["lr"]/16 for group in optimizer.param_groups]
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=.5,
        patience=15, threshold=.001, threshold_mode="rel", min_lr=minimum_lrs) if staged else None
    initial_prior = {name: core.tensor_digest(getattr(model, name))
                     for name in ("target_embedding", "decoder", "output")}

    def check_deadline(where):
        _require(time.monotonic() < deadline, "conditioning deadline "+where)

    def loss(source):
        logits = model(source, labels[:, :-1])
        return torch.nn.functional.cross_entropy(logits.flatten(0, 1), labels[:, 1:].flatten(), ignore_index=0)

    def panel(source):
        check_deadline("before evaluation")
        ce = float(loss(source))
        generated = core._greedy(torch, model, source, 512, 32, deadline)
        _require(generated is not None, "conditioning deadline during generation")
        predictions, statuses = generated[1:]
        return dict(cross_entropy=ce,
            exact=sum(status == "eos" and tokens == row["target_ids"][1:-1]
                      for tokens, status, row in zip(predictions, statuses, rows)),
            predictions=[dict(id=row["id"], token_ids=tokens, status=status)
                         for row, tokens, status in zip(rows, predictions, statuses)])

    def evaluate(step):
        model.eval()
        with torch.inference_mode():
            value = dict(step=step, conditioned=panel(sources), zero_source=panel(torch.zeros_like(sources)),
                         rotated_source=panel(sources.roll(1, 0)),
                         condition_preactivation_rms=float(model.condition(sources).square().mean().sqrt()),
                         source_residual_rms=float(model.source_to_embedding(sources).square().mean().sqrt()))
        value["conditioned_advantage_over_zero_ce"] = value["zero_source"]["cross_entropy"]-value["conditioned"]["cross_entropy"]
        value["conditioned_advantage_over_rotated_ce"] = value["rotated_source"]["cross_entropy"]-value["conditioned"]["cross_entropy"]
        return value

    observations = [evaluate(0)]
    updates = []
    started = time.monotonic()
    frozen_prior_digest = None
    for step in range(1, steps+1):
        check_deadline("before optimizer update")
        frozen = staged and step <= 40
        for parameter in prior:
            parameter.requires_grad_(not frozen)
        model.train()
        optimizer.zero_grad(set_to_none=True)
        objective = loss(sources)
        _require(bool(torch.isfinite(objective)), "nonfinite conditioning loss")
        objective.backward()
        gradient_norm = float(torch.nn.utils.clip_grad_norm_(parameters, 1., error_if_nonfinite=True))
        gradients = {name: float(p.grad.norm()) if p.grad is not None else 0.
                     for name, p in model.named_parameters() if name in SOURCE_WEIGHTS}
        rates = {group["name"]: group["lr"] for group in optimizer.param_groups}
        check_deadline("before optimizer step")
        optimizer.step()
        _require(all(bool(torch.isfinite(p).all()) for p in parameters), "nonfinite conditioning parameters")
        with torch.inference_mode():
            after = float(loss(sources))
        _require(math.isfinite(after), "nonfinite post-update conditioning loss")
        if scheduler is not None and step > 40:
            # Reset phase: only joint-fit post-update training CE feeds this
            # scheduler. Neither counterfactual panel nor holdout is an input.
            scheduler.step(after)
        if staged and step == min(40, steps):
            frozen_prior_digest = {name: core.tensor_digest(getattr(model, name))
                                   for name in ("target_embedding", "decoder", "output")}
            _require(frozen_prior_digest == initial_prior, "frozen copied prior changed")
        updates.append(dict(step=step, loss_before_update=float(objective.detach()),
            loss_after_update=after, learning_rates=rates, copied_prior_frozen=frozen,
            gradient_norm_before_clip=gradient_norm, source_gradient_norms_after_clip=gradients))
        if step in (20, 40, 100, steps):
            observations.append(evaluate(step))
    fit_seconds = time.monotonic()-started
    for parameter in parameters:
        parameter.requires_grad_(True)
    token_count = int((labels[:, 1:] != 0).sum())
    return dict(arm=arm, optimizer_steps=steps, row_presentations=steps*len(rows),
        target_token_presentations=steps*token_count, fit_seconds=fit_seconds,
        seconds_per_row_presentation=fit_seconds/(steps*len(rows)), normalization=normalization,
        initial_tensor_sha256=initial_digest, final_tensor_sha256=core.tensor_digest(model),
        initial_copied_prior_sha256=initial_prior, frozen_phase_copied_prior_sha256=frozen_prior_digest,
        observations=observations, updates=updates,
        schedule="40_source_only_then_joint_training_CE_plateau_patience15_factor.5_floor1/16" if staged else "constant",
        source_rate_policy="base_lr" if arm == "joint_unscaled" else "base_lr/max(1,max_train_normalized_source_L1)",
        model_state={name: tensor.detach().tolist() for name, tensor in model.state_dict().items()})


def train_native_comparison(result, *, donor, codec, training_labels, max_seconds=300):
    """Three fixed matched fits using one live, real native-owner operation.

    The last iterate is reported in every arm. There is no selection, holdout,
    promotion, embedding finetuning or architecture qualification in this pilot.
    """
    from .source_embeddings_4096_full_owner import require_live_result
    started = time.monotonic()
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds)
             and 0 < max_seconds <= 300, "bounded total comparison deadline required")
    native = require_live_result(result)
    rows = pilot._training_rows(native["rows"], training_labels, codec)
    _require(len(rows) == 2, "fixed two-source matched conditioning diagnostic required")
    digest = core.tensor_digest(donor)
    fits = []
    for arm in ARMS:
        _require(require_live_result(result) == native, "native operation binding changed before fit")
        model = pilot._new_body(donor, vocabulary_size=32)
        fit = _fit_arm(model, rows, arm=arm, deadline=started+max_seconds)
        _require(not fits or fit["initial_tensor_sha256"] == fits[0]["initial_tensor_sha256"],
                 "matched arms have different initial tensors")
        fits.append(fit)
        _require(require_live_result(result) == native, "native operation binding changed during fit")
    _require(core.tensor_digest(donor) == digest, "conditioning experiment changed donor")
    receipt = dict(schema=SCHEMA, dimension=4096, arms=fits, codec=deepcopy(codec),
        donor_tensor_sha256=digest, native_provenance=deepcopy(native["provenance"]),
        training_rows_sha256=core.digest(rows), training_source_count=len(rows),
        encoder_context_tokens=512, decoder_output_tokens=512, temperature=0,
        optimizer="fresh_AdamW_default_betas_eps_weight_decay.01", max_grad_norm=1.,
        optimizer_resumable=False, validation_count=0, selection_policy="none_report_all_last_iterates",
        loss_scope="training_full32V_token_cross_entropy_only",
        projection_policy="identity_no_learned_embedding_reconstruction",
        bridge_names=[], legal_ir_evaluate_provers=False, metric_disk_cache_used=False,
        workers=1, elapsed_seconds=time.monotonic()-started, **FALSE)
    receipt["receipt_sha256"] = core.digest(receipt)
    return receipt
