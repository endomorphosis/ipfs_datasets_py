"""Private feature pretraining over the existing resumable sparse training lanes.

This purpose does not run deterministic source qualification or enqueue source
repairs. Raw decoder reconstruction and bridge objectives govern private updates;
formalization, inference promotion, and publication remain separate unchanged
policies. Callers must reserve/supervise resources for the whole invocation.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from . import autoencoder_incremental_training as inc
from . import autoencoder_training_coordinator as coordinator
from .autoencoder_training_worker import BRIDGE_NAMES, TrainingJobSpec, execute_training_job

SCHEMA = "autoencoder-feature-pretraining/v1"
POLICY = "raw-decoder-and-shared-ir-private-candidates/v1"
_FALSE = {"qualified": False, "admitted": False, "formalized": False,
          "promotion_performed": False, "publication_performed": False}


def _require(value, message):
    if not value:
        raise inc.IncrementalTrainingError(message)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _text_key(text):
    return hashlib.sha256(" ".join(text.casefold().split()).encode()).hexdigest()


def _validate_template(spec):
    _require(type(spec) is TrainingJobSpec, "feature intake requires immutable TrainingJobSpec templates")
    config = spec.training_config
    _require(config.projection_reconstruction_objective == "raw_decoder",
             "feature pretraining requires the explicit raw_decoder objective")
    _require(tuple(config.legal_ir_bridge_names) == tuple(BRIDGE_NAMES)
             and config.legal_ir_evaluate_provers is False and config.legal_ir_parallel_workers == 1
             and config.metric_disk_cache == 0 and config.use_sample_memory is False,
             "feature pretraining requires the complete fixed bridge/cache/prover policy")
    _require(spec.capture_sparse_patches is True and spec.candidate_storage == "sparse",
             "feature pretraining requires owner-replayed sparse candidates")
    _require(spec.target_snapshot_artifact is not None and bool(spec.target_snapshot_id),
             "feature pretraining requires an immutable shared target artifact")
    _require(bool(spec.samples) and bool(spec.validation_samples), "feature pretraining requires disjoint tuning samples")
    records = (*spec.samples, *spec.validation_samples)
    models = {row.embedding_model for row in records}
    _require(len(models) == 1 and all(row.embedding_vector and not row.embedding_model.lower().startswith(
        ("mock:", "test:", "deterministic:")) for row in records), "feature pretraining requires supplied non-mock embeddings")
    dimensions = {len(row.embedding_vector) for row in records}
    _require(len(dimensions) == 1 and all(all(_finite(v) for v in row.embedding_vector) for row in records),
             "feature embedding dimensions or finite values differ")
    _require(not ({_text_key(row.text) for row in spec.samples} &
                  {_text_key(row.text) for row in spec.validation_samples}), "feature training/tuning source overlap")
    return {"model": next(iter(models)), "dimension": next(iter(dimensions)),
            "validation_sha256": inc._sha([asdict(row) for row in spec.validation_samples])}


def _supervision_receipt(sample_ids, bridge_names):
    return {"schema_version": "feature-shared-target-supervision/v1", "complete": True,
            "target_sample_ids": sorted(sample_ids), "target_count": len(sample_ids),
            "bridge_names": list(bridge_names),
            "returned_accepted_bridge_count": len(sample_ids) * len(bridge_names),
            "failed_bridge_count": 0, "timeout_target_count": 0,
            "scope": "native payload bridge supervision; not semantic qualification or Lean admission",
            "admitted": False, "formalized": False}


def verify_feature_target_supervision(targets, statuses, bridge_names, *, sample_ids):
    """Check existing hydrated payloads before training, without decoding twice.

    Native multiview's accepted flag requires every requested report to return
    and be accepted without failures. Its document metadata independently keeps
    the attempted/implemented/accepted/failed bridge counts. These are target
    supervision observations, never proof or source semantic qualification.
    """
    from ...logic.bridge.multiview import LegalIRTrainingTarget
    names = tuple(bridge_names)
    _require(names == tuple(BRIDGE_NAMES), "feature targets require all five bridge names")
    _require(len(set(sample_ids)) == len(sample_ids) and sample_ids and targets is not None
             and set(targets) == set(sample_ids), "feature shared target selection is incomplete")
    for sample_id in sample_ids:
        target = targets[sample_id]
        _require(statuses.get(sample_id) == "ready", "feature target has timeout or nonready status")
        _require(type(target) is LegalIRTrainingTarget and target.accepted is True
                 and tuple(target.bridge_names) == names and target.document.document_id == sample_id,
                 "feature target lacks accepted native five-bridge supervision")
        metadata = target.document.metadata
        _require(type(metadata) is dict and tuple(metadata.get("bridge_names", ())) == names
                 and all(type(metadata.get(key)) is int and metadata[key] == count for key, count in
                         (("attempted_bridge_count", len(names)), ("implemented_bridge_count", len(names)),
                          ("accepted_bridge_count", len(names)), ("failed_bridge_count", 0))),
                 "feature target bridge returns/acceptance are incomplete or include failures")
    return _supervision_receipt(sample_ids, names)


def _feature_evidence(registry, spec, completion):
    """Validate the already replay-verified worker receipt before advancing a lane."""
    _validate_template(spec)
    result = completion["result"]
    _require(result.get("sparse_replay_verified") is True, "feature candidate sparse replay was not verified")
    reference = result["worker_receipt_artifact"]
    registry.verify_artifact(reference)
    _require(reference["bytes"] <= 64 * 1024 * 1024, "feature worker receipt exceeds byte bound")
    worker = json.loads(registry.artifact_path(reference).read_bytes())
    config = spec.training_config
    _require(worker.get("base_version_id") == spec.base_version_id
             and worker.get("job_spec_canonical_sha256") == spec.canonical_sha256,
             "feature worker parent or job binding differs")
    _require(tuple(worker.get("bridge_names", ())) == tuple(BRIDGE_NAMES)
             and worker.get("legal_ir_evaluate_provers") is False
             and worker.get("legal_ir_parallel_workers") == 1
             and worker.get("metric_disk_cache") == 0 and worker.get("use_sample_memory") is False,
             "feature worker bridge/cache/prover evidence differs")
    total = len(spec.samples) + len(spec.validation_samples)
    _require(worker.get("shared_targets_verified") is True
             and worker.get("target_snapshot_id") == spec.target_snapshot_id
             and worker.get("shared_target_count") == total
             and worker.get("shared_target_status_counts") == {"ready": total}
             and worker.get("shared_timeout_fallback_count") == 0,
             "feature worker lacks complete verified shared targets")
    report = worker["training_report"]
    _require(report.get("projection_reconstruction_objective") == "raw_decoder",
             "feature completion does not attest the raw decoder objective")
    raw = report.get("decoder_preprojection_observation", {})
    _require(raw.get("changes_acceptance") is True and raw.get("sample_scope") == "tuning",
             "feature completion lacks raw tuning acceptance evidence")
    tuning_count = len(spec.validation_samples)
    from .legal_samples import _sample_id
    from .legal_modal_parser import LegalModalParser
    normalizer = LegalModalParser()
    tuning_ids = {_sample_id(row.title, row.section, normalizer.normalize_text(row.text))
                  for row in spec.validation_samples}
    selected_ids = {_sample_id(row.title, row.section, normalizer.normalize_text(row.text))
                    for row in (*spec.samples, *spec.validation_samples)}
    _require(worker.get("shared_target_supervision") == _supervision_receipt(selected_ids, BRIDGE_NAMES),
             "feature worker lacks verified complete five-bridge target supervision")
    _require(len(tuning_ids) == tuning_count, "feature tuning samples are duplicated")
    metrics = {}
    for when in ("before", "after"):
        evaluation, observation = report.get(when, {}), raw.get(when, {})
        _require(observation.get("complete") is True and observation.get("finite") is True
                 and observation.get("requested_sample_count") == tuning_count
                 and observation.get("observed_sample_count") == tuning_count
                 and observation.get("used_for_acceptance") is True
                 and observation.get("sample_memory_used") is False,
                 "feature raw tuning observation is incomplete or nonfinite")
        _require(evaluation.get("sample_count") == tuning_count
                 and evaluation.get("legal_ir_target_count") == tuning_count,
                 "feature raw evaluation target/sample coverage differs")
        for name in ("embedding_cosine_similarity", "reconstruction_loss", "cross_entropy_loss"):
            _require(_finite(evaluation.get(name)), "feature evaluation contains nonfinite or missing " + name)
        _require(evaluation["reconstruction_loss"] >= 0, "feature reconstruction loss is negative")
        for evaluation_name, raw_name in (("embedding_cosine_similarity", "embedding_cosine_similarity_mean"),
                                          ("reconstruction_loss", "reconstruction_loss_mean")):
            _require(_finite(observation.get(raw_name)) and math.isclose(evaluation[evaluation_name], observation[raw_name],
                     abs_tol=1e-12, rel_tol=1e-10), "feature evaluation differs from raw decoder observation")
        rows = observation.get("sample_metrics")
        _require(type(rows) is list and len(rows) == tuning_count
                 and all(type(row) is dict for row in rows)
                 and {row.get("sample_id") for row in rows} == tuning_ids
                 and all(_finite(row.get("embedding_cosine_similarity"))
                         and _finite(row.get("reconstruction_loss"))
                         and row["reconstruction_loss"] >= 0 for row in rows),
                 "feature raw tuning sample identities or metrics differ")
        for name in ("embedding_cosine_similarity", "reconstruction_loss"):
            _require(math.isclose(sum(row[name] for row in rows) / tuning_count, evaluation[name],
                                 abs_tol=1e-12, rel_tol=1e-10),
                     "feature raw tuning row aggregate differs")
        losses = evaluation.get("legal_ir_losses")
        _require(type(losses) is dict and losses and all(_finite(value) for value in losses.values()),
                 "feature legal IR loss evidence missing or nonfinite")
        metrics[when] = {"embedding_cosine_similarity": evaluation["embedding_cosine_similarity"],
                         "reconstruction_loss": evaluation["reconstruction_loss"],
                         "legal_ir_target_count": evaluation["legal_ir_target_count"]}
    _require(set(report["before"]["legal_ir_losses"]) == set(report["after"]["legal_ir_losses"]),
             "feature legal IR loss coverage changed")
    accepted = completion["optimizer_accepted_epochs"]
    _require(report.get("accepted_epochs") == accepted, "feature accepted-epoch count differs")
    # Each accepted epoch must improve the raw weighted objective and pass its
    # unchanged optimizer guards. The final bound permits the existing per-epoch
    # tolerance to accumulate; higher-is-better IR metrics retain their direction.
    epochs = report.get("epoch_reports", [])
    accepted_reports = [row for row in epochs if row.get("accepted") is True]
    _require(len(accepted_reports) == accepted, "feature accepted epoch evidence differs")
    if accepted:
        from .modal_autoencoder import _metric_higher_is_better
        _require(all(_finite(row.get("committed_objective_delta"))
                     and row["committed_objective_delta"] > 0
                     and row.get("pareto_regressions") == {}
                     and row.get("rejection_reasons", []) == [] for row in accepted_reports),
                 "feature accepted epoch lacks objective improvement or violates optimizer guards")
        tolerance = max(0.0, config.max_legal_ir_loss_regression) * accepted
        _require(all((value - report["after"]["legal_ir_losses"][key]
                     if _metric_higher_is_better(key) else report["after"]["legal_ir_losses"][key] - value)
                     <= tolerance + 1e-12 for key, value in report["before"]["legal_ir_losses"].items()),
                 "feature accepted candidate exceeds its IR regression budget")
        _require(completion["next_base_version_id"] == completion["candidate_version_id"],
                 "accepted feature completion did not continue its candidate")
    else:
        _require(completion["next_base_version_id"] == spec.base_version_id,
                 "rejected feature completion changed its parent")
    return {"schema_version": SCHEMA, "policy": POLICY, "run_id": spec.run_id,
            "batch_id": completion["batch_id"], "lane_index": completion["lane_index"],
            "base_version_id": spec.base_version_id, "candidate_version_id": completion["candidate_version_id"],
            "next_base_version_id": completion["next_base_version_id"],
            "worker_receipt_artifact": reference, "raw_tuning_metrics": metrics,
            "optimizer_accepted_epochs": accepted, "feature_status": "updated" if accepted else "consumed_without_update",
            "semantic_qualification_status": "deferred_not_evaluated", "lake_executed": False,
            "source_repair_submitted": False, "target_snapshot_id": spec.target_snapshot_id,
            "bridge_names": list(BRIDGE_NAMES), "legal_ir_evaluate_provers": False,
            "metric_disk_cache": 0, "legal_ir_parallel_workers": 1, "use_sample_memory": False,
            "global_holdout_verified": False, "heldout_canary": False,
            "validation_role": "repeated_selection_tuning", **_FALSE}


def run_feature_incremental_training(registry, templates, *, state_directory,
        machine_shard_count=1, machine_shard_index=0, lane_count=2, max_batches=16,
        max_parallel_workers=None, capacity_callback=None, reuse_native_workers=False,
        producer_identity=None, control_transport="quack", publication_repository=None,
        executor_factory=None, worker_function=execute_training_job):
    """Train private feature candidates; source semantic gaps do not block intake.

    Existing worker/owner contracts retain source, target, sparse replay and
    checkpoint integrity. The invocation's resource owner supplies capacity.
    Non-mock supplied vectors are required; producer_identity binds the caller's
    independently verified embedding evidence, without upgrading legacy corpus
    provenance. Exact duplicates consume no further training. New batches/epoch
    identities may continue each private lane; rejected batches retain its head.
    """
    import duckdb
    from . import autoencoder_native_pool as pools
    native = executor_factory is None and worker_function is execute_training_job
    _require(publication_repository is None, "feature pretraining publication is disabled")
    _require(control_transport in {"quack", "owner"}, "unknown feature control transport")
    for name, value, bound in (("lane_count", lane_count, 32), ("max_batches", max_batches, inc.MAX_BATCHES),
                               ("machine_shard_count", machine_shard_count, 65536)):
        _require(type(value) is int and 1 <= value <= bound, "invalid " + name)
    _require(type(machine_shard_index) is int and 0 <= machine_shard_index < machine_shard_count,
             "invalid feature machine shard index")
    maximum = lane_count if max_parallel_workers is None else max_parallel_workers
    _require(type(maximum) is int and 1 <= maximum <= 32, "invalid feature worker ceiling")
    _require(type(reuse_native_workers) is bool and (capacity_callback is None or callable(capacity_callback)),
             "invalid feature runtime policy")
    _require(len(templates) <= inc.MAX_BATCHES, "feature intake exceeds batch bound")
    embeddings = [_validate_template(spec) for spec in templates]
    _require(not embeddings or all(row == embeddings[0] for row in embeddings),
             "feature embedding or tuning policy differs across batches")
    if native:
        embedding_evidence = producer_identity.get("embedding_verification", {}) if type(producer_identity) is dict else {}
        _require(type(embedding_evidence) is dict
                 and embedding_evidence.get("local_embedding_verification") is True
                 and embedding_evidence.get("selected_training_validation_disjoint") is True,
                 "native feature training requires caller-verified local embedding evidence")
    directory = Path(state_directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    native_manifest = pools._package_manifest() if native else None
    binding = {"schema_version": SCHEMA, "training_purpose": "feature_pretraining", "policy": POLICY,
               "producer_identity": producer_identity, "native_producer_manifest": native_manifest,
               "control_transport": control_transport, "database_path": str(registry.database_path),
               "machine_shard_count": machine_shard_count, "machine_shard_index": machine_shard_index,
               "lane_count": lane_count, "execution_mode": "native" if native else "injected_test"}
    # Outer lock serializes intake, policy and split registration across bounded
    # calls to the existing incremental owner (which uses its own separate lock).
    with inc._lock(directory / "feature-owner"):
        policy_path = directory / "feature-policy.json"
        if policy_path.exists():
            previous = json.loads(policy_path.read_bytes())
            _require({key: previous.get(key) for key in binding} == binding, "feature stream policy/source binding changed")
            _require(not embeddings or previous.get("embedding_policy") == embeddings[0],
                     "feature embedding/tuning policy changed")
            binding = previous
        else:
            _require(not (directory / "progress.duckdb").exists() and not (directory / "qualification.duckdb").exists(),
                     "feature pretraining requires a fresh explicitly bound stream")
            _require(bool(embeddings), "new feature stream requires templates")
            binding["embedding_policy"] = embeddings[0]
            binding["embedding_verification_scope"] = "supplied non-mock finite vectors; caller evidence bound by producer_identity; no invented corpus authority"
            inc._write(policy_path, binding)
        db = duckdb.connect(str(directory / "feature-inputs.duckdb"))
        pool = None
        try:
            db.execute("CREATE TABLE IF NOT EXISTS samples (text_hash VARCHAR PRIMARY KEY, split VARCHAR NOT NULL, embedding_sha256 VARCHAR NOT NULL)")
            db.execute("BEGIN TRANSACTION")
            try:
                # Register remote shard exclusions too when provided, as in the
                # qualified runner; this is not a global corpus authentication.
                for spec in templates:
                    for split, rows in (("training", spec.samples), ("tuning", spec.validation_samples)):
                        for row in rows:
                            key = _text_key(row.text)
                            embedding_sha = inc._sha([row.embedding_model, row.embedding_vector])
                            previous = db.execute("SELECT split,embedding_sha256 FROM samples WHERE text_hash=?", [key]).fetchone()
                            _require(previous is None or previous == (split, embedding_sha),
                                     "feature source overlap or embedding identity drift")
                            db.execute("INSERT INTO samples VALUES (?,?,?) ON CONFLICT DO NOTHING", [key, split, embedding_sha])
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK"); raise
            evidence_dir = directory / "feature-evidence"; evidence_dir.mkdir(exist_ok=True)
            waves_dir = directory / "feature-waves"; waves_dir.mkdir(exist_ok=True)
            completed, dispatches, wave_refs, capacities = {}, [], [], []
            last, deferred = None, False

            def guard():
                if native and pools._package_manifest() != native_manifest:
                    raise inc.IncrementalTrainingError("feature producer source changed; start a fresh stream")

            def verify(owner, spec, completion):
                guard()
                evidence = _feature_evidence(owner, spec, completion)
                path = evidence_dir / (spec.run_id + ".json")
                if path.exists():
                    _require(json.loads(path.read_bytes()) == evidence, "persisted feature evidence changed")
                else:
                    inc._write(path, evidence)
                completed[spec.run_id] = {**evidence, "feature_evidence_artifact": registry.stage_artifact(path)}
                guard()

            def dispatch(owner, specs, **kwargs):
                nonlocal pool
                guard()
                retain = native and reuse_native_workers and len(specs) <= pools.MAX_RETAINED_WORKERS
                if pool is not None and (not retain or pool.max_workers != len(specs)
                        or pool.submitted_jobs + len(specs) > pools.MAX_POOL_JOBS):
                    pool.close(); pool = None
                if retain and pool is None:
                    pool = pools._NativeTrainingPool(len(specs), expected_manifest=native_manifest)
                extra = {"_native_pool": pool} if pool is not None else {}
                if control_transport == "quack":
                    from ...duckdb_control.autoencoder_shared_weight_control import SharedWeightRegistry
                    with SharedWeightRegistry(owner, enable_prototype=True) as shared:
                        report = coordinator.run_training_jobs(shared, specs, **kwargs, **extra)
                        report["weight_control"] = shared.transport_report()
                else:
                    report = coordinator.run_training_jobs(owner, specs, **kwargs, **extra)
                    report["weight_control"] = {"transport": "trusted_owner_local", "native_quack": False}
                guard()
                return report

            pending_templates = list(templates)
            while len(dispatches) < max_batches:
                guard()
                ceiling = min(maximum, lane_count, max_batches - len(dispatches))
                # Pending intake count is an upper bound; the lower owner selects
                # at most one job per durable lane and skips completed batches.
                capacity = ({"workers": ceiling, "scope": "private_feature_training"} if capacity_callback is None
                            else capacity_callback(pending_count=ceiling, max_workers=ceiling))
                _require(type(capacity) is dict and type(capacity.get("workers")) is int
                         and 0 <= capacity["workers"] <= ceiling, "invalid feature capacity callback result")
                capacity = json.loads(json.dumps(capacity, allow_nan=False))
                capacities.append(capacity)
                if capacity["workers"] == 0:
                    last = inc.run_incremental_training(registry, pending_templates, state_directory=directory,
                        machine_shard_count=machine_shard_count, machine_shard_index=machine_shard_index,
                        lane_count=lane_count, max_batches=1, executor_factory=executor_factory,
                        worker_function=worker_function, completion_validator=verify,
                        dispatch_function=dispatch, intake_only=True)
                    pending_templates = []
                    deferred = True; break
                # max_batches limits the underlying owner to the admitted width;
                # persistent lane topology remains unchanged across wider resumes.
                last = inc.run_incremental_training(registry, pending_templates, state_directory=directory,
                    machine_shard_count=machine_shard_count, machine_shard_index=machine_shard_index,
                    lane_count=lane_count, max_batches=capacity["workers"], executor_factory=executor_factory,
                    worker_function=worker_function, completion_validator=verify, dispatch_function=dispatch)
                pending_templates = []
                guard()
                if last["dispatched_run_ids"]:
                    path = waves_dir / (inc._sha(last["dispatched_run_ids"]) + ".json")
                    if path.exists():
                        _require(json.loads(path.read_bytes()) == last, "feature dispatch wave evidence changed")
                    else:
                        inc._write(path, last)
                    wave_refs.append(registry.stage_artifact(path))
                    dispatches.extend(last["dispatched_run_ids"])
                if not last["dispatched_run_ids"] or not last["pending_batch_count"]:
                    break
            guard()
            return {"schema_version": SCHEMA, "training_purpose": "feature_pretraining", "policy": binding,
                    "dispatched_run_ids": dispatches, "completed": list(completed.values()),
                    "completed_batch_count": last["completed_batch_count"] if last else 0,
                    "pending_batch_count": last["pending_batch_count"] if last else None,
                    "blocked": last["blocked"] if last else [], "capacity_reports": capacities,
                    "capacity_deferred": deferred, "intake_durable": last is not None,
                    "dispatch_report_artifacts": wave_refs,
                    "max_parallel_workers": maximum, "reuse_native_workers": reuse_native_workers and native,
                    "weight_control_transport": control_transport,
                    "execution_mode": "native_feature_training" if native else "injected_test",
                    "resume_granularity": "completed_batch", "qualification_enforced": False,
                    "semantic_qualification_status": "deferred_not_evaluated", "source_repair_submitted": False,
                    "lake_executed": False, "heldout_canary": False, "global_holdout_verified": False,
                    "embedding_verification_scope": binding["embedding_verification_scope"], **_FALSE}
        finally:
            if pool is not None:
                pool.close()
            db.close()
