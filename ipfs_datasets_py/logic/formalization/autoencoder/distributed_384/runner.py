"""Local threaded campaigns with immutable Hugging Face exchange.

The host owns one DuckDB connection. Workers receive numerical inputs, never a
connection or tuning labels. Every round refits the declared corpus head while
retaining its published encoder and target vocabulary. Candidates remain advisory.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
import hashlib
import os
import threading
import time
import uuid

from . import contracts as c, numerics, profiles
from .local_store import LocalTrainingStore
from .. import structured_source_384 as decoder


def _write_bytes(path, data):
    """Preserve the original checkpoint bytes, with create-only publication."""
    c.require(type(data) is bytes and 0 < len(data) <= c.MAX_BYTES, "bounded bytes required")
    path = Path(path).absolute()
    directory = None
    temporary = ".base-" + uuid.uuid4().hex
    created = False
    try:
        path, directory = c._parent_fd(path, create=True)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
        except FileExistsError:
            c.require(c._read_at(directory, path.name, c.MAX_BYTES) == data, "immutable base conflicts")
        os.fsync(directory)
        c.require(c.read_bound(path)[0] == data, "published base path changed")
    finally:
        if created:
            os.unlink(temporary, dir_fd=directory)
        if directory is not None:
            os.close(directory)
    return path


def _rows(path):
    value = c.read_json(path)
    if type(value) is dict:
        c.require(set(value) == {"rows"}, "row wrapper must contain only rows")
        value = value["rows"]
    c.require(type(value) is list and value, "nonempty row list required")
    return value


def _round(round_dir, *, training=False, validation=False):
    root = Path(round_dir).absolute()
    plan = c.read_json(root / "plan.json")
    numerics.validate_plan(plan)
    base, reference = c.read_json_bound(root / "base.json")
    c.require(reference["sha256"] == plan["base_checkpoint_sha256"], "base bytes differ")
    numerics._base(base, plan)
    result = dict(root=root, plan=plan, base=base)
    for enabled, name in ((training, "training"), (validation, "validation")):
        if enabled:
            rows = _rows(root / (name + ".json"))
            c.require(c.digest(rows) == plan["dataset"][name + "_rows_sha256"], name + " corpus differs")
            result[name] = rows
    return result


def _repo(plan):
    return profiles.get_profile(plan["domain_id"])["checkpoint_descriptor"]["repository_id"]


def _prefix(plan, kind):
    return "training/structured384/" + plan["plan_id"] + "/" + kind


def _summary(root, plan):
    return dict(schema="distributed-structured-384-round/v1", round_dir=str(root),
        **c.binding(plan), shards=len(plan["shards"]), machine_count=plan["machine_count"],
        training_rows=len(plan["training_manifest"]), validation_rows=len(plan["validation_manifest"]),
        repository_id=_repo(plan), **c.FALSE)


def prepare_round(domain, training_path, validation_path, output_dir, *, source_descriptor,
                  base_path=None, cache_dir=None, local_files_only=False, shard_size=32,
                  machine_count=1, required_families=None):
    c.require(type(local_files_only) is bool, "boolean local_files_only required")
    profile = profiles.get_profile(domain)
    if base_path is None:
        base_path = profiles.load_parent(domain, cache_dir=cache_dir, local_files_only=local_files_only)
    base_raw, _ = c.read_bound(base_path)
    base = c._parse(base_raw)
    c.require(base.get("domain_id") == domain, "checkpoint domain differs")
    training, validation = _rows(training_path), _rows(validation_path)
    required = profile["default_required_families"] if required_families is None else required_families
    c.require(type(required) in (list, tuple) and bool(required), "nonempty required families needed")
    root = Path(output_dir).absolute()
    saved_base = _write_bytes(root / "base.json", base_raw)
    plan = numerics.make_plan(saved_base, training, validation, source_descriptor=source_descriptor,
        shard_size=shard_size, machine_count=machine_count, required_families=required)
    c.write_json(root / "training.json", training)
    c.write_json(root / "validation.json", validation)
    c.write_json(root / "plan.json", plan)
    c.write_json(root / "inputs.json", dict(schema="distributed-structured-384-inputs/v1",
        plan=plan, base_checkpoint_raw=base_raw.decode("utf-8"),
        training_rows=training, validation_rows=validation))
    return _summary(root, plan)


def publish_inputs(round_dir, *, upload=False):
    from . import exchange
    c.require(type(upload) is bool, "boolean upload required")
    data = _round(round_dir, training=True, validation=True)
    root, plan = data["root"], data["plan"]
    if upload:
        c.require(plan["dataset"]["source"].get("redistribution_allowed") is True,
                  "publishing plaintext inputs requires reviewed redistributable provenance")
    staged = exchange.stage_bundle(root / "inputs.json", root / "bundles" / "inputs",
        domain_id=plan["domain_id"], kind="inputs", binding=c.binding(plan))
    result = exchange.publish_bundle(staged["manifest_path"], repository_id=_repo(plan),
        prefix=_prefix(plan, "inputs"), upload=upload)
    c.write_json(root / "receipts" / (c.digest(result) + ".json"), result)
    return result


def fetch_inputs(reference, output_dir, *, local_files_only=False):
    from . import exchange
    c.require(type(reference) is dict and reference.get("kind") == "inputs", "inputs reference required")
    c.require(type(local_files_only) is bool, "boolean local_files_only required")
    root = Path(output_dir).absolute()
    received = exchange.receive_bundle(reference, root / "received-inputs",
                                       local_files_only=local_files_only)
    value = c.read_json(received["payload_path"])
    _write_bytes(root / "base.json", value["base_checkpoint_raw"].encode("utf-8"))
    c.write_json(root / "training.json", value["training_rows"])
    c.write_json(root / "validation.json", value["validation_rows"])
    c.write_json(root / "plan.json", value["plan"])
    c.write_json(root / "inputs.json", value)
    data = _round(root, training=True, validation=True)
    return _summary(root, data["plan"])


def _work(plan, base, training, shard_id):
    start = time.perf_counter()
    rows = numerics.shard_rows(plan, training, shard_id)
    update = numerics.compute_update(plan, base, rows, shard_id)
    return update, dict(shard_id=shard_id, rows=len(rows), thread=threading.current_thread().name,
                        numerical_seconds=time.perf_counter() - start)


def run_local(round_dir, database_path, artifact_root, *, machine_index=0, workers=4, upload=False):
    from threadpoolctl import threadpool_limits
    from . import exchange
    c.require(type(workers) is int and 1 <= workers <= 32, "workers must be within 1..32")
    c.require(type(upload) is bool, "boolean upload required")
    data = _round(round_dir, training=True)
    root, plan, base = data["root"], data["plan"], data["base"]
    c.require(type(machine_index) is int and 0 <= machine_index < plan["machine_count"],
              "machine index out of range")
    assigned = [s for s in plan["shards"] if s["machine_index"] == machine_index]
    timings, references = [], []
    started = time.perf_counter()
    with LocalTrainingStore(database_path, artifact_root) as store:
        store.register_campaign(plan, root / "base.json")
        # BLAS limits are process-wide, so set them once around the whole pool.
        with threadpool_limits(limits=1), ThreadPoolExecutor(max_workers=workers,
                thread_name_prefix="ir384-worker") as pool:
            active = {}
            for shard in assigned:
                lease = store.claim(plan, shard["shard_id"], "local-" + str(machine_index))
                if lease is not None:
                    future = pool.submit(_work, plan, base, data["training"], shard["shard_id"])
                    active[future] = lease
            while active:
                done, _ = wait(active, timeout=20, return_when=FIRST_COMPLETED)
                for future in done:
                    lease = active.pop(future)
                    update, timing = future.result()
                    path = c.write_json(root / "updates" / (update["update_id"] + ".json"), update)
                    store.complete(plan, lease, path)
                    timings.append(timing)
                for future, lease in list(active.items()):
                    active[future] = store.renew(plan, lease)
        numerical_done = time.perf_counter()
        completed = store.completed(plan)
        for shard in assigned:
            path = completed.get(shard["shard_id"])
            c.require(path is not None, "assigned shard incomplete")
            update = c.read_json(path)
            numerics.validate_update(plan, base, update)
            staged = exchange.stage_bundle(path, root / "bundles" / update["update_id"],
                domain_id=plan["domain_id"], kind="update", binding=c.binding(plan))
            result = exchange.publish_bundle(staged["manifest_path"], repository_id=_repo(plan),
                prefix=_prefix(plan, "updates"), upload=upload)
            references.append(result)
            c.write_json(root / "receipts" / (c.digest(result) + ".json"), result)
        result = dict(schema="distributed-structured-384-worker-run/v1", **c.binding(plan),
            machine_index=machine_index, workers=workers, computed_shards=len(timings),
            completed_assigned_shards=len(assigned), timings=timings, publications=references,
            numerical_wall_seconds=numerical_done-started, total_wall_seconds=time.perf_counter()-started,
            database_path=str(Path(database_path).absolute()), **c.FALSE)
        c.write_json(root / "runs" / (c.digest(result) + ".json"), result)
        return result


def _projection_evidence(plan, checkpoint, validation):
    rows = [{k: row[k] for k in ("id", "source_text", "embedding")} for row in validation]
    predictions = decoder.Runtime(checkpoint).infer(rows)["rows"]
    expected = {row["id"]: row for row in rows}
    c.require(len(predictions) == len(rows) and {row["id"] for row in predictions} == set(expected),
              "projection prediction identities differ")
    by_id = {row["id"]: row for row in predictions}
    reports = []
    counts = {f: dict(supported=0, missing_context=0, failed=0) for f in plan["recipe"]["required_families"]}
    for row in rows:
        prediction = by_id[row["id"]]
        c.require(prediction["source_sha256"] == hashlib.sha256(row["source_text"].encode()).hexdigest()
            and prediction["head_sha256"] == checkpoint["head_sha256"]
            and prediction["projection_sha256"] == checkpoint["projection_sha256"]
            and prediction["target_access"] is False and prediction["teacher_forcing"] is False,
            "projection prediction provenance differs")
        report = profiles.project_candidate(plan["domain_id"], prediction["candidate_ir"],
                    row["source_text"], required_families=plan["recipe"]["required_families"])
        for family in report["families"]:
            counts[family["family_id"]][family["status"]] += 1
        reports.append(dict(id=row["id"], candidate_sha256=c.digest(prediction["candidate_ir"]),
            source_sha256=prediction["source_sha256"], head_sha256=prediction["head_sha256"],
            projection_sha256=prediction["projection_sha256"], report=report))
    return dict(schema="distributed-structured-384-projections/v1", rows=reports,
        family_counts=counts, all_required_families_supported=all(
            r["report"]["all_required_families_supported"] for r in reports),
        target_access=False, qualification_scope="typed_projection_only", lake_build_executed=False, **c.FALSE)


def merge_round(round_dir, database_path, artifact_root, *, update_paths=(), discover=False,
                upload=False, full_anchor=False):
    from . import exchange
    c.require(all(type(value) is bool for value in (discover, upload, full_anchor)),
              "boolean discover, upload and full_anchor required")
    c.require(type(update_paths) in (list, tuple), "update_paths must be a list or tuple")
    data = _round(round_dir, validation=True)
    root, plan, base = data["root"], data["plan"], data["base"]
    paths = list(update_paths)
    references = []
    if discover:
        references = exchange.discover_bundles(_repo(plan), _prefix(plan, "updates"),
                                               kind="update", expected_binding=c.binding(plan))
        for reference in references:
            received = exchange.receive_bundle(reference, root / "imported" / reference["manifest_sha256"])
            paths.append(received["payload_path"])
    with LocalTrainingStore(database_path, artifact_root) as store:
        store.register_campaign(plan, root / "base.json")
        completed = store.completed(plan)
        known = {key: c.read_json(path)["update_id"] for key, path in completed.items()}
        for path in paths:
            update = c.read_json(path)
            numerics.validate_update(plan, base, update)
            shard_id = update["shard_id"]
            if shard_id in known:
                c.require(known[shard_id] == update["update_id"], "conflicting duplicate shard update")
                continue
            lease = store.claim(plan, shard_id, "coordinator-import")
            c.require(lease is not None, "unexpected completed shard")
            store.complete(plan, lease, path)
            known[shard_id] = update["update_id"]
        updates = [c.read_json(path) for path in store.completed(plan).values()]
        result = numerics.merge_updates(plan, base, updates, data["validation"])
        evidence = result["report"]
        evidence["projection_evidence"] = _projection_evidence(plan, result["checkpoint"], data["validation"])
        checkpoint_path = c.write_json(root / "checkpoints" / (c.digest(result["checkpoint"]) + ".json"), result["checkpoint"])
        evidence_path = c.write_json(root / "evidence" / (c.digest(evidence) + ".json"), evidence)
        version = store.record_checkpoint(plan, checkpoint_path, evidence)
        kind = "anchors" if full_anchor else "checkpoints"
        staged = exchange.stage_bundle(checkpoint_path, root / "bundles" / kind,
            domain_id=plan["domain_id"], kind="checkpoint", binding=c.binding(plan),
            parent_path=None if full_anchor else root / "base.json")
        request = dict(repository_id=_repo(plan), prefix=_prefix(plan, kind),
                       manifest_path=str(staged["manifest_path"]))
        if upload:
            publication_path = c.write_json(root / "publication-plans" / (c.digest(request) + ".json"), request)
            queued = store.enqueue_publication(plan, version["version_id"], publication_path)
            event = store.publication_status(queued["event_id"])
            if event["status"] == "acknowledged":
                publication = event["receipt"]
            else:
                delivery = store.claim_publication(queued["event_id"], "coordinator-publisher", lease_seconds=3600)
                publication = exchange.publish_bundle(upload=True, **request)
                store.ack_publication(queued["event_id"], delivery["lease"], publication)
        else:
            publication = exchange.publish_bundle(upload=False, **request)
        summary = dict(schema="distributed-structured-384-merged-run/v1", **c.binding(plan),
            checkpoint_path=str(checkpoint_path), evidence_path=str(evidence_path),
            version_id=version["version_id"], publication=publication,
            discovered_updates=len(references), report=evidence, **c.FALSE)
        c.write_json(root / "merges" / (c.digest(summary) + ".json"), summary)
        return summary
