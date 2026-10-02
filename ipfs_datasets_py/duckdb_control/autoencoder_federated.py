"""Owner-side registration of federated rounds using existing registry records.

Workers retain private weights. This adapter records a round and a complete
materialized aggregate; it does not start trainers, transport parameter bytes,
implement a checkpoint codec, or select an inference head. Importing it opens
no database or network connection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Any

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import (
    AggregateCandidate,
    FederatedRound,
    aggregate_round,
)

from .autoencoder_registry import AutoencoderRegistry, RegistryError


RUN_SCHEMA = "autoencoder-federated-registry-run/v1"


def _round(round_spec: FederatedRound) -> FederatedRound:
    if type(round_spec) is not FederatedRound:
        raise RegistryError("a FederatedRound is required")
    # Reconstruct at the owner boundary so invalid direct object mutations do
    # not create durable records. All snapshots returned by the contract own
    # their dictionaries.
    return FederatedRound(**{
        name: getattr(round_spec, name) for name in round_spec.__dataclass_fields__
    })


def _spec(round_spec: FederatedRound) -> dict[str, Any]:
    return {"schema": RUN_SCHEMA, "round_sha256": round_spec.round_sha256,
            "round": round_spec.manifest}


def _base(registry: AutoencoderRegistry, base_version_id: str,
          round_spec: FederatedRound) -> None:
    version = registry.get_version(base_version_id)
    if version["variant_id"] != round_spec.model_id:
        raise RegistryError("federated model_id must match the registry variant")
    if version["artifact"]["sha256"] != round_spec.base_sha256:
        raise RegistryError("federated base differs from the registered checkpoint")
    registry.verify_artifact(version["artifact"])


def create_federated_run(
    registry: AutoencoderRegistry, operation_id: str, run_id: str,
    base_version_id: str, round_spec: FederatedRound,
) -> dict[str, Any]:
    """Persist the approved round without claiming a lease or running training.

    ``round_spec.model_id`` is the registry variant ID. The owner must prepare
    its parameter commitment from the verified base checkpoint, and approve
    each client's local-data identity and sample count before calling this.
    """
    round_spec = _round(round_spec)
    spec = _spec(round_spec)
    _base(registry, base_version_id, round_spec)
    return registry.create_run(operation_id, run_id, round_spec.model_id,
                               base_version_id, spec)


CheckpointVerifier = Callable[[FederatedRound, AggregateCandidate, Path], bool]


def complete_federated_run(
    registry: AutoencoderRegistry, operation_id: str, lease: Mapping[str, Any],
    round_spec: FederatedRound, base_parameters: dict, updates: list | tuple,
    checkpoint_path: str | Path, *, verify_checkpoint: CheckpointVerifier,
) -> dict[str, Any]:
    """Verify and record a complete checkpoint containing the computed aggregate.

    The trusted owner supplies ``verify_checkpoint(round, candidate, path)``.
    It must read the *staged immutable bytes*, check their numeric parameters
    against the candidate, and enforce its complete checkpoint/optimizer/head
    policy. Returning exactly ``True`` confirms materialization only; admission
    and model selection require the registry's separate evaluation and CAS.

    The caller first computes the aggregate to materialize it using the model's
    codec. This function recomputes it from the approved updates. Numeric rows
    alone are not a complete Legal checkpoint. Local optimizer state and corpus
    provenance must not be copied into an aggregate as shared authority.
    """
    round_spec = _round(round_spec)
    spec = _spec(round_spec)
    if not callable(verify_checkpoint):
        raise RegistryError("a trusted owner checkpoint verifier is required")
    if not isinstance(lease, Mapping) or "run_id" not in lease:
        raise RegistryError("a registry run lease is required")
    run = registry.get_run(lease["run_id"])
    if (run["spec"] != spec or run["variant_id"] != round_spec.model_id
            or run["lease"] != dict(lease)):
        raise RegistryError("run, round or lease binding differs")
    if run["status"] not in ("running", "completed"):
        raise RegistryError("federated run must be running or an exact completion retry")
    _base(registry, run["base_version_id"], round_spec)
    candidate = aggregate_round(round_spec, base_parameters, updates)
    artifact = registry.stage_artifact(checkpoint_path)
    stored = registry.artifact_path(artifact)
    if verify_checkpoint(round_spec, candidate, stored) is not True:
        raise RegistryError("owner checkpoint materialization verification failed")
    # Catch any accidental mutation of the staged file by a verifier. The
    # registry checks bytes again on completion before its short transaction.
    registry.verify_artifact(artifact)
    result = {"schema": "autoencoder-federated-registry-result/v1",
              "candidate_sha256": candidate.candidate_sha256,
              "aggregation": candidate.provenance,
              "materialization_verified": True,
              "admitted": False, "qualified": False,
              "promotion_performed": False, "publication_performed": False}
    return registry.complete_run(operation_id, lease, artifact, result)


__all__ = ["CheckpointVerifier", "RUN_SCHEMA", "create_federated_run",
           "complete_federated_run"]
