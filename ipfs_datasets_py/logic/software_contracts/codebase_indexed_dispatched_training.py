"""Source-owned training retries with exact native request recovery.

This entrypoint keeps the existing checkpoint producer and transport sidecar
formats. Completed retries rebuild the requested round from live source and
the verified original parent before recovering its immutable queue receipts.
The request index is enabled by default; callers can retain bounded legacy
discovery by passing ``use_request_index=False``.
"""
from __future__ import annotations

import re
import time

from ipfs_datasets_py.duckdb_control.autoencoder_federated import create_federated_run
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import ClientSpec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_sync import (
    GradientBackendUnavailable,
    TrainingMode,
)

from . import codebase_dispatched_federation as owner
from . import codebase_federated_training as federation
from . import codebase_indexed_dispatch_recovery as indexed
from . import codebase_source_training as source


def train_current_indexed_dispatched_codebase_round(index, repository, *, expected_head, registry,
        base_version_id, clients, operation_id, dispatcher, worker=None, artifacts=None,
        epochs=1, learning_rate=.002, seed=1729, mode=TrainingMode.FEDERATED,
        limits=None, scheduler=None, parent_lease=None, cancel_event=None,
        admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024,
        use_request_index=True):
    """Train a compatible round or recover its exact completed request cohort.

    A completed call still verifies the requested source head, parent, client
    partition and optimizer configuration. Its native round registration is an
    idempotent payload check. Recovery publishes provenance only, without a
    queue claim, dispatch, artifact-worker invocation or optimizer step.

    Incomplete calls use the existing source-owned executor after preflight.
    This wrapper does not change that executor's sequential completion path.
    Opting out changes queue discovery; source and prospective model bounds
    are checked for both policies before native run creation or delegation.
    """
    source._require(type(use_request_index) is bool, "explicit request-index policy required")
    arguments = dict(expected_head=expected_head, registry=registry, base_version_id=base_version_id,
        clients=clients, operation_id=operation_id, dispatcher=dispatcher, worker=worker, artifacts=artifacts,
        epochs=epochs, learning_rate=learning_rate, seed=seed, mode=mode, limits=limits,
        scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
        admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds,
        memory_mb=memory_mb)
    source._require(type(mode) is TrainingMode, "explicit native training mode required")
    if mode is not TrainingMode.FEDERATED:
        raise GradientBackendUnavailable("dispatched CodebaseIR executor implements federation only")
    source._native_owners(index, registry)
    source._text(operation_id, "operation_id", 128)
    source._require(re.fullmatch(r"[A-Za-z0-9._:-]+", operation_id), "native operation token required")
    source._require(type(dispatcher) is owner._transport().CodebaseQueueDispatcher,
                    "native CodebaseQueueDispatcher required")
    if artifacts is None:
        selected_worker = getattr(dispatcher, "handler", None) if worker is None else worker
        artifacts = getattr(selected_worker, "artifacts", index.artifacts)
    queue, artifacts, limits = indexed._owners(index, registry, dispatcher, None,
                                             artifacts, limits, use_request_index)
    configuration = federation._configuration(epochs, learning_rate, seed)
    with source._resources(index, repository, expected_head, scheduler=scheduler,
            parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds,
            memory_mb=memory_mb, limits=limits) as (_, _, remaining, observe):
        base = indexed._checked_child(index, registry, base_version_id, limits)
        source._require(base["depth"] < limits.max_ancestry, "prospective federation ancestry depth exceeded")
        adapter = federation._adapter().CodebaseFeatureCheckpoint.from_runtime(
            federation._runtime(base["saved"]), base_sha256=base["row"]["artifact"]["sha256"],
            base_version_id=base_version_id)
        source._require(adapter.state["optimizer_config"]["learning_rate"] == configuration["learning_rate"],
                        "private Adam resume requires the parent learning rate")
        selections = [source.CodebaseTrainingSelection.from_dict(item) for item in base["origin"]["selections"]]
        approved_clients = federation._clients(clients, selections)
        payloads, current_train = federation._capture(index, expected_head, base, approved_clients,
                                                       configuration, limits)
        source._require(len(base["history"]) + len(current_train) <= limits.max_training_history,
                        "prospective training history exceeds admitted history bound")
        run_id = "codebase-dispatched-fed:" + operation_id
        round_spec = adapter.build_round(run_id, "codebase-source:" + base["origin_version_id"],
            tuple(ClientSpec(item["client_id"], item["sample_count"], features.digest(item)) for item in payloads),
            max_local_steps=epochs)
        remaining()
        create_federated_run(registry, "codebase-dispatched-create:" + operation_id,
                             run_id, base_version_id, round_spec)
        completed = registry.get_run_completion(run_id)
        if completed is not None:
            native = completed["run"]
            source._require(native["spec"]["round"] == round_spec.manifest
                and native["base_version_id"] == base_version_id
                and native["variant_id"] == round_spec.model_id,
                "completed native round differs from requested source round")
            if use_request_index:
                record = indexed.recover_indexed_dispatched_codebase_round(index, registry,
                    completed["candidate_version"]["version_id"], queue=queue,
                    artifacts=artifacts, limits=limits)
                observe()
                remaining()
                return owner.CodebaseDispatchedTrainingRecord(record.artifact_cid, record._payload, True)
        execution_deadline = time.monotonic() + remaining()

    # Do not hold an extra root reservation around the existing executor. It
    # reacquires its source lease and repeats the idempotent exact-round check.
    arguments["timeout_seconds"] = execution_deadline - time.monotonic()
    if arguments["timeout_seconds"] <= 0:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseTimeoutError
        raise LeaseTimeoutError("CodebaseIR training deadline exceeded during preflight")
    return owner.train_current_dispatched_codebase_round(index, repository, **arguments)


__all__ = ["train_current_indexed_dispatched_codebase_round"]
