"""Bounded independent autoencoder lanes over immutable training batches.

One owner writes the registry. Spawned workers never share mutable model state.
Resume is at completed batch boundaries, not in the middle of an optimizer step.
The caller must reserve resources for the whole invocation before dispatch.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Sequence

from .autoencoder_training_worker import TrainingJobSpec, execute_training_job, verify_corpus_job_inputs
from . import autoencoder_training_coordinator as coordinator

SCHEMA = "autoencoder-incremental-training-v1"
MAX_BATCHES = 100_000
MAX_STATE_BYTES = 128 * 1024 * 1024


class IncrementalTrainingError(ValueError):
    pass


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _portable(value):
    if isinstance(value, dict):
        return {key: _portable(item) for key, item in value.items()
                if not (key == "path" and {"sha256", "bytes"}.issubset(value))}
    if isinstance(value, (list, tuple)):
        return [_portable(item) for item in value]
    return value


def batch_identity(spec: TrainingJobSpec) -> str:
    """Content identity, independent of owner paths and scheduling labels.

    Different evidence/code/split/optimizer identities intentionally make a new
    batch. Callers wanting record-granular assignment should supply one-record
    templates with stable evidence and dataset snapshot identities.
    """
    payload = spec.to_dict()
    for name in ("job_id", "run_id", "output_directory", "base_version_id"):
        payload.pop(name)
    return _sha(_portable(payload))


def assignment(spec: TrainingJobSpec, machine_shard_count: int, lane_count: int) -> dict:
    for name, value, maximum in (("machine_shard_count", machine_shard_count, 65536),
                                  ("lane_count", lane_count, 32)):
        if type(value) is not int or not 1 <= value <= maximum:
            raise IncrementalTrainingError(f"invalid {name}")
    digest = batch_identity(spec)
    # Separate hash domains avoid correlation between host and lane partitions.
    return {"batch_id": digest,
            "machine_shard_index": int(_sha(["machine", digest]), 16) % machine_shard_count,
            "lane_index": int(_sha(["lane", digest]), 16) % lane_count}


def _write(path, value):
    raw = _raw(value) + b"\n"
    if len(raw) > MAX_STATE_BYTES:
        raise IncrementalTrainingError("incremental state exceeds byte bound")
    fd, temporary = tempfile.mkstemp(prefix=".incremental-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "owner.lock").open("a+b") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IncrementalTrainingError("incremental directory already has an owner") from exc
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _stage_payload(registry, template):
    payload = template.to_dict()
    def stage(value):
        if isinstance(value, dict) and {"path", "sha256", "bytes"}.issubset(value):
            artifact = registry.stage_artifact(value["path"], value["sha256"])
            if artifact != {name: value[name] for name in ("sha256", "bytes")}:
                raise IncrementalTrainingError("staged artifact identity differs")
            return {**artifact, "path": str(registry.artifact_path(artifact))}
        if isinstance(value, list):
            return [stage(item) for item in value]
        if isinstance(value, dict):
            return {name: stage(item) for name, item in value.items()}
        return value
    return stage(payload)


def _policy(registry, spec):
    base = registry.get_version(spec.base_version_id)
    if base["artifact"] != {"sha256": spec.base_checkpoint.sha256, "bytes": spec.base_checkpoint.bytes}:
        raise IncrementalTrainingError("template baseline differs from registered version")
    variant = registry.get_variant(base["variant_id"])["manifest"]
    return {"variant_id": base["variant_id"], "variant": variant,
            "initial_base_version_id": spec.base_version_id,
            "code_identity": spec.code_identity,
            "expected_source_sha256": dict(spec.expected_source_sha256 or {}),
            "training_config": spec.to_dict()["training_config"],
            "autoencoder_config": spec.to_dict()["autoencoder_config"],
            "candidate_storage": spec.candidate_storage,
            "capture_sparse_patches": spec.capture_sparse_patches,
            **({"target_shard_max_bytes": spec.target_shard_max_bytes}
               if spec.target_shard_max_bytes != 64 * 1024 * 1024 else {})}


def _verify_completed(registry, spec):
    # Reuse the owner replay contract: a completed DuckDB row alone is not a
    # verified checkpoint, and a candidate never becomes a promoted model.
    from .autoencoder_campaign_plan import _completed
    run = registry.get_run(spec.run_id)
    result = _completed(registry, {"spec": spec, "run": run,
                                  "corpus_verification": verify_corpus_job_inputs(spec)})
    accepted = run["result"]["optimizer_accepted_epochs"]
    if type(accepted) is not int or accepted < 0:
        raise IncrementalTrainingError("invalid accepted epoch count")
    return result, run["result"], accepted


def _expected_job(registry, directory, binding, row, policy, parent):
    run_id = "incremental-" + _sha([binding, row["variant_id"], row["batch_id"]])
    payload = {**row["template"], **coordinator.registered_checkpoint_inputs(registry, parent),
               "job_id": run_id, "run_id": run_id, "base_version_id": parent,
               "output_directory": str(directory / "outputs" / run_id)}
    if parent != policy["initial_base_version_id"]:
        payload["arrow_feature_weights_artifact"] = None
    return TrainingJobSpec.from_dict(payload)


def _register_job(registry, directory, variant_id, spec):
    path = directory / (spec.run_id + ".json")
    if not path.exists() or path.read_bytes() != _raw(spec.to_dict()) + b"\n":
        raise IncrementalTrainingError("persisted job artifact changed")
    artifact = registry.stage_artifact(path)
    registry.create_run("create-" + spec.run_id, spec.run_id, variant_id, spec.base_version_id,
                        {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": artifact})


def _completion(registry, row, spec):
    version, result, accepted = _verify_completed(registry, spec)
    return {"batch_id": row["batch_id"], "run_id": spec.run_id,
            "variant_id": row["variant_id"], "lane_index": row["lane_index"],
            "optimizer_accepted_epochs": accepted, "candidate_version_id": version["version_id"],
            "next_base_version_id": version["version_id"] if accepted else spec.base_version_id,
            "consumed_without_update": not bool(accepted), "result": result}


def run_incremental_training(registry, templates: Sequence[TrainingJobSpec], *, state_directory,
                             machine_shard_count=1, machine_shard_index=0, lane_count=2,
                             max_batches=16, executor_factory=None,
                             worker_function=execute_training_job, completion_validator=None,
                             dispatch_function=None, intake_only=False):
    """Append immutable batches; independently continue each private lane.

    Baselines must be registered; template jobs need not be. Exact duplicates
    are skipped. A local indexed DuckDB progress database stores bounded rows,
    separate from the registry's sealed schema. Only this owner opens it. A
    restart verifies the latest completion/checkpoint of each populated lane;
    completed history remains durable without being rewritten or rescanned.
    Optional owner callbacks may validate (never mutate) completion evidence
    before any lane update, and supply a bounded dispatch transport. Defaults
    preserve the original optimizer-only behavior and stream identity.
    Explicit intake_only persists/verifies intake and recovered completions
    without dispatching a new worker; max_batches bounds remain unchanged.

    An optimizer rejection consumes the batch and retains its prior parent.
    Failed/running attempts block that lane for explicit recovery. Resource
    admission belongs to the invocation wrapper. Completion reports contain
    only newly finished and latest resume-verified rows, with global counters.
    """
    import duckdb
    if type(intake_only) is not bool:
        raise IncrementalTrainingError("intake_only must be a boolean")
    if completion_validator is not None and not callable(completion_validator):
        raise IncrementalTrainingError("completion validator must be callable")
    if dispatch_function is not None and not callable(dispatch_function):
        raise IncrementalTrainingError("dispatch function must be callable")

    def verified_completion(row, spec):
        result = _completion(registry, row, spec)
        if completion_validator is not None:
            prior = _sha(result)
            completion_validator(registry, spec, result)
            if _sha(result) != prior:
                raise IncrementalTrainingError("completion validator mutated owner-verified evidence")
        return result

    for name, value, maximum in (("machine_shard_count", machine_shard_count, 65536),
                                  ("lane_count", lane_count, 32), ("max_batches", max_batches, MAX_BATCHES)):
        if type(value) is not int or not 1 <= value <= maximum:
            raise IncrementalTrainingError(f"invalid {name}")
    if type(machine_shard_index) is not int or not 0 <= machine_shard_index < machine_shard_count:
        raise IncrementalTrainingError("invalid machine shard index")
    if len(templates) > MAX_BATCHES or any(type(spec) is not TrainingJobSpec for spec in templates):
        raise IncrementalTrainingError("invalid template sequence")
    directory = Path(state_directory).resolve()
    binding = {"schema_version": SCHEMA, "database_path": str(registry.database_path),
               "artifact_root": str(registry.artifact_root), "machine_shard_count": machine_shard_count,
               "machine_shard_index": machine_shard_index, "lane_count": lane_count}
    with _lock(directory):
        db = duckdb.connect(str(directory / "progress.duckdb"))
        try:
            db.execute("CREATE TABLE IF NOT EXISTS stream (singleton INTEGER PRIMARY KEY, binding VARCHAR NOT NULL, total_batches BIGINT NOT NULL, completed_batches BIGINT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS policies (variant_id VARCHAR PRIMARY KEY, payload VARCHAR NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS lanes (variant_id VARCHAR, lane_index INTEGER, head VARCHAR NOT NULL, last_batch VARCHAR, PRIMARY KEY(variant_id,lane_index))")
            db.execute("CREATE SEQUENCE IF NOT EXISTS batch_sequence START 1")
            db.execute("CREATE TABLE IF NOT EXISTS batches (ordinal BIGINT DEFAULT nextval('batch_sequence'), batch_id VARCHAR PRIMARY KEY, variant_id VARCHAR NOT NULL, lane_index INTEGER NOT NULL, template VARCHAR NOT NULL, job VARCHAR, completed VARCHAR)")
            db.execute("CREATE TABLE IF NOT EXISTS pending (batch_id VARCHAR PRIMARY KEY, variant_id VARCHAR NOT NULL, lane_index INTEGER NOT NULL, ordinal BIGINT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS pending_lane ON pending(variant_id,lane_index,ordinal)")
            found = db.execute("SELECT binding FROM stream WHERE singleton=1").fetchone()
            if found is None:
                db.execute("INSERT INTO stream VALUES (1,?,0,0)", [_raw(binding).decode()])
            elif json.loads(found[0]) != binding:
                raise IncrementalTrainingError("incremental owner/topology binding changed")
            policies = {key: json.loads(value) for key, value in db.execute("SELECT variant_id,payload FROM policies").fetchall()}
            skipped_remote = 0
            for template in templates:
                placed = assignment(template, machine_shard_count, lane_count)
                if placed["machine_shard_index"] != machine_shard_index:
                    skipped_remote += 1
                    continue
                policy = _policy(registry, template)
                variant_id = policy["variant_id"]
                if variant_id in policies and policies[variant_id] != policy:
                    raise IncrementalTrainingError("variant baseline/code/training policy changed; use a new stream")
                if db.execute("SELECT 1 FROM batches WHERE batch_id=?", [placed["batch_id"]]).fetchone():
                    continue
                payload = _stage_payload(registry, template)
                encoded = _raw(payload)
                if len(encoded) > 64 * 1024 * 1024:
                    raise IncrementalTrainingError("template exceeds bounded row size")
                db.execute("BEGIN TRANSACTION")
                try:
                    if variant_id not in policies:
                        db.execute("INSERT INTO policies VALUES (?,?)", [variant_id, _raw(policy).decode()])
                    db.execute("INSERT INTO lanes VALUES (?,?,?,NULL) ON CONFLICT DO NOTHING",
                               [variant_id, placed["lane_index"], policy["initial_base_version_id"]])
                    db.execute("INSERT INTO batches(batch_id,variant_id,lane_index,template) VALUES (?,?,?,?)",
                               [placed["batch_id"], variant_id, placed["lane_index"], encoded.decode()])
                    db.execute("INSERT INTO pending SELECT batch_id,variant_id,lane_index,ordinal FROM batches WHERE batch_id=?", [placed["batch_id"]])
                    db.execute("UPDATE stream SET total_batches=total_batches+1 WHERE singleton=1")
                    db.execute("COMMIT")
                except BaseException:
                    db.execute("ROLLBACK")
                    raise
                policies[variant_id] = policy

            def decode_row(raw):
                row = dict(zip(("batch_id", "variant_id", "lane_index", "template", "job", "completed"), raw))
                for name in ("template", "job", "completed"):
                    if row[name] is not None:
                        row[name] = json.loads(row[name])
                template = TrainingJobSpec.from_dict(row["template"])
                placed = assignment(template, machine_shard_count, lane_count)
                if placed != {"batch_id": row["batch_id"], "machine_shard_index": machine_shard_index,
                              "lane_index": row["lane_index"]}:
                    raise IncrementalTrainingError("persisted template identity or assignment changed")
                if _policy(registry, template) != policies[row["variant_id"]]:
                    raise IncrementalTrainingError("persisted variant policy changed")
                return row

            fields = "batch_id,variant_id,lane_index,template,job,completed"
            completed, heads = {}, {}
            # Only the durable tip of each lane requires checkpoint replay on
            # restart. Replaying a sparse tip still verifies its entire closure.
            for variant_id, lane, head, last in db.execute("SELECT * FROM lanes ORDER BY variant_id,lane_index").fetchall():
                heads[(variant_id, lane)] = head
                if last is None:
                    if head != policies[variant_id]["initial_base_version_id"]:
                        raise IncrementalTrainingError("empty lane parent changed")
                    continue
                raw = db.execute("SELECT " + fields + " FROM batches WHERE batch_id=?", [last]).fetchone()
                if raw is None:
                    raise IncrementalTrainingError("lane completion missing")
                row = decode_row(raw)
                if row["completed"] is None or row["job"] is None or (row["variant_id"], row["lane_index"]) != (variant_id,lane):
                    raise IncrementalTrainingError("lane completion binding changed")
                spec = TrainingJobSpec.from_dict(row["job"])
                expected = _expected_job(registry,directory,binding,row,policies[variant_id],spec.base_version_id)
                if expected.to_dict() != row["job"]:
                    raise IncrementalTrainingError("persisted job differs from template")
                _register_job(registry,directory,variant_id,spec)
                verified = verified_completion(row,spec)
                if verified != row["completed"] or verified["next_base_version_id"] != head:
                    raise IncrementalTrainingError("durable completion or lane head changed")
                completed[row["batch_id"]] = verified
            dispatched, reports, blocked = [], [], {}
            (directory / "outputs").mkdir(exist_ok=True)
            while True:
                selected, recovered = [], False
                for lane, head in heads.items():
                    if lane in blocked:
                        continue
                    pending = db.execute("SELECT batch_id FROM pending WHERE variant_id=? AND lane_index=? ORDER BY ordinal LIMIT 1", list(lane)).fetchone()
                    raw = None if pending is None else db.execute("SELECT " + fields + " FROM batches WHERE batch_id=?", [pending[0]]).fetchone()
                    if pending is not None and raw is None:
                        raise IncrementalTrainingError("pending batch missing from durable inventory")
                    if raw is None:
                        continue
                    row = decode_row(raw)
                    spec = _expected_job(registry,directory,binding,row,policies[lane[0]],head)
                    if row["job"] is not None:
                        if row["job"] != spec.to_dict():
                            raise IncrementalTrainingError("persisted job or checkpoint chain changed")
                        _register_job(registry,directory,row["variant_id"],spec)
                        run = registry.get_run(spec.run_id)
                        if run["status"] == "completed":
                            verified = verified_completion(row,spec)
                            db.execute("BEGIN TRANSACTION")
                            try:
                                db.execute("UPDATE batches SET completed=? WHERE batch_id=?", [_raw(verified).decode(),row["batch_id"]])
                                db.execute("UPDATE lanes SET head=?,last_batch=? WHERE variant_id=? AND lane_index=?",
                                           [verified["next_base_version_id"],row["batch_id"],*lane])
                                db.execute("DELETE FROM pending WHERE batch_id=?", [row["batch_id"]])
                                db.execute("UPDATE stream SET completed_batches=completed_batches+1 WHERE singleton=1")
                                db.execute("COMMIT")
                            except BaseException:
                                db.execute("ROLLBACK")
                                raise
                            heads[lane] = verified["next_base_version_id"]
                            completed[row["batch_id"]] = verified
                            recovered = True
                            continue
                        if run["status"] != "queued" or run["attempt"] != 0 or Path(spec.output_directory).exists():
                            blocked[lane] = {"batch_id":row["batch_id"],"run_id":spec.run_id,
                                             "status":run["status"],"recovery_required":True}
                            continue
                    if not intake_only and len(dispatched)+len(selected) < max_batches and len(selected) < lane_count:
                        selected.append((row,spec))
                if not selected:
                    if recovered:
                        continue
                    counts = db.execute("SELECT total_batches,completed_batches FROM stream WHERE singleton=1").fetchone()
                    return {"schema_version":SCHEMA,"binding":binding,"dispatched_run_ids":dispatched,
                            "completed":list(completed.values()),"completed_batch_count":counts[1],
                            "completion_window":"latest_resumed_lane_tips_and_current_invocation",
                            "blocked":list(blocked.values()),"pending_batch_count":counts[0]-counts[1],
                            "skipped_other_machine_templates":skipped_remote,"dispatch_reports":reports,
                            "execution_mode":"native_training" if executor_factory is None and worker_function is execute_training_job else "injected_test",
                            "resume_granularity":"completed_batch","admitted":False,"formalized":False,
                            "promotion_performed":False,"publication_performed":False}
                for row,spec in selected:
                    if row["job"] is None:
                        path = directory / (spec.run_id+".json")
                        if path.exists() and path.read_bytes() != _raw(spec.to_dict())+b"\n":
                            raise IncrementalTrainingError("orphan job artifact differs")
                        if not path.exists():
                            _write(path,spec.to_dict())
                        db.execute("UPDATE batches SET job=? WHERE batch_id=?",[_raw(spec.to_dict()).decode(),row["batch_id"]])
                    _register_job(registry,directory,row["variant_id"],spec)
                report = (dispatch_function or coordinator.run_training_jobs)(registry,[spec for _,spec in selected],
                    max_workers=min(lane_count,len(selected)),executor_factory=executor_factory,worker_function=worker_function)
                reports.append(report)
                dispatched.extend(spec.run_id for _,spec in selected)
        finally:
            db.close()
