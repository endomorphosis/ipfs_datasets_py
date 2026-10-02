"""Bounded opt-in lifecycle for source384 adaptation through native run owners."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import threading
import time
import weakref

from . import codebase_model_generation as generation
from . import codebase_training_corpus as corpus_owner
from . import codebase_source_384 as numerical
from .codebase_ir import StaleCodebaseError
from ...duckdb_control import autoencoder_registry as native

SCHEMA = "codebase-training-job@1"
_ISSUED = weakref.WeakKeyDictionary()
_raw, _sha, _require = numerical._raw, numerical._sha, numerical._require


def _pins():
    return dict(lifecycle=_sha(Path(__file__).read_bytes()),
        registry=_sha(Path(native.__file__).read_bytes()), generation=generation._pins())


def _receipt(registry, operation, command, payload, result):
    return registry._mutate(operation, command, payload, lambda cx: deepcopy(result))


@dataclass(frozen=True, eq=False)
class CodebaseTrainingJob:
    def to_dict(self):
        _require(self in _ISSUED, "locally prepared training job required")
        return deepcopy(_ISSUED[self]["descriptor"])


def prepare_job(index, repository, *, expected_head, frozen_corpus, registry,
                parent_version_id, branch, expected_model_head, operation_id,
                embedding_snapshot, policy):
    """Freeze limits and native run identity before any numerical child starts."""
    numerical._owners(index, registry)
    policy = native.AutoencoderRegistry._lifecycle_policy(policy)
    numerical._limits(policy["wall_time_seconds"], policy["memory_bytes"] // 1024**2, operation_id)
    _require(policy["memory_bytes"] % 1024**2 == 0, "integral MiB reservation required")
    _require(policy["expected_head"] == expected_model_head, "job policy and parent head differ")
    generation._head(registry, parent_version_id, branch, expected_model_head)
    corpus = corpus_owner.verify_frozen_corpus(frozen_corpus, index, expected_head=expected_head)
    _require(len(corpus["rows"]) <= policy["max_samples"], "selected corpus exceeds sample budget")
    _, parent = numerical._lineage(index, registry, parent_version_id)[0]
    snapshot = str(Path(embedding_snapshot).resolve())
    worker_input = dict(action="train", parent=parent, corpus=corpus["fit_source_corpus"],
                        producer=numerical._pins(), embedding_snapshot=snapshot)
    _require(len(_raw(worker_input)) <= policy["max_input_bytes"], "numerical request exceeds input byte budget")
    request = dict(schema=generation.SCHEMA, operation_id=operation_id, parent_version_id=parent_version_id,
        branch=branch, expected_model_head=deepcopy(expected_model_head), source_head=expected_head.to_dict(),
        corpus_sha256=corpus["corpus_sha256"], producer=generation._pins(),
        environment=generation._environment(), embedding_snapshot=snapshot)
    run_id = "source384:generation:" + _sha(_raw(request))
    numerical_request = dict(profile=numerical.PROFILE, corpus_sha256=_sha(_raw(corpus["fit_source_corpus"])),
        producer=numerical._pins(), parent_version_id=parent_version_id, embedding_snapshot=snapshot)
    registry.create_run("create:" + run_id, run_id, expected_model_head["variant_id"],
                        parent_version_id, numerical_request)
    registry.configure_run_lifecycle(run_id, policy)
    descriptor = dict(schema=SCHEMA, producer=_pins(), native_run_id=run_id, policy=policy,
        generation_request=request, numerical_request_sha256=_sha(_raw(numerical_request)),
        expected_source_head=expected_head.to_dict(), corpus_sha256=corpus["corpus_sha256"],
        input_bytes=len(_raw(worker_input)), samples=len(corpus["rows"]),
        optimizer_steps=0, head_refits_per_attempt=1, retries=policy["max_attempts"]-1,
        proof_authority=False, admitted=False, promotion_performed=False)
    descriptor["job_sha256"] = _sha(_raw(descriptor))
    artifact = generation._stage(registry, descriptor)
    binding = _receipt(registry, "bind-job:" + descriptor["job_sha256"], "BindCodebaseTrainingJob",
        dict(run_id=run_id, job_artifact=artifact), dict(run_id=run_id, job_artifact=artifact))
    job = CodebaseTrainingJob()
    _ISSUED[job] = dict(descriptor=descriptor, binding=binding, index=index, repository=repository,
        expected_head=expected_head, frozen_corpus=frozen_corpus, registry=registry,
        arguments=dict(parent_version_id=parent_version_id, branch=branch,
            expected_model_head=deepcopy(expected_model_head), operation_id=operation_id,
            embedding_snapshot=snapshot))
    return job


def _state(job):
    _require(type(job) is CodebaseTrainingJob and job in _ISSUED, "locally prepared training job required")
    state = _ISSUED[job]
    descriptor = state["descriptor"]
    _require(descriptor["producer"] == _pins(), "training job owner implementation changed")
    _require(state["registry"].get_run_lifecycle(descriptor["native_run_id"]) == descriptor["policy"],
             "training job lifecycle policy changed")
    return state


def inspect_job(job):
    """Read durable state only; never claim, fit, promote or publish."""
    state = _state(job)
    run = state["registry"].get_run(state["descriptor"]["native_run_id"])
    return dict(schema=SCHEMA, job_sha256=state["descriptor"]["job_sha256"],
        native_run_id=run["run_id"], status=run["status"], attempt=run["attempt"], fence=run["fence"],
        terminal=deepcopy(run["result"]) if run["status"] in {"cancelled", "superseded"} else None,
        training_executed=False, admitted=False, promotion_performed=False)


def terminate_job(job, *, terminal="cancelled", reason="owner cancellation", successor=None):
    state = _state(job)
    registry, run_id = state["registry"], state["descriptor"]["native_run_id"]
    successor_run = None if successor is None else _state(successor)["descriptor"]["native_run_id"]
    for _ in range(3):
        run = registry.get_run(run_id)
        if run["status"] in {"cancelled", "superseded", "completed"}:
            return inspect_job(job)
        operation = "job-stop:" + _sha(_raw(dict(run_id=run_id, terminal=terminal,
            attempt=run["attempt"], fence=run["fence"], reason=reason, successor=successor_run)))
        try:
            registry.terminate_run(operation, run_id, terminal=terminal, expected_attempt=run["attempt"],
                expected_fence=run["fence"], reason=reason, successor_run_id=successor_run)
            return inspect_job(job)
        except native.RegistryError:
            changed = registry.get_run(run_id)
            if (changed["attempt"], changed["fence"]) == (run["attempt"], run["fence"]):
                raise
    raise native.RegistryError("training terminal transition could not fence the changing run")


class _Cancellation:
    def __init__(self, job, external, deadline):
        self.job, self.external, self.deadline = job, external, deadline
        self.state = _state(job)
        self._lock = threading.RLock()

    def is_set(self):
        with self._lock:
            state = self.state
            request = state["descriptor"]["generation_request"]
            expected = request["expected_model_head"]
            registry = state["registry"]
            run = registry.get_run(state["descriptor"]["native_run_id"])
            if run["status"] in {"cancelled", "superseded"}:
                return True
            if registry.resolve_head(expected["variant_id"], expected["branch"]) != expected:
                terminate_job(self.job, terminal="superseded", reason="expected parent head changed")
                return True
            if (self.external is not None and self.external.is_set()) or time.monotonic() >= self.deadline:
                terminate_job(self.job, reason="external cancellation" if time.monotonic() < self.deadline else "wall-time budget expired")
                return True
            return False


def execute_job(job, *, scheduler=None, parent_lease=None, cancel_event=None,
                timeout_seconds=None, memory_mb=None):
    """Consume an actual native parent lease and terminate revoked children."""
    state = _state(job)
    registry, descriptor = state["registry"], state["descriptor"]
    if scheduler is not None and parent_lease is not None:
        raise ValueError("choose scheduler or actual parent lease")
    policy = descriptor["policy"]
    limit = policy["wall_time_seconds"] if timeout_seconds is None else min(timeout_seconds, policy["wall_time_seconds"])
    memory = policy["memory_bytes"] // 1024**2
    _require(memory_mb is None or memory_mb == memory, "phase and native job memory reservations must match")
    numerical._limits(limit, memory, "execute")
    if cancel_event is not None:
        _require(callable(getattr(cancel_event, "is_set", None)), "cooperative cancellation signal required")
    run = registry.get_run(descriptor["native_run_id"])
    finish_operation = "finish-job:" + descriptor["job_sha256"]
    # A saved finish is historical state, not current-source admission.
    with registry._transaction() as cx:
        row = cx.execute("SELECT receipt FROM autoencoder_control.operations WHERE operation_id=?", [finish_operation]).fetchone()
    if row is not None:
        import json
        saved = json.loads(row[0])
        _require(set(saved) == {"schema", "operation_id", "command", "admitted", "outcome"}
            and saved["schema"] == native.SCHEMA and saved["command"] == "FinishCodebaseTrainingJob"
            and saved["operation_id"] == finish_operation and saved["admitted"] is False,
            "closed durable job finish required")
        outcome = saved["outcome"]
        _require(outcome["schema"] == SCHEMA and outcome["job_sha256"] == descriptor["job_sha256"]
            and outcome["native_run_id"] == descriptor["native_run_id"] and outcome["status"] == "completed",
            "durable job finish identity differs")
        resolved = registry.resolve_operation(finish_operation, "FinishCodebaseTrainingJob",
            dict(job_sha256=descriptor["job_sha256"], result=outcome))
        _require(resolved == saved, "durable job finish operation differs")
        replay = generation.load_generation(state["index"], registry, outcome["generation_version_id"])
        _require(replay["numerical_child"]["version_id"] == outcome["numerical_child_version_id"],
                 "durable job numerical child differs")
        return dict(outcome, training_executed=False, historical_replay=True, current_source_verified=False)
    if run["status"] in {"cancelled", "superseded"}:
        return inspect_job(job)
    _require(run["status"] != "running", "training job is already owned by another live attempt")
    signal = _Cancellation(job, cancel_event, time.monotonic()+limit)
    try:
        if signal.is_set():
            return inspect_job(job)
        result = generation.adapt_current_source384(state["index"], state["repository"],
            expected_head=state["expected_head"], frozen_corpus=state["frozen_corpus"], registry=registry,
            **state["arguments"], scheduler=scheduler, parent_lease=parent_lease, cancel_event=signal,
            timeout_seconds=max(.000001, signal.deadline-time.monotonic()), memory_mb=memory)
        _require(result["numerical_child_version_id"] == registry.get_run_completion(
            descriptor["native_run_id"])["candidate_version"]["version_id"], "job completed a different native run")
        value = dict(schema=SCHEMA, job_sha256=descriptor["job_sha256"], native_run_id=descriptor["native_run_id"],
            status="completed", generation_version_id=result["version_id"],
            numerical_child_version_id=result["numerical_child_version_id"],
            training_executed=result["training_executed"], historical_replay=False,
            current_source_verified=True, evaluation=result["evaluation"], promotion_performed=False)
        issued = _receipt(registry, finish_operation, "FinishCodebaseTrainingJob",
                          dict(job_sha256=descriptor["job_sha256"], result=value), dict(outcome=value))
        return deepcopy(issued["outcome"])
    except BaseException as error:
        if isinstance(error, StaleCodebaseError):
            terminate_job(job, terminal="superseded", reason="captured repository source changed")
        elif signal.is_set():
            pass
        run = registry.get_run(descriptor["native_run_id"])
        if run["status"] in {"cancelled", "superseded"}:
            return dict(inspect_job(job), bounded_child_returned=True, failure_type=type(error).__name__)
        raise


__all__ = ["CodebaseTrainingJob", "prepare_job", "execute_job", "inspect_job", "terminate_job", "SCHEMA"]
