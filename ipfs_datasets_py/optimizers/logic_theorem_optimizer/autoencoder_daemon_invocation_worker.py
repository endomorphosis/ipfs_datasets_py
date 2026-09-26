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
