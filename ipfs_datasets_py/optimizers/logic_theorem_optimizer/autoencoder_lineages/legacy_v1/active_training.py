"""Opt-in, bounded family-feature updates for the preserved 8D runtime.

The historical trainer's candidate prefix starts with two LegalIR-view heads.
For a bridge-off feature run, a small prefix cap can prevent any family update.
This separate helper directly schedules the existing family-logit update and
keeps its frozen objective and strict regression checks. It neither replaces
the historical trainer nor changes linguistic IR, weights on disk, or formula
decoding. Numerical target-aware reconstruction is not semantic fidelity.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time

from . import linguistic, linguistic_cached, daemon_teacher, linguistic_view_reuse
from ._snapshot import modal_autoencoder as frozen

SCHEMA = "legacy-active-family-training/v1"
_MODELS = (linguistic.LinguisticAutoencoder,
           linguistic_cached.CachedLinguisticAutoencoder,
           linguistic_cached.StreamedCachedLinguisticAutoencoder,
           daemon_teacher.HistoricalDaemonAutoencoder,
           linguistic_view_reuse.ViewReuseCachedLinguisticAutoencoder,
           linguistic_view_reuse.ViewReuseStreamedCachedLinguisticAutoencoder,
           linguistic_view_reuse.ViewReuseHistoricalDaemonAutoencoder)
_EVALUATE = dict(legal_ir_bridge_names=(), legal_ir_evaluate_provers=False,
                 legal_ir_parallel_workers=1, use_sample_memory=False)
_OBJECTIVE = dict(cross_entropy=1.0, reconstruction=1.0, cosine_gap=1.5, legal_ir=1.0)
_GUARDS = dict(max_cosine_regression=.01, max_reconstruction_regression=.02,
               max_cross_entropy_regression=0.0, max_legal_ir_loss_regression=.02)
_FALSE = dict(admitted=False, formalized=False, roundtrip_ok=False, qualified=False,
              proof_authority=False, semantic_correctness_verified=False,
              independent_validation=False, lake_executed=False,
              formula_training_executed=False, promotion_performed=False,
              publication_performed=False, sample_memory_used=False)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value, label, low, high, *, inclusive_low=True):
    _require(type(value) in (int, float) and math.isfinite(value)
             and (value >= low if inclusive_low else value > low) and value <= high,
             label + " is outside its finite bound")


def _samples_digest(rows):
    digest = hashlib.sha256()
    for sample in rows:
        content = sample.to_json().encode()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _source_identity():
    path = Path(__file__)
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


_IMPORTED_SOURCE_IDENTITY = _source_identity()
_IMPORTED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_require(_source_identity() == _IMPORTED_SOURCE_IDENTITY, "active training source changed during import")


def _evaluation(model, rows):
    result = model.evaluate(rows, **_EVALUATE)
    _require(result.sample_count == len(rows), "legacy evaluation sample coverage differs")
    _require(result.legal_ir_target_count == 0 and not result.legal_ir_losses,
             "active-family helper is explicitly bridge-off")
    for name in ("embedding_cosine_similarity", "reconstruction_loss", "cross_entropy_loss",
                 "cross_entropy_excess_loss", "cross_entropy_entropy_loss"):
        _require(math.isfinite(getattr(result, name)), "nonfinite evaluation metric: " + name)
    return result


def train_active_family_features(model, samples, *, validation_samples,
                                epochs=3, learning_rate=.01, min_learning_rate=.0001,
                                max_learning_rate=.35, growth_factor=1.5,
                                shrink_factor=.5, max_line_search_attempts=2,
                                max_seconds=60):
    """Update family features with unchanged strict old-objective acceptance.

    Validation rows are tuning data because they select updates. Each cycle
    tries at most ``max_line_search_attempts``; a rejection rolls back before
    decreasing the next rate. A first-attempt acceptance grows only the next
    cycle's rate. Pass the returned ``next_learning_rate`` explicitly when
    continuing a saved model; this helper does not own checkpoint storage.

    The monotonic deadline includes validation and initial evaluation. Inflight
    Python operations cannot be interrupted: late candidates roll back instead
    of being committed. One private model per writer is required; this is not
    an inference/training concurrency mechanism. Only touched state rows are
    journaled, and no whole-model weight copy is made by this helper.
    """
    started = time.monotonic()
    _require(_source_identity() == _IMPORTED_SOURCE_IDENTITY,
             "active training source changed since import; use a fresh process")
    _number(max_seconds, "max_seconds", 0, 600, inclusive_low=False)
    deadline = started + max_seconds
    _require(type(epochs) is int and 1 <= epochs <= 64, "epochs must be in 1..64")
    _require(type(max_line_search_attempts) is int and 1 <= max_line_search_attempts <= 8,
             "max_line_search_attempts must be in 1..8")
    for name, value in (("learning_rate", learning_rate), ("min_learning_rate", min_learning_rate),
                        ("max_learning_rate", max_learning_rate)):
        _number(value, name, 0, 1, inclusive_low=False)
    _require(min_learning_rate <= learning_rate <= max_learning_rate,
             "initial learning rate must lie within its explicit bounds")
    _number(growth_factor, "growth_factor", 1, 2)
    _number(shrink_factor, "shrink_factor", 0, 1, inclusive_low=False)
    _require(shrink_factor < 1, "shrink_factor must be below one")
    _require(type(model) in _MODELS, "an explicit preserved 8D linguistic model is required")
    model._require_profile()
    _require(model.compute_backend != "torch_cuda", "active-family helper currently supports CPU execution only")
    _require(model.state._active_state_transaction is None, "model already has an active writer")
    _require(type(samples) in (tuple, list) and type(validation_samples) in (tuple, list)
             and 1 <= len(samples) <= 128 and 1 <= len(validation_samples) <= 128,
             "one to 128 explicit training and tuning samples required")
    training, tuning = model._samples(samples), model._samples(validation_samples)
    ids = [sample.sample_id for sample in training + tuning]
    texts = [" ".join(sample.text.lower().split()) for sample in training + tuning]
    _require(len(set(ids)) == len(ids) and len(set(texts)) == len(texts),
             "training and tuning require unique disjoint IDs and normalized sources")
    source_identity = _IMPORTED_SOURCE_IDENTITY
    source_sha = _IMPORTED_SOURCE_SHA256
    digests = (_samples_digest(training), _samples_digest(tuning))
    configuration = model.describe()

    def unchanged():
        model._require_profile()
        _require(_source_identity() == source_identity, "active training source changed")
        _require((_samples_digest(training), _samples_digest(tuning)) == digests,
                 "training or tuning inputs changed during optimization")

    def expired():
        return time.monotonic() >= deadline

    rate = float(learning_rate)
    before = best = None
    reports = []
    accepted = attempts = 0
    stopped = "epoch_limit"
    if expired():
        stopped = "deadline_during_setup"
    else:
        before = best = _evaluation(model, tuning)
        # Match the historical trainer's preparation of training feature/target
        # caches. Targets remain bridge-off and these rows never select updates.
        if not expired():
            _evaluation(model, training)
        if expired():
            stopped = "deadline_during_setup"

    if stopped == "epoch_limit":
        for epoch in range(1, epochs + 1):
            chosen = False
            for attempt in range(1, max_line_search_attempts + 1):
                unchanged()
                if expired():
                    stopped = "deadline_before_proposal"
                    break
                attempted_rate = rate
                transaction = model.state.transaction(label=f"active-family:{epoch}:{attempt}").begin()
                record = {"epoch": epoch, "attempt": attempt, "learning_rate": attempted_rate,
                          "accepted": False, "update": "family_logits", "holdout_evaluated": False}
                attempts += 1
                try:
                    norms = model._apply_projection_update_batch(
                        training, update_targets=("family_logits",), learning_rate=attempted_rate,
                        l2_regularization=0.0, update_backend="python_sparse_batch")
                    record["update_norms"] = norms
                    _require(norms["finite"], "nonfinite legacy feature proposal")
                    model._invalidate_state_dependent_evaluator_caches()
                    if expired():
                        stopped = record["reason"] = "deadline_after_proposal"
                    elif not norms["nonzero_update"]:
                        record["reason"] = "zero_update"
                    else:
                        after = _evaluation(model, tuning)
                        unchanged()
                        regressions = frozen._evaluation_regressions_for_training(best, after, **_GUARDS)
                        delta = (frozen._evaluation_objective_for_training(best, **_OBJECTIVE)
                                 - frozen._evaluation_objective_for_training(after, **_OBJECTIVE))
                        _require(math.isfinite(delta), "nonfinite proposal objective")
                        record.update(holdout_evaluated=True, objective_delta=delta,
                                      pareto_regressions=regressions,
                                      before=best.to_dict(), after=after.to_dict())
                        if expired():
                            stopped = record["reason"] = "deadline_after_evaluation"
                        elif not regressions and delta > 0.0:
                            patch = transaction.commit()
                            record.update(accepted=True, reason="strict", patch=patch.to_dict())
                            best, chosen = after, True
                            accepted += 1
                        else:
                            record["reason"] = "regression_or_no_strict_improvement"
                finally:
                    if transaction.active:
                        transaction.rollback()
                    model._invalidate_state_dependent_evaluator_caches()
                reports.append(record)
                if chosen:
                    rate = min(max_learning_rate, attempted_rate * growth_factor) if attempt == 1 else attempted_rate
                    break
                if stopped.startswith("deadline"):
                    break
                reduced = max(min_learning_rate, attempted_rate * shrink_factor)
                rate = reduced
                if reduced == attempted_rate:
                    stopped = "minimum_learning_rate"
                    break
            if stopped.startswith("deadline") or not chosen:
                if stopped == "epoch_limit":
                    stopped = "line_search_exhausted"
                break
    unchanged()
    return {"schema": SCHEMA, "source_sha256": source_sha,
            "model_profile": configuration, "training_manifest_sha256": digests[0],
            "tuning_manifest_sha256": digests[1], "training_sample_count": len(training),
            "validation_sample_count": len(tuning), "validation_role": "tuning_used_for_update_selection",
            "before": None if before is None else before.to_dict(),
            "after": None if best is None else best.to_dict(),
            "accepted_epochs": accepted, "proposal_count": attempts, "epoch_reports": reports,
            "next_learning_rate": rate, "stopped_reason": stopped,
            "elapsed_seconds": time.monotonic() - started,
            "deadline_scope": "setup_included_monotonic; inflight_operations_soft; late_candidates_rolled_back",
            "objective_weights": dict(_OBJECTIVE), "strict_regression_tolerances": dict(_GUARDS),
            "acceptance_policy": "unchanged_frozen_strict_objective_and_regression_checks",
            "proposal_policy": "first_acceptable_family_feature_update_with_bounded_backtracking",
            "candidate_update_order": ["family_logits"], "projection_update_backend": "python_sparse_batch",
            "max_line_search_attempts": max_line_search_attempts, "requested_epochs": epochs,
            "initial_learning_rate": learning_rate, "min_learning_rate": min_learning_rate,
            "max_learning_rate": max_learning_rate, "growth_factor": growth_factor, "shrink_factor": shrink_factor,
            "legal_ir_bridge_names": [], "legal_ir_target_count": 0, "legal_ir_evaluate_provers": False,
            "legal_ir_parallel_workers": 1, "independent_reconstruction_verified": False,
            "reconstruction_scope": "unchanged_historical_target_aware_linguistic_hash_features",
            "training_executed": accepted > 0, **_FALSE}


__all__ = ["SCHEMA", "train_active_family_features"]
