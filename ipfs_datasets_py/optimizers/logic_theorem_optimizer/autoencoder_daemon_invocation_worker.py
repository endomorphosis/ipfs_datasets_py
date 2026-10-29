"""Offline native daemon child and independent full-checkpoint verifier.

The production owner launches this file directly: only stdlib imports precede
the irreversible network filter. Compatibility -m launches import package
ancestors before that filter and do not establish the same bootstrap boundary.
This process never opens a registry database or grants lease authority.
"""
from __future__ import annotations

import ctypes
import ctypes.util
from contextlib import nullcontext
import errno
import json
import os
from pathlib import Path
import socket
import sys
import time

if __package__ in {None, ""}:
    __package__ = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"


def _contracts():
    from . import autoencoder_daemon_invocation_contracts
    return autoencoder_daemon_invocation_contracts


def _deny_network():
    """Same libseccomp filter as audit_native_uscode_embedding_production."""
    library = ctypes.util.find_library("seccomp")
    if not library:
        raise RuntimeError("native daemon requires libseccomp network denial")
    lib = ctypes.CDLL(library, use_errno=True)
    lib.seccomp_init.argtypes, lib.seccomp_init.restype = [ctypes.c_uint32], ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes, lib.seccomp_syscall_resolve_name.restype = [ctypes.c_char_p], ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_load.argtypes, lib.seccomp_load.restype = [ctypes.c_void_p], ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    context = lib.seccomp_init(0x7FFF0000)
    if not context:
        raise RuntimeError("seccomp context creation failed")
    names = ("socket", "connect", "sendto", "sendmsg", "sendmmsg")
    try:
        for name in names:
            number = lib.seccomp_syscall_resolve_name(name.encode("ascii"))
            if number < 0 or lib.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0) != 0:
                raise RuntimeError(f"cannot deny {name}")
        if lib.seccomp_load(context) != 0:
            raise RuntimeError("seccomp load failed")
    finally:
        lib.seccomp_release(context)
    try:
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except PermissionError:
        return {"mechanism": "linux_seccomp", "denied_syscalls": list(names), "socket_denial_verified": True}
    else:
        connection.close()
        raise RuntimeError("network denial was ineffective")


def _require(condition, message):
    if not condition:
        raise _contracts().DaemonInvocationError(message)


def _closed(value, fields):
    _require(type(value) is dict and set(value) == set(fields), "invalid closed worker query")


def _inputs(reference, arguments):
    from .autoencoder_daemon_corpus_inputs import DaemonCorpusInputDescriptor, VerifiedDaemonCorpusInputs
    _require(reference == {"path": arguments["autoencoder_corpus_input"],
                           "sha256": arguments["autoencoder_corpus_input_sha256"],
                           "bytes": arguments["autoencoder_corpus_input_bytes"]},
             "effective input descriptor differs from request")
    return VerifiedDaemonCorpusInputs(DaemonCorpusInputDescriptor(**reference))


def _weights(value, state, base_identity):
    """Validate the explicit sidecar against this loaded authoritative base."""
    if "arrow_feature_weights" not in value:
        return None
    from .autoencoder_daemon_weight_session import VerifiedDaemonWeightSession
    session = VerifiedDaemonWeightSession(value["arrow_feature_weights"],
        base_artifact=value["base_artifact"], base_identity=base_identity)
    try:
        session.verify_base_state(state)
        return session
    except BaseException as exc:
        try:
            session.close()
        except BaseException as cleanup:
            exc.add_note(f"weight session cleanup also failed: {type(cleanup).__name__}")
        raise


def _close_weights(session, result):
    if session is None:
        return
    primary = sys.exc_info()[1]
    try:
        session.close()
    except BaseException as cleanup:
        if primary is None:
            raise
        primary.add_note(f"weight session cleanup also failed: {type(cleanup).__name__}")
    finally:
        result["arrow_feature_weights"] = session.summary()


def _verify_weight_provenance(session, summary, checkpoint_metadata, native=None):
    c = _contracts()
    expected = session.provenance()
    _require(c.canonical(checkpoint_metadata.get("arrow_feature_weights_provenance")) == c.canonical(expected)
             and c.canonical(summary.get("arrow_feature_weights", {}).get("provenance")) == c.canonical(expected),
             "candidate feature-weight provenance differs")
    if native is not None:
        observed = native.get("arrow_feature_weights", {})
        _require(observed.get("base_verified") is True and observed.get("attached") is True
                 and observed.get("closed") is True and observed.get("poisoned") is False
                 and observed.get("current_storage") in {"mapped_overlay", "detached_native"}
                 and c.canonical(observed.get("provenance")) == c.canonical(expected),
                 "native feature-weight session did not close cleanly with exact provenance")


def _load_launch(reference):
    c = _contracts()
    launch = c.parse_json(c.verify(reference, c.MAX_REQUEST_BYTES))
    _require(type(launch) is dict and "request" in launch, "missing launch request")
    request = c.validate_request(c.parse_json(c.verify(launch["request"], c.MAX_REQUEST_BYTES)))
    c.validate_launch(launch, request)
    _require(Path.cwd() == Path(launch["attempt_directory"]), "worker cwd differs from exclusive attempt")
    _require(dict(os.environ) == request["environment"], "worker environment differs from sealed request")
    arguments = c.effective_configuration(launch["daemon_argv"])
    _require(arguments == request["effective_arguments"], "actual daemon arguments differ from request")
    _require(c.producer_identity(arguments) == request["producer_identity"], "producer/source identity differs before use")
    binding = {"request_sha256": launch["request"]["sha256"], "launch_sha256": reference["sha256"]}
    return launch, request, arguments, binding


def _describe(query, result):
    c = _contracts()
    fields = {"daemon_argv", "base_artifact", "input_snapshot"}
    optional = {"arrow_feature_weights"} if type(query) is dict and "arrow_feature_weights" in query else set()
    _closed(query, fields | optional)
    arguments = c.effective_configuration(query["daemon_argv"])
    producer = c.producer_identity(arguments)
    inputs = _inputs(query["input_snapshot"], arguments)
    weights = None
    try:
        inputs.verify_boundary("describe_before")
        loaded = c.load_full_checkpoint(query["base_artifact"])
        result.update(effective_arguments=arguments, producer_identity=producer,
                      base_identity=loaded.state.state_identity_record().to_dict())
        weights = _weights(query, loaded.state, result["base_identity"])
        if weights is not None:
            weights.verify_boundary("describe_after")
        inputs.verify_boundary("describe_after")
        _require(c.producer_identity(arguments) == producer, "producer/source changed during description")
    finally:
        try:
            _close_weights(weights, result)
        finally:
            inputs.close()
            result["input_verification"] = inputs.summary()


def _copy_base(reference, destination):
    c = _contracts()
    raw = c.verify(reference, c.MAX_CHECKPOINT_BYTES)
    destination.parent.mkdir(parents=True, exist_ok=True)
    c.safe_path(destination, exists=False)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    local = c.describe(destination, c.MAX_CHECKPOINT_BYTES)
    _require(all(local[key] == reference[key] for key in ("sha256", "bytes")), "private base copy differs")
    return local


def _cycle_log(reference):
    c = _contracts()
    cycles = []
    for line in c.verify(reference).splitlines():
        _require(len(line) <= c.MAX_REQUEST_BYTES, "daemon log row exceeds bound")
        row = c.parse_json(line)
        _require(type(row) is dict, "daemon log row must be an object")
        if row.get("event") == "cycle":
            cycles.append(row)
    _require(len(cycles) == 1 and cycles[0].get("cycle") == 1, "expected exactly one completed cycle log")
    return cycles[0]


def _evidence_paths(request):
    root = Path.cwd() / "workspace"
    run = request["run_id"]
    return (root / "test-logs" / f"{run}.summary", root / "test-logs" / f"{run}.jsonl",
            root / "todo-queues" / f"{run}.state.json")


def _runtime_guards(request, summary, final):
    persisted, writer = summary.get("final_state_persistence", {}), summary.get("async_artifact_writer", {})
    inputs = summary.get("corpus_inputs", {})
    expected = request["input_snapshot"]
    checks = {
        "exactly_one_cycle": type(summary.get("cycles")) is int and summary["cycles"] == 1,
        "durable": persisted.get("durable") is True and persisted.get("checkpoint_enqueued") is True,
        "checksum": persisted.get("checksum") == final["sha256"],
        "bytes": persisted.get("written_bytes") == final["bytes"] == persisted.get("checkpoint_bytes"),
        "writer_drained": summary.get("async_artifact_writer_shutdown", {}).get("drained") is True,
        "writer_clean": writer.get("failed_count") == 0 and not writer.get("last_error"),
        "input_closed": inputs.get("closed") is True,
        "input_integrity": inputs.get("input_integrity_verified") is True and inputs.get("poisoned") is False,
        "input_failure_absent": inputs.get("failure") is None and not summary.get("corpus_input_failure"),
        "input_descriptor": summary.get("corpus_input_descriptor") == expected,
        "input_identity": summary.get("corpus_input_identity") == {key: expected[key] for key in ("sha256", "bytes")},
        "target_failure_absent": not summary.get("shared_target_failure"),
    }
    if request["effective_arguments"]["snapshot_evaluation_enabled"]:
        checks["snapshot_drained"] = summary.get("snapshot_shutdown", {}).get("drained") is True
        checks["snapshot_closed"] = summary.get("snapshot_evaluator", {}).get("closed") is True
    if request["schema"] == _contracts().WEIGHT_REQUEST_SCHEMA:
        weights = summary.get("arrow_feature_weights", {})
        checks["feature_weights_verified"] = weights.get("base_verified") is True
        checks["feature_weights_attached"] = weights.get("attached") is True
        checks["feature_weights_integrity"] = weights.get("poisoned") is False
        checks["feature_weights_storage"] = weights.get("current_storage") in {"mapped_overlay", "detached_native"}
    _require(all(checks.values()), "daemon runtime completion guards failed: " + ",".join(k for k,v in checks.items() if not v))
    return checks


def _sample_memory_policy(observation, request, cycle):
    passes = []
    for event in observation["events"]:
        metadata = event.get("metadata", {})
        if "use_sample_memory" in metadata:
            value = metadata["use_sample_memory"]
            _require(type(value) is bool, "observed sample-memory policy must be boolean")
            passes.append({"phase": event["phase"], "cycle": event["cycle"], "use_sample_memory": value})
    return {"scope": "observed synchronous daemon evaluation calls; internal snapshot/trainer calls not expanded",
            "evaluation_passes": passes,
            "requested_sample_memory_arguments": {key: value for key, value in request["effective_arguments"].items()
                                                   if "sample_memory" in key},
            "projection_report_sample_memory_used": cycle.get("feature_projection_report", {}).get("sample_memory_used"),
            "memory_hit_counts": None}


def _execute(launch_reference, result):
    c = _contracts()
    launch, request, arguments, binding = _load_launch(launch_reference)
    from .autoencoder_daemon_observation import observation_session
    from . import uscode_modal_daemon_runner as runner
    result.update(request=launch["request"], launch=launch_reference, binding=binding,
                  guards={"source_before": True}, entrypoint="uscode_modal_daemon_runner.main(argv)",
                  callable_replacements=[], native_exit_code=None)
    inputs = _inputs(request["input_snapshot"], arguments)
    observation, primary, weights = None, None, None
    try:
        _require(inputs.summary()["variant_manifest_sha256"] == request["variant_manifest_sha256"], "input variant differs")
        inputs.verify_boundary("execute_before")
        summary_path, log_path, state_path = _evidence_paths(request)
        _require(not summary_path.exists() and not log_path.exists(), "attempt already has daemon history")
        local = _copy_base(request["base_artifact"], state_path)
        base = c.load_full_checkpoint(local)
        _require(base.state.state_identity_record().to_dict() == request["base_identity"], "loaded base identity differs")
        weights = _weights(request, base.state, request["base_identity"])
        del base
        context = nullcontext()
        if weights is not None:
            from .autoencoder_daemon_weight_session import weight_session
            context = weight_session(weights)
        with context, observation_session(binding=binding) as observation:
            started = time.perf_counter()
            try:
                result["native_exit_code"] = runner.main(launch["daemon_argv"])
            finally:
                result["daemon_seconds_including_shutdown"] = time.perf_counter() - started
        result["observation"] = observation.to_dict()
        _require(result["native_exit_code"] == 0 and result["observation"]["success"] is True, "native daemon did not complete successfully")
        result["summary_artifact"] = c.describe(summary_path)
        result["summary"] = c.parse_json(c.verify(result["summary_artifact"]))
        result["log_artifact"] = c.describe(log_path)
        result["final_checkpoint"] = c.describe(state_path, c.MAX_CHECKPOINT_BYTES)
        result["runtime_guards"] = _runtime_guards(request, result["summary"], result["final_checkpoint"])
        cycle = _cycle_log(result["log_artifact"])
        result["accepted_projection_epochs"] = cycle.get("feature_projection_report", {}).get("accepted_epochs", 0)
        result["sample_memory_policy"] = _sample_memory_policy(result["observation"], request, cycle)
        final = c.load_full_checkpoint(result["final_checkpoint"], compact_only=True)
        _require(final.manifest.metadata.get("daemon_invocation") == binding, "final checkpoint invocation binding differs")
        if weights is not None:
            _verify_weight_provenance(weights, result["summary"], final.manifest.metadata)
        result["state_identity"] = final.state.state_identity_record().to_dict()
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if observation is not None:
            result["observation"] = observation.to_dict()
        try:
            if weights is not None:
                weights.verify_boundary("execute_after")
            inputs.verify_boundary("execute_after")
            result["guards"]["inputs_after"] = True
            c.verify(launch_reference, c.MAX_REQUEST_BYTES)
            c.verify(launch["request"], c.MAX_REQUEST_BYTES)
            c.verify(request["base_artifact"], c.MAX_CHECKPOINT_BYTES)
            _require(c.producer_identity(arguments) == request["producer_identity"], "producer/source changed during execution")
            result["guards"]["source_after"] = True
        except BaseException as exc:
            result["final_guard_error"] = _error(exc)
            if primary is None:
                raise
        finally:
            try:
                _close_weights(weights, result)
            finally:
                inputs.close()
                result["input_verification"] = inputs.summary()


def _verify_observation(observation, request, binding, loaded, base_metric, inputs, cycle, summary):
    c = _contracts()
    _require(observation.get("binding") == binding and observation.get("schema") == "autoencoder-daemon-observation-v1",
             "observation binding/schema differs")
    _require(observation.get("success") is True and observation.get("closed") is True
             and observation.get("exit_code") == 0 and observation.get("error") is None,
             "observation did not close successfully")
    _require(observation.get("observations_only") is True and observation.get("lease_authority_verified") is False
             and observation.get("admitted") is False and observation.get("promoted") is False,
             "observation authority flags differ")
    events = observation.get("events")
    _require(type(events) is list and len(events) <= 128, "invalid bounded observation events")
    _require(all(type(row) is dict and row.get("kind") in {"state", "selection"} for row in events), "unknown observation event")
    states = [row for row in events if row.get("kind") == "state"]
    phases = [row.get("phase") for row in states]
    for phase in ("registered_base", "startup_complete", "completed_cycle", "final_shutdown"):
        _require(phases.count(phase) == 1, "missing or repeated required observation phase")
    _require(phases[:2] == ["registered_base", "startup_complete"] and phases[-2:] == ["completed_cycle", "final_shutdown"],
             "observation state boundary order differs")
    base, startup, completed, final = (next(row for row in states if row["phase"] == p) for p in
                                      ("registered_base", "startup_complete", "completed_cycle", "final_shutdown"))
    _require(base["cycle"] == startup["cycle"] == 0 and all(row["cycle"] == 1 for row in states[2:]), "observation cycles differ")
    _require(base["state_identity"] == request["base_identity"] and base["metadata"].get("checkpoint_loaded") is True,
             "observed registered base differs")
    _require(base["metric_state_identity"] == base_metric, "observed base metric identity differs")
    identity = loaded.state.state_identity_record().to_dict()
    metric = loaded.state.state_identity_record(metric_lineage=c.METRIC_LINEAGE).to_dict()
    _require(final["state_identity"] == identity and final["metric_state_identity"] == metric,
             "observed final state differs from reconstructed full checkpoint")
    _require(final["metadata"]["final_state_persistence"] == summary["final_state_persistence"], "final persistence observations differ")
    selections = [row for row in events if row.get("kind") == "selection"]
    _require(len(selections) == 1 and selections[0]["cycle"] == 1, "expected exactly one observed selection")
    selected = selections[0]
    for role in ("train", "validation"):
        row = selected[role]
        indices = row["indices"]
        _require(type(indices) is list and len(indices) == request["effective_arguments"][role + "_count"], "selected sample count differs")
        _require(all(type(i) is int and i in inputs.indices_for(role) for i in indices) and len(set(indices)) == len(indices),
                 "selected indices differ from frozen partition")
        _require(indices == cycle[role + "_indices"], "observed selection differs from cycle log")
        samples = [inputs.build_sample(index) for index in indices]
        inputs.verify_selected(indices, samples, role=role)
        _require(row["sample_ids"] == [sample.sample_id for sample in samples]
                 and row["record_ids"] == [inputs.record_id(index) for index in indices], "observed sample/record identity differs")
    from .snapshot_evaluator import canonical_holdout_version
    from .uscode_modal_daemon_runner import _compiler_commit
    expected_versions = {"state_version": metric["digest"], "schema_version": c.METRIC_LINEAGE,
        "compiler_version": _compiler_commit(Path.cwd()),
        "holdout_version": canonical_holdout_version(selected["validation"]["sample_ids"],
                                                     validation_mode=completed["metadata"]["validation_mode"])}
    _require(completed["metadata"]["validation_mode"] == cycle.get("validation_mode")
             and final["metadata"].get("validation_mode") == cycle.get("validation_mode"),
             "observed validation mode differs from completed cycle")
    _require(final["versions"] == expected_versions, "final snapshot lineage tuple differs")
    _require(completed["versions"]["compiler_version"] == expected_versions["compiler_version"]
             and completed["versions"]["holdout_version"] == expected_versions["holdout_version"]
             and completed["versions"]["schema_version"] == c.METRIC_LINEAGE
             and completed["versions"]["state_version"] == completed["metric_state_identity"]["digest"],
             "completed-cycle observation lineage is inconsistent")
    published = summary.get("latest_published_snapshot")
    if request["effective_arguments"]["snapshot_evaluation_enabled"]:
        _require(type(published) is dict and published.get("sequence") == 1
                 and published.get("versions") == completed["versions"]
                 and published.get("metadata", {}).get("daemon_invocation") == binding,
                 "completed cycle differs from published snapshot")
    promoted = summary.get("latest_promoted_snapshot_evaluation", {})
    evaluation_matches = (promoted.get("sequence") == 1 and promoted.get("status") == "succeeded"
                          and promoted.get("versions") == expected_versions
                          and summary.get("latest_promoted_snapshot_complete") is True)
    return identity, metric, evaluation_matches


def _verify(query, result):
    c = _contracts()
    _closed(query, ("launch", "native_result", "candidate"))
    launch, request, arguments, binding = _load_launch(query["launch"])
    native = c.parse_json(c.verify(query["native_result"]))
    _require(native.get("schema") == c.RESULT_SCHEMA and native.get("mode") == "execute" and native.get("success") is True
             and native.get("native_exit_code") == 0 and native.get("binding") == binding
             and native.get("request") == launch["request"] and native.get("launch") == query["launch"],
             "native result binding or completion differs")
    _require(native.get("network_guard", {}).get("socket_denial_verified") is True
             and native.get("callable_replacements") == []
             and all(native.get("guards", {}).get(key) is True for key in ("source_before", "source_after", "inputs_after")),
             "native result guards incomplete")
    summary_path, log_path, state_path = _evidence_paths(request)
    for key, path in (("summary_artifact", summary_path), ("log_artifact", log_path), ("final_checkpoint", state_path)):
        _require(native[key]["path"] == str(path), "native evidence escaped expected attempt path")
    summary = c.parse_json(c.verify(native["summary_artifact"]))
    _require(summary == native["summary"], "native summary differs from its sealed artifact")
    cycle = _cycle_log(native["log_artifact"])
    _require(all(query["candidate"][key] == native["final_checkpoint"][key] for key in ("sha256", "bytes")), "staged candidate differs from native final bytes")
    checks = _runtime_guards(request, summary, query["candidate"])
    inputs = _inputs(request["input_snapshot"], arguments)
    weights = None
    shadow_endpoints = None
    try:
        inputs.verify_boundary("verify_before")
        _require(inputs.summary()["variant_manifest_sha256"] == request["variant_manifest_sha256"], "input variant differs")
        if request.get("sparse_shadow") is True:
            from .autoencoder_daemon_sparse_shadow import _VerifiedCheckpointEndpoints
            shadow_endpoints = _VerifiedCheckpointEndpoints(request["base_artifact"])
            base = shadow_endpoints.base
        else:
            base = c.load_full_checkpoint(request["base_artifact"])
        _require(base.state.state_identity_record().to_dict() == request["base_identity"], "registered base identity differs")
        base_metric = base.state.state_identity_record(metric_lineage=c.METRIC_LINEAGE).to_dict()
        weights = _weights(request, base.state, request["base_identity"])
        del base
        loaded = (shadow_endpoints.load_final(query["candidate"]) if shadow_endpoints is not None
                  else c.load_full_checkpoint(query["candidate"], compact_only=True))
        if weights is not None:
            _verify_weight_provenance(weights, summary, loaded.manifest.metadata, native)
        _require(loaded.manifest.metadata.get("daemon_invocation") == binding, "candidate launch metadata differs")
        _require(loaded.manifest.metadata.get("corpus_input_identity") == {k: request["input_snapshot"][k] for k in ("sha256", "bytes")}, "candidate input metadata differs")
        _require(loaded.manifest.metadata.get("run_id") == request["run_id"] and loaded.manifest.metadata.get("cycle") == 1, "candidate run/cycle metadata differs")
        _require(loaded.manifest.metadata.get("reason") == "clean_shutdown", "candidate is not the sealed shutdown checkpoint")
        verified_inputs = inputs.summary()
        from .autoencoder_daemon_corpus_inputs import corpus_input_checkpoint_provenance
        provenance = corpus_input_checkpoint_provenance(request["input_snapshot"], verified_inputs)
        _require(c.canonical(loaded.manifest.metadata.get("corpus_input_provenance")) == c.canonical(provenance)
                 and c.canonical(summary.get("corpus_input_provenance")) == c.canonical(provenance),
                 "candidate input provenance differs")
        identity, metric, evaluation_matches = _verify_observation(native["observation"], request, binding, loaded, base_metric, inputs, cycle, summary)
        persisted = summary["final_state_persistence"]
        _require(persisted["checkpoint_identity"] == identity["digest"] and persisted["checkpoint_revision"] == identity["revision"], "durable checkpoint identity differs")
        epochs = cycle.get("feature_projection_report", {}).get("accepted_epochs", 0)
        _require(type(epochs) is int and epochs >= 0 and epochs == native["accepted_projection_epochs"], "accepted projection count differs")
        memory_policy = _sample_memory_policy(native["observation"], request, cycle)
        _require(memory_policy == native.get("sample_memory_policy"), "per-pass sample-memory observations differ")
        result.update(state_identity=identity, metric_state_identity=metric,
                      evaluation_matches_final=evaluation_matches, accepted_projection_epochs=epochs,
                      runtime_guards=checks, binding=binding, intermediate_states_replayed=False,
                      sample_memory_policy=memory_policy)
        if request.get("sparse_shadow") is True:
            # Ordinary full-candidate validation remains mandatory. Transfer its
            # loader-origin endpoints to the consuming diagnostic helper; the
            # original base must be released before the independent replay load.
            del loaded
            from .autoencoder_daemon_sparse_shadow import (
                SCHEMA as shadow_schema, _write_checkpoint_shadow_from_verified_endpoints,
            )
            from .autoencoder_daemon_shadow_evidence import shadow_provenance
            shadow_directory = Path.cwd() / "sparse-shadow"
            shadow_directory.mkdir(mode=0o700)
            shadow = _write_checkpoint_shadow_from_verified_endpoints(
                shadow_endpoints, request["base_artifact"], query["candidate"],
                base_version_id=request["base_version_id"], output_directory=shadow_directory,
                provenance=shadow_provenance(request_ref=launch["request"],
                    launch_ref=query["launch"], native_result_ref=query["native_result"]))
            _require(shadow.get("schema") == shadow_schema and shadow.get("passed") is True
                     and shadow.get("mode") == "diagnostic_only"
                     and shadow.get("full_checkpoint_authoritative") is True,
                     "required sparse shadow did not verify")
            required_shadow_checks = {"all_native_components_exact", "canonical_native_state_exact",
                "metric_lineage_identity_exact", "revision_exact", "patch_endpoint_binding_exact",
                "independent_base_reload", "compact_final_bytes_exact", "source_artifacts_unchanged",
                "published_patch_bytes_exact"}
            shadow_checks = shadow.get("checks")
            _require(type(shadow_checks) is dict and set(shadow_checks) == required_shadow_checks
                     and all(value is True for value in shadow_checks.values()),
                     "required sparse shadow checks are incomplete")
            capture = shadow["capture_report"]
            for observed, expected in (
                    (capture["base_snapshot"]["plain_identity"], request["base_identity"]),
                    (capture["result_snapshot"]["plain_identity"], identity),
                    (shadow["metric_state_identity"], metric),
                    (shadow["regenerated_compact_checkpoint"],
                     {key: query["candidate"][key] for key in ("sha256", "bytes")})):
                _require(c.canonical(observed) == c.canonical(expected),
                         "sparse shadow differs from independently verified endpoints")
            result["sparse_shadow"] = shadow
        inputs.verify_boundary("verify_after")
        if weights is not None:
            weights.verify_boundary("verify_after")
        _require(c.producer_identity(arguments) == request["producer_identity"], "producer/source changed during verification")
        for key in ("launch", "native_result", "candidate"):
            c.verify(query[key], c.MAX_CHECKPOINT_BYTES if key == "candidate" else c.MAX_RESULT_BYTES)
        for key in ("summary_artifact", "log_artifact"):
            c.verify(native[key])
        c.verify(launch["request"], c.MAX_REQUEST_BYTES)
        result["guards"] = {"source_before": True, "source_after": True, "inputs_after": True}
    finally:
        try:
            if shadow_endpoints is not None:
                shadow_endpoints.close()
        finally:
            try:
                _close_weights(weights, result)
            finally:
                inputs.close()
                result["input_verification"] = inputs.summary()


def _error(exc):
    try:
        message = str(exc)[:4096]
    except BaseException:
        message = "exception string unavailable"
    return {"type": f"{type(exc).__module__}.{type(exc).__qualname__}", "message": message}


def main(argv=None):
    started = time.perf_counter()
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 3 or argv[0] not in {"describe", "execute", "verify"}:
        print("usage: worker {describe|execute|verify} querypath outputpath", file=sys.stderr)
        return 1
    mode, query_path, output = argv
    result = {"schema": "autoencoder-daemon-invocation-result-v1", "mode": mode, "success": False,
              "admitted": False, "promoted": False, "publication_performed": False,
              "lease_authority_verified": False, "runtime_computation_replayed": False}
    try:
        result["network_guard"] = _deny_network()
        c = _contracts()
        if mode == "execute":
            _execute(c.describe(query_path, c.MAX_REQUEST_BYTES), result)
        else:
            {"describe": _describe, "verify": _verify}[mode](c.read_json(query_path), result)
        result["success"] = True
    except BaseException as exc:
        result["error"] = _error(exc)
    result["elapsed_seconds"] = time.perf_counter() - started
    try:
        _contracts().write_new(output, result)
    except BaseException as exc:
        # Never overwrite an existing receipt or hide the primary diagnostic.
        failure = {"schema": result["schema"], "mode": mode, "success": False,
                   "admitted": False, "promoted": False, "publication_performed": False,
                   "error": result.get("error", _error(exc)), "receipt_error": _error(exc)}
        try:
            if not Path(output).exists():
                _contracts().write_new(output, failure, _contracts().MAX_REQUEST_BYTES)
        except BaseException as secondary:
            failure["failure_receipt_error"] = _error(secondary)
        print(json.dumps(failure), file=sys.stderr)
        return 1
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


# This fixed numerical adapter is called only by the original trainer child
# after its genuine retained READY/RUN barrier. It creates no grant or process.
_F18_COMPUTE_FIELDS = frozenset(("input_descriptors", "initial_parity", "runtime_contract",
                               "population_manifest", "max_steps_per_arm", "max_seconds_per_arm"))
_F18_PROFILE_SHA256 = "56bd0a248a07de09519f95e5c4bae02ab9d8eb1134b483c257c1f7e7bcb07147"
_F18_V2_PROFILE_SHA256 = "d80a08844c06daae6466a39b87bc0c395e0dd4a2da01b284704a4e03e44af0f1"
_F18_RECIPE_SHA256 = "d22b932b80c48b688ff3f18d5f141152a6032b7cb2f6195845840af818d8dc84"
_F18_V1_PARITY_SHA256 = "738273e56a0bcad5e77825b7227e3a7df49861d02885df6165a7b3cb28bbaf92"
_F18_V2_PARITY_SHA256 = "1b564a1658aaee6b0449d3114697f08661239b9436b46a27fc225f19722e1cb3"
_F18_SOURCE_SHA256 = "fb7449d4794ca9a279b2df2ea533b89d360344ff786edc0798395ab799db1823"
_F18_JOINT_SHA256 = "791c283f625ae7d8841e7afa697b34cbfa5c74361d0c0129b66af31fb5e13679"
_F18_MODEL_ROOT = "2ed0ccf633f55fac202e2edb95ea9fa6e390b8d99381a05925f4dd5221925883"
_F18_FROZEN_ROOT = "8562a4a944412a0385b26a88469fd669701573803c0eea3f444190f523414778"
_F18_ROLES = ("retained_final_F18_donor_checkpoint", "trained_F15_teacher_checkpoint",
              "original_TRAIN_source_export", "fresh_source_export",
              "trained_F15_TRAIN168_teacher_capture", "qualified_F18_training_mask_certificate_v02")
_F18_PANELS = (("training168", 168, (128, 40)), ("old_tune", 96, (96,)),
               ("fresh_tune", 36, (36,)), ("fresh_challenge", 36, (36,)),
               ("old_authored_eval", 72, (72,)), ("authored_dev", 72, (72,)),
               ("authored_eval", 72, (72,)), ("law", 8, (8,)),
               ("fresh_dev", 36, (36,)), ("fresh_test", 36, (36,)))
_F18_FALSE = dict(admitted=False, formalized=False, promoted=False,
                  training_authority_verified=False, semantic_accuracy_qualified=False)


def _f18_require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_f18_compute(value, *, version=1):
    """Pure lexical envelope validation; no input, numerical or grant access."""
    _f18_require(type(version) is int and version in (1, 2), "explicit supported F18 version required")
    fields = _F18_COMPUTE_FIELDS | ({"learning_rate"} if version == 2 else set())
    _f18_require(type(value) is dict and set(value) == fields,
                 "closed fixed F18 compute fields required")
    if version == 2:
        import sys
        rate = value["learning_rate"]
        _f18_require(type(rate) in (int, float) and 0 < rate <= sys.float_info.max,
                     "explicit finite positive TRAIN learning_rate required")
    for name in ("input_descriptors", "initial_parity", "runtime_contract", "population_manifest"):
        ref = value[name]
        _f18_require(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"},
                     "closed F18 metadata reference required")
        path = ref["path"]
        _f18_require(type(path) is str and 0 < len(path) <= 4096 and "\x00" not in path
                     and Path(path).is_absolute() and str(Path(path)) == path
                     and ".." not in Path(path).parts, "literal absolute F18 reference path required")
        _f18_require(type(ref["bytes"]) is int and 0 < ref["bytes"] <= 128 * 1024
                     and type(ref["sha256"]) is str and len(ref["sha256"]) == 64
                     and all(ch in "0123456789abcdef" for ch in ref["sha256"]),
                     "bounded F18 metadata bytes/SHA256 required")
    _f18_require(type(value["max_steps_per_arm"]) is int and value["max_steps_per_arm"] == 32
                 and type(value["max_seconds_per_arm"]) is int and value["max_seconds_per_arm"] == 32,
                 "fixed32-step/32-second F18 arms required")
    return {key: dict(item) if type(item) is dict else item for key, item in value.items()}


def _f18_identity(path):
    import stat
    value = _contracts().safe_path(path).lstat()
    _f18_require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1,
                 "F18 input must be an unaliased regular file")
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _f18_open(c, reference, limit, opened):
    before = _f18_identity(reference["path"])
    raw = c.verify(reference, limit)
    _f18_require(_f18_identity(reference["path"]) == before, "F18 input changed at opening fence")
    opened.append((dict(reference), before, limit))
    return raw


def _f18_close(c, opened):
    for reference, identity, limit in opened:
        _f18_require(_f18_identity(reference["path"]) == identity, "F18 input changed before closing fence")
        c.verify(reference, limit)
        _f18_require(_f18_identity(reference["path"]) == identity, "F18 input changed at closing fence")


def _f18_owners(request):
    import hashlib
    from . import legal_span_modality_conditions_retention as f18
    from . import legal_span_conditions_fullspan_training_v1 as profile
    from ...logic.legal_ir import joint_span_selection as joint
    root = Path(request["cwd"])
    for module, expected in ((profile, _F18_PROFILE_SHA256), (f18, _F18_SOURCE_SHA256),
                             (joint, _F18_JOINT_SHA256)):
        path = Path(module.__file__).resolve()
        _f18_require(path.is_relative_to(root) and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                     "qualified F18 numerical source generation differs")
    profile._reuse_owners()
    return f18, profile, joint


def _f18_authenticate(c, f18, profile, manifest, raw, descriptors):
    donor = f18.load_checkpoint(descriptors[0]["path"], expected_sha256=descriptors[0]["sha256"])
    _f18_require(donor["progress"]["optimizer_steps"] == 32, "final trained F18 donor required")
    teacher = c.parse_json(raw[_F18_ROLES[1]])
    _f18_require(f18._raw(teacher) == f18._raw(donor["source_actor_refinement_checkpoint"])
                 and f18.checkpoint_digest(teacher) == f18.SOURCE_ACTOR_REFINEMENT_SHA256
                 and f18.checkpoint_digest(teacher["model_state"]) == f18.SOURCE_ACTOR_REFINEMENT_MODEL_SHA256,
                 "external/nested F15 teacher differs")
    _f18_require(raw[_F18_ROLES[4]] == donor["teacher_capture_utf8"].encode(),
                 "external/nested TRAIN-only F15 capture differs")
    certificate = c.parse_json(raw[_F18_ROLES[5]])
    _f18_require(f18._raw(certificate) == f18._raw(donor["training_mask_certificate"])
                 and f18.checkpoint_digest(certificate) == donor["training_mask_certificate_sha256"],
                 "external/nested training mask differs")
    training, expected = donor["teacher_training_examples"], manifest["population_roots"]
    _f18_require(type(training) is list and len(training) == 168
                 and f18.checkpoint_digest(training) == donor["training_manifest_sha256"] == expected["training_manifest_sha256"]
                 and f18.checkpoint_digest(training[:96]) == expected["legacy_prefix_sha256"],
                 "original TRAIN168/legacy96 manifest differs")
    records = f18._training_records(training)
    present = [i for i, row in enumerate(records) if row["labels"]["presence"][3] is True]
    _f18_require(len(records) == 168 and len(present) == 72
                 and sum(row["labels"]["presence"][3] is False for row in records) == 96,
                 "typed mixed TRAIN72/96 population differs")
    for key, value in expected["aggregate_roots"].items():
        _f18_require(donor["training_mask_certificate"]["targets"][key] == value,
                     "source/teacher/mask aggregate differs")
    _f18_require(donor["teacher_training"]["rows_sha256"] == expected["teacher_rows_sha256"],
                 "teacher row root differs")
    keys = ("hidden_size", "embedding_dim", "projection_width", "latent_dimension", "latent_enabled",
            "residual_scale", "seed", "batch_size", "learning_rate")
    provenance = profile.donor_provenance(donor["model_state"], config={key: donor["config"][key] for key in keys},
        gold_present_train_indices=present, gold_present_row_ids=[records[i]["id"] for i in present])
    _f18_require(f18.checkpoint_digest(donor["model_state"]) == _F18_MODEL_ROOT
                 and profile.frozen38_seal(donor["model_state"]) == _F18_FROZEN_ROOT,
                 "authenticated final F18 all42/frozen38 roots differ")
    bindings = {"schema": profile.BINDINGS_SCHEMA, "donor_checkpoint_sha256": descriptors[0]["sha256"],
        "donor_model_state_sha256": _F18_MODEL_ROOT, "donor_provenance_sha256": f18.checkpoint_digest(provenance),
        "source_parent_checkpoint_sha256": donor["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": donor["source_parent_model_state_sha256"],
        "context_contract_sha256": donor["context_contract_sha256"],
        "training_manifest_sha256": donor["training_manifest_sha256"],
        "prepared_training_records_sha256": f18.checkpoint_digest(records),
        "teacher_checkpoint_sha256": f18.SOURCE_ACTOR_REFINEMENT_SHA256,
        "teacher_model_state_sha256": f18.SOURCE_ACTOR_REFINEMENT_MODEL_SHA256,
        "teacher_capture_sha256": f18.TEACHER_CAPTURE_SHA256,
        "teacher_training_sha256": f18.checkpoint_digest(donor["teacher_training"]),
        "row_weight_training_sha256": f18.checkpoint_digest(donor["row_weight_training"]),
        "training_mask_certificate_sha256": f18.checkpoint_digest(certificate)}
    _f18_require(set(bindings) == profile.BINDING_FIELDS and len(bindings) == 15,
                 "exact15 independent F18 bindings required")
    return donor, records, provenance, bindings


def _f18_source_panels(c, f18, donor, records, raw, population):
    import math
    original, fresh = (c.parse_json(raw[_F18_ROLES[index]]) for index in (2, 3))
    _f18_require(type(original) is dict and set(original) == {
        "schema", "training_rows", "training_metadata", "diagnostic_sources", "semantic_gold"}
        and original["schema"] == "temporal-adapter-source-only-diagnostics-export/v1"
        and original["semantic_gold"] is False, "closed original source export required")
    _f18_require(type(original["training_rows"]) is list and type(original["training_metadata"]) is list
        and len(original["training_rows"]) == len(original["training_metadata"]) == 168
        and f18._raw(original["training_rows"]) == f18._raw(donor["teacher_training_examples"])
        and f18.checkpoint_digest(original["training_rows"]) == donor["training_manifest_sha256"],
        "original source-export raw TRAIN168 join differs")
    old_names = {name for name, _, _ in _F18_PANELS[1:8]}
    _f18_require(type(original["diagnostic_sources"]) is dict and set(original["diagnostic_sources"]) == old_names,
                 "exact seven original source panels required")
    _f18_require(type(fresh) is dict and set(fresh) == {"schema", "populations", "semantic_gold"}
        and fresh["schema"] == "temporal-attention-fresh-source-export/v1" and fresh["semantic_gold"] is False
        and type(fresh["populations"]) is dict and set(fresh["populations"]) == {"fresh_dev", "fresh_test"},
        "closed fresh source export required")
    _f18_require(population.get("schema") == "retained-final-f18-source-only-632-parity-descriptors/v1"
        and [(row["panel"], row["expected_rows"], tuple(row["chunk_sizes"])) for row in population["panels"]]
        == list(_F18_PANELS), "qualified632 population roster differs")
    result, ids, texts = {}, set(), set()
    for name, count, _ in _F18_PANELS:
        offered = records if name == "training168" else (fresh["populations"][name]
            if name in {"fresh_dev", "fresh_test"} else original["diagnostic_sources"][name])
        _f18_require(type(offered) is list and len(offered) == count, "complete original panel count differs")
        if name != "training168":
            _f18_require(all(type(row) is dict and set(row) == {"id", "source_text", "latent"} for row in offered),
                         "reference/gold fields forbidden in source-only rows")
        rows = [{key: row[key] for key in ("id", "source_text", "latent")} for row in offered]
        for row in rows:
            _f18_require(type(row["id"]) is str and row["id"].strip() and type(row["source_text"]) is str
                and 0 < len(row["source_text"].strip()) <= 16384 and row["id"] not in ids
                and row["source_text"] not in texts, "unique bounded original source identity required")
            _f18_require(type(row["latent"]) is list and len(row["latent"]) == 384
                and all(type(v) in (int, float) and math.isfinite(v) for v in row["latent"]),
                "finite original dormant384 vectors required")
            if name in {"fresh_dev", "fresh_test"}:
                _f18_require(all(v == 0.0 for v in row["latent"]), "fresh-only zero384 vectors required")
            ids.add(row["id"]); texts.add(row["source_text"])
        result[name] = rows
    _f18_require(len(ids) == len(texts) == 632, "exact distinct632 source population required")
    return result


def _f18_parity(parity, bindings, compute, population, descriptors):
    """Bind the genuine fresh v1 zero-step result, separate from v2 parity."""
    _f18_require(compute["initial_parity"]["sha256"] == _F18_V1_PARITY_SHA256
        and compute["initial_parity"]["bytes"] == 31655
        and type(parity) is dict
        and parity.get("schema") == "retained-f18-four-tensor-initial632-parity-result/v1"
        and parity.get("profile_source_sha256") == _F18_PROFILE_SHA256
        and parity.get("original_f18_source_sha256") == _F18_SOURCE_SHA256
        and parity.get("initial632_parity_qualified") is True
        and parity.get("parity_receipt_fabricated") is False,
        "exact qualified v1 initial632 parity generation required")
    binding_fields = {"schema", "donor_checkpoint_sha256", "donor_model_state_sha256",
        "donor_provenance_sha256", "source_parent_checkpoint_sha256", "source_parent_model_state_sha256",
        "context_contract_sha256", "training_manifest_sha256", "prepared_training_records_sha256",
        "teacher_checkpoint_sha256", "teacher_model_state_sha256", "teacher_capture_sha256",
        "teacher_training_sha256", "row_weight_training_sha256", "training_mask_certificate_sha256"}
    _f18_require(type(bindings) is dict and set(bindings) == binding_fields
        and bindings.get("schema") == "conditions-fullspan-f18-four-tensor-input-bindings/v1"
        and all(type(bindings[key]) is str and len(bindings[key]) == 64
            and all(char in "0123456789abcdef" for char in bindings[key])
            for key in binding_fields - {"schema"})
        and parity.get("expected_input_bindings") == bindings
        and parity.get("inputs_sha256") == compute["input_descriptors"]["sha256"]
        and parity.get("parity_manifest_sha256") == compute["population_manifest"]["sha256"]
        and parity.get("runtime_contract_sha256") == compute["runtime_contract"]["sha256"],
        "v1 parity independent input/population/runtime bindings differ")
    assets = parity.get("verified_assets")
    _f18_require(type(assets) is list and len(assets) == len(descriptors) == 6
        and all(type(a) is dict and type(b) is dict
            and a.get("role") == b.get("role") == role
            and all(a.get(key) == b.get(key) for key in ("bytes", "sha256"))
            for a, b, role in zip(assets, descriptors, _F18_ROLES, strict=True)),
        "v1 parity six authenticated physical asset identities differ")
    _f18_require(parity.get("authenticated_final_F18_whole_sha256") == bindings["donor_checkpoint_sha256"]
        and parity.get("all42_model_state_sha256") == bindings["donor_model_state_sha256"] == _F18_MODEL_ROOT
        and parity.get("frozen38_sha256_including_modality") == _F18_FROZEN_ROOT,
        "v1 parity authenticated donor/frozen roots differ")
    for name, expected in (("head_binary32_scalar_comparisons", 194812),
            ("canonical_capture_source_forwards", 632), ("canonical_capture_chunks", 11),
            ("training_rows", 168), ("conditions_present", 72), ("conditions_absent", 96),
            ("optimizer_updates", 0), ("gradient_calls", 0), ("teacher_model_restores", 0)):
        _f18_require(type(parity.get(name)) is int and parity[name] == expected,
                     "v1 parity finite zero-step counts differ: " + name)
    _f18_require(all(parity.get(key) is False for key in (
        "fit_executed", "scoring_executed", "new_trained_weights", "admitted", "formalized", "promoted")),
        "v1 parity control is not a TRAIN experiment or authority")
    panels = parity.get("panel_comparisons")
    _f18_require(type(panels) is list and len(panels) == len(_F18_PANELS)
        and all(type(row) is dict and row.get("panel") == name
            and type(row.get("rows")) is int and row["rows"] == count
            and type(row.get("binary32_head_scalars")) is int and row["binary32_head_scalars"] > 0
            and all(row.get(key) is True for key in (
                "all_heads_bitwise_equal", "entire_greedy_formal_rows_equal", "complete_joint_rows_equal"))
            for row, (name, count, _) in zip(panels, _F18_PANELS, strict=True))
        and sum(row["binary32_head_scalars"] for row in panels) == 194812,
        "v1 parity complete ten-panel binary32/greedy/joint comparison required")
    for name, index in (("authenticated_final_F18_checkpoint", 0), ("original_source_export", 2), ("fresh_source_export", 3)):
        _f18_require(all(population["source_inputs"][name][key] == descriptors[index][key]
            for key in ("bytes", "sha256")), "original632 source asset identity differs")


def _f18_v2_profile(request):
    """Select the separately qualified v2 numerical owner after original RUN."""
    import hashlib
    from . import legal_span_conditions_fullspan_training_v2 as profile
    root = Path(request["cwd"])
    for module, expected in ((profile, _F18_V2_PROFILE_SHA256), (profile.recipes, _F18_RECIPE_SHA256)):
        path = Path(module.__file__).resolve()
        _f18_require(path.is_relative_to(root)
            and request["source_sha256"].get(str(path)) == expected
            and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
            "qualified v2 numerical/recipe source generation differs")
    profile._implementation()
    return profile


def _f18_v2_parity(parity, bindings, compute, population, descriptors):
    """Reuse the exact closed zero-step result, independently of the TRAIN rate."""
    _f18_require(compute["initial_parity"]["sha256"] == _F18_V2_PARITY_SHA256
        and compute["initial_parity"]["bytes"] == 31777
        and type(parity) is dict
        and parity.get("schema") == "retained-f18-four-tensor-initial632-parity-result/v2"
        and parity.get("profile_source_sha256") == _F18_V2_PROFILE_SHA256
        and parity.get("original_f18_source_sha256") == _F18_SOURCE_SHA256
        and parity.get("initial632_parity_qualified") is True
        and parity.get("parity_receipt_fabricated") is False,
        "exact qualified v2 initial632 parity generation required")
    _f18_require(parity.get("expected_input_bindings") == bindings
        and parity.get("inputs_sha256") == compute["input_descriptors"]["sha256"]
        and parity.get("parity_manifest_sha256") == compute["population_manifest"]["sha256"]
        and parity.get("runtime_contract_sha256") == compute["runtime_contract"]["sha256"],
        "v2 parity independent input/population/runtime bindings differ")
    assets = parity.get("verified_assets")
    _f18_require(type(assets) is list and len(assets) == len(descriptors) == 6
        and all(type(a) is dict and type(b) is dict
            and a.get("role") == b.get("role") == role
            and all(a.get(key) == b.get(key) for key in ("bytes", "sha256"))
            for a, b, role in zip(assets, descriptors, _F18_ROLES, strict=True)),
        "v2 parity six authenticated physical asset identities differ")
    _f18_require(parity.get("authenticated_final_F18_whole_sha256") == bindings["donor_checkpoint_sha256"]
        and parity.get("all42_model_state_sha256") == bindings["donor_model_state_sha256"] == _F18_MODEL_ROOT
        and parity.get("frozen38_sha256_including_modality") == _F18_FROZEN_ROOT,
        "v2 parity authenticated donor/frozen roots differ")
    for name, expected in (("head_binary32_scalar_comparisons", 194812),
            ("canonical_capture_source_forwards", 632), ("canonical_capture_chunks", 11),
            ("training_rows", 168), ("conditions_present", 72), ("conditions_absent", 96),
            ("optimizer_updates", 0), ("gradient_calls", 0), ("teacher_model_restores", 0)):
        _f18_require(type(parity.get(name)) is int and parity[name] == expected,
                     "v2 parity finite zero-step counts differ: " + name)
    _f18_require(all(parity.get(key) is False for key in (
        "fit_executed", "scoring_executed", "new_trained_weights", "admitted", "formalized", "promoted"))
        and parity.get("experiment_rate_selected") is None
        and parity.get("parity_optimizer_learning_rate") == 0.001
        and parity.get("donor_config_learning_rate") == 0.001,
        "v2 parity control is not a TRAIN experiment or authority")
    panels = parity.get("panel_comparisons")
    _f18_require(type(panels) is list and len(panels) == len(_F18_PANELS)
        and all(type(row) is dict and row.get("panel") == name
            and type(row.get("rows")) is int and row["rows"] == count
            and type(row.get("binary32_head_scalars")) is int and row["binary32_head_scalars"] > 0
            and all(row.get(key) is True for key in (
                "all_heads_bitwise_equal", "entire_greedy_formal_rows_equal", "complete_joint_rows_equal"))
            for row, (name, count, _) in zip(panels, _F18_PANELS, strict=True))
        and sum(row["binary32_head_scalars"] for row in panels) == 194812,
        "v2 parity complete ten-panel binary32/greedy/joint comparison required")
    for name, index in (("authenticated_final_F18_checkpoint", 0), ("original_source_export", 2), ("fresh_source_export", 3)):
        _f18_require(all(population["source_inputs"][name][key] == descriptors[index][key]
            for key in ("bytes", "sha256")), "v2 parity source population asset differs")


from contextlib import contextmanager as _f18_contextmanager


@_f18_contextmanager
def _f18_runtime(c, runtime, opened, request):
    import hashlib
    import subprocess
    _f18_require(type(runtime) is dict and set(runtime) == {"schema", "requested_library", "ctypes_util_pin",
        "cuda_pathfinder_pin", "library_pin", "subprocess_fallback_allowed", "unlisted_library_names_allowed"}
        and runtime["schema"] == "pinned-libdl-resolution/v1" and runtime["requested_library"] == "dl"
        and runtime["subprocess_fallback_allowed"] is False and runtime["unlisted_library_names_allowed"] is False,
        "closed original libdl runtime contract required")
    for name in ("ctypes_util_pin", "cuda_pathfinder_pin", "library_pin"):
        _f18_open(c, runtime[name], 128 * 1024, opened)
    _f18_require(Path(ctypes.util.__file__).resolve() == Path(runtime["ctypes_util_pin"]["path"]),
                 "real stdlib ctypes.util origin differs")
    observations = {"external_process_attempts": [], "scoped_dl_resolver_calls": [], "resolver_restored": False}
    original_popen, original_resolver = subprocess.Popen, ctypes.util.find_library
    class RefusedPopen(original_popen):
        def __init__(self, argv, *args, **kwargs):
            observations["external_process_attempts"].append(repr(argv))
            raise RuntimeError("external subprocess outside fixed F18 numerical worker")
    def find_dl(name):
        observations["scoped_dl_resolver_calls"].append(name)
        _f18_require(type(name) is str and name == "dl", "unlisted runtime library lookup")
        return runtime["library_pin"]["path"]
    subprocess.Popen = RefusedPopen
    ctypes.util.find_library = find_dl
    try:
        try:
            import torch
        finally:
            ctypes.util.find_library = original_resolver
            observations["resolver_restored"] = True
        path = Path(torch.__file__).resolve()
        _f18_require(request["source_sha256"].get(str(path)) == hashlib.sha256(path.read_bytes()).hexdigest(),
                     "actual Torch source origin not pinned by original request")
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        yield torch, observations
        _f18_require(not observations["external_process_attempts"]
                     and all(name == "dl" for name in observations["scoped_dl_resolver_calls"]),
                     "numerical runtime scope changed")
    finally:
        ctypes.util.find_library = original_resolver
        subprocess.Popen = original_popen


def _f18_capture_arm(c, f18, profile, joint, torch, checkpoint, kwargs, panels, directory):
    import hashlib
    runtime = profile.restore_optimizer(torch, checkpoint, **kwargs)
    outputs, total = [], 0
    for name, count, sizes in _F18_PANELS:
        rows, chunks, cursor = panels[name], [], 0
        for size in sizes:
            chunk = profile.captured_inference(runtime, checkpoint, rows[cursor:cursor + size], **kwargs)
            total += size
            _f18_require(chunk["actual_source_forwards"] == size and chunk["extra_capture_forwards"] == 0
                and chunk["cumulative_source_forwards"] == total
                and all(type(v) is int and v == size for table in chunk["forward_counter_deltas"].values() for v in table.values())
                and chunk["target_access"] is False and chunk["teacher_forcing"] is False,
                "canonical trained capture accounting differs")
            chunks.append(chunk); cursor += size
        _f18_require(cursor == count, "complete trained source panel required")
        raw = c.write_new(directory / (name + "-raw.json"), {"schema": "f18-paired-target-free-panel/v2" if "recipe" in kwargs else "f18-paired-target-free-panel/v1",
            "panel": name, "rows": count, "chunks": chunks, "source_model_forwards": count,
            "target_access": False, "teacher_forcing": False, **_F18_FALSE}, 32 * 1024 * 1024)
        occurrences = [row for chunk in chunks for row in chunk["occurrences"]]
        _f18_require(len(occurrences) == count, "complete trained occurrences required")
        selected = []
        for row, occurrence in zip(rows, occurrences, strict=True):
            _f18_require(row["id"] == occurrence["id"] and occurrence["source_sha256"]
                == hashlib.sha256(row["source_text"].encode()).hexdigest(), "trained capture source join differs")
            selected.append({"id": row["id"], "result": joint.select_joint_spans(row["source_text"],
                occurrence["scores"], top_k=8, max_search_nodes=50000)})
        chosen = c.write_new(directory / (name + "-joint.json"), {"schema": "modality-conditions-retention-joint-panel/v1",
            "rows": selected, "top_k": 8, "max_search_nodes": 50000, "reference_scoring_performed": False,
            **_F18_FALSE}, 32 * 1024 * 1024)
        outputs.append({"panel": name, "rows": count, "raw": raw, "joint": chosen})
    _f18_require(total == runtime["model_forwards"] == 632, "exact trained632 native source count required")
    return outputs


def _f18_fit_pair(c, f18, profile, joint, torch, donor, records, provenance, bindings, panels, directory,
                  *, learning_rate=None):
    results, updates, captures = [], 0, 0
    base = dict(state=donor["model_state"], provenance=provenance, records=records,
                teacher=donor["teacher_training"], weights=donor["row_weight_training"], expected_bindings=bindings)
    recipes = None
    if learning_rate is not None:
        import sys
        _f18_require(type(learning_rate) in (int, float) and 0 < learning_rate <= sys.float_info.max,
                     "explicit finite positive TRAIN learning_rate required")
        # Build and validate both from caller-bound data before either arm exists.
        recipes = []
        for margin in (0.0, 0.25):
            expected = dict(donor_config=provenance["config"], expected_bindings=bindings,
                            learning_rate=learning_rate, margin_weight=margin)
            recipe = profile.recipes.build_optimizer_recipe(**expected)
            recipes.append(profile.recipes.validate_optimizer_recipe(recipe, **expected))
    for index, (label, margin) in enumerate((("arm-0", 0.0), ("arm-025", 0.25))):
        arm = directory / label
        arm.mkdir(mode=0o700)
        kwargs = {**base, "margin_weight": margin}
        recipe_ref = None
        if recipes is not None:
            kwargs.update(recipe=recipes[index], learning_rate=learning_rate)
            recipe_ref = c.write_new(arm / "optimizer-recipe.json", recipes[index], 128 * 1024)
        initial = profile.build_checkpoint(**kwargs)
        initial_ref = profile.save_checkpoint(initial, arm / "initial-checkpoint.json", **kwargs)
        trained, report = profile.run_admitted_updates(initial, torch=torch, **kwargs, max_steps=32, max_seconds=32)
        checkpoint_ref = profile.save_checkpoint(trained, arm / "checkpoint.json", **kwargs)
        report_ref = c.write_new(arm / "training-report.json", report, 32 * 1024 * 1024)
        steps = report["optimizer_steps"]
        _f18_require(type(steps) is int and 0 <= steps <= 32 and len(report["batch_trace"]) == steps
            and report["requested_steps"] == 32 and report["before_progress"] == initial["progress"]
            and report["after_progress"] == trained["progress"]
            and report["checkpoint_sha256"] == profile.checkpoint_digest(trained)
            and type(report["all_requested_steps_completed"]) is bool
            and report["all_requested_steps_completed"] is (steps == 32), "finite32 training report differs")
        updates += steps
        row = {"arm": label, "margin_weight": margin, "initial_checkpoint": initial_ref,
               "checkpoint": checkpoint_ref, "report": report_ref, "optimizer_updates": steps,
               "model_state_sha256": trained["model_state_sha256"], "progress": dict(trained["progress"])}
        if recipe_ref is not None:
            row.update(optimizer_recipe=recipe_ref, learning_rate=learning_rate,
                       donor_config_learning_rate=provenance["config"]["learning_rate"])
        results.append(row)
        if steps != 32:
            return results, updates, captures, False
        _f18_require(trained["progress"] == {"epochs_completed": 2, "row_cursor": 48, "optimizer_steps": 32},
                     "exact32 mixed168 schedule progress required")
        persisted = profile.load_checkpoint(checkpoint_ref["path"], expected_sha256=checkpoint_ref["sha256"], **kwargs)
        _f18_require(profile.checkpoint_digest(persisted) == profile.checkpoint_digest(trained),
                     "trained checkpoint readback differs")
        row["captures"] = _f18_capture_arm(c, f18, profile, joint, torch, persisted, kwargs, panels, arm)
        captures += 632
    return results, updates, captures, True


def run_f18_paired_training(request, *, output_directory):
    """Fixed0/.25 numerical work under caller-owned original trainer custody.

    Called only after the genuine parent READY/RUN boundary. This function does
    not inspect a bool/token as a grant, schedule a process, claim a lease, score
    cases or change authority flags. All four metadata refs and six payloads
    are opened here, never by the pre-release CLI shape parser.
    """
    import hashlib
    _f18_require(type(request) is dict and type(request.get("schema")) is str
        and request["schema"] in ("owned-f18-conditions-training-request/v1", "owned-f18-conditions-training-request/v2")
        and request.get("mode") == "paired_fit", "fixed paired-fit trainer request required")
    version = 2 if request["schema"] == "owned-f18-conditions-training-request/v2" else 1
    compute = validate_f18_compute(request.get("compute"), version=version)
    profile_sha256 = _F18_V2_PROFILE_SHA256 if version == 2 else _F18_PROFILE_SHA256
    c, opened = _contracts(), []
    output = c.safe_path(output_directory)
    _f18_require(output.is_dir() and output == Path(request["outputs"]["exports"]), "original owned exports required")
    directory = output / "f18-paired"
    directory.mkdir(mode=0o700)
    metadata = {name: c.parse_json(_f18_open(c, compute[name], 128 * 1024, opened)) for name in
                ("input_descriptors", "initial_parity", "runtime_contract", "population_manifest")}
    manifest = metadata["input_descriptors"]
    _f18_require(type(manifest) is dict and manifest.get("schema") == "retained-f18-input-authentication-descriptors/v1"
        and type(manifest.get("assets")) is list and len(manifest["assets"]) == 6
        and tuple(row.get("role") for row in manifest["assets"]) == _F18_ROLES,
        "exact six original F18 authentication roles required")
    descriptors, raw = manifest["assets"], {}
    for row in descriptors:
        _f18_require(type(row) is dict and set(row) == {"path", "bytes", "sha256", "role"},
                     "closed original F18 asset descriptor required")
        ref = {key: row[key] for key in ("path", "bytes", "sha256")}
        raw[row["role"]] = _f18_open(c, ref, 32 * 1024 * 1024, opened)
    _f18_require(len({row["path"] for row in descriptors}) == 6, "six distinct original F18 assets required")
    f18, profile, joint = _f18_owners(request)
    started = time.monotonic()
    with _f18_runtime(c, metadata["runtime_contract"], opened, request) as (torch, runtime_observations):
        donor, records, provenance, bindings = _f18_authenticate(c, f18, profile, manifest, raw, descriptors)
        fit_options = {}
        if version == 2:
            _f18_v2_parity(metadata["initial_parity"], bindings, compute, metadata["population_manifest"], descriptors)
            numerical = _f18_v2_profile(request)
            fit_options["learning_rate"] = compute["learning_rate"]
        else:
            _f18_parity(metadata["initial_parity"], bindings, compute, metadata["population_manifest"], descriptors)
            numerical = profile
        panels = _f18_source_panels(c, f18, donor, records, raw, metadata["population_manifest"])
        arms, updates, captures, complete = _f18_fit_pair(c, f18, numerical, joint, torch, donor, records,
                                                        provenance, bindings, panels, directory, **fit_options)
        freeze = None
        if complete:
            _f18_require(updates == 64 and captures == 1264 and len(arms) == 2
                and sum(len(row["captures"]) * 2 for row in arms) == 40, "complete finite pair required")
            freeze = c.write_new(directory / "pair-output-freeze.json", {
                "schema": "f18-paired-training-output-freeze/v" + str(version), "profile_sha256": profile_sha256,
                "input_metadata": {key: compute[key] for key in
                    ("input_descriptors", "initial_parity", "runtime_contract", "population_manifest")},
                "donor_model_state_sha256": _F18_MODEL_ROOT, "frozen38_sha256": _F18_FROZEN_ROOT,
                "input_bindings": bindings, "arms": arms, "optimizer_updates": updates,
                "source_capture_forwards": captures, "raw_joint_files": 40,
                "evaluation_gold_reference_or_comparator_bodies_opened": 0,
                "future_scoring_performed": False,
                 **({"training_learning_rate": compute["learning_rate"], "donor_config_learning_rate": 0.001,
                     "optimizer_recipe_source_sha256": _F18_RECIPE_SHA256} if version == 2 else {}),
                 **_F18_FALSE}, 4 * 1024 * 1024)
        _f18_close(c, opened)
    return {"schema": "f18-paired-conditions-training-result/v" + str(version), "completed": complete,
        **({"training_learning_rate": compute["learning_rate"], "donor_config_learning_rate": 0.001,
            "optimizer_recipe_source_sha256": _F18_RECIPE_SHA256} if version == 2 else {}),
        "profile_source_sha256": profile_sha256, "optimizer_updates": updates,
        "model_forwards": updates + captures, "training_model_forwards": updates,
        "capture_source_forwards": captures, "model_forward_scope": "one batch call per update plus one source call per capture",
        "legacy6_donor_restore_calls": 1, "fit_fresh4_restore_calls": len(arms) if all(row["optimizer_updates"] > 0 for row in arms) else None,
        "fit_fresh4_restore_calls_upper_bound": len(arms),
        "capture_fresh4_restore_calls": sum("captures" in row for row in arms),
        "teacher_model_restores": 0, "teacher_model_forwards": 0,
        "arms": arms, "output_freeze": freeze, "input_bindings": bindings,
        "runtime_observations": runtime_observations, "elapsed_seconds": time.monotonic() - started,
        "training_executed": bool(updates), "scoring_performed": False,
        "native_or_source_cleanup_asserted_by_worker": False, **_F18_FALSE}
