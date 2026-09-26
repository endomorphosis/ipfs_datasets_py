"""Single-owner orchestration of bounded native daemon invocations.

Only the owner calls the registry. Child processes receive immutable files,
and final checkpoint verification runs independently of the training child.
Completion creates a candidate, never a branch promotion or a Lean admit.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
import uuid

from .autoencoder_daemon_invocation_contracts import (
    ROOT, REQUEST_SCHEMA, SHADOW_REQUEST_SCHEMA, WEIGHT_REQUEST_SCHEMA, LAUNCH_SCHEMA, MAX_REQUEST_BYTES, MAX_RESULT_BYTES,
    MAX_CHECKPOINT_BYTES, MAX_ARROW_FEATURE_WEIGHT_BYTES, DaemonInvocationError, canonical, digest, describe,
    execution_environment, identifier, parse_json, read_json, reference,
    safe_path, validate_request, verify, write_new,
)
from .autoencoder_daemon_operation_journal import DurableDaemonOperationJournal
from .autoencoder_daemon_resources import DaemonResourceReservation, _process, _group_usage

WORKER_SCRIPT = Path(__file__).with_name("autoencoder_daemon_invocation_worker.py")


def _artifact(ref):
    return {key: ref[key] for key in ("sha256", "bytes")}


def _result_reference(path, observed):
    ref = describe(path)
    if canonical(parse_json(verify(ref, MAX_RESULT_BYTES))) != canonical(observed):
        raise DaemonInvocationError("child result changed after supervised observation")
    return ref


def _checked_weight_result(result, weights, base, base_identity):
    """Reconcile native validation with the owner's sealed input descriptors."""
    observed = result.get("arrow_feature_weights", {})
    provenance = observed.get("provenance", {})
    if (observed.get("base_verified") is not True or observed.get("closed") is not True
            or observed.get("poisoned") is not False
            or canonical(provenance.get("artifact")) != canonical(_artifact(weights))
            or canonical(provenance.get("base_artifact")) != canonical(_artifact(base))
            or canonical(provenance.get("base_identity")) != canonical(base_identity)):
        raise DaemonInvocationError("native feature-weight validation differs from the sealed base/sidecar")


def _terminate(process, identity):
    # The leader may already have exited while descendants still own work.
    # Check its recorded Linux birth identity before signalling a reused PID.
    if identity is not None and _group_usage(identity)["live_processes"]:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                break
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                process.poll()
                if not _group_usage(identity)["live_processes"]:
                    break
                time.sleep(0.05)
            if not _group_usage(identity)["live_processes"]:
                break
        if _group_usage(identity)["live_processes"]:
            raise DaemonInvocationError("isolated child process group did not terminate")
    if process.poll() is None:
        process.wait(timeout=10)


def _assert_live_lease(registry, lease):
    current = registry.get_run(lease["run_id"])
    if current["status"] != "running":
        raise DaemonInvocationError("execution run is no longer running")
    # Same local owner contract as CompleteRun. Historical ClaimRun/RenewLease
    # receipts alone never assert that their lease is still live.
    registry._check_lease(lease, current["lease"])


def _child(mode, query, output, *, cwd, environment, reservation, timeout_seconds, heartbeat=lambda: None):
    """Supervise an isolated process group; a timeout never starts a replacement."""
    log_path = output.with_suffix(".log")
    started = time.monotonic()
    process = None
    child_identity = None
    primary = None
    with log_path.open("xb") as log:
        try:
            # Script bootstrap installs seccomp before importing package
            # ancestors; -m would import those ancestors before the filter.
            process = subprocess.Popen([sys.executable, str(WORKER_SCRIPT), mode, str(query), str(output)],
                cwd=cwd, env=dict(environment), stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True)
            observed = _process(process.pid)
            if observed is not None:
                child_identity = {key: observed[key] for key in ("pid", "birth")}
            reservation.check_usage(cwd, child_pid=process.pid)
            next_usage = time.monotonic() + 5
            while process.poll() is None:
                heartbeat()
                if time.monotonic() >= next_usage:
                    reservation.check_usage(cwd)
                    next_usage = time.monotonic() + 5
                if time.monotonic() - started > timeout_seconds:
                    raise DaemonInvocationError("native invocation subprocess exceeded hard timeout")
                time.sleep(min(0.2, max(0.01, timeout_seconds / 100)))
            heartbeat()
            if process.returncode != 0:
                raise DaemonInvocationError(f"{mode} child failed with exit {process.returncode}; see {log_path}")
            if child_identity is not None and _group_usage(child_identity)["live_processes"]:
                raise DaemonInvocationError("native child returned with a live descendant process")
            reservation.check_usage(cwd)
            result = read_json(output, MAX_RESULT_BYTES)
            if result.get("success") is not True:
                raise DaemonInvocationError(f"{mode} child did not produce a successful receipt")
            return result
        except BaseException as exc:
            primary = exc
            raise
        finally:
            try:
                if process is not None:
                    _terminate(process, child_identity)
                log.flush()
                os.fsync(log.fileno())
            except BaseException as cleanup:
                if primary is None:
                    raise
                primary.add_note(f"child cleanup also failed: {type(cleanup).__name__}")


def _reservation(policy):
    if type(policy) is not dict or set(policy) != {"ledger_path", "roots", "storage_bytes", "memory_mb", "cpu_slots"}:
        raise DaemonInvocationError("invalid closed invocation resource policy")
    return DaemonResourceReservation(policy["ledger_path"], roots=policy["roots"],
        storage_bytes=policy["storage_bytes"], memory_mb=policy["memory_mb"],
        cpu_slots=policy["cpu_slots"], timeout_seconds=0, ledger_lock_timeout_seconds=5)


def _within_roots(path, policy):
    path = safe_path(path)
    if not any(path == Path(root) or Path(root) in path.parents for root in policy["roots"]):
        raise DaemonInvocationError("owner artifact/output path is outside reserved campaign roots")


def _stage(registry, path, expected_sha256, *, heartbeat=lambda: None):
    # stage_artifact performs file work and _ensure_owner, but no connection or
    # SQL calls. All registry commands stay on the calling owner thread.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="daemon-artifact-stage") as pool:
        future = pool.submit(registry.stage_artifact, path, expected_sha256=expected_sha256)
        while not future.done():
            heartbeat()
            time.sleep(0.1)
        return future.result()


def prepare_daemon_invocation(registry: Any, *, run_id: str, variant_id: str,
        base_version_id: str, input_snapshot: Mapping[str, Any], daemon_argv: Sequence[str],
        output_directory: str | Path, resource_policy: Mapping[str, Any],
        environment_overrides: Mapping[str, str] | None = None,
        sparse_shadow: bool = False, arrow_feature_weights: Mapping[str, Any] | None = None) -> dict:
    """Create a distinct daemon run bound to actual native parsed arguments.

    The output directory must already exist and belongs exclusively to this
    invocation. Repeated preparation resolves the exact CreateRun operation.
    This call does not start training, acquire its execution lease, or promote.
    Optional sparse shadow verification is sealed into a distinct v2 request;
    the default retains the existing v1 request and full candidate semantics.
    Explicit mapped feature weights use v3, bound to this invocation's base.
    The owner stages their exact bytes; retries compare content, not a source
    pathname that may name another identical immutable copy.
    """
    identifier(run_id, "run_id")
    identifier(variant_id, "variant_id")
    if type(sparse_shadow) is not bool:
        raise DaemonInvocationError("sparse_shadow must be a bool")
    weights = (None if arrow_feature_weights is None else
               reference(arrow_feature_weights, MAX_ARROW_FEATURE_WEIGHT_BYTES, with_path=True))
    request_schema = (WEIGHT_REQUEST_SCHEMA if weights is not None else
                      SHADOW_REQUEST_SCHEMA if sparse_shadow else REQUEST_SCHEMA)
    output = safe_path(output_directory)
    if not output.is_dir():
        raise DaemonInvocationError("invocation output must be an existing directory")
    policy = dict(resource_policy)
    _within_roots(output, policy)
    _within_roots(registry.artifact_root, policy)
    binding = {"schema": request_schema, "run_id": run_id, "variant_id": variant_id,
               "base_version_id": base_version_id}
    journal_path = output / "owner-operations.json"
    if not journal_path.exists() and any(output.iterdir()):
        raise DaemonInvocationError("nonempty invocation output has no durable owner journal")
    with DurableDaemonOperationJournal(journal_path, binding) as journal:
        prepared = journal.get_metadata("prepared")
        if prepared is not None:
            request = validate_request(parse_json(verify(prepared["request"], MAX_REQUEST_BYTES)))
            if (request["daemon_argv"] != list(daemon_argv) or request["input_snapshot"] != dict(input_snapshot)
                    or request["resource_policy"] != policy
                    or request["environment"] != execution_environment(environment_overrides)
                    or request.get("sparse_shadow", False) is not sparse_shadow
                    or (weights is not None and _artifact(request["arrow_feature_weights"]) != _artifact(weights))):
                raise DaemonInvocationError("preparation retry changed immutable settings")
            journal.invoke(registry, "create-run", "CreateRun", {
                "run_id": run_id, "variant_id": variant_id, "base_version_id": base_version_id,
                "spec": {"schema": request_schema, "request_artifact": _artifact(prepared["request"])}})
            return prepared
        with _reservation(policy) as reservation:
            preparation = output / ("prepare-" + uuid.uuid4().hex)
            preparation.mkdir(mode=0o700)
            reservation.check_usage(preparation)
            reservation.account_external_bytes("owner-journal", 8 * 1024 * 1024)
            version = registry.get_version(base_version_id)
            if version["variant_id"] != variant_id:
                raise DaemonInvocationError("registered base belongs to another variant")
            ref = registry.verify_artifact(version["artifact"])
            base = {**ref, "path": str(registry.artifact_path(ref))}
            reference(base, MAX_CHECKPOINT_BYTES, with_path=True)
            snapshot = dict(input_snapshot)
            reference(snapshot, 1024 * 1024, with_path=True)
            if str(registry.artifact_path(_artifact(snapshot))) != snapshot["path"]:
                raise DaemonInvocationError("input snapshot is not staged with this owner")
            registry.verify_artifact(_artifact(snapshot))
            capsule = parse_json(verify(snapshot, 1024 * 1024))
            from .autoencoder_training_coordinator import registered_corpus_job_inputs
            from ...duckdb_control.contracts import canonical_json_bytes
            anchor = registered_corpus_job_inputs(registry, capsule["run_id"])
            variant = registry.get_variant(variant_id)["manifest"]
            import hashlib
            variant_sha = hashlib.sha256(canonical_json_bytes(variant)).hexdigest()
            if (capsule["variant_id"] != variant_id or capsule["variant_manifest_sha256"] != variant_sha
                    or capsule["job_spec_sha256"] != anchor["spec"].canonical_sha256
                    or capsule["job_spec_artifact"] != anchor["job_spec_artifact"]
                    or capsule["artifact_root"] != str(registry.artifact_root)):
                raise DaemonInvocationError("input capsule differs from registered owner anchor")
            environment = execution_environment(environment_overrides)
            query = preparation / "configuration-query.json"
            weight_settings = {}
            if weights is not None:
                verify(weights, MAX_ARROW_FEATURE_WEIGHT_BYTES)
                reservation.account_external_bytes(weights["sha256"], weights["bytes"])
                staged_weights = registry.stage_artifact(weights["path"], expected_sha256=weights["sha256"])
                if staged_weights != _artifact(weights):
                    raise DaemonInvocationError("staged feature weights differ from explicit descriptor")
                weight_settings["arrow_feature_weights"] = {
                    **staged_weights, "path": str(registry.artifact_path(staged_weights))}
            write_new(query, {"daemon_argv": list(daemon_argv), "base_artifact": base,
                              "input_snapshot": snapshot, **weight_settings})
            described = _child("describe", query, preparation / "configuration.json",
                cwd=preparation, environment=environment, reservation=reservation, timeout_seconds=120)
            if weights is not None:
                _checked_weight_result(described, weight_settings["arrow_feature_weights"], base,
                                       described["base_identity"])
            if described["effective_arguments"]["run_id"] != run_id:
                raise DaemonInvocationError("native run ID differs from owner execution run")
            for field, value in (("autoencoder_corpus_input", snapshot["path"]),
                    ("autoencoder_corpus_input_sha256", snapshot["sha256"]),
                    ("autoencoder_corpus_input_bytes", snapshot["bytes"])):
                if described["effective_arguments"].get(field) != value:
                    raise DaemonInvocationError("actual daemon input descriptor differs from owner capsule")
            options = ({"sparse_shadow": sparse_shadow, **weight_settings} if weights is not None else
                       {"sparse_shadow": True} if sparse_shadow else {})
            request = validate_request({**binding, **options, "base_artifact": base,
                "base_identity": described["base_identity"], "input_snapshot": snapshot,
                "variant_manifest_sha256": variant_sha, "daemon_argv": list(daemon_argv),
                "effective_arguments": described["effective_arguments"], "environment": environment,
                "producer_identity": described["producer_identity"], "output_directory": str(output),
                "resource_policy": policy})
            local = write_new(preparation / "request.json", request, MAX_REQUEST_BYTES)
            reservation.account_external_bytes(local["sha256"], local["bytes"])
            staged = registry.stage_artifact(local["path"], expected_sha256=local["sha256"])
            request_ref = {**staged, "path": str(registry.artifact_path(staged))}
            prepared = {"request": request_ref, "journal_path": str(journal_path), "binding": binding}
            # Persist before CreateRun; a lost response reuses this exact request.
            journal.set_metadata("prepared", prepared)
            reservation.check_usage(preparation)
            journal.invoke(registry, "create-run", "CreateRun", {
                "run_id": run_id, "variant_id": variant_id, "base_version_id": base_version_id,
                "spec": {"schema": request_schema, "request_artifact": staged}})
            reservation.check_usage(preparation)
            reservation.release(artifacts_durable=True)
            return prepared


def run_owned_daemon_invocation(registry: Any, prepared: Mapping[str, Any], *,
        lease_seconds: float = 300, timeout_seconds: float = 900) -> dict:
    """Run one real native cycle; independently verify and register its result.

    A restart resolves a pending completion before inspecting current files.
    Uncommitted attempts are quarantined, never attached to a fresh lease.
    """
    import math
    for name, value, maximum in (("lease_seconds", lease_seconds, 86400), ("timeout_seconds", timeout_seconds, 86400)):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 < value <= maximum:
            raise DaemonInvocationError(f"invalid {name}")
    if set(prepared) != {"request", "journal_path", "binding"}:
        raise DaemonInvocationError("invalid prepared invocation handle")
    safe_path(prepared["journal_path"])  # Missing restart history must not create a new journal.
    invocation_deadline = time.monotonic() + timeout_seconds
    with DurableDaemonOperationJournal(prepared["journal_path"], prepared["binding"]) as journal:
        if journal.get_metadata("prepared") != dict(prepared):
            raise DaemonInvocationError("invocation handle differs from owner journal")
        operations = journal.operations()
        if "complete" in operations:
            old = operations["complete"]
            receipt = journal.invoke(registry, "complete", old["command"], old["payload"])
            return {"completion": receipt, "historical_retry": True,
                    "current_artifact_availability_checked": False, "admitted": False}
        if journal.get_metadata("attempt") is not None:
            raise DaemonInvocationError("uncommitted prior attempt requires quarantine; no implicit rerun")
        request = validate_request(parse_json(verify(prepared["request"], MAX_REQUEST_BYTES)))
        run = registry.get_run(request["run_id"])
        if (run["variant_id"] != request["variant_id"] or run["base_version_id"] != request["base_version_id"]
                or run["spec"] != {"schema": request["schema"], "request_artifact": _artifact(prepared["request"])}):
            raise DaemonInvocationError("request differs from registered execution run")
        with _reservation(request["resource_policy"]) as reservation:
            lease = journal.invoke(registry, "claim", "ClaimRun", {"run_id": request["run_id"],
                "worker_id": "native-daemon-owner", "lease_seconds": lease_seconds})["lease"]
            _assert_live_lease(registry, lease)
            output = safe_path(request["output_directory"])
            attempt = output / ("attempt-" + str(lease["attempt"]) + "-" + str(lease["fence"]) + "-" + uuid.uuid4().hex)
            # Durable attempt fact precedes startup and any private base copy.
            journal.set_metadata("attempt", {"lease": lease, "directory": str(attempt),
                                              "reservation": reservation.to_dict()})
            attempt.mkdir(mode=0o700)
            reservation.check_usage(attempt)
            reservation.account_external_bytes("owner-journal", 8 * 1024 * 1024)
            next_renewal = time.monotonic() + lease_seconds / 3
            renewal_number = 0
            next_usage = time.monotonic() + 5

            def heartbeat(force=False):
                nonlocal lease, next_renewal, renewal_number, next_usage
                if time.monotonic() >= invocation_deadline:
                    raise DaemonInvocationError("owned invocation exceeded its wall-time bound")
                if force or time.monotonic() >= next_renewal:
                    renewal_number += 1
                    lease = journal.invoke(registry, f"renew-{renewal_number:04d}", "RenewLease",
                        {"lease": lease, "lease_seconds": lease_seconds})["lease"]
                    journal.set_metadata("current_lease", lease)
                    _assert_live_lease(registry, lease)
                    next_renewal = time.monotonic() + lease_seconds / 3
                if force or time.monotonic() >= next_usage:
                    reservation.check_usage(attempt)
                    next_usage = time.monotonic() + 5

            launch = {"schema": LAUNCH_SCHEMA, "request": dict(prepared["request"]), "lease": lease,
                "attempt_directory": str(attempt), "daemon_argv": request["daemon_argv"],
                "environment": request["environment"], "base_artifact": request["base_artifact"],
                "resource_reservation_id": reservation.to_dict()["reservation_id"]}
            launch_ref = write_new(attempt / "launch.json", launch, MAX_REQUEST_BYTES)
            journal.set_metadata("launch", launch_ref)
            try:
                result_path = attempt / "native-result.json"
                native = _child("execute", Path(launch_ref["path"]), result_path, cwd=attempt,
                    environment=request["environment"], reservation=reservation,
                    timeout_seconds=max(0.01, invocation_deadline-time.monotonic()), heartbeat=heartbeat)
                result_ref = _result_reference(result_path, native)
                final = native["final_checkpoint"]
                safe_path(final["path"])
                if attempt not in Path(final["path"]).parents:
                    raise DaemonInvocationError("candidate escaped exclusive attempt directory")
                verify(final, MAX_CHECKPOINT_BYTES)
                heartbeat(force=True)
                reservation.account_external_bytes(final["sha256"], final["bytes"])
                staged = _stage(registry, final["path"], final["sha256"], heartbeat=heartbeat)
                candidate = {**staged, "path": str(registry.artifact_path(staged))}
                query = attempt / "verification-query.json"
                write_new(query, {"launch": launch_ref, "native_result": result_ref, "candidate": candidate})
                audit_path = attempt / "owner-verification.json"
                independent = _child("verify", query, audit_path, cwd=attempt,
                    environment=request["environment"], reservation=reservation,
                    timeout_seconds=min(max(0.01, invocation_deadline-time.monotonic()), 300), heartbeat=heartbeat)
                if request["schema"] == WEIGHT_REQUEST_SCHEMA:
                    _checked_weight_result(independent, request["arrow_feature_weights"],
                                           request["base_artifact"], request["base_identity"])
                audit_ref = _result_reference(audit_path, independent)
                evidence = {}
                # Preserve the descriptors checked by the independent verifier.
                # Re-describing these paths here would silently bind a changed
                # file to a fresh digest between verification and CAS staging.
                evidence_refs = [("launch", launch_ref), ("native_result", result_ref),
                                 ("owner_verification", audit_ref)]
                if request.get("sparse_shadow") is True:
                    from .autoencoder_daemon_shadow_evidence import validate_owned_shadow_evidence
                    # Artifact decoding/hashing performs no registry operations.
                    # Keep the owner dispatcher available for lease renewal.
                    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="daemon-shadow-evidence") as pool:
                        future = pool.submit(validate_owned_shadow_evidence, independent.get("sparse_shadow"),
                            request=request, launch_ref=launch_ref, native_result_ref=result_ref,
                            candidate=candidate, independent=independent, attempt=attempt)
                        while not future.done():
                            heartbeat()
                            time.sleep(0.1)
                        evidence_refs.extend(future.result())
                elif "sparse_shadow" in independent:
                    raise DaemonInvocationError("verifier returned shadow evidence without a sealed request")
                for name in ("summary_artifact", "log_artifact"):
                    ref = native[name]
                    if attempt not in safe_path(ref["path"]).parents:
                        raise DaemonInvocationError("diagnostic artifact escaped attempt")
                    verify(ref)
                    evidence_refs.append((name, ref))
                for name, item in evidence_refs:
                    reservation.account_external_bytes(item["sha256"], item["bytes"])
                    evidence[name] = _stage(registry, item["path"], item["sha256"], heartbeat=heartbeat)
                heartbeat(force=True)
                result = {"schema": "autoencoder-daemon-owned-completion-v1", "request_artifact": _artifact(prepared["request"]),
                    "evidence": evidence, "state_identity": independent["state_identity"],
                    "evaluation_matches_final": independent["evaluation_matches_final"],
                    "accepted_projection_epochs": independent["accepted_projection_epochs"],
                    "admitted": False, "promoted": False, "publication_performed": False}
                # No renewal overlaps this exact command/payload. The registry
                # rejects expiry if its final artifact rehash takes too long.
                completion = journal.invoke(registry, "complete", "CompleteRun",
                    {"lease": lease, "artifact": staged, "result": result})
                reservation.release(artifacts_durable=True)
                return {"completion": completion, "historical_retry": False,
                        "owner_verification": independent, "admitted": False}
            except BaseException as exc:
                # An ambiguous completion must be resolved before any fail or
                # lease reclaim. Do not overwrite its pending exact operation.
                try:
                    if "complete" not in journal.operations():
                        failure = {"type": type(exc).__name__, "message": str(exc)[:2048],
                                   "attempt_directory": str(attempt), "admitted": False}
                        journal.set_metadata("quarantine", failure)
                        if not journal.pending():
                            _assert_live_lease(registry, lease)
                            journal.invoke(registry, "fail", "FailRun", {"lease": lease, "result": failure})
                except BaseException as cleanup:
                    exc.add_note(f"failure recording also failed: {type(cleanup).__name__}")
                raise
