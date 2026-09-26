"""Immutable plans and restart reconciliation for registered v8 training jobs.

The registry remains the only writer. This layer neither creates another queue
nor retries uncertain attempts. It dispatches existing jobs through the normal
coordinator; callers retain responsibility for resource admission/supervision.
Plan completion means durable candidate transport, never optimizer improvement,
source authority, publication, promotion, or Lean admission.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from . import autoencoder_training_coordinator as coordinator
from .autoencoder_training_worker import CAMPAIGN_SCHEMA_VERSION, TrainingJobSpec, execute_training_job

SCHEMA = "autoencoder-campaign-plan-v1"
STATUS_SCHEMA = "autoencoder-campaign-plan-status-v1"
MAX_PLAN_BYTES = 4 * 1024 * 1024
MAX_BATCHES = 128
MAX_TOTAL_RECORDS = 32768
MAX_TOTAL_JOB_BYTES = 64 * 1024 * 1024
PARENT_POLICIES = {"common_fixed_parent", "explicit_registered_parents"}
_FALSE = ("admitted", "formalized", "source_authority_authenticated", "global_holdout_verified")
_ROOTS = ("source_inventory", "source_partitions", "embedding_receipt_set")
_BATCH_FIELDS = {"ordinal", "batch_id", "run_id", "job_id", "job_spec_artifact", "job_spec_sha256",
    "base_version_id", "training_record_ids", "validation_record_ids", "target_snapshot_id",
    "target_snapshot_artifact", "arrow_feature_weights_artifact", "training_config_sha256", "autoencoder_config_sha256"}
_COVERAGE_FIELDS = {"physical_row_count", "eligible_unique_input_count", "source_partition_counts",
    "unique_embedding_status_counts", "planned_training_record_count", "planned_validation_record_count",
    "planned_validation_occurrences"}
_FIELDS = {"schema_version", "artifact_root", "variant_id", "variant_manifest_sha256",
    "source_campaign_binding", "parent_policy", "batches", "coverage", *_FALSE}


class CampaignPlanError(ValueError):
    """A plan, registered job or durable completion has inconsistent bindings."""


def _require(value, message):
    if not value:
        raise CampaignPlanError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    except (ValueError, TypeError) as exc:
        raise CampaignPlanError("plan values must be finite JSON") from exc


def _sha(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _hash(value):
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def _token(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}", value) is not None


def _ref(value):
    _require(type(value) is dict and set(value) == {"sha256", "bytes"}
             and _hash(value["sha256"]) and type(value["bytes"]) is int
             and 0 < value["bytes"] < 2**63, "invalid artifact descriptor")
    return value


def _bare(value):
    return {key: value[key] for key in ("sha256", "bytes")}


def _batch_id(batch):
    return "sha256:" + _sha({key: value for key, value in batch.items() if key != "batch_id"})


def _validate(plan):
    _require(type(plan) is dict and set(plan) == _FIELDS, "unexpected plan fields")
    _require(plan["schema_version"] == SCHEMA and type(plan["parent_policy"]) is str
             and plan["parent_policy"] in PARENT_POLICIES,
             "unsupported campaign plan schema or parent policy")
    _require(all(plan[name] is False for name in _FALSE), "plan cannot claim semantic or admission authority")
    _require(type(plan["artifact_root"]) is str and Path(plan["artifact_root"]).is_absolute()
             and str(Path(plan["artifact_root"])) == plan["artifact_root"], "artifact root must be absolute and normalized")
    _require(_token(plan["variant_id"]) and _hash(plan["variant_manifest_sha256"]), "invalid variant identity")
    roots = plan["source_campaign_binding"]
    _require(type(roots) is dict and set(roots) == set(_ROOTS), "plan requires exactly three campaign roots")
    for ref in roots.values():
        _ref(ref)
    batches = plan["batches"]
    _require(type(batches) is list and 1 <= len(batches) <= MAX_BATCHES, "plan batch count exceeds bound")
    runs, jobs, train, validation, parents = set(), set(), set(), set(), set()
    validation_occurrences, total = 0, 0
    for index, batch in enumerate(batches):
        _require(type(batch) is dict and set(batch) == _BATCH_FIELDS, "unexpected batch fields")
        _require(type(batch["ordinal"]) is int and batch["ordinal"] == index
                 and batch["batch_id"] == _batch_id(batch), "batch identity or order differs")
        for name in ("run_id", "job_id", "base_version_id"):
            _require(_token(batch[name]), "invalid batch identifier")
        for name in ("job_spec_sha256", "training_config_sha256", "autoencoder_config_sha256"):
            _require(_hash(batch[name]), "invalid batch digest")
        _ref(batch["job_spec_artifact"])
        _require(batch["job_spec_artifact"]["bytes"] <= 64 * 1024 * 1024, "job artifact exceeds bound")
        _require(batch["run_id"] not in runs and batch["job_id"] not in jobs, "duplicate run or job")
        runs.add(batch["run_id"])
        jobs.add(batch["job_id"])
        parents.add(batch["base_version_id"])
        for name in ("target_snapshot_artifact", "arrow_feature_weights_artifact"):
            if batch[name] is not None:
                _ref(batch[name])
        _require(type(batch["target_snapshot_id"]) is str
                 and (batch["target_snapshot_id"] == "" or re.fullmatch("sha256:[0-9a-f]{64}", batch["target_snapshot_id"])),
                 "invalid target snapshot identity")
        _require(bool(batch["target_snapshot_id"]) == (batch["target_snapshot_artifact"] is not None),
                 "target snapshot binding is incomplete")
        selected = []
        for name in ("training_record_ids", "validation_record_ids"):
            ids = batch[name]
            _require(type(ids) is list and 1 <= len(ids) <= 256
                     and all(type(item) is str and re.fullmatch("sha256:[0-9a-f]{64}", item) for item in ids)
                     and len(set(ids)) == len(ids), "invalid ordered record selection")
            selected.append(set(ids))
            total += len(ids)
        _require(len(batch["training_record_ids"]) <= 128 and sum(map(len, selected)) <= 256,
                 "batch exceeds bounded cycle feedback/projection size")
        _require(not selected[0].intersection(selected[1]) and not train.intersection(selected[0]),
                 "role overlap or duplicate training members in one-pass plan")
        train.update(selected[0])
        validation.update(selected[1])
        validation_occurrences += len(batch["validation_record_ids"])
    _require(total <= MAX_TOTAL_RECORDS and not train.intersection(validation), "plan record bound or role isolation failed")
    _require(sum(batch["job_spec_artifact"]["bytes"] for batch in batches) <= MAX_TOTAL_JOB_BYTES,
             "plan aggregate job bytes exceed bound")
    _require(plan["parent_policy"] != "common_fixed_parent" or len(parents) == 1, "fixed-parent plan has different bases")
    coverage = plan["coverage"]
    _require(type(coverage) is dict and set(coverage) == _COVERAGE_FIELDS, "unexpected coverage fields")
    for name in _COVERAGE_FIELDS - {"source_partition_counts", "unique_embedding_status_counts"}:
        _require(type(coverage[name]) is int and 0 <= coverage[name] < 2**63, "invalid coverage count")
    for name, fields in (("source_partition_counts", {"train", "validation", "canary", "holdout"}),
                         ("unique_embedding_status_counts", {"embedded", "missing_input", "token_limit_exceeded", "unattempted"})):
        counts = coverage[name]
        _require(type(counts) is dict and set(counts) == fields
                 and all(type(value) is int and 0 <= value < 2**63 for value in counts.values()), "invalid coverage denominator")
    _require(coverage["planned_training_record_count"] == len(train)
             and coverage["planned_validation_record_count"] == len(validation)
             and coverage["planned_validation_occurrences"] == validation_occurrences, "planned coverage differs from selections")
    _require(sum(coverage["source_partition_counts"].values()) == coverage["physical_row_count"]
             and sum(coverage["unique_embedding_status_counts"].values()) == coverage["eligible_unique_input_count"],
             "campaign coverage denominators do not reconcile")


def encode_campaign_plan(plan) -> bytes:
    _validate(plan)
    raw = _raw(plan)
    _require(len(raw) <= MAX_PLAN_BYTES, "campaign plan exceeds byte bound")
    return raw


def decode_campaign_plan(raw: bytes) -> dict:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_PLAN_BYTES, "campaign plan exceeds byte bound")
    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, "duplicate JSON key")
            value[key] = item
        return value
    def invalid(value):
        raise CampaignPlanError("nonfinite JSON constant")
    try:
        plan = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CampaignPlanError("invalid plan JSON") from exc
    _require(encode_campaign_plan(plan) == raw, "plan JSON is not canonical")
    return plan


def _coverage(verification, batches):
    source = verification["source_campaign_verification"]
    partition = source["source_partition_verification"]
    receipt = source["receipt_set_verification"]
    return {"physical_row_count": partition["physical_row_count"],
        "eligible_unique_input_count": receipt["eligible_unique_input_count"],
        "source_partition_counts": partition["partition_counts"],
        "unique_embedding_status_counts": receipt["unique_status_counts"],
        "planned_training_record_count": len({key for batch in batches for key in batch["training_record_ids"]}),
        "planned_validation_record_count": len({key for batch in batches for key in batch["validation_record_ids"]}),
        "planned_validation_occurrences": sum(len(batch["validation_record_ids"]) for batch in batches)}


def _verify_extra_artifacts(registry, spec):
    inputs = coordinator.registered_checkpoint_inputs(registry, spec.base_version_id)
    _require(inputs["base_checkpoint"] == asdict(spec.base_checkpoint), "job base differs from registered version")
    expected = sorted(inputs["base_checkpoint_dependencies"], key=lambda item: item["sha256"])
    supplied = sorted((asdict(item) for item in spec.base_checkpoint_dependencies), key=lambda item: item["sha256"])
    _require(expected == supplied, "job base dependency closure differs")
    for ref in (spec.target_snapshot_artifact, spec.arrow_feature_weights_artifact):
        if ref is not None:
            bare = registry.verify_artifact({"sha256": ref.sha256, "bytes": ref.bytes})
            _require(Path(ref.path) == registry.artifact_path(bare), "shared artifact is outside owner CAS")


def _capture(registry, run_ids, parent_policy, *, root_scope=None):
    operation = nullcontext()
    if root_scope is not None:
        from .autoencoder_campaign_job_inputs import _root_scope_operation
        operation = _root_scope_operation(root_scope)
    with operation:
        _require(type(run_ids) in (list, tuple) and 1 <= len(run_ids) <= MAX_BATCHES
                 and all(_token(item) for item in run_ids) and len(set(run_ids)) == len(run_ids), "invalid bounded run selection")
        _require(type(parent_policy) is str and parent_policy in PARENT_POLICIES, "unsupported parent policy")
        resolved, batches, identity, job_bytes = [], [], None, 0
        for ordinal, run_id in enumerate(run_ids):
            # Bound retained inline vectors before loading the next complete job.
            registered = registry.get_run(run_id)
            descriptor = _ref(registered["spec"]["job_spec_artifact"])
            job_bytes += descriptor["bytes"]
            _require(job_bytes <= MAX_TOTAL_JOB_BYTES, "plan aggregate job bytes exceed bound")
            item = (coordinator.registered_corpus_job_inputs(registry, run_id) if root_scope is None else
                    coordinator._registered_corpus_job_inputs(registry, run_id, root_scope=root_scope))
            spec, run, variant, verified = item["spec"], item["run"], item["variant"], item["corpus_verification"]
            _require(spec.schema_version == CAMPAIGN_SCHEMA_VERSION, "campaign plan requires v8 registered jobs")
            _require(verified.get("source_campaign_verified") is True
                     and verified.get("produced_record_projection_verified") is True, "campaign job is not verified")
            current = (run["variant_id"], _sha(variant), variant["source_campaign_binding"])
            _require(identity is None or identity == current, "plan mixes variants or campaign roots")
            identity = current
            _verify_extra_artifacts(registry, spec)
            payload = spec.to_dict()
            batch = {"ordinal": ordinal, "run_id": run_id, "job_id": spec.job_id,
                "job_spec_artifact": item["job_spec_artifact"], "job_spec_sha256": spec.canonical_sha256,
                "base_version_id": spec.base_version_id, "training_record_ids": verified["training_record_ids"],
                "validation_record_ids": verified["validation_record_ids"], "target_snapshot_id": spec.target_snapshot_id,
                "target_snapshot_artifact": _bare(asdict(spec.target_snapshot_artifact)) if spec.target_snapshot_artifact else None,
                "arrow_feature_weights_artifact": _bare(asdict(spec.arrow_feature_weights_artifact)) if spec.arrow_feature_weights_artifact else None,
                "training_config_sha256": _sha(payload["training_config"]), "autoencoder_config_sha256": _sha(payload["autoencoder_config"])}
            batch["batch_id"] = _batch_id(batch)
            batches.append(batch)
            resolved.append(item)
        plan = {"schema_version": SCHEMA, "artifact_root": str(registry.artifact_root),
            "variant_id": identity[0], "variant_manifest_sha256": identity[1], "source_campaign_binding": identity[2],
            "parent_policy": parent_policy, "batches": batches,
            "coverage": _coverage(resolved[0]["corpus_verification"], batches), **{key: False for key in _FALSE}}
        encode_campaign_plan(plan)
        return plan, resolved


def build_campaign_plan(registry, run_ids, *, parent_policy="common_fixed_parent") -> dict:
    """Verify existing jobs and describe one bounded, ordered training pass.

    The plan never invents job IDs, source selections or future parent versions.
    Shared validation members may repeat; training members must be distinct.
    """
    return _build_campaign_plan(registry, run_ids, parent_policy=parent_policy)


def _build_campaign_plan(registry, run_ids, *, parent_policy="common_fixed_parent", root_scope=None):
    operation = nullcontext()
    if root_scope is not None:
        from .autoencoder_campaign_job_inputs import _root_scope_operation
        operation = _root_scope_operation(root_scope)
    with operation:
        before = _source_hash()
        captured = (_capture(registry, run_ids, parent_policy)[0] if root_scope is None else
                    _capture(registry, run_ids, parent_policy, root_scope=root_scope)[0])
        plan = decode_campaign_plan(encode_campaign_plan(captured))
        _require(before == _source_hash(), "campaign plan helper changed during construction")
        return plan


def seal_campaign_plan(registry, run_ids, *, parent_policy="common_fixed_parent") -> dict:
    """Store a freshly verified canonical plan in the existing immutable CAS."""
    return _seal_campaign_plan(registry, run_ids, parent_policy=parent_policy)


def _seal_campaign_plan(registry, run_ids, *, parent_policy="common_fixed_parent", root_scope=None):
    operation = nullcontext()
    if root_scope is not None:
        from .autoencoder_campaign_job_inputs import _root_scope_operation
        operation = _root_scope_operation(root_scope)
    with operation:
        before = _source_hash()
        plan = (build_campaign_plan(registry, run_ids, parent_policy=parent_policy) if root_scope is None else
                _build_campaign_plan(registry, run_ids, parent_policy=parent_policy, root_scope=root_scope))
        raw = encode_campaign_plan(plan)
        _require(before == _source_hash(), "campaign plan helper changed before sealing")
        descriptor, filename = tempfile.mkstemp(prefix=".campaign-plan-", dir=registry.artifact_root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            return registry.stage_artifact(filename, hashlib.sha256(raw).hexdigest())
        finally:
            Path(filename).unlink(missing_ok=True)


def _read_artifact(registry, ref, limit):
    _ref(ref)
    _require(ref["bytes"] <= limit, "artifact exceeds read bound")
    path = registry.artifact_path(registry.verify_artifact(ref))
    raw = coordinator._read_bounded(path, limit)
    _require(len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"], "artifact changed during reading")
    return raw


def _verify_completed_candidate(registry, spec, receipt, result, version, lease):
    """Verify retained CAS evidence, including pre-compaction job ancestry."""
    from .modal_autoencoder_patch_codec import MAX_PATCH_BYTES, decode_patch, replay_patch
    from .modal_autoencoder_sparse_checkpoint import checkpoint_identity, encode_manifest, resolve_checkpoint

    segments = receipt.get("sparse_patch_segments")
    _require(type(segments) is list, "missing accepted patch sequence")
    candidate = _bare(receipt["candidate"])
    expected = {"sparse_replay_verified": False, "sparse_patch_artifacts": [],
                "checkpoint_storage": "full_json", "checkpoint_dependencies": []}
    if not spec.capture_sparse_patches:
        _require(not segments and version["artifact"] == candidate, "unexpected sparse segments or full candidate")
        resolved = resolve_checkpoint(candidate, resolver=lambda ref: registry.artifact_path(registry.verify_artifact(ref)))
        identity = resolved.state.state_identity_record().to_dict()
        _require(identity == {**receipt["candidate_state_identity"], "revision": 0}, "completed full state identity differs")
        _require(dict(resolved.materialized_checkpoint) == receipt["candidate_materialized_checkpoint"],
                 "completed full materialized checkpoint differs")
    else:
        _require(len(segments) == receipt["optimizer_accepted_epochs"], "accepted segment count differs")
        allowed = {ref.sha256: asdict(ref) for ref in (spec.base_checkpoint, *spec.base_checkpoint_dependencies)}
        def base_resolver(ref):
            _require(ref["sha256"] in allowed and _bare(allowed[ref["sha256"]]) == ref,
                     "checkpoint dependency is outside job binding")
            return registry.artifact_path(registry.verify_artifact(ref))
        base = resolve_checkpoint(_bare(asdict(spec.base_checkpoint)), resolver=base_resolver)
        _require({ref["sha256"] for ref in base.artifacts} == set(allowed), "unused base checkpoint dependency")
        state = base.state
        _require(state.state_identity_record().to_dict() == receipt["base_state_identity"]
                 and dict(base.materialized_checkpoint) == receipt["base_materialized_checkpoint"],
                 "completed base state or materialized bytes differ")
        patches = []
        for index, descriptor in enumerate(segments):
            _require(type(descriptor) is dict, "invalid accepted segment descriptor")
            path = Path(descriptor["path"])
            _require(not path.is_symlink()
                     and path.resolve() == (Path(spec.output_directory) / f"accepted-{index:06d}.patch.json").resolve(),
                     "accepted segment attempt path differs")
            ref = _bare(descriptor)
            segment = decode_patch(_read_artifact(registry, ref, MAX_PATCH_BYTES))
            context = descriptor.get("capture_context", {})
            provenance = {"job_id": spec.job_id, "run_id": spec.run_id,
                          "job_spec_sha256": spec.canonical_sha256, "commit_label": context.get("label", "")}
            _require(dict(segment.provenance) == provenance, "accepted patch provenance differs")
            expected_context = {"base_state_identity": segment.base_state_identity,
                "result_state_identity": segment.result_state_identity, "base_revision": segment.patch.base_revision,
                "result_revision": segment.patch.result_revision}
            _require(all(context.get(key) == value for key, value in expected_context.items()), "patch capture context differs")
            replay_patch(state, segment, expected_base_version_id=spec.base_version_id, expected_sequence=index)
            patches.append(ref)
        materialized = checkpoint_identity(state)
        _require(state.state_identity_record().to_dict() == receipt["candidate_state_identity"]
                 and materialized == receipt["candidate_materialized_checkpoint"], "accepted patches do not reproduce candidate")
        expected.update(sparse_replay_verified=True, sparse_patch_artifacts=patches,
                        sparse_patch_bytes=sum(ref["bytes"] for ref in patches), candidate_materialized_checkpoint=materialized)
        if spec.candidate_storage == "sparse":
            manifest = encode_manifest(parent=_bare(asdict(spec.base_checkpoint)), base_version_id=spec.base_version_id,
                patches=patches, materialized_checkpoint=materialized, state_identity=state.state_identity(),
                result_revision=state.state_revision,
                provenance={"job_id": spec.job_id, "run_id": spec.run_id, "job_spec_sha256": spec.canonical_sha256})
            _require(_read_artifact(registry, candidate, 1024 * 1024) == manifest, "worker manifest ancestry or patch sequence differs")
            policy_dict = result["sparse_compaction_policy"]
            _require(type(policy_dict) is dict and set(policy_dict) == {"max_depth", "max_patch_fraction"}, "invalid recorded compaction policy")
            policy = coordinator.SparseCheckpointPolicy(**policy_dict)
            depth, cumulative = base.depth + 1, base.total_patch_bytes + expected["sparse_patch_bytes"]
            reasons = []
            if depth >= policy.max_depth:
                reasons.append("max_depth")
            if cumulative >= base.anchor_checkpoint["bytes"] * policy.max_patch_fraction:
                reasons.append("patch_fraction")
            expected.update(worker_candidate_artifact=candidate, sparse_compaction_policy=policy_dict,
                sparse_compaction_performed=bool(reasons), sparse_compaction_reasons=reasons,
                candidate_chain_depth_before_compaction=depth, candidate_cumulative_patch_bytes_before_compaction=cumulative)
            if reasons:
                _require(version["artifact"] == materialized, "compacted candidate differs from replayed bytes")
                registry.verify_artifact(materialized)
                expected.update(checkpoint_storage="full_json", checkpoint_dependencies=[], checkpoint_chain_depth=0,
                                checkpoint_cumulative_patch_bytes=0, checkpoint_anchor=materialized)
            else:
                _require(version["artifact"] == candidate, "registered sparse candidate differs from worker manifest")
                closure = {ref["sha256"]: dict(ref) for ref in (*base.artifacts, *patches)}
                expected.update(checkpoint_storage="sparse_manifest",
                    checkpoint_dependencies=sorted(closure.values(), key=lambda ref: ref["sha256"]),
                    checkpoint_chain_depth=depth, checkpoint_cumulative_patch_bytes=cumulative,
                    checkpoint_anchor=dict(base.anchor_checkpoint))
        else:
            _require(version["artifact"] == candidate == materialized, "registered full candidate differs from accepted replay")
            registry.verify_artifact(candidate)
        assignment = {key: lease[key] for key in ("run_id", "attempt", "owner_generation", "fence", "worker_id")}
        _require(result.get("sparse_acceptance_assignment") == assignment, "sparse acceptance lease assignment differs")
    _require(all(_raw(result.get(key)) == _raw(value) for key, value in expected.items()), "completed storage/replay summary differs")


def _completed(registry, item):
    spec, run = item["spec"], item["run"]
    completion = registry.get_run_completion(spec.run_id)
    _require(completion is not None and completion["run"] == run, "completed run changed during reconciliation")
    version, result = completion["candidate_version"], run["result"]
    _require(result.get("job_spec_sha256") == spec.canonical_sha256 and result.get("admitted") is False
             and result.get("promotion_performed") is False
             and result.get("execution_mode") in {"native_training", "injected_test"}, "completed job result differs")
    receipt_ref = result["worker_receipt_artifact"]
    receipt = coordinator._read_json(_read_artifact(registry, receipt_ref, 64 * 1024 * 1024))
    _require(type(receipt) is dict and receipt.get("execution_mode") == result["execution_mode"],
             "completed worker receipt execution mode differs")
    coordinator._verify_receipt_payload(spec, receipt, native=result["execution_mode"] == "native_training",
                                        corpus_verification=item["corpus_verification"])
    expected_summary = coordinator._result_summary(receipt, receipt_ref, native=result["execution_mode"] == "native_training")
    _require(all(_raw(result.get(key)) == _raw(value) for key, value in expected_summary.items()), "completed receipt and summary differ")
    _verify_completed_candidate(registry, spec, receipt, result, version, run["lease"])
    return version


def _inspect(registry, artifact):
    raw = _read_artifact(registry, artifact, MAX_PLAN_BYTES)
    plan = decode_campaign_plan(raw)
    _require(plan["artifact_root"] == str(registry.artifact_root), "plan artifact root differs from owner")
    current, resolved = _capture(registry, [batch["run_id"] for batch in plan["batches"]], plan["parent_policy"])
    _require(encode_campaign_plan(current) == raw, "plan differs from current verified registered jobs")
    rows = []
    for batch, item in zip(plan["batches"], resolved, strict=True):
        run, spec = item["run"], item["spec"]
        row = {"batch_id": batch["batch_id"], "run_id": spec.run_id, "job_id": spec.job_id,
               "attempt": run["attempt"], "fence": run["fence"]}
        if run["status"] == "completed":
            version = _completed(registry, item)
            row.update(status="completed", candidate_version_id=version["version_id"], candidate=version["artifact"])
        elif (run["status"] == "queued" and run["attempt"] == run["fence"] == 0
              and run["lease"] is None and run["result"] is None and not Path(spec.output_directory).exists()
              and Path(spec.output_directory).parent.is_dir()):
            row.update(status="queued")
        else:
            row.update(status="unresolved", reason="existing_attempt_requires_explicit_recovery", registry_status=run["status"])
        rows.append(row)
    counts = {status: sum(row["status"] == status for row in rows) for status in ("completed", "queued", "unresolved")}
    report = {"schema_version": STATUS_SCHEMA, "plan_artifact": dict(artifact), "plan_sha256": artifact["sha256"],
        "status": "unresolved" if counts["unresolved"] else "ready" if counts["queued"] else "complete",
        "batch_count": len(rows), **{key + "_count": value for key, value in counts.items()},
        "batches": rows, "coverage": plan["coverage"], **{key: False for key in _FALSE},
        "promotion_performed": False, "publication_performed": False}
    return report, resolved


def _source_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def inspect_campaign_plan(registry, artifact) -> dict:
    """Reverify every job and durable completion without dispatch or mutation."""
    before = _source_hash()
    report, _ = _inspect(registry, artifact)
    _require(before == _source_hash(), "campaign plan helper changed during inspection")
    return report


def run_campaign_plan(registry, artifact, *, max_new_batches=32, max_workers=2, lease_seconds=300.0,
                      poll_seconds=0.25, executor_factory=None, worker_function=execute_training_job) -> dict:
    """Dispatch an ordered bounded slice, then reverify durable progress.

    All entries are checked before the first claim. Running/failed/ambiguous
    attempts block dispatch. A completed run is skipped only after registry
    history, receipt and current checkpoint replay agree. This supplies resume
    between batches; it does not recover interrupted worker computation.
    """
    _require(type(max_new_batches) is int and 1 <= max_new_batches <= MAX_BATCHES, "invalid dispatch batch bound")
    _require(type(max_workers) is int and 1 <= max_workers <= 32, "invalid worker bound")
    before = _source_hash()
    report, resolved = _inspect(registry, artifact)
    selected = [] if report["status"] == "unresolved" else [
        item["spec"] for row, item in zip(report["batches"], resolved, strict=True) if row["status"] == "queued"][:max_new_batches]
    _require(before == _source_hash(), "campaign plan helper changed before dispatch")
    dispatch = None
    if selected:
        dispatch = coordinator.run_training_jobs(registry, selected, max_workers=max_workers,
            lease_seconds=lease_seconds, poll_seconds=poll_seconds,
            executor_factory=executor_factory, worker_function=worker_function)
        report, _ = _inspect(registry, artifact)
    _require(before == _source_hash(), "campaign plan helper changed during dispatch")
    return {**report, "dispatch": dispatch, "dispatched_run_ids": [spec.run_id for spec in selected],
        "completed_run_ids": [row["run_id"] for row in report["batches"] if row["status"] == "completed"],
        "deferred_run_ids": [row["run_id"] for row in report["batches"] if row["status"] == "queued"]}
