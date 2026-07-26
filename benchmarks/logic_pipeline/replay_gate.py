"""CID-native fresh detached replay authority for HSSL-G238.

The older replay orchestrator remains available in :mod:`.replay` for
revision-1 compatibility.  This module is the revision-2 decision boundary:
it derives the exact replay population from a complete source index, requires
every success plus a deterministic failure sample, and compares semantic,
native-kernel, status, and independent-resource identities.  It performs no
fixture, corpus, manifest, or holdout I/O; its operational source validator
only rechecks caller-supplied private evidence bytes and live Git worktrees.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from types import MappingProxyType
from typing import Final, Mapping, Self, Sequence

from .causal_runtime import (
    CausalRuntimeEvidenceV2,
    validate_causal_runtime_evidence_v2,
)
from .cache_measurement import (
    symai_backend_identity,
    symai_semantic_payload,
)
from .content_addressing import cid_for_dag_json, validate_cid
from .contracts import OutcomeStatus, StageName
from .namespace_provenance import (
    G240_REPLAY_NAMESPACE_RECEIPT_SCHEMA_V2,
    G240_REPLAY_ORCHESTRATION_RECEIPT_SCHEMA_V2,
    G240PrivateReplayValidationSourcesV2,
    RuntimeNamespaceProvenanceError,
    g240_cache_namespace_set_cid,
    g240_worktree_safety_projection_cid,
    validate_g240_private_replay_sources_v2,
)
from .resource_statistics import (
    IndependentResourceReceiptV2,
    RESOURCE_REPLAY_COMPARISON_POLICY_V2_CID,
    compare_resource_replay_measurements_v2,
    runtime_resource_replay_coordinate_cid_v2,
    validate_independent_resource_receipt_v2,
)
from .report import (
    _stable_native_kernel_replay_projection,
    _stable_provenance_source_replay_projection,
    _stable_stage_replay_projection,
)


G238_REPLAY_SOURCE_RECORD_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-replay-source-record.v2"
)
G238_REPLAY_SOURCE_INDEX_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-replay-source-index.v2"
)
G238_DETACHED_REPLAY_RECEIPT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-execution-replay-receipt.v2"
)
G238_REPLAY_GATE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-execution-replay-gate.v2"
)
G238_REPLAY_POLICY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-execution-replay-policy.v2"
)
G238_SEMANTIC_OBSERVATION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-replay-semantic-observation.v2"
)
G238_RUNTIME_COORDINATE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-replay-runtime-coordinate.v2"
)
G238_SEMANTIC_IDENTITY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-replay-semantic-identity.v2"
)
G238_KERNEL_IDENTITY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-replay-kernel-identity.v2"
)
G238_STATUS_IDENTITY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-replay-status-identity.v2"
)
G238_COMPARISON_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-replay-comparison.v2"
)
G238_GIT_COMMIT_IDENTITY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.git-commit-identity.v2"
)
G238_FAILURE_SAMPLE_PER_STRATUM: Final = 1
G238_REPLAY_POLICY_V2_CID: Final = cid_for_dag_json(
    {
        "schema": G238_REPLAY_POLICY_SCHEMA_V2,
        "success_population": "all",
        "failure_population": (
            "lexicographically-lowest-record-cid-per-"
            "split-cache-variant-stratum"
        ),
        "failure_sample_per_stratum": G238_FAILURE_SAMPLE_PER_STRATUM,
        "required_identity_equalities": [
            "semantic",
            "terminal_native_kernel",
            "status",
            "resource_coordinate_policy_component",
        ],
        "resource_measurement_comparison_policy_cid": (
            RESOURCE_REPLAY_COMPARISON_POLICY_V2_CID
        ),
        "resource_measurements": (
            "paired_frozen_tolerance_evidence_not_receipt_equality"
        ),
        "fresh_isolation_dimensions": [
            "detached_worktree",
            "run",
            "process",
            "state",
            "cache",
        ],
        "operational_source_authority": {
            "namespace_receipt_schema": (
                G240_REPLAY_NAMESPACE_RECEIPT_SCHEMA_V2
            ),
            "orchestration_receipt_schema": (
                G240_REPLAY_ORCHESTRATION_RECEIPT_SCHEMA_V2
            ),
            "required_private_sources": [
                "source_policy",
                "source_executor_contract",
                "source_namespace_receipt",
                "source_worktree_safety_receipt",
                "replay_namespace_receipt",
                "replay_request",
                "replay_receipt",
                "replay_worktree_safety_receipt",
                "canonical_runtime_evidence_bytes",
            ],
            "source_recompute_live_worktrees": True,
            "source_namespace_values_come_from_per_target_receipt": True,
            "replay_command_equals_frozen_source_executor": True,
            "resource_producer_equals_replay_executor": True,
            "resource_validator_equals_replay_validator": True,
            "all_operational_authorities_distinct": True,
        },
        "holdout_access": False,
        "auto_merge": False,
    }
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_VARIANT = re.compile(r"A(?:[0-9]|1[0-2])\Z")
_SPLITS: Final = frozenset({"pilot", "development"})
_CACHE_MODES: Final = frozenset({"cold", "warm"})
_SOURCE_STATUSES: Final = frozenset({"success", "failure"})


class FreshReplayGateError(ValueError):
    """Raised when revision-2 detached replay evidence is malformed."""


def HSSLEV2381F50() -> str:
    """Return AST-verifiable evidence for the bounded G238 validator lane."""

    return (
        "CID-native all-success and deterministic failure-sample replay "
        "with fresh detached worktree, run, process, state, and cache "
        "isolation"
    )


def _cid(value: object, field: str) -> str:
    try:
        return validate_cid(value)
    except (TypeError, ValueError) as exc:
        raise FreshReplayGateError(
            f"{field} must be a canonical CIDv1/base32/sha2-256 value"
        ) from exc


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise FreshReplayGateError(
            f"{field} must be a safe nonempty identifier"
        )
    return value


def _commit(value: object, field: str = "source_commit") -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise FreshReplayGateError(
            f"{field} must be a full lowercase Git object id"
        )
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise FreshReplayGateError(
            f"{field} must be an object with string keys"
        )
    return value


def _plain(value: object) -> object:
    """Return detached DAG-JSON data, normalizing semantic enums."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise FreshReplayGateError(
                "G238 DAG-JSON object keys must be strings"
            )
        return {
            str(key): _plain(member)
            for key, member in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_plain(member) for member in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise FreshReplayGateError(
        f"G238 value is not DAG-JSON: {type(value).__name__}"
    )


def _freeze(value: object) -> object:
    """Deep-freeze detached DAG-JSON so caller mutation cannot change a CID."""

    plain = _plain(value)
    if isinstance(plain, dict):
        return MappingProxyType(
            {
                key: _freeze(member)
                for key, member in plain.items()
            }
        )
    if isinstance(plain, list):
        return tuple(_freeze(member) for member in plain)
    return plain


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise FreshReplayGateError(f"{field} fields changed")


def g238_git_commit_cid(source_commit: str) -> str:
    """Address a Git OID without misrepresenting the bare OID as a CID."""

    commit = _commit(source_commit)
    return cid_for_dag_json(
        {
            "schema": G238_GIT_COMMIT_IDENTITY_SCHEMA_V2,
            "object_format": "sha1" if len(commit) == 40 else "sha256",
            "object_type": "commit",
            "oid": commit,
        }
    )


def _runtime(
    value: CausalRuntimeEvidenceV2 | Mapping[str, object],
    field: str,
) -> CausalRuntimeEvidenceV2:
    try:
        source = value.to_dict() if isinstance(
            value, CausalRuntimeEvidenceV2
        ) else value
        return validate_causal_runtime_evidence_v2(source)
    except (TypeError, ValueError) as exc:
        raise FreshReplayGateError(
            f"{field} failed complete causal-runtime replay"
        ) from exc


def _runtime_coordinate_payload(
    evidence: CausalRuntimeEvidenceV2,
) -> dict[str, object]:
    """Project a run-independent immutable treatment coordinate."""

    result = evidence.case_result
    return {
        "schema": G238_RUNTIME_COORDINATE_SCHEMA_V2,
        "resource_replay_coordinate_cid": (
            runtime_resource_replay_coordinate_cid_v2(evidence)
        ),
        "source_cid": evidence.compiler_exposure.source_cid,
        "proof_context_cid": evidence.proof_context_cid,
        "case_id": result.case_id,
        "split": result.split.value,
        "cache_mode": result.cache_mode.value,
        "variant_id": result.variant_id,
        "stage_route": [
            stage.stage.value for stage in result.stages
        ],
        "run_identity_excluded": True,
        "runtime_receipt_identity_excluded": True,
        "holdout_included": False,
    }


def runtime_replay_coordinate_cid_v2(
    evidence: CausalRuntimeEvidenceV2 | Mapping[str, object],
) -> str:
    """Return the immutable G238 coordinate of complete runtime evidence."""

    replayed = _runtime(evidence, "runtime evidence")
    return cid_for_dag_json(_runtime_coordinate_payload(replayed))


def _stage_projection(stage: object) -> dict[str, object]:
    """Project deterministic stage semantics after typed receipt validation."""

    # CausalRuntimeEvidenceV2 validation has already replayed every StageRecord.
    # The mature revision-1 replay projection additionally validates
    # native-kernel, Hammer, Leanstral, and SyMAI subreceipts before removing
    # their explicitly documented run/cache/request bindings.
    try:
        if (
            stage.stage  # type: ignore[union-attr]
            in {StageName.COMPILER, StageName.SPACY}
            or (
                stage.stage  # type: ignore[union-attr]
                in {StageName.HAMMER, StageName.LEANSTRAL}
                and stage.status.value != "success"  # type: ignore[union-attr]
            )
        ):
            data = _plain(stage.data)  # type: ignore[union-attr]
            effective = _plain(
                stage.provenance.effective_identity  # type: ignore[union-attr]
            )
            requested = _plain(
                stage.provenance.requested_identity  # type: ignore[union-attr]
            )
            if not isinstance(data, dict) or not isinstance(
                effective, dict
            ) or not isinstance(requested, dict):
                raise FreshReplayGateError(
                    "G238 basic stage replay projection must use objects"
                )
            for field in (
                "consumed_artifact_sha256",
                "semantic_context_sha256",
                "semantic_artifact_sha256s",
                "generation_boundary_sha256",
                "premise_selection_sha256",
                "compiler_reference_exposure_cid",
            ):
                data.pop(field, None)
                effective.pop(field, None)
            requested.pop("compiler_reference_exposure_cid", None)
            source = tuple(
                _stable_provenance_source_replay_projection(
                    stage.provenance.source  # type: ignore[union-attr]
                )
            )
            if (
                len(source) == 3
                and source[:2]
                == (
                    "benchmarks.logic_pipeline.adapters",
                    "causal_runtime_v2",
                )
            ):
                _cid(source[2], "causal runtime provenance receipt CID")
                source = source[:2]
            stable = {
                "data": data,
                "requested_identity": requested,
                "effective_identity": effective,
                "adapter_id": stage.provenance.adapter_id,  # type: ignore[union-attr]
                "source": list(source),
                "environment_sha256": (
                    stage.provenance.environment_sha256  # type: ignore[union-attr]
                ),
            }
        elif stage.stage is StageName.SYMAI:  # type: ignore[union-attr]
            semantic_payload = _plain(symai_semantic_payload(stage))
            requested_identity = _plain(
                stage.provenance.requested_identity  # type: ignore[union-attr]
            )
            if not isinstance(semantic_payload, dict) or not isinstance(
                requested_identity, dict
            ):
                raise FreshReplayGateError(
                    "G238 SyMAI replay projection must use objects"
                )
            context = semantic_payload.get("semantic_context")
            if isinstance(context, dict):
                semantic_payload["semantic_context"] = {
                    key: context[key]
                    for key in ("schema", "source_cid")
                    if key in context
                }
            requested_identity.pop("semantic_context_cid", None)
            stable = {
                "data": {
                    "semantic_payload": semantic_payload,
                },
                "requested_identity": requested_identity,
                "effective_identity": symai_backend_identity(stage),
                "adapter_id": stage.provenance.adapter_id,  # type: ignore[union-attr]
                "source": list(
                    _stable_provenance_source_replay_projection(
                        stage.provenance.source  # type: ignore[union-attr]
                    )
                ),
                "environment_sha256": (
                    stage.provenance.environment_sha256  # type: ignore[union-attr]
                ),
            }
        else:
            stable = _stable_stage_replay_projection(
                stage  # type: ignore[arg-type]
            )
    except (TypeError, ValueError) as exc:
        raise FreshReplayGateError(
            "G238 stage failed deterministic replay projection"
        ) from exc
    return {
        "stage": stage.stage.value,  # type: ignore[union-attr]
        "status": stage.status.value,  # type: ignore[union-attr]
        "adapter_version": stage.adapter_version,  # type: ignore[union-attr]
        "failure_code": (
            None
            if stage.failure_code is None  # type: ignore[union-attr]
            else stage.failure_code.value  # type: ignore[union-attr]
        ),
        "kernel_accepted": stage.kernel_accepted,  # type: ignore[union-attr]
        "stable_stage": _plain(stable),
    }


def _semantic_projection(
    evidence: CausalRuntimeEvidenceV2,
) -> dict[str, object]:
    """Project every deterministic non-kernel stage observation."""

    return {
        "schema": G238_SEMANTIC_IDENTITY_SCHEMA_V2,
        "runtime_coordinate_cid": runtime_replay_coordinate_cid_v2(
            evidence
        ),
        "stages": [
            _stage_projection(stage)
            for stage in evidence.case_result.stages
            if stage.stage is not StageName.KERNEL
        ],
        "terminal_kernel_excluded": True,
        "volatile_telemetry_excluded": True,
        "holdout_included": False,
    }


def _kernel_projection(
    evidence: CausalRuntimeEvidenceV2,
) -> dict[str, object]:
    """Project the exact terminal native-kernel execution semantics."""

    kernel = next(
        (
            stage
            for stage in evidence.case_result.stages
            if stage.stage is StageName.KERNEL
        ),
        None,
    )
    try:
        native = (
            None
            if kernel is None
            else _stable_native_kernel_replay_projection(kernel)
        )
    except (TypeError, ValueError) as exc:
        raise FreshReplayGateError(
            "G238 terminal kernel failed replay projection"
        ) from exc
    kernel_stage = None
    if kernel is not None:
        requested_identity = _plain(
            kernel.provenance.requested_identity
        )
        if not isinstance(requested_identity, dict):  # pragma: no cover
            raise FreshReplayGateError(
                "G238 kernel requested identity must be an object"
            )
        # The complete compiler exposure is independently validated and its
        # stable candidate/source identities remain in this projection.  Its
        # receipt CID changes solely because the fresh compiler StageRecord
        # carries the new run identity.
        requested_identity.pop(
            "compiler_reference_exposure_cid",
            None,
        )
        kernel_stage = {
            "stage": kernel.stage.value,
            "status": kernel.status.value,
            "adapter_version": kernel.adapter_version,
            "failure_code": (
                None
                if kernel.failure_code is None
                else kernel.failure_code.value
            ),
            "kernel_accepted": kernel.kernel_accepted,
            "requested_identity": requested_identity,
            "effective_adapter_id": kernel.provenance.adapter_id,
            "environment_sha256": (
                kernel.provenance.environment_sha256
            ),
            "stable_native_execution": _plain(native),
            "non_native_data": (
                _plain(kernel.data) if native is None else None
            ),
        }
    return {
        "schema": G238_KERNEL_IDENTITY_SCHEMA_V2,
        "runtime_coordinate_cid": runtime_replay_coordinate_cid_v2(
            evidence
        ),
        "kernel_present": kernel is not None,
        "kernel_stage": kernel_stage,
        "native_kernel_execution": _plain(native),
        "volatile_telemetry_excluded": True,
        "holdout_included": False,
    }


def _status_projection(
    evidence: CausalRuntimeEvidenceV2,
) -> dict[str, object]:
    """Project exact outcome and ordered stage-status semantics."""

    result = evidence.case_result
    return {
        "schema": G238_STATUS_IDENTITY_SCHEMA_V2,
        "runtime_coordinate_cid": runtime_replay_coordinate_cid_v2(
            evidence
        ),
        "outcome_status": result.status.value,
        "failure_code": (
            None
            if result.failure_code is None
            else result.failure_code.value
        ),
        "verification_authority": result.verification_authority.value,
        "kernel_accepted": result.kernel_accepted,
        "stage_statuses": [
            {
                "stage": stage.stage.value,
                "status": stage.status.value,
                "failure_code": (
                    None
                    if stage.failure_code is None
                    else stage.failure_code.value
                ),
                "kernel_accepted": stage.kernel_accepted,
            }
            for stage in result.stages
        ],
        "holdout_included": False,
    }


def _terminal_status(
    evidence: CausalRuntimeEvidenceV2,
) -> tuple[str, str | None]:
    result = evidence.case_result
    if result.status is OutcomeStatus.VERIFIED:
        return "success", None
    failure = (
        result.failure_code.value
        if result.failure_code is not None
        else result.status.value
    )
    return "failure", _safe_id(failure, "failure_kind")


@dataclass(frozen=True, slots=True)
class G238SemanticObservationV2:
    """A complete-runtime-derived, run-independent semantic observation."""

    schema: str
    runtime_evidence_cid: str
    runtime_coordinate_cid: str
    semantic_projection: Mapping[str, object]
    semantic_identity_cid: str
    holdout_accessed: bool
    observation_cid: str

    def __post_init__(self) -> None:
        if self.schema != G238_SEMANTIC_OBSERVATION_SCHEMA_V2:
            raise FreshReplayGateError(
                "unsupported G238 semantic-observation schema"
            )
        for field in (
            "runtime_evidence_cid",
            "runtime_coordinate_cid",
            "semantic_identity_cid",
        ):
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        projection = _mapping(
            self.semantic_projection,
            "G238 semantic projection",
        )
        frozen = _freeze(projection)
        if not isinstance(frozen, Mapping):  # pragma: no cover
            raise FreshReplayGateError(
                "G238 semantic projection must remain an object"
            )
        object.__setattr__(self, "semantic_projection", frozen)
        if (
            self.semantic_identity_cid
            != cid_for_dag_json(_plain(frozen))
        ):
            raise FreshReplayGateError(
                "G238 semantic identity CID changed"
            )
        if self.holdout_accessed is not False:
            raise FreshReplayGateError(
                "G238 semantic observation crossed the holdout boundary"
            )
        if self.observation_cid != cid_for_dag_json(
            self.identity_payload()
        ):
            raise FreshReplayGateError(
                "G238 semantic-observation CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "runtime_evidence_cid": self.runtime_evidence_cid,
            "runtime_coordinate_cid": self.runtime_coordinate_cid,
            "semantic_projection": _plain(self.semantic_projection),
            "semantic_identity_cid": self.semantic_identity_cid,
            "holdout_accessed": self.holdout_accessed,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "observation_cid": self.observation_cid,
        }

    @classmethod
    def create(
        cls,
        evidence: CausalRuntimeEvidenceV2 | Mapping[str, object],
    ) -> Self:
        replayed = _runtime(evidence, "semantic runtime evidence")
        projection = _semantic_projection(replayed)
        payload: dict[str, object] = {
            "schema": G238_SEMANTIC_OBSERVATION_SCHEMA_V2,
            "runtime_evidence_cid": replayed.receipt_cid,
            "runtime_coordinate_cid": (
                runtime_replay_coordinate_cid_v2(replayed)
            ),
            "semantic_projection": projection,
            "semantic_identity_cid": cid_for_dag_json(projection),
            "holdout_accessed": False,
        }
        return cls(
            **payload,  # type: ignore[arg-type]
            observation_cid=cid_for_dag_json(payload),
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G238 semantic observation")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G238 semantic observation",
        )
        return cls(**data)  # type: ignore[arg-type]


def validate_g238_semantic_observation_v2(
    value: G238SemanticObservationV2 | Mapping[str, object],
    evidence: CausalRuntimeEvidenceV2 | Mapping[str, object],
) -> G238SemanticObservationV2:
    """Source-recompute a semantic observation from its complete runtime."""

    observation = (
        G238SemanticObservationV2.from_dict(value.to_dict())
        if isinstance(value, G238SemanticObservationV2)
        else G238SemanticObservationV2.from_dict(value)
    )
    expected = G238SemanticObservationV2.create(evidence)
    if observation.to_dict() != expected.to_dict():
        raise FreshReplayGateError(
            "G238 semantic observation did not runtime-recompute"
        )
    return observation


@dataclass(frozen=True, slots=True)
class G238ReplaySourceRecordV2:
    """One complete, independently metered result eligible for replay."""

    schema: str
    runtime_evidence: CausalRuntimeEvidenceV2
    semantic_observation: G238SemanticObservationV2
    resource_receipt: IndependentResourceReceiptV2
    runtime_evidence_cid: str
    case_cid: str
    split: str
    cache_mode: str
    variant_id: str
    terminal_status: str
    failure_kind: str | None
    semantic_identity_cid: str
    kernel_identity_cid: str
    status_identity_cid: str
    resource_replay_identity_cid: str
    record_cid: str

    def __post_init__(self) -> None:
        if self.schema != G238_REPLAY_SOURCE_RECORD_SCHEMA_V2:
            raise FreshReplayGateError(
                "unsupported G238 replay source-record schema"
            )
        runtime = _runtime(
            self.runtime_evidence,
            "G238 source runtime evidence",
        )
        object.__setattr__(self, "runtime_evidence", runtime)
        semantic = validate_g238_semantic_observation_v2(
            self.semantic_observation,
            runtime,
        )
        object.__setattr__(self, "semantic_observation", semantic)
        try:
            resource = validate_independent_resource_receipt_v2(
                self.resource_receipt,
                runtime,
            )
        except (TypeError, ValueError) as exc:
            raise FreshReplayGateError(
                "G238 source resource receipt failed runtime binding"
            ) from exc
        object.__setattr__(self, "resource_receipt", resource)
        for field in (
            "runtime_evidence_cid",
            "case_cid",
            "semantic_identity_cid",
            "kernel_identity_cid",
            "status_identity_cid",
            "resource_replay_identity_cid",
        ):
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        expected_coordinate_cid = runtime_replay_coordinate_cid_v2(runtime)
        expected_kernel_cid = cid_for_dag_json(
            _kernel_projection(runtime)
        )
        expected_status_cid = cid_for_dag_json(
            _status_projection(runtime)
        )
        if (
            self.runtime_evidence_cid != runtime.receipt_cid
            or self.case_cid != expected_coordinate_cid
            or semantic.runtime_coordinate_cid
            != expected_coordinate_cid
            or self.semantic_identity_cid
            != semantic.semantic_identity_cid
            or self.kernel_identity_cid != expected_kernel_cid
            or self.status_identity_cid != expected_status_cid
            or self.resource_replay_identity_cid
            != resource.replay_identity_cid
        ):
            raise FreshReplayGateError(
                "G238 source derived identity changed"
            )
        result = runtime.case_result
        if self.split not in _SPLITS:
            raise FreshReplayGateError(
                "G238 source split must be pilot or development"
            )
        if self.cache_mode not in _CACHE_MODES:
            raise FreshReplayGateError(
                "G238 source cache mode must be cold or warm"
            )
        if not isinstance(self.variant_id, str) or not _VARIANT.fullmatch(
            self.variant_id
        ):
            raise FreshReplayGateError(
                "G238 source variant must be one of A0 through A12"
            )
        if (
            self.split != result.split.value
            or self.cache_mode != result.cache_mode.value
            or self.variant_id != result.variant_id
        ):
            raise FreshReplayGateError(
                "G238 source coordinate differs from its runtime"
            )
        if self.terminal_status not in _SOURCE_STATUSES:
            raise FreshReplayGateError(
                "G238 source status must be success or failure"
            )
        if self.terminal_status == "success":
            if self.failure_kind is not None:
                raise FreshReplayGateError(
                    "successful G238 source cannot name a failure"
                )
        elif (
            not isinstance(self.failure_kind, str)
            or not _SAFE_ID.fullmatch(self.failure_kind)
        ):
            raise FreshReplayGateError(
                "failed G238 source requires a stable failure kind"
            )
        if (
            (self.terminal_status, self.failure_kind)
            != _terminal_status(runtime)
        ):
            raise FreshReplayGateError(
                "G238 source terminal status differs from its runtime"
            )
        if self.record_cid != cid_for_dag_json(self.identity_payload()):
            raise FreshReplayGateError(
                "G238 replay source-record CID changed"
            )

    @property
    def failure_stratum(self) -> tuple[str, str, str]:
        return (self.split, self.cache_mode, self.variant_id)

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "runtime_evidence": self.runtime_evidence.to_dict(),
            "semantic_observation": self.semantic_observation.to_dict(),
            "resource_receipt": self.resource_receipt.to_dict(),
            "runtime_evidence_cid": self.runtime_evidence_cid,
            "case_cid": self.case_cid,
            "split": self.split,
            "cache_mode": self.cache_mode,
            "variant_id": self.variant_id,
            "terminal_status": self.terminal_status,
            "failure_kind": self.failure_kind,
            "semantic_identity_cid": self.semantic_identity_cid,
            "kernel_identity_cid": self.kernel_identity_cid,
            "status_identity_cid": self.status_identity_cid,
            "resource_replay_identity_cid": (
                self.resource_replay_identity_cid
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "record_cid": self.record_cid}

    @classmethod
    def create(
        cls,
        *,
        runtime_evidence: CausalRuntimeEvidenceV2,
        semantic_observation: G238SemanticObservationV2,
        resource_receipt: IndependentResourceReceiptV2,
    ) -> Self:
        runtime = _runtime(
            runtime_evidence,
            "G238 source runtime evidence",
        )
        semantic = validate_g238_semantic_observation_v2(
            semantic_observation,
            runtime,
        )
        try:
            resource = validate_independent_resource_receipt_v2(
                resource_receipt,
                runtime,
            )
        except (TypeError, ValueError) as exc:
            raise FreshReplayGateError(
                "G238 source resource receipt failed runtime binding"
            ) from exc
        terminal_status, failure_kind = _terminal_status(runtime)
        result = runtime.case_result
        payload: dict[str, object] = {
            "schema": G238_REPLAY_SOURCE_RECORD_SCHEMA_V2,
            "runtime_evidence": runtime.to_dict(),
            "semantic_observation": semantic.to_dict(),
            "resource_receipt": resource.to_dict(),
            "runtime_evidence_cid": runtime.receipt_cid,
            "case_cid": runtime_replay_coordinate_cid_v2(runtime),
            "split": result.split.value,
            "cache_mode": result.cache_mode.value,
            "variant_id": result.variant_id,
            "terminal_status": terminal_status,
            "failure_kind": failure_kind,
            "semantic_identity_cid": semantic.semantic_identity_cid,
            "kernel_identity_cid": cid_for_dag_json(
                _kernel_projection(runtime)
            ),
            "status_identity_cid": cid_for_dag_json(
                _status_projection(runtime)
            ),
            "resource_replay_identity_cid": (
                resource.replay_identity_cid
            ),
        }
        typed = {
            **payload,
            "runtime_evidence": runtime,
            "semantic_observation": semantic,
            "resource_receipt": resource,
        }
        return cls(
            **typed,  # type: ignore[arg-type]
            record_cid=cid_for_dag_json(payload),
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G238 replay source record")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G238 replay source record",
        )
        return cls(
            **{
                **data,
                "runtime_evidence": _runtime(
                    _mapping(
                        data["runtime_evidence"],
                        "G238 source runtime evidence",
                    ),
                    "G238 source runtime evidence",
                ),
                "semantic_observation": (
                    G238SemanticObservationV2.from_dict(
                        data["semantic_observation"]
                    )
                ),
                "resource_receipt": (
                    IndependentResourceReceiptV2.from_dict(
                        data["resource_receipt"]
                    )
                ),
            }
        )  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class G238ReplaySourceIndexV2:
    """Frozen source population from which replay targets are derived."""

    schema: str
    source_run_id: str
    source_commit: str
    source_commit_cid: str
    recursive_gitlinks_cid: str
    environment_cid: str
    route_manifest_cid: str
    case_index_cid: str
    run_plan_cid: str
    source_worktree_cid: str
    source_executor_authority_cid: str
    failure_sample_per_stratum: int
    replay_policy_cid: str
    records: tuple[G238ReplaySourceRecordV2, ...]
    index_cid: str

    def __post_init__(self) -> None:
        if self.schema != G238_REPLAY_SOURCE_INDEX_SCHEMA_V2:
            raise FreshReplayGateError(
                "unsupported G238 replay source-index schema"
            )
        _safe_id(self.source_run_id, "source_run_id")
        object.__setattr__(self, "source_commit", _commit(self.source_commit))
        for field in (
            "source_commit_cid",
            "recursive_gitlinks_cid",
            "environment_cid",
            "route_manifest_cid",
            "case_index_cid",
            "run_plan_cid",
            "source_worktree_cid",
            "source_executor_authority_cid",
            "replay_policy_cid",
        ):
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        if self.source_commit_cid != g238_git_commit_cid(
            self.source_commit
        ):
            raise FreshReplayGateError(
                "G238 source commit CID does not address the Git commit"
            )
        if self.replay_policy_cid != G238_REPLAY_POLICY_V2_CID:
            raise FreshReplayGateError("G238 replay policy changed")
        if (
            type(self.failure_sample_per_stratum) is not int
            or self.failure_sample_per_stratum
            != G238_FAILURE_SAMPLE_PER_STRATUM
        ):
            raise FreshReplayGateError(
                "G238 failure sampling count changed"
            )
        records = tuple(
            value
            if isinstance(value, G238ReplaySourceRecordV2)
            else G238ReplaySourceRecordV2.from_dict(value)
            for value in self.records
        )
        record_cids = tuple(record.record_cid for record in records)
        if (
            not records
            or record_cids != tuple(sorted(record_cids))
            or len(record_cids) != len(set(record_cids))
            or len(
                {record.runtime_evidence_cid for record in records}
            )
            != len(records)
        ):
            raise FreshReplayGateError(
                "G238 source records must be nonempty, sorted, and unique"
            )
        object.__setattr__(self, "records", records)
        if self.index_cid != cid_for_dag_json(self.identity_payload()):
            raise FreshReplayGateError(
                "G238 replay source-index CID changed"
            )

    @property
    def required_records(self) -> tuple[G238ReplaySourceRecordV2, ...]:
        successes = [
            record
            for record in self.records
            if record.terminal_status == "success"
        ]
        failures: dict[
            tuple[str, str, str],
            list[G238ReplaySourceRecordV2],
        ] = {}
        for record in self.records:
            if record.terminal_status == "failure":
                failures.setdefault(record.failure_stratum, []).append(record)
        sampled_failures = [
            sorted(records, key=lambda item: item.record_cid)[0]
            for _, records in sorted(failures.items())
        ]
        return tuple(
            sorted(
                (*successes, *sampled_failures),
                key=lambda item: item.record_cid,
            )
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_run_id": self.source_run_id,
            "source_commit": self.source_commit,
            "source_commit_cid": self.source_commit_cid,
            "recursive_gitlinks_cid": self.recursive_gitlinks_cid,
            "environment_cid": self.environment_cid,
            "route_manifest_cid": self.route_manifest_cid,
            "case_index_cid": self.case_index_cid,
            "run_plan_cid": self.run_plan_cid,
            "source_worktree_cid": self.source_worktree_cid,
            "source_executor_authority_cid": (
                self.source_executor_authority_cid
            ),
            "failure_sample_per_stratum": (
                self.failure_sample_per_stratum
            ),
            "replay_policy_cid": self.replay_policy_cid,
            "records": [record.to_dict() for record in self.records],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "index_cid": self.index_cid}

    @classmethod
    def create(
        cls,
        *,
        source_run_id: str,
        source_commit: str,
        recursive_gitlinks_cid: str,
        environment_cid: str,
        route_manifest_cid: str,
        case_index_cid: str,
        run_plan_cid: str,
        source_worktree_cid: str,
        source_executor_authority_cid: str,
        records: Sequence[G238ReplaySourceRecordV2],
    ) -> Self:
        commit = _commit(source_commit)
        ordered = tuple(sorted(records, key=lambda item: item.record_cid))
        payload: dict[str, object] = {
            "schema": G238_REPLAY_SOURCE_INDEX_SCHEMA_V2,
            "source_run_id": source_run_id,
            "source_commit": commit,
            "source_commit_cid": g238_git_commit_cid(commit),
            "recursive_gitlinks_cid": recursive_gitlinks_cid,
            "environment_cid": environment_cid,
            "route_manifest_cid": route_manifest_cid,
            "case_index_cid": case_index_cid,
            "run_plan_cid": run_plan_cid,
            "source_worktree_cid": source_worktree_cid,
            "source_executor_authority_cid": (
                source_executor_authority_cid
            ),
            "failure_sample_per_stratum": (
                G238_FAILURE_SAMPLE_PER_STRATUM
            ),
            "replay_policy_cid": G238_REPLAY_POLICY_V2_CID,
            "records": ordered,
        }
        cid_payload = {
            **payload,
            "records": [record.to_dict() for record in ordered],
        }
        return cls(
            **payload,  # type: ignore[arg-type]
            index_cid=cid_for_dag_json(cid_payload),
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G238 replay source index")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G238 replay source index",
        )
        records = data["records"]
        if not isinstance(records, list):
            raise FreshReplayGateError(
                "G238 replay source-index arrays changed"
            )
        return cls(
            **{
                **data,
                "records": tuple(
                    G238ReplaySourceRecordV2.from_dict(record)
                    for record in records
                ),
            }
        )  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class G238DetachedReplayReceiptV2:
    """One complete, CID-addressed execution replay attempt."""

    schema: str
    target_record_cid: str
    source_index_cid: str
    source_runtime_evidence_cid: str
    source_run_id: str
    replay_run_id: str
    source_commit: str
    source_commit_cid: str
    recursive_gitlinks_cid: str
    environment_cid: str
    route_manifest_cid: str
    case_index_cid: str
    run_plan_cid: str
    source_worktree_cid: str
    replay_worktree_cid: str
    source_namespace_receipt_cid: str
    source_process_namespace_cid: str
    replay_process_namespace_cid: str
    source_state_namespace_cid: str
    replay_state_namespace_cid: str
    source_cache_namespace_cid: str
    replay_cache_namespace_cid: str
    replay_executor_authority_cid: str
    replay_validator_authority_cid: str
    replay_runtime_evidence: CausalRuntimeEvidenceV2 | None
    replay_semantic_observation: G238SemanticObservationV2 | None
    replay_resource_receipt: IndependentResourceReceiptV2 | None
    comparison: Mapping[str, object] | None
    detached: bool
    attached: bool
    auto_merge: bool
    holdout_accessed: bool
    receipt_cid: str

    def __post_init__(self) -> None:
        if self.schema != G238_DETACHED_REPLAY_RECEIPT_SCHEMA_V2:
            raise FreshReplayGateError(
                "unsupported G238 detached replay receipt schema"
            )
        required_cids = (
            "target_record_cid",
            "source_index_cid",
            "source_runtime_evidence_cid",
            "source_commit_cid",
            "recursive_gitlinks_cid",
            "environment_cid",
            "route_manifest_cid",
            "case_index_cid",
            "run_plan_cid",
            "source_worktree_cid",
            "replay_worktree_cid",
            "source_namespace_receipt_cid",
            "source_process_namespace_cid",
            "replay_process_namespace_cid",
            "source_state_namespace_cid",
            "replay_state_namespace_cid",
            "source_cache_namespace_cid",
            "replay_cache_namespace_cid",
            "replay_executor_authority_cid",
            "replay_validator_authority_cid",
        )
        for field in required_cids:
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        _safe_id(self.source_run_id, "source_run_id")
        _safe_id(self.replay_run_id, "replay_run_id")
        object.__setattr__(self, "source_commit", _commit(self.source_commit))
        if self.source_commit_cid != g238_git_commit_cid(
            self.source_commit
        ):
            raise FreshReplayGateError(
                "G238 receipt source commit CID changed"
            )
        for field in (
            "detached",
            "attached",
            "auto_merge",
            "holdout_accessed",
        ):
            if type(getattr(self, field)) is not bool:
                raise FreshReplayGateError(
                    f"{field} must be an observed boolean"
                )
        runtime = self.replay_runtime_evidence
        semantic = self.replay_semantic_observation
        resource = self.replay_resource_receipt
        comparison = self.comparison
        if runtime is not None:
            runtime = _runtime(
                runtime,
                "G238 replay runtime evidence",
            )
            object.__setattr__(
                self, "replay_runtime_evidence", runtime
            )
            if runtime.case_result.run_id != self.replay_run_id:
                raise FreshReplayGateError(
                    "G238 replay run ID differs from complete runtime"
                )
        if semantic is not None:
            if runtime is None:
                raise FreshReplayGateError(
                    "G238 semantic observation requires replay runtime"
                )
            semantic = validate_g238_semantic_observation_v2(
                semantic,
                runtime,
            )
            object.__setattr__(
                self, "replay_semantic_observation", semantic
            )
        if resource is not None:
            if runtime is None:
                raise FreshReplayGateError(
                    "G238 resource receipt requires replay runtime"
                )
            try:
                resource = validate_independent_resource_receipt_v2(
                    resource,
                    runtime,
                )
            except (TypeError, ValueError) as exc:
                raise FreshReplayGateError(
                    "G238 replay resource receipt failed runtime binding"
                ) from exc
            object.__setattr__(
                self, "replay_resource_receipt", resource
            )
        complete = all(
            item is not None for item in (runtime, semantic, resource)
        )
        if comparison is not None:
            if not complete:
                raise FreshReplayGateError(
                    "G238 comparison requires all complete replay evidence"
                )
            comparison_data = _mapping(
                comparison,
                "G238 replay comparison",
            )
            supplied_cid = _cid(
                comparison_data.get("comparison_receipt_cid"),
                "comparison_receipt_cid",
            )
            body = {
                key: _plain(member)
                for key, member in comparison_data.items()
                if key != "comparison_receipt_cid"
            }
            if supplied_cid != cid_for_dag_json(body):
                raise FreshReplayGateError(
                    "G238 replay comparison CID changed"
                )
            frozen = _freeze(comparison_data)
            if not isinstance(frozen, Mapping):  # pragma: no cover
                raise FreshReplayGateError(
                    "G238 replay comparison must remain an object"
                )
            object.__setattr__(self, "comparison", frozen)
        elif complete:
            raise FreshReplayGateError(
                "complete G238 replay evidence requires a comparison"
            )
        if self.receipt_cid != cid_for_dag_json(self.identity_payload()):
            raise FreshReplayGateError(
                "G238 detached replay receipt CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name
            not in {
                "receipt_cid",
                "replay_runtime_evidence",
                "replay_semantic_observation",
                "replay_resource_receipt",
                "comparison",
            }
        }
        payload.update(
            {
                "replay_runtime_evidence": (
                    None
                    if self.replay_runtime_evidence is None
                    else self.replay_runtime_evidence.to_dict()
                ),
                "replay_semantic_observation": (
                    None
                    if self.replay_semantic_observation is None
                    else self.replay_semantic_observation.to_dict()
                ),
                "replay_resource_receipt": (
                    None
                    if self.replay_resource_receipt is None
                    else self.replay_resource_receipt.to_dict()
                ),
                "comparison": (
                    None
                    if self.comparison is None
                    else _plain(self.comparison)
                ),
            }
        )
        return payload

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_cid": self.receipt_cid}

    @classmethod
    def create(
        cls,
        *,
        source_index: G238ReplaySourceIndexV2,
        source_record: G238ReplaySourceRecordV2,
        replay_run_id: str,
        replay_worktree_cid: str,
        source_namespace_receipt_cid: str,
        source_process_namespace_cid: str,
        source_state_namespace_cid: str,
        source_cache_namespace_cid: str,
        replay_process_namespace_cid: str,
        replay_state_namespace_cid: str,
        replay_cache_namespace_cid: str,
        replay_executor_authority_cid: str,
        replay_validator_authority_cid: str,
        replay_runtime_evidence: CausalRuntimeEvidenceV2 | None,
        replay_semantic_observation: G238SemanticObservationV2 | None,
        replay_resource_receipt: IndependentResourceReceiptV2 | None,
        detached: bool = True,
        attached: bool = False,
        auto_merge: bool = False,
        holdout_accessed: bool = False,
    ) -> Self:
        """Build a receipt whose source observations need operational replay.

        The per-target source namespace values are intentionally absent from
        the population index.  The positive gate authenticates them against
        the private G240 source receipt before accepting this receipt.
        """

        index = G238ReplaySourceIndexV2.from_dict(
            source_index.to_dict()
        )
        record = G238ReplaySourceRecordV2.from_dict(
            source_record.to_dict()
        )
        if not any(
            item.record_cid == record.record_cid
            for item in index.records
        ):
            raise FreshReplayGateError(
                "G238 replay target is absent from its source index"
            )
        runtime = (
            None
            if replay_runtime_evidence is None
            else _runtime(
                replay_runtime_evidence,
                "G238 replay runtime evidence",
            )
        )
        semantic = (
            None
            if replay_semantic_observation is None
            else (
                validate_g238_semantic_observation_v2(
                    replay_semantic_observation,
                    runtime,
                )
                if runtime is not None
                else replay_semantic_observation
            )
        )
        resource = (
            None
            if replay_resource_receipt is None
            else (
                validate_independent_resource_receipt_v2(
                    replay_resource_receipt,
                    runtime,
                )
                if runtime is not None
                else replay_resource_receipt
            )
        )
        comparison = (
            build_g238_replay_comparison_v2(
                record,
                runtime,
                semantic,
                resource,
            )
            if (
                runtime is not None
                and semantic is not None
                and resource is not None
            )
            else None
        )
        payload: dict[str, object] = {
            "schema": G238_DETACHED_REPLAY_RECEIPT_SCHEMA_V2,
            "target_record_cid": record.record_cid,
            "source_index_cid": index.index_cid,
            "source_runtime_evidence_cid": (
                record.runtime_evidence_cid
            ),
            "source_run_id": index.source_run_id,
            "replay_run_id": replay_run_id,
            "source_commit": index.source_commit,
            "source_commit_cid": index.source_commit_cid,
            "recursive_gitlinks_cid": index.recursive_gitlinks_cid,
            "environment_cid": index.environment_cid,
            "route_manifest_cid": index.route_manifest_cid,
            "case_index_cid": index.case_index_cid,
            "run_plan_cid": index.run_plan_cid,
            "source_worktree_cid": index.source_worktree_cid,
            "replay_worktree_cid": replay_worktree_cid,
            "source_namespace_receipt_cid": (
                source_namespace_receipt_cid
            ),
            "source_process_namespace_cid": source_process_namespace_cid,
            "replay_process_namespace_cid": (
                replay_process_namespace_cid
            ),
            "source_state_namespace_cid": source_state_namespace_cid,
            "replay_state_namespace_cid": replay_state_namespace_cid,
            "source_cache_namespace_cid": source_cache_namespace_cid,
            "replay_cache_namespace_cid": replay_cache_namespace_cid,
            "replay_executor_authority_cid": (
                replay_executor_authority_cid
            ),
            "replay_validator_authority_cid": (
                replay_validator_authority_cid
            ),
            "replay_runtime_evidence": (
                None if runtime is None else runtime.to_dict()
            ),
            "replay_semantic_observation": (
                None if semantic is None else semantic.to_dict()
            ),
            "replay_resource_receipt": (
                None if resource is None else resource.to_dict()
            ),
            "comparison": comparison,
            "detached": detached,
            "attached": attached,
            "auto_merge": auto_merge,
            "holdout_accessed": holdout_accessed,
        }
        typed = {
            **payload,
            "replay_runtime_evidence": runtime,
            "replay_semantic_observation": semantic,
            "replay_resource_receipt": resource,
        }
        return cls(
            **typed,  # type: ignore[arg-type]
            receipt_cid=cid_for_dag_json(payload),
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G238 detached replay receipt")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G238 detached replay receipt",
        )
        runtime_data = data["replay_runtime_evidence"]
        semantic_data = data["replay_semantic_observation"]
        resource_data = data["replay_resource_receipt"]
        return cls(
            **{
                **data,
                "replay_runtime_evidence": (
                    None
                    if runtime_data is None
                    else _runtime(
                        _mapping(
                            runtime_data,
                            "G238 replay runtime evidence",
                        ),
                        "G238 replay runtime evidence",
                    )
                ),
                "replay_semantic_observation": (
                    None
                    if semantic_data is None
                    else G238SemanticObservationV2.from_dict(
                        semantic_data
                    )
                ),
                "replay_resource_receipt": (
                    None
                    if resource_data is None
                    else IndependentResourceReceiptV2.from_dict(
                        resource_data
                    )
                ),
            }
        )  # type: ignore[arg-type]


def build_g238_replay_comparison_v2(
    source_record: G238ReplaySourceRecordV2 | Mapping[str, object],
    replay_runtime_evidence: CausalRuntimeEvidenceV2 | Mapping[str, object],
    replay_semantic_observation: (
        G238SemanticObservationV2 | Mapping[str, object]
    ),
    replay_resource_receipt: (
        IndependentResourceReceiptV2 | Mapping[str, object]
    ),
) -> dict[str, object]:
    """Recompute one semantic/kernel/status/resource replay comparison.

    Complete source and replay records are replayed before projection.  No
    caller-provided identity CID is accepted as proof.  Deterministic
    semantics, native-kernel execution, and status compare exactly; resource
    telemetry is judged only by the separately frozen G237 paired policy.
    """

    source = (
        G238ReplaySourceRecordV2.from_dict(source_record.to_dict())
        if isinstance(source_record, G238ReplaySourceRecordV2)
        else G238ReplaySourceRecordV2.from_dict(source_record)
    )
    replay_runtime = _runtime(
        replay_runtime_evidence,
        "G238 replay runtime evidence",
    )
    replay_semantic = validate_g238_semantic_observation_v2(
        replay_semantic_observation,
        replay_runtime,
    )
    try:
        replay_resource = validate_independent_resource_receipt_v2(
            replay_resource_receipt,
            replay_runtime,
        )
        resource_comparison = compare_resource_replay_measurements_v2(
            source.resource_receipt,
            replay_resource,
        )
    except (TypeError, ValueError) as exc:
        raise FreshReplayGateError(
            "G238 resource comparison failed receipt replay"
        ) from exc

    source_runtime_coordinate_cid = (
        runtime_replay_coordinate_cid_v2(source.runtime_evidence)
    )
    replay_runtime_coordinate_cid = (
        runtime_replay_coordinate_cid_v2(replay_runtime)
    )
    replay_kernel_identity_cid = cid_for_dag_json(
        _kernel_projection(replay_runtime)
    )
    replay_status_identity_cid = cid_for_dag_json(
        _status_projection(replay_runtime)
    )
    runtime_coordinate_equal = (
        source_runtime_coordinate_cid
        == replay_runtime_coordinate_cid
    )
    semantic_equal = (
        source.semantic_identity_cid
        == replay_semantic.semantic_identity_cid
    )
    kernel_equal = (
        source.kernel_identity_cid
        == replay_kernel_identity_cid
    )
    status_equal = (
        source.status_identity_cid
        == replay_status_identity_cid
    )
    resource_identity_equal = (
        source.resource_replay_identity_cid
        == replay_resource.replay_identity_cid
    )
    failures: list[str] = []
    if not runtime_coordinate_equal:
        failures.append("runtime_coordinate_mismatch")
    if not semantic_equal:
        failures.append("semantic_identity_mismatch")
    if not kernel_equal:
        failures.append("kernel_identity_mismatch")
    if not status_equal:
        failures.append("status_identity_mismatch")
    if not resource_identity_equal:
        failures.append("resource_replay_identity_mismatch")
    resource_failure_codes = resource_comparison.get("failure_codes")
    if not isinstance(resource_failure_codes, list) or not all(
        isinstance(code, str) for code in resource_failure_codes
    ):
        raise FreshReplayGateError(
            "G238 resource comparison failure codes changed"
        )
    failures.extend(resource_failure_codes)
    failure_codes = sorted(set(failures))
    body: dict[str, object] = {
        "schema": G238_COMPARISON_SCHEMA_V2,
        "replay_policy_cid": G238_REPLAY_POLICY_V2_CID,
        "resource_comparison_policy_cid": (
            RESOURCE_REPLAY_COMPARISON_POLICY_V2_CID
        ),
        "source_record_cid": source.record_cid,
        "source_runtime_evidence_cid": source.runtime_evidence_cid,
        "replay_runtime_evidence_cid": replay_runtime.receipt_cid,
        "source_runtime_coordinate_cid": (
            source_runtime_coordinate_cid
        ),
        "replay_runtime_coordinate_cid": (
            replay_runtime_coordinate_cid
        ),
        "runtime_coordinate_equal": runtime_coordinate_equal,
        "source_semantic_observation_cid": (
            source.semantic_observation.observation_cid
        ),
        "replay_semantic_observation_cid": (
            replay_semantic.observation_cid
        ),
        "source_semantic_identity_cid": (
            source.semantic_identity_cid
        ),
        "replay_semantic_identity_cid": (
            replay_semantic.semantic_identity_cid
        ),
        "semantic_equal": semantic_equal,
        "source_kernel_identity_cid": source.kernel_identity_cid,
        "replay_kernel_identity_cid": replay_kernel_identity_cid,
        "kernel_equal": kernel_equal,
        "source_status_identity_cid": source.status_identity_cid,
        "replay_status_identity_cid": replay_status_identity_cid,
        "status_equal": status_equal,
        "source_resource_replay_identity_cid": (
            source.resource_replay_identity_cid
        ),
        "replay_resource_replay_identity_cid": (
            replay_resource.replay_identity_cid
        ),
        "resource_identity_equal": resource_identity_equal,
        "resource_comparison": resource_comparison,
        "resource_comparison_receipt_cid": resource_comparison[
            "comparison_receipt_cid"
        ],
        "complete": not failure_codes,
        "passed": not failure_codes,
        "failure_codes": failure_codes,
        "holdout_included": False,
    }
    return {
        **body,
        "comparison_receipt_cid": cid_for_dag_json(body),
    }


def validate_g238_replay_comparison_v2(
    value: object,
    source_record: G238ReplaySourceRecordV2 | Mapping[str, object],
    replay_runtime_evidence: CausalRuntimeEvidenceV2 | Mapping[str, object],
    replay_semantic_observation: (
        G238SemanticObservationV2 | Mapping[str, object]
    ),
    replay_resource_receipt: (
        IndependentResourceReceiptV2 | Mapping[str, object]
    ),
) -> str:
    """Source-recompute one complete G238 comparison receipt."""

    data = _mapping(value, "G238 replay comparison")
    rebuilt = build_g238_replay_comparison_v2(
        source_record,
        replay_runtime_evidence,
        replay_semantic_observation,
        replay_resource_receipt,
    )
    _exact(data, set(rebuilt), "G238 replay comparison")
    if _plain(data) != rebuilt:
        raise FreshReplayGateError(
            "G238 replay comparison did not source-recompute"
        )
    return _cid(
        data["comparison_receipt_cid"],
        "comparison_receipt_cid",
    )


def _flag(failures: set[str], condition: bool, code: str) -> None:
    if condition:
        failures.add(code)


def build_g238_detached_replay_gate_v2(
    source_index: G238ReplaySourceIndexV2 | Mapping[str, object],
    replay_receipts: Sequence[
        G238DetachedReplayReceiptV2 | Mapping[str, object]
    ],
    *,
    validator_authority_cid: str,
    operational_replay_sources: Mapping[
        str, G240PrivateReplayValidationSourcesV2
    ]
    | None = None,
) -> dict[str, object]:
    """Recompute the exact detached replay population and positive gate."""

    index = (
        source_index
        if isinstance(source_index, G238ReplaySourceIndexV2)
        else G238ReplaySourceIndexV2.from_dict(source_index)
    )
    validator_cid = _cid(
        validator_authority_cid, "validator_authority_cid"
    )
    receipts = tuple(
        receipt
        if isinstance(receipt, G238DetachedReplayReceiptV2)
        else G238DetachedReplayReceiptV2.from_dict(receipt)
        for receipt in replay_receipts
    )
    required = {
        record.record_cid: record for record in index.required_records
    }
    by_target: dict[str, list[G238DetachedReplayReceiptV2]] = {}
    for receipt in receipts:
        by_target.setdefault(receipt.target_record_cid, []).append(receipt)
    operational = (
        {}
        if operational_replay_sources is None
        else dict(operational_replay_sources)
    )
    if (
        any(not isinstance(key, str) for key in operational)
        or any(
            not isinstance(
                item, G240PrivateReplayValidationSourcesV2
            )
            for item in operational.values()
        )
    ):
        raise FreshReplayGateError(
            "G238 operational replay sources must be keyed private G240 "
            "validation bundles"
        )

    failures: set[str] = set()
    required_cids = set(required)
    presented_cids = set(by_target)
    _flag(
        failures,
        bool(required_cids - presented_cids),
        "missing_required_replay",
    )
    _flag(
        failures,
        bool(presented_cids - required_cids),
        "unexpected_replay_target",
    )
    _flag(
        failures,
        any(len(values) != 1 for values in by_target.values()),
        "duplicate_replay_target",
    )
    if not receipts:
        failures.add("receipt_only_replay_unavailable")
    _flag(
        failures,
        bool(required_cids - set(operational)),
        "missing_operational_replay_source",
    )
    _flag(
        failures,
        bool(set(operational) - required_cids),
        "unexpected_operational_replay_source",
    )

    for field in (
        "replay_worktree_cid",
        "replay_process_namespace_cid",
        "replay_state_namespace_cid",
        "replay_cache_namespace_cid",
    ):
        values = [getattr(receipt, field) for receipt in receipts]
        _flag(
            failures,
            len(values) != len(set(values)),
            f"shared_{field}",
        )
    replay_runs = [receipt.replay_run_id for receipt in receipts]
    _flag(
        failures,
        len(replay_runs) != len(set(replay_runs)),
        "shared_replay_run",
    )

    validated_receipts: list[str] = []
    validated_comparisons: list[str] = []
    validated_namespace_receipts: list[str] = []
    validated_orchestration_receipts: list[str] = []
    for target_cid in sorted(required):
        matches = by_target.get(target_cid, ())
        if len(matches) != 1:
            continue
        receipt = matches[0]
        record = required[target_cid]
        _flag(
            failures,
            (
                receipt.source_index_cid != index.index_cid
                or receipt.source_run_id != index.source_run_id
                or receipt.source_commit != index.source_commit
                or receipt.source_commit_cid != index.source_commit_cid
                or receipt.recursive_gitlinks_cid
                != index.recursive_gitlinks_cid
                or receipt.environment_cid != index.environment_cid
                or receipt.route_manifest_cid
                != index.route_manifest_cid
                or receipt.case_index_cid != index.case_index_cid
                or receipt.run_plan_cid != index.run_plan_cid
                or receipt.source_worktree_cid
                != index.source_worktree_cid
            ),
            "stale_source_binding",
        )
        _flag(
            failures,
            receipt.source_runtime_evidence_cid
            != record.runtime_evidence_cid,
            "source_record_mismatch",
        )
        _flag(
            failures,
            receipt.source_run_id == receipt.replay_run_id,
            "same_run_replay",
        )
        _flag(
            failures,
            receipt.source_worktree_cid == receipt.replay_worktree_cid,
            "same_worktree_replay",
        )
        _flag(
            failures,
            (
                receipt.source_process_namespace_cid
                == receipt.replay_process_namespace_cid
            ),
            "process_namespace_not_isolated",
        )
        _flag(
            failures,
            (
                receipt.source_state_namespace_cid
                == receipt.replay_state_namespace_cid
            ),
            "state_namespace_not_isolated",
        )
        _flag(
            failures,
            (
                receipt.source_cache_namespace_cid
                == receipt.replay_cache_namespace_cid
            ),
            "cache_namespace_not_isolated",
        )
        _flag(
            failures,
            not receipt.detached or receipt.attached,
            "replay_not_detached",
        )
        _flag(
            failures,
            receipt.auto_merge,
            "replay_auto_merge_enabled",
        )
        _flag(
            failures,
            receipt.holdout_accessed,
            "replay_accessed_holdout",
        )
        _flag(
            failures,
            (
                receipt.replay_validator_authority_cid
                != validator_cid
                or receipt.replay_validator_authority_cid
                == receipt.replay_executor_authority_cid
                or receipt.replay_validator_authority_cid
                == index.source_executor_authority_cid
            ),
            "replay_authority_not_independent",
        )
        replay_values = (
            receipt.replay_runtime_evidence,
            receipt.replay_semantic_observation,
            receipt.replay_resource_receipt,
            receipt.comparison,
        )
        partial = any(value is None for value in replay_values)
        _flag(
            failures,
            partial,
            "partial_replay_evidence",
        )
        if not partial:
            assert receipt.replay_runtime_evidence is not None
            assert receipt.replay_semantic_observation is not None
            assert receipt.replay_resource_receipt is not None
            assert receipt.comparison is not None
            rebuilt = build_g238_replay_comparison_v2(
                record,
                receipt.replay_runtime_evidence,
                receipt.replay_semantic_observation,
                receipt.replay_resource_receipt,
            )
            comparison_matches = _plain(receipt.comparison) == rebuilt
            _flag(
                failures,
                not comparison_matches,
                "replay_comparison_not_source_recomputed",
            )
            operational_matches = False
            private_sources = operational.get(target_cid)
            if private_sources is not None:
                try:
                    (
                        policy,
                        source_namespace,
                        replay_namespace,
                        orchestration,
                    ) = validate_g240_private_replay_sources_v2(
                        private_sources,
                        source_runtime_evidence=(
                            record.runtime_evidence
                        ),
                        replay_runtime_evidence=(
                            receipt.replay_runtime_evidence
                        ),
                    )
                    replay_resource = receipt.replay_resource_receipt
                    assert replay_resource is not None
                    cache_set_cid = g240_cache_namespace_set_cid(
                        replay_namespace.replay_cache_namespace_cids
                    )
                    source_cache_set_cid = g240_cache_namespace_set_cid(
                        source_namespace.cache_namespace_cids
                    )
                    source_worktree_cid = (
                        g240_worktree_safety_projection_cid(
                            private_sources.source_worktree_safety_receipt
                        )
                    )
                    disjoint_authorities = {
                        policy.namespace_authority_cid,
                        index.source_executor_authority_cid,
                        source_namespace.observer_identity_cid,
                        record.resource_receipt.meter_identity_cid,
                        record.resource_receipt.validator_identity_cid,
                        replay_namespace.replay_executor_identity_cid,
                        replay_namespace.replay_observer_identity_cid,
                        orchestration.orchestration_observer_identity_cid,
                        replay_resource.meter_identity_cid,
                    }
                    operational_matches = (
                        policy.run_id == index.source_run_id
                        and policy.source_commit_cid
                        == index.source_commit_cid
                        and policy.recursive_gitlinks_cid
                        == index.recursive_gitlinks_cid
                        and policy.environment_cid
                        == index.environment_cid
                        and source_namespace.runtime_evidence_cid
                        == record.runtime_evidence_cid
                        and source_namespace.receipt_cid
                        == receipt.source_namespace_receipt_cid
                        and source_namespace.process_namespace_cid
                        == receipt.source_process_namespace_cid
                        and source_namespace.state_namespace_cid
                        == receipt.source_state_namespace_cid
                        and source_cache_set_cid
                        == receipt.source_cache_namespace_cid
                        and source_namespace.executor_identity_cid
                        == index.source_executor_authority_cid
                        and record.resource_receipt.producer_identity_cid
                        == index.source_executor_authority_cid
                        and source_worktree_cid
                        == index.source_worktree_cid
                        and replay_namespace.replay_run_id
                        == receipt.replay_run_id
                        and replay_namespace.replay_worktree_cid
                        == receipt.replay_worktree_cid
                        and replay_namespace.replay_process_namespace_cid
                        == receipt.replay_process_namespace_cid
                        and replay_namespace.replay_state_namespace_cid
                        == receipt.replay_state_namespace_cid
                        and cache_set_cid
                        == receipt.replay_cache_namespace_cid
                        and replay_namespace.replay_executor_identity_cid
                        == receipt.replay_executor_authority_cid
                        and replay_namespace.replay_observer_identity_cid
                        == receipt.replay_validator_authority_cid
                        and replay_resource.producer_identity_cid
                        == receipt.replay_executor_authority_cid
                        and replay_resource.validator_identity_cid
                        == receipt.replay_validator_authority_cid
                        and len(disjoint_authorities) == 9
                    )
                except (
                    AttributeError,
                    TypeError,
                    ValueError,
                    RuntimeNamespaceProvenanceError,
                ):
                    operational_matches = False
                _flag(
                    failures,
                    not operational_matches,
                    "operational_replay_not_source_recomputed",
                )
                if operational_matches:
                    validated_namespace_receipts.append(
                        str(replay_namespace.receipt_cid)
                    )
                    validated_orchestration_receipts.append(
                        str(orchestration.receipt_cid)
                    )
            if comparison_matches:
                comparison_cid = _cid(
                    rebuilt["comparison_receipt_cid"],
                    "comparison_receipt_cid",
                )
                validated_comparisons.append(comparison_cid)
                comparison_failures = rebuilt["failure_codes"]
                if not isinstance(comparison_failures, list):
                    raise FreshReplayGateError(
                        "G238 comparison failure codes changed"
                    )
                failures.update(
                    str(code) for code in comparison_failures
                )
            if comparison_matches and operational_matches:
                validated_receipts.append(receipt.receipt_cid)

    failure_codes = sorted(failures)
    body: dict[str, object] = {
        "schema": G238_REPLAY_GATE_SCHEMA_V2,
        "goal_id": "HSSL-G238",
        "evidence": HSSLEV2381F50(),
        "replay_policy_cid": G238_REPLAY_POLICY_V2_CID,
        "source_index_cid": index.index_cid,
        "source_commit_cid": index.source_commit_cid,
        "recursive_gitlinks_cid": index.recursive_gitlinks_cid,
        "environment_cid": index.environment_cid,
        "route_manifest_cid": index.route_manifest_cid,
        "case_index_cid": index.case_index_cid,
        "run_plan_cid": index.run_plan_cid,
        "validator_authority_cid": validator_cid,
        "source_record_count": len(index.records),
        "source_success_count": sum(
            record.terminal_status == "success"
            for record in index.records
        ),
        "source_failure_count": sum(
            record.terminal_status == "failure"
            for record in index.records
        ),
        "required_replay_count": len(required),
        "required_target_record_cids": sorted(required),
        "presented_target_record_cids": sorted(presented_cids),
        "presented_replay_receipt_cids": sorted(
            receipt.receipt_cid for receipt in receipts
        ),
        "validated_replay_receipt_cids": sorted(validated_receipts),
        "validated_comparison_receipt_cids": sorted(
            validated_comparisons
        ),
        "validated_namespace_receipt_cids": sorted(
            validated_namespace_receipts
        ),
        "validated_orchestration_receipt_cids": sorted(
            validated_orchestration_receipts
        ),
        "status": "complete" if not failure_codes else "incomplete",
        "passed": not failure_codes,
        "failure_codes": failure_codes,
    }
    return {**body, "receipt_cid": cid_for_dag_json(body)}


def validate_g238_detached_replay_gate_v2(
    value: object,
    source_index: G238ReplaySourceIndexV2 | Mapping[str, object],
    replay_receipts: Sequence[
        G238DetachedReplayReceiptV2 | Mapping[str, object]
    ],
    *,
    validator_authority_cid: str,
    operational_replay_sources: Mapping[
        str, G240PrivateReplayValidationSourcesV2
    ]
    | None = None,
) -> str:
    """Source-recompute a G238 gate and return its canonical receipt CID."""

    data = _mapping(value, "G238 detached replay gate")
    expected = {
        "schema",
        "goal_id",
        "evidence",
        "replay_policy_cid",
        "source_index_cid",
        "source_commit_cid",
        "recursive_gitlinks_cid",
        "environment_cid",
        "route_manifest_cid",
        "case_index_cid",
        "run_plan_cid",
        "validator_authority_cid",
        "source_record_count",
        "source_success_count",
        "source_failure_count",
        "required_replay_count",
        "required_target_record_cids",
        "presented_target_record_cids",
        "presented_replay_receipt_cids",
        "validated_replay_receipt_cids",
        "validated_comparison_receipt_cids",
        "validated_namespace_receipt_cids",
        "validated_orchestration_receipt_cids",
        "status",
        "passed",
        "failure_codes",
        "receipt_cid",
    }
    _exact(data, expected, "G238 detached replay gate")
    rebuilt = build_g238_detached_replay_gate_v2(
        source_index,
        replay_receipts,
        validator_authority_cid=validator_authority_cid,
        operational_replay_sources=operational_replay_sources,
    )
    if dict(data) != rebuilt:
        raise FreshReplayGateError(
            "G238 detached replay gate did not source-recompute"
        )
    return _cid(data["receipt_cid"], "receipt_cid")


__all__ = [
    "G238_COMPARISON_SCHEMA_V2",
    "G238_DETACHED_REPLAY_RECEIPT_SCHEMA_V2",
    "G238_FAILURE_SAMPLE_PER_STRATUM",
    "G238_GIT_COMMIT_IDENTITY_SCHEMA_V2",
    "G238_KERNEL_IDENTITY_SCHEMA_V2",
    "G238_REPLAY_GATE_SCHEMA_V2",
    "G238_REPLAY_POLICY_SCHEMA_V2",
    "G238_REPLAY_POLICY_V2_CID",
    "G238_REPLAY_SOURCE_INDEX_SCHEMA_V2",
    "G238_REPLAY_SOURCE_RECORD_SCHEMA_V2",
    "G238_RUNTIME_COORDINATE_SCHEMA_V2",
    "G238_SEMANTIC_IDENTITY_SCHEMA_V2",
    "G238_SEMANTIC_OBSERVATION_SCHEMA_V2",
    "G238_STATUS_IDENTITY_SCHEMA_V2",
    "G238DetachedReplayReceiptV2",
    "G238ReplaySourceIndexV2",
    "G238ReplaySourceRecordV2",
    "G238SemanticObservationV2",
    "FreshReplayGateError",
    "HSSLEV2381F50",
    "build_g238_detached_replay_gate_v2",
    "build_g238_replay_comparison_v2",
    "g238_git_commit_cid",
    "runtime_replay_coordinate_cid_v2",
    "validate_g238_detached_replay_gate_v2",
    "validate_g238_replay_comparison_v2",
    "validate_g238_semantic_observation_v2",
]
