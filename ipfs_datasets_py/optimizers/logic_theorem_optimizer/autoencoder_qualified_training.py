"""Resumable, bounded training with candidate qualification at every attempt.

The owner alone writes DuckDB. Optimizer workers retain private state and emit
sparse checkpoints. A failed qualification is durable work, never an admission
or a qualified completion. The original optimizer-only runner remains a lower
level primitive; the operator entry point uses this runner.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from . import autoencoder_incremental_training as inc
from . import autoencoder_training_coordinator as coordinator
from .autoencoder_training_worker import TrainingJobSpec, SampleRecord, execute_training_job

SCHEMA = "autoencoder-qualified-incremental-training-v1"
GATES = ("metric_gate", "semantic_gate", "family_syntax_gate", "lake_gate", "heldout_gate")


def _text_key(text):
    return hashlib.sha256(" ".join(text.casefold().split()).encode()).hexdigest()


def _artifact(registry, path):
    ref = registry.stage_artifact(path)
    return {**ref, "path": str(registry.artifact_path(ref))}


def _read_artifact(registry, descriptor):
    ref = {key: descriptor[key] for key in ("sha256", "bytes")}
    registry.verify_artifact(ref)
    return json.loads(registry.artifact_path(ref).read_bytes())


def _disposition(receipt, round_number, max_rounds):
    qualified = all(receipt.get("gate_results", {}).get(name, {}).get("passed") is True for name in GATES)
    if receipt.get("qualified") is not qualified:
        raise inc.IncrementalTrainingError("qualification summary differs from required gates")
    retry = not qualified and receipt.get("needs_training") is True and round_number < max_rounds
    status = "qualified" if qualified else "pending" if retry else "training_exhausted" if receipt.get("needs_training") else "needs_repair"
    return qualified, retry, status


def _validation(spec, policy):
    # Explicit qualification samples supplement (never silently replace) any
    # optimizer tuning validation in a prebuilt job. CLI jobs train on their
    # own rows and keep all qualification validation outside the optimizer.
    rows = [asdict(row) for row in spec.validation_samples] + policy["qualification_samples"]
    return list({inc._sha(row): row for row in rows}.values())


def _verify_receipt_binding(receipt, spec, policy):
    if policy["execution_mode"] != "native":
        return
    if any(receipt.get("source_sha256", {}).get(key) != value
           for key, value in (spec.expected_source_sha256 or {}).items() if key != "worker"):
        raise inc.IncrementalTrainingError("qualification differs from training producer source")
    samples = {"training": [asdict(row) for row in spec.samples],
               "heldout": _validation(spec, policy)}
    if receipt.get("sample_set_sha256") != inc._sha(samples):
        raise inc.IncrementalTrainingError("qualification sample binding changed")
    if receipt.get("requested_model_config") != spec.to_dict()["autoencoder_config"]:
        raise inc.IncrementalTrainingError("qualification model configuration changed")


def _job(registry, directory, binding, row, policy, parent):
    run_id = "qualified-" + inc._sha([binding, row["batch_id"], row["round"]])
    payload = {**row["template"], **coordinator.registered_checkpoint_inputs(registry, parent),
               "job_id": run_id, "run_id": run_id, "base_version_id": parent,
               "output_directory": str(directory / "outputs" / run_id)}
    if parent != policy["initial_base_version_id"]:
        payload["arrow_feature_weights_artifact"] = None
    return TrainingJobSpec.from_dict(payload)


def _qualify(registry, directory, row, spec, completed, policy, qualifier):
    version_id = completed["candidate_version_id"]
    inputs = coordinator.registered_checkpoint_inputs(registry, version_id)
    record_path = directory / (spec.run_id + ".qualification.json")
    expected = {"candidate_version_id": version_id,
                "candidate_artifact": {key: inputs["base_checkpoint"][key] for key in ("sha256", "bytes")},
                "job_sha256": spec.canonical_sha256, "qualification_policy": policy}
    if record_path.exists():
        record = json.loads(record_path.read_bytes())
        if record["binding"] != expected:
            raise inc.IncrementalTrainingError("qualification binding changed")
        receipt = _read_artifact(registry, record["receipt_artifact"])
    else:
        output = directory / "qualifications" / spec.run_id
        # An unfinished qualifier has not produced authoritative evidence. Do
        # not overwrite its artifacts or silently retry an uncertain process.
        if output.exists():
            raise inc.IncrementalTrainingError("unfinished qualification requires recovery: " + spec.run_id)
        receipt = qualifier(inputs["base_checkpoint"], version_id,
                            [asdict(sample) for sample in spec.samples], output,
                            checkpoint_dependencies=inputs.get("base_checkpoint_dependencies", ()),
                            model_config=spec.to_dict()["autoencoder_config"],
                            heldout_samples=_validation(spec, policy),
                            lake_timeout_seconds=policy["lake_timeout_seconds"])
        if receipt.get("candidate_version_id") != version_id or receipt.get("candidate_artifact") != expected["candidate_artifact"]:
            raise inc.IncrementalTrainingError("qualifier returned evidence for another candidate")
        _verify_receipt_binding(receipt, spec, policy)
        _disposition(receipt, row["round"], policy["max_training_rounds"])
        # The staged envelope is the resume authority; a DuckDB flag alone is
        # never sufficient evidence of a model or Lake result.
        receipt = {key: value for key, value in receipt.items() if key != "receipt_artifact"}
        temporary = directory / (spec.run_id + ".qualification-payload.json")
        inc._write(temporary, receipt)
        record = {"binding": expected, "receipt_artifact": _artifact(registry, temporary)}
        inc._write(record_path, record)
    gates = receipt.get("gate_results", {})
    passed = all(gates.get(name, {}).get("passed") is True for name in GATES)
    if receipt.get("qualified") is not passed:
        raise inc.IncrementalTrainingError("qualification summary differs from required gates")
    if receipt.get("candidate_version_id") != version_id or receipt.get("candidate_artifact") != expected["candidate_artifact"]:
        raise inc.IncrementalTrainingError("persisted qualification candidate changed")
    _verify_receipt_binding(receipt, spec, policy)
    return receipt, record["receipt_artifact"]


def run_qualified_incremental_training(registry, templates, *, state_directory,
        machine_shard_count=1, machine_shard_index=0, lane_count=2, max_batches=16,
        max_training_rounds=3, lake_timeout_seconds=120, producer_identity=None,
        qualification_samples=(), control_transport="quack", publication_repository=None,
        executor_factory=None, worker_function=execute_training_job, qualifier=None):
    """Train, qualify and retry measured metric failures within fixed budgets.

    Validation is disjoint from gradient-training intake across the entire
    stream. Qualification validation participates in repeated selection, so it
    is tuning validation, not an independent generalization canary. Structural
    failures create repair tasks; additional SGD cannot itself repair a parser.
    A new state directory is required for migration from optimizer-only v1.
    """
    import duckdb
    from .autoencoder_candidate_qualification import qualify_candidate
    native = qualifier is None and executor_factory is None and worker_function is execute_training_job
    qualifier = qualify_candidate if qualifier is None else qualifier
    for name, value, maximum in (("machine_shard_count", machine_shard_count, 65536),
                                 ("lane_count", lane_count, 32), ("max_batches", max_batches, 100000),
                                 ("max_training_rounds", max_training_rounds, 100),
                                 ("lake_timeout_seconds", lake_timeout_seconds, 600)):
        if type(value) is not int or not 1 <= value <= maximum:
            raise inc.IncrementalTrainingError("invalid " + name)
    if type(machine_shard_index) is not int or not 0 <= machine_shard_index < machine_shard_count:
        raise inc.IncrementalTrainingError("invalid machine shard index")
    if control_transport not in {"quack", "owner"}:
        raise inc.IncrementalTrainingError("invalid weight control transport")
    if publication_repository not in (None, "justicedao/uscode-autoformal-span-cache"):
        raise inc.IncrementalTrainingError("unsupported sparse publication repository")
    if len(templates) > inc.MAX_BATCHES or any(type(spec) is not TrainingJobSpec for spec in templates):
        raise inc.IncrementalTrainingError("invalid templates")
    if any(spec.arrow_embedding_inputs_artifact is not None for spec in templates):
        raise inc.IncrementalTrainingError("mapped embedding inputs need an explicit qualification sample resolver; supplied vectors are supported")
    qualification_samples = [asdict(row if isinstance(row, SampleRecord) else SampleRecord.from_dict(row))
                             for row in qualification_samples]
    if len(qualification_samples) > 32:
        raise inc.IncrementalTrainingError("qualification validation exceeds 32 rows")
    policy = {"max_training_rounds": max_training_rounds, "lake_timeout_seconds": lake_timeout_seconds,
              "required_gates": list(GATES), "min_cosine": .72, "max_reconstruction_loss": .20,
              "producer_identity": producer_identity, "qualification_samples": qualification_samples,
              "control_transport": control_transport,
              "publication_repository": publication_repository,
              "execution_mode": "native" if native else "injected_test"}
    directory = Path(state_directory).resolve()
    binding = {"schema_version": SCHEMA, "database_path": str(registry.database_path),
               "artifact_root": str(registry.artifact_root), "machine_shard_count": machine_shard_count,
               "machine_shard_index": machine_shard_index, "lane_count": lane_count, "policy": policy}
    with inc._lock(directory):
        if (directory / "progress.duckdb").exists():
            raise inc.IncrementalTrainingError("optimizer-only progress requires a new qualified stream directory")
        db = duckdb.connect(str(directory / "qualification.duckdb"))
        try:
            db.execute("CREATE TABLE IF NOT EXISTS stream (singleton INTEGER PRIMARY KEY, binding VARCHAR NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS policies (variant_id VARCHAR PRIMARY KEY, payload VARCHAR NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS lanes (variant_id VARCHAR, lane_index INTEGER, head VARCHAR NOT NULL, tip VARCHAR, PRIMARY KEY(variant_id,lane_index))")
            db.execute("CREATE SEQUENCE IF NOT EXISTS batch_sequence START 1")
            db.execute("CREATE TABLE IF NOT EXISTS batches (ordinal BIGINT DEFAULT nextval('batch_sequence'), batch_id VARCHAR PRIMARY KEY, variant_id VARCHAR, lane_index INTEGER, template VARCHAR NOT NULL, round INTEGER NOT NULL, status VARCHAR NOT NULL, latest VARCHAR)")
            db.execute("CREATE INDEX IF NOT EXISTS active_batches ON batches(status,variant_id,lane_index,ordinal)")
            db.execute("CREATE TABLE IF NOT EXISTS attempts (run_id VARCHAR PRIMARY KEY, batch_id VARCHAR NOT NULL, round INTEGER NOT NULL, job VARCHAR NOT NULL, completed VARCHAR, UNIQUE(batch_id,round))")
            db.execute("CREATE TABLE IF NOT EXISTS splits (text_key VARCHAR PRIMARY KEY, split VARCHAR NOT NULL)")
            found = db.execute("SELECT binding FROM stream WHERE singleton=1").fetchone()
            if found is None:
                db.execute("INSERT INTO stream VALUES (1,?)", [inc._raw(binding).decode()])
            elif json.loads(found[0]) != binding:
                raise inc.IncrementalTrainingError("qualified owner/topology/policy binding changed")
            policies = {key: json.loads(value) for key, value in db.execute("SELECT * FROM policies").fetchall()}
            for sample in qualification_samples:
                key = _text_key(sample["text"])
                old = db.execute("SELECT split FROM splits WHERE text_key=?", [key]).fetchone()
                if old and old[0] != "validation":
                    raise inc.IncrementalTrainingError("training/validation source overlap")
                db.execute("INSERT INTO splits VALUES (?,'validation') ON CONFLICT DO NOTHING", [key])
            skipped = 0
            for template in templates:
                placed = inc.assignment(template, machine_shard_count, lane_count)
                # Register split exclusions even for remote shards: a shared
                # validation row must never train on another local lane/host.
                split_entries = {}
                for split, rows in (("training", template.samples), ("validation", template.validation_samples)):
                    for sample in rows:
                        key = _text_key(sample.text)
                        old = db.execute("SELECT split FROM splits WHERE text_key=?", [key]).fetchone()
                        if (old and old[0] != split) or (key in split_entries and split_entries[key] != split):
                            raise inc.IncrementalTrainingError("training/validation source overlap")
                        split_entries[key] = split
                for key, split in split_entries.items():
                    db.execute("INSERT INTO splits VALUES (?,?) ON CONFLICT DO NOTHING", [key, split])
                if placed["machine_shard_index"] != machine_shard_index:
                    skipped += 1
                    continue
                item_policy = inc._policy(registry, template)
                variant = item_policy["variant_id"]
                if variant in policies and policies[variant] != item_policy:
                    raise inc.IncrementalTrainingError("variant code/training policy changed; use a new stream")
                if db.execute("SELECT 1 FROM batches WHERE batch_id=?", [placed["batch_id"]]).fetchone():
                    continue
                payload = inc._stage_payload(registry, template)
                db.execute("BEGIN TRANSACTION")
                try:
                    if variant not in policies:
                        db.execute("INSERT INTO policies VALUES (?,?)", [variant, inc._raw(item_policy).decode()])
                    db.execute("INSERT INTO lanes VALUES (?,?,?,NULL) ON CONFLICT DO NOTHING",
                               [variant, placed["lane_index"], item_policy["initial_base_version_id"]])
                    db.execute("INSERT INTO batches(batch_id,variant_id,lane_index,template,round,status) VALUES (?,?,?,?,1,'pending')",
                               [placed["batch_id"], variant, placed["lane_index"], inc._raw(payload).decode()])
                    db.execute("COMMIT")
                except BaseException:
                    db.execute("ROLLBACK")
                    raise
                policies[variant] = item_policy

            def verify_attempt(run_id):
                raw = db.execute("SELECT job,completed,batch_id,round FROM attempts WHERE run_id=?", [run_id]).fetchone()
                if raw is None or raw[1] is None:
                    raise inc.IncrementalTrainingError("lane tip lacks verified attempt")
                spec, saved = TrainingJobSpec.from_dict(json.loads(raw[0])), json.loads(raw[1])
                if spec.run_id != run_id or saved["run_id"] != run_id or (saved["batch_id"], saved["round"]) != raw[2:]:
                    raise inc.IncrementalTrainingError("attempt identity changed")
                batch = db.execute("SELECT template,variant_id,lane_index FROM batches WHERE batch_id=?", [raw[2]]).fetchone()
                if batch is None or (saved["variant_id"], saved["lane_index"]) != batch[1:]:
                    raise inc.IncrementalTrainingError("attempt batch binding changed")
                template = TrainingJobSpec.from_dict(json.loads(batch[0]))
                if inc.batch_identity(template) != saved["batch_id"]:
                    raise inc.IncrementalTrainingError("completed template identity changed")
                row = {**saved, "template": template.to_dict()}
                if _job(registry, directory, binding, row, policies[saved["variant_id"]], spec.base_version_id).to_dict() != spec.to_dict():
                    raise inc.IncrementalTrainingError("completed job binding changed")
                inc._register_job(registry, directory, saved["variant_id"], spec)
                verified = inc._completion(registry, saved, spec)
                if verified != saved["optimizer"]:
                    raise inc.IncrementalTrainingError("optimizer completion changed")
                receipt = _read_artifact(registry, saved["qualification_artifact"])
                if receipt.get("candidate_version_id") != verified["candidate_version_id"]:
                    raise inc.IncrementalTrainingError("qualification tip version changed")
                expected_artifact = registry.get_version(verified["candidate_version_id"])["artifact"]
                if receipt.get("candidate_artifact") != expected_artifact or saved["qualified"] != all(
                        receipt.get("gate_results", {}).get(name, {}).get("passed") is True for name in GATES):
                    raise inc.IncrementalTrainingError("qualification tip evidence changed")
                qualified, _, status = _disposition(receipt, saved["round"], max_training_rounds)
                if saved["qualification_status"] != status or saved["qualified"] != qualified:
                    raise inc.IncrementalTrainingError("qualification status changed")
                _verify_receipt_binding(receipt, spec, policy)
                _read_artifact(registry, saved["repair_outbox"])
                return saved

            heads, completed = {}, {}
            for variant, lane, head, tip in db.execute("SELECT * FROM lanes ORDER BY variant_id,lane_index").fetchall():
                heads[(variant, lane)] = head
                if tip:
                    saved = verify_attempt(tip)
                    if (saved["optimizer"]["next_base_version_id"] != head or
                            (saved["variant_id"], saved["lane_index"]) != (variant, lane)):
                        raise inc.IncrementalTrainingError("private lane head changed")
                    completed[tip] = saved
                elif head != policies[variant]["initial_base_version_id"]:
                    raise inc.IncrementalTrainingError("initial lane head changed")
            (directory / "outputs").mkdir(exist_ok=True)
            (directory / "qualifications").mkdir(exist_ok=True)
            (directory / "repair-outbox").mkdir(exist_ok=True)
            dispatched, reports, blocked = [], [], {}
            while True:
                selected, recovered = [], False
                for lane, head in heads.items():
                    if lane in blocked:
                        continue
                    raw = db.execute("SELECT batch_id,variant_id,lane_index,template,round FROM batches WHERE status='pending' AND variant_id=? AND lane_index=? ORDER BY ordinal LIMIT 1", list(lane)).fetchone()
                    if not raw:
                        continue
                    row = dict(zip(("batch_id", "variant_id", "lane_index", "template", "round"), raw))
                    row["template"] = json.loads(row["template"])
                    template = TrainingJobSpec.from_dict(row["template"])
                    if inc.assignment(template, machine_shard_count, lane_count) != {
                            "batch_id": row["batch_id"], "machine_shard_index": machine_shard_index, "lane_index": lane[1]}:
                        raise inc.IncrementalTrainingError("persisted template or assignment changed")
                    if inc._policy(registry, template) != policies[lane[0]]:
                        raise inc.IncrementalTrainingError("persisted training policy changed")
                    spec = _job(registry, directory, binding, row, policies[lane[0]], head)
                    attempt = db.execute("SELECT job FROM attempts WHERE run_id=?", [spec.run_id]).fetchone()
                    if attempt:
                        if json.loads(attempt[0]) != spec.to_dict():
                            raise inc.IncrementalTrainingError("persisted attempt or checkpoint chain changed")
                        inc._register_job(registry, directory, lane[0], spec)
                        run = registry.get_run(spec.run_id)
                        if run["status"] == "completed":
                            optimization = inc._completion(registry, row, spec)
                            receipt, artifact = _qualify(registry, directory, row, spec, optimization, policy, qualifier)
                            qualified, retry, status = _disposition(receipt, row["round"], max_training_rounds)
                            tasks = list(receipt.get("repair_todos", ()))
                            publication = None
                            if qualified and publication_repository:
                                from ...huggingface.autoencoder_incremental import (
                                    IncrementalPublicationError, stage_sparse_update, enqueue_sparse_update,
                                )
                                # Queue locally before the progress commit. An
                                # owner crash replays this exact immutable plan;
                                # uploads happen after durable training intake.
                                try:
                                    staged = stage_sparse_update(registry, optimization["candidate_version_id"],
                                        {key: artifact[key] for key in ("sha256", "bytes")},
                                        directory / "weight-publications" / spec.run_id,
                                        lane_id=f"shard-{machine_shard_index}-lane-{lane[1]}",
                                        repository_id=publication_repository)
                                    publication = enqueue_sparse_update(registry, staged["manifest_path"])
                                except IncrementalPublicationError as exc:
                                    publication = {"status": "deferred", "uploaded": False,
                                                   "reason": str(exc), "admitted": False}
                                    tasks.append({"kind": "publication_repair", "candidate_version_id": optimization["candidate_version_id"],
                                                  "evidence": publication, "qualification_artifact": artifact,
                                                  "acceptance": "Publish verified sparse closure and evidence without weakening gates or uploading an unapproved full anchor.",
                                                  "admitted": False})
                            if status == "training_exhausted":
                                tasks.append({"kind": "training_repair", "reason": "bounded_training_rounds_exhausted",
                                              "acceptance": "Meet unchanged absolute metric, semantic, syntax and Lake gates.",
                                              "evidence": receipt.get("metric_gate", {}), "admitted": False})
                            outbox = {"schema_version": "qualification-repair-outbox/v1", "run_id": spec.run_id,
                                      "candidate_version_id": optimization["candidate_version_id"],
                                      "qualification_artifact": artifact, "source_samples": row["template"]["samples"],
                                      "tasks": tasks, "supervisor_submitted": False, "published": False, "admitted": False}
                            outpath = directory / "repair-outbox" / (spec.run_id + ".json")
                            if outpath.exists() and json.loads(outpath.read_bytes()) != outbox:
                                raise inc.IncrementalTrainingError("durable repair outbox changed")
                            if not outpath.exists():
                                inc._write(outpath, outbox)
                            saved = {"batch_id": row["batch_id"], "variant_id": lane[0], "lane_index": lane[1],
                                     "round": row["round"], "run_id": spec.run_id, "optimizer": optimization,
                                     "qualification_artifact": artifact, "qualified": qualified,
                                     "qualification_status": status, "repair_outbox": _artifact(registry, outpath),
                                     "publication": publication,
                                     "admitted": False, "formalized": False}
                            db.execute("BEGIN TRANSACTION")
                            try:
                                db.execute("UPDATE attempts SET completed=? WHERE run_id=?", [inc._raw(saved).decode(), spec.run_id])
                                db.execute("UPDATE batches SET status=?,round=?,latest=? WHERE batch_id=?",
                                           [status, row["round"] + int(retry), spec.run_id, row["batch_id"]])
                                db.execute("UPDATE lanes SET head=?,tip=? WHERE variant_id=? AND lane_index=?",
                                           [optimization["next_base_version_id"], spec.run_id, *lane])
                                db.execute("COMMIT")
                            except BaseException:
                                db.execute("ROLLBACK")
                                raise
                            heads[lane] = optimization["next_base_version_id"]
                            completed[spec.run_id] = saved
                            recovered = True
                            continue
                        if run["status"] != "queued" or run["attempt"] != 0 or Path(spec.output_directory).exists():
                            blocked[lane] = {"batch_id": row["batch_id"], "run_id": spec.run_id,
                                             "status": run["status"], "recovery_required": True}
                            continue
                    if len(dispatched) + len(selected) < max_batches and len(selected) < lane_count:
                        selected.append((row, spec))
                if not selected:
                    if recovered:
                        continue
                    counts = dict(db.execute("SELECT status,count(*) FROM batches GROUP BY status").fetchall())
                    return {"schema_version": SCHEMA, "binding": binding, "dispatched_run_ids": dispatched,
                            "completed": list(completed.values()), "batch_status_counts": counts,
                            "qualified_batch_count": counts.get("qualified", 0),
                            "pending_batch_count": counts.get("pending", 0),
                            "completed_batch_count": sum(counts.values()) - counts.get("pending", 0),
                            "blocked": list(blocked.values()), "dispatch_reports": reports,
                            "skipped_other_machine_templates": skipped,
                            "execution_mode": "native_training_and_qualification" if native else "injected_test",
                            "resume_granularity": "qualified_attempt", "heldout_canary": False,
                            "validation_role": "tuning_validation_repeated_candidate_selection",
                            "weight_control_transport": control_transport,
                            "admitted": False, "formalized": False, "promotion_performed": False,
                            "publication_performed": False}
                for row, spec in selected:
                    path = directory / (spec.run_id + ".json")
                    if path.exists() and path.read_bytes() != inc._raw(spec.to_dict()) + b"\n":
                        raise inc.IncrementalTrainingError("orphan job artifact differs")
                    if not path.exists():
                        inc._write(path, spec.to_dict())
                    db.execute("INSERT INTO attempts(run_id,batch_id,round,job) VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                               [spec.run_id, row["batch_id"], row["round"], inc._raw(spec.to_dict()).decode()])
                    inc._register_job(registry, directory, row["variant_id"], spec)
                if control_transport == "quack":
                    from ...duckdb_control.autoencoder_shared_weight_control import SharedWeightRegistry
                    with SharedWeightRegistry(registry, enable_prototype=True) as shared:
                        report = coordinator.run_training_jobs(shared, [spec for _, spec in selected],
                            max_workers=min(lane_count, len(selected)), executor_factory=executor_factory,
                            worker_function=worker_function)
                        report["weight_control"] = shared.transport_report()
                else:
                    report = coordinator.run_training_jobs(registry, [spec for _, spec in selected],
                        max_workers=min(lane_count, len(selected)), executor_factory=executor_factory,
                        worker_function=worker_function)
                    report["weight_control"] = {"transport": "trusted_owner_local", "native_quack": False}
                reports.append(report)
                dispatched.extend(spec.run_id for _, spec in selected)
        finally:
            db.close()
