"""CID-native independent resource, paired-statistics, and Pareto evidence.

This module is the bounded HSSL-G237 trust boundary.  Runtime telemetry is
useful diagnostic evidence, but it is not allowed to certify its own
operational cost.  Each selected full runtime receipt therefore joins to one
independently metered resource receipt whose producer, meter, and validator
identities are distinct.

The gate keeps efficacy and cost in separate CID-addressed aggregates.  Cost
comparisons preserve exact A0/candidate case and source-derived stratum links,
including one-sided missingness, before projecting complete pairs through the
frozen paired-bootstrap implementation in :mod:`statistics`.  Pareto
membership is then recomputed from those separate aggregates with metric
directions and safety as a hard feasibility constraint.

G237 verifies the pinned G236 safety receipt's schema, state, and CID.  It does
not replace the G236 source validator: the composing G231 gate must first call
``validate_reviewed_control_safety_gate_v2`` with the complete reviewed
control index, manifests, and runtime population, then pin that returned
receipt CID here.

No function opens a fixture, corpus, manifest path, or holdout.  The only
legacy SHA-256 value touched here is the already-frozen environment identity
inside :class:`CausalRuntimeEvidenceV2`; it is immediately wrapped in an
explicit compatibility envelope and represented externally by a DAG-JSON CID.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from types import MappingProxyType
from typing import Final, Mapping, Sequence, Self

from .causal_runtime import (
    CausalRuntimeEvidenceV2,
    validate_causal_runtime_evidence_v2,
)
from .content_addressing import cid_for_dag_json, validate_cid
from .contracts import (
    CacheMode,
    MetricCategory,
    MetricDirection,
    Split,
)
from .reviewed_control import REVIEWED_CONTROL_SAFETY_GATE_SCHEMA_V2
from .revised_pilot_authorization import (
    G210_VARIANT_IDS,
    G210RuntimeReceiptMatrixV2,
    RevisedPilotAuthorizationError,
    validate_g234_efficacy_gate_v2,
)
from .statistics import (
    AnalysisDomain,
    ComparisonSpec,
    Estimator,
    MetricKind,
    MissingKind,
    PairedCaseObservation,
    StatisticalPlan,
    StratumDimension,
    analyze_paired,
)
from .variants import VARIANT_REGISTRY


INDEPENDENT_COMPONENT_RESOURCE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "independent-component-resource.v2"
)
INDEPENDENT_RESOURCE_RECEIPT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "independent-resource-receipt.v2"
)
RESOURCE_MEASUREMENT_POLICY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "independent-resource-measurement-policy.v2"
)
RESOURCE_ENVIRONMENT_COMPATIBILITY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "resource-environment-compatibility.v2"
)
RESOURCE_RUN_IDENTITY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.resource-run-identity.v2"
)
RESOURCE_CASE_MANIFEST_COMPATIBILITY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "resource-case-manifest-compatibility.v2"
)
RESOURCE_COORDINATE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "resource-runtime-coordinate.v2"
)
RESOURCE_REPLAY_COORDINATE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "resource-replay-coordinate.v2"
)
RESOURCE_REPLAY_IDENTITY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "resource-replay-identity.v2"
)
RESOURCE_REPLAY_MEASUREMENT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "resource-replay-measurement.v2"
)
RESOURCE_REPLAY_COMPARISON_POLICY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "resource-replay-comparison-policy.v2"
)
RESOURCE_REPLAY_COMPARISON_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "resource-replay-comparison.v2"
)
RESOURCE_EVIDENCE_SET_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.resource-evidence-set.v2"
)
RESOURCE_STRATUM_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.resource-stratum.v2"
)
PAIRED_COST_OBSERVATION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "paired-cost-observation.v2"
)
PAIRED_COST_ANALYSIS_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.paired-cost-analysis.v2"
)
RESOURCE_COST_AGGREGATE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.resource-cost-aggregate.v2"
)
RESOURCE_EFFICACY_PROJECTION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "resource-gate-efficacy-projection.v2"
)
RESOURCE_PARETO_FRONTIER_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "resource-safety-pareto-frontier.v2"
)
RESOURCE_STATISTICS_GATE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "resource-statistics-pareto-gate.v2"
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_RESOURCE_FIELDS: Final = (
    "wall_time_ms",
    "peak_memory_bytes",
    "model_calls",
    "retries",
    "solver_processes",
    "accelerator_minutes",
    "queue_delay_ms",
    "released",
    "process_group_reaped",
)
_COST_METRICS: Final = (
    "wall_time_ms",
    "peak_memory_bytes",
    "model_calls",
    "retries",
    "solver_processes",
    "accelerator_minutes",
    "queue_delay_ms",
)
_STATISTIC_METRICS: Final = (
    "wall_time_ms",
    "peak_memory_bytes",
    "model_calls",
    "accelerator_minutes",
)


class ResourceStatisticsError(ValueError):
    """Raised when G237 evidence violates its frozen trust boundary."""


def HSSLEV2374E49() -> str:
    """Return AST-verifiable evidence for the bounded G237 lane."""

    return (
        "CID-native independent resource receipts, exact missing-aware A0 "
        "pairs, replayed statistics, and safety-feasible Pareto evidence"
    )


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ResourceStatisticsError(
                "resource DAG-JSON objects require string keys"
            )
        return {
            str(key): _plain(member)
            for key, member in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_plain(member) for member in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise ResourceStatisticsError(
        "resource value is not DAG-JSON: "
        f"{type(value).__name__}"
    )


def _freeze(value: object) -> object:
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


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ResourceStatisticsError(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ResourceStatisticsError(f"{field} must be an array")
    return value


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise ResourceStatisticsError(
            f"{field} fields changed: "
            f"missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ResourceStatisticsError(
            f"{field} must be a safe 1-128 character identifier"
        )
    return value


def _cid(
    value: object,
    field: str,
    *,
    codecs: tuple[str, ...] = ("dag-json",),
) -> str:
    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as exc:
        raise ResourceStatisticsError(
            f"{field} must be a canonical CIDv1/base32/sha2-256 value"
        ) from exc


def _nonnegative_number(
    value: object,
    field: str,
    *,
    integer: bool = False,
) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResourceStatisticsError(
            f"{field} must be a nonnegative finite number"
        )
    if integer and not isinstance(value, int):
        raise ResourceStatisticsError(f"{field} must be an integer")
    result = int(value) if integer else float(value)
    if result < 0 or not math.isfinite(float(result)):
        raise ResourceStatisticsError(
            f"{field} must be a nonnegative finite number"
        )
    return result


def resource_measurement_policy_v2() -> dict[str, object]:
    """Return the fixed independent-meter and missingness policy."""

    return {
        "schema": RESOURCE_MEASUREMENT_POLICY_SCHEMA_V2,
        "runtime_authority": "CausalRuntimeEvidenceV2.receipt_cid",
        "measurement_authority": "independent_operational_meter",
        "producer_meter_validator_must_be_distinct": True,
        "component_fields": list(_RESOURCE_FIELDS),
        "null_requires_nonempty_reason": True,
        "missing_work_is_never_zero": True,
        "release_and_reap_required": True,
        "pilot_and_development_only": True,
        "holdout_included": False,
    }


RESOURCE_MEASUREMENT_POLICY_V2_CID: Final = cid_for_dag_json(
    resource_measurement_policy_v2()
)


def resource_replay_comparison_policy_v2() -> dict[str, object]:
    """Return frozen, deterministic source/replay measurement tolerances.

    Counts are semantic operational events and therefore compare exactly.
    Timing, memory, accelerator use, and queue delay are independently
    measured quantities, so an exact receipt-CID equality would make a real
    detached replay impossible.  Their inclusive bounds combine a small
    absolute floor with a preregistered relative allowance.
    """

    return {
        "schema": RESOURCE_REPLAY_COMPARISON_POLICY_SCHEMA_V2,
        "identity_fields": [
            "measurement_policy_cid",
            "replay_coordinate_cid",
            "component_ids",
            "holdout_included",
        ],
        "identity_comparison": "exact",
        "component_population_comparison": "exact",
        "missing_measurements": "incomplete_not_zero",
        "lifecycle_fields": {
            "released": "exact_true",
            "process_group_reaped": "exact_true",
        },
        "metric_tolerances": {
            "wall_time_ms": {
                "absolute": 10.0,
                "relative_millionths": 250_000,
            },
            "peak_memory_bytes": {
                "absolute": 1_048_576,
                "relative_millionths": 150_000,
            },
            "model_calls": {
                "absolute": 0,
                "relative_millionths": 0,
            },
            "retries": {
                "absolute": 0,
                "relative_millionths": 0,
            },
            "solver_processes": {
                "absolute": 0,
                "relative_millionths": 0,
            },
            "accelerator_minutes": {
                "absolute": 0.01,
                "relative_millionths": 250_000,
            },
            "queue_delay_ms": {
                "absolute": 20.0,
                "relative_millionths": 500_000,
            },
        },
        "bound_rule": (
            "absolute_delta<=max(absolute,"
            "abs(source)*relative_millionths/1000000)"
        ),
        "paired_evidence_required": True,
        "holdout_included": False,
    }


RESOURCE_REPLAY_COMPARISON_POLICY_V2_CID: Final = cid_for_dag_json(
    resource_replay_comparison_policy_v2()
)


@dataclass(frozen=True, slots=True)
class IndependentComponentResourceV2:
    """One component's independently observed operational measurements."""

    component_id: str
    wall_time_ms: float | None
    peak_memory_bytes: int | None
    model_calls: int | None
    retries: int | None
    solver_processes: int | None
    accelerator_minutes: float | None
    queue_delay_ms: float | None
    released: bool | None
    process_group_reaped: bool | None
    missing_reasons: Mapping[str, str]
    schema: str = INDEPENDENT_COMPONENT_RESOURCE_SCHEMA_V2

    def __post_init__(self) -> None:
        if self.schema != INDEPENDENT_COMPONENT_RESOURCE_SCHEMA_V2:
            raise ResourceStatisticsError(
                "unsupported independent component-resource schema"
            )
        object.__setattr__(
            self,
            "component_id",
            _safe_id(self.component_id, "component_id"),
        )
        numeric_integer = {
            "peak_memory_bytes",
            "model_calls",
            "retries",
            "solver_processes",
        }
        for field in _COST_METRICS:
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(
                    self,
                    field,
                    _nonnegative_number(
                        value,
                        field,
                        integer=field in numeric_integer,
                    ),
                )
        for field in ("released", "process_group_reaped"):
            value = getattr(self, field)
            if value is not None and not isinstance(value, bool):
                raise ResourceStatisticsError(
                    f"{field} must be boolean or null"
                )
        reasons = _mapping(self.missing_reasons, "missing_reasons")
        normalized: dict[str, str] = {}
        for key, reason in reasons.items():
            if key not in _RESOURCE_FIELDS:
                raise ResourceStatisticsError(
                    f"missing_reasons contains unknown field {key!r}"
                )
            if not isinstance(reason, str) or not reason.strip():
                raise ResourceStatisticsError(
                    f"missing_reasons.{key} must be nonempty"
                )
            normalized[key] = reason.strip()
        missing = {
            field for field in _RESOURCE_FIELDS
            if getattr(self, field) is None
        }
        if set(normalized) != missing:
            raise ResourceStatisticsError(
                "null resource fields and missing_reasons must match exactly"
            )
        object.__setattr__(
            self,
            "missing_reasons",
            MappingProxyType(dict(sorted(normalized.items()))),
        )

    @property
    def complete(self) -> bool:
        return not self.missing_reasons

    @property
    def lifecycle_safe(self) -> bool:
        return self.released is True and self.process_group_reaped is True

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "component_id": self.component_id,
            **{
                field: getattr(self, field)
                for field in _RESOURCE_FIELDS
            },
            "missing_reasons": dict(self.missing_reasons),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "independent component resource")
        expected = {
            "schema",
            "component_id",
            *_RESOURCE_FIELDS,
            "missing_reasons",
        }
        _exact(data, expected, "independent component resource")
        reasons = _mapping(data["missing_reasons"], "missing_reasons")
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            component_id=data["component_id"],  # type: ignore[arg-type]
            wall_time_ms=data["wall_time_ms"],  # type: ignore[arg-type]
            peak_memory_bytes=data[
                "peak_memory_bytes"
            ],  # type: ignore[arg-type]
            model_calls=data["model_calls"],  # type: ignore[arg-type]
            retries=data["retries"],  # type: ignore[arg-type]
            solver_processes=data[
                "solver_processes"
            ],  # type: ignore[arg-type]
            accelerator_minutes=data[
                "accelerator_minutes"
            ],  # type: ignore[arg-type]
            queue_delay_ms=data[
                "queue_delay_ms"
            ],  # type: ignore[arg-type]
            released=data["released"],  # type: ignore[arg-type]
            process_group_reaped=data[
                "process_group_reaped"
            ],  # type: ignore[arg-type]
            missing_reasons={
                str(key): str(reason)
                for key, reason in reasons.items()
            },
        )


def _runtime_environment_identity_cid(
    evidence: CausalRuntimeEvidenceV2,
) -> str:
    # This is the sole frozen SHA compatibility join in G237.  The digest is
    # never re-exported as a bare field; only this envelope's CID crosses the
    # resource boundary.
    environments = {
        stage.provenance.environment_sha256
        for stage in (
            *evidence.semantic_frontend,
            *evidence.case_result.stages,
        )
    }
    if len(environments) != 1:
        raise ResourceStatisticsError(
            "runtime evidence does not have one frozen environment identity"
        )
    body = {
        "schema": RESOURCE_ENVIRONMENT_COMPATIBILITY_SCHEMA_V2,
        "compatibility_source": (
            "StageProvenance.environment_sha256"
        ),
        "digest_algorithm": "sha2-256",
        "frozen_environment_digest": next(iter(environments)),
    }
    return cid_for_dag_json(body)


def _runtime_run_identity_cid(
    evidence: CausalRuntimeEvidenceV2,
) -> str:
    body = {
        "schema": RESOURCE_RUN_IDENTITY_SCHEMA_V2,
        "run_id": evidence.case_result.run_id,
    }
    return cid_for_dag_json(body)


def _runtime_coordinate_payload(
    evidence: CausalRuntimeEvidenceV2,
) -> dict[str, object]:
    result = evidence.case_result
    return {
        "schema": RESOURCE_COORDINATE_SCHEMA_V2,
        "runtime_evidence_cid": evidence.receipt_cid,
        "source_cid": evidence.compiler_exposure.source_cid,
        "environment_identity_cid": (
            _runtime_environment_identity_cid(evidence)
        ),
        "run_identity_cid": _runtime_run_identity_cid(evidence),
        "case_id": result.case_id,
        "split": result.split.value,
        "cache_mode": result.cache_mode.value,
        "variant_id": result.variant_id,
        "proof_context_cid": evidence.proof_context_cid,
        "compiler_reference_exposure_cid": (
            evidence.compiler_exposure.receipt_cid
        ),
        "holdout_included": False,
    }


def _runtime_replay_coordinate_payload(
    evidence: CausalRuntimeEvidenceV2,
) -> dict[str, object]:
    """Project the immutable treatment coordinate shared by fresh replays."""

    result = evidence.case_result
    runtime_body = evidence.identity_body()
    manifest_identity_cid = cid_for_dag_json(
        {
            "schema": RESOURCE_CASE_MANIFEST_COMPATIBILITY_SCHEMA_V2,
            "compatibility_source": "CaseResultRecord.case_manifest_sha256",
            "digest_algorithm": "sha2-256",
            "frozen_manifest_digest": result.case_manifest_sha256,
        }
    )
    return {
        "schema": RESOURCE_REPLAY_COORDINATE_SCHEMA_V2,
        "semantic_protocol_cid": runtime_body["semantic_protocol_cid"],
        "causal_proof_protocol_cid": runtime_body[
            "causal_proof_protocol_cid"
        ],
        "source_cid": evidence.compiler_exposure.source_cid,
        "environment_identity_cid": (
            _runtime_environment_identity_cid(evidence)
        ),
        "case_manifest_identity_cid": manifest_identity_cid,
        "case_id": result.case_id,
        "split": result.split.value,
        "cache_mode": result.cache_mode.value,
        "variant_id": result.variant_id,
        "variant_profile_cid": cid_for_dag_json(
            _plain(VARIANT_REGISTRY[result.variant_id].to_dict())
        ),
        "proof_context_cid": evidence.proof_context_cid,
        # A detached replay must use a new run and runtime receipt.  Neither
        # value is part of this immutable treatment coordinate.
        "run_identity_excluded": True,
        "runtime_receipt_identity_excluded": True,
        "holdout_included": False,
    }


def runtime_resource_coordinate_cid_v2(
    evidence: CausalRuntimeEvidenceV2,
) -> str:
    """Return the exact CID-native runtime coordinate for resource joins."""

    replayed = validate_causal_runtime_evidence_v2(evidence.to_dict())
    return cid_for_dag_json(_runtime_coordinate_payload(replayed))


def runtime_resource_replay_coordinate_cid_v2(
    evidence: CausalRuntimeEvidenceV2,
) -> str:
    """Return the run-independent resource coordinate used by G238."""

    replayed = validate_causal_runtime_evidence_v2(evidence.to_dict())
    return cid_for_dag_json(_runtime_replay_coordinate_payload(replayed))


@dataclass(frozen=True, slots=True)
class IndependentResourceReceiptV2:
    """Independent operational evidence bound to one full runtime receipt."""

    runtime_evidence_cid: str
    source_cid: str
    environment_identity_cid: str
    run_identity_cid: str
    coordinate_cid: str
    replay_coordinate_cid: str
    producer_identity_cid: str
    meter_identity_cid: str
    validator_identity_cid: str
    components: tuple[IndependentComponentResourceV2, ...]
    measurement_policy_cid: str = RESOURCE_MEASUREMENT_POLICY_V2_CID
    holdout_included: bool = False
    schema: str = INDEPENDENT_RESOURCE_RECEIPT_SCHEMA_V2

    def __post_init__(self) -> None:
        if self.schema != INDEPENDENT_RESOURCE_RECEIPT_SCHEMA_V2:
            raise ResourceStatisticsError(
                "unsupported independent resource-receipt schema"
            )
        object.__setattr__(
            self,
            "runtime_evidence_cid",
            _cid(self.runtime_evidence_cid, "runtime_evidence_cid"),
        )
        object.__setattr__(
            self,
            "source_cid",
            _cid(self.source_cid, "source_cid", codecs=("raw",)),
        )
        for field in (
            "environment_identity_cid",
            "run_identity_cid",
            "coordinate_cid",
            "replay_coordinate_cid",
            "producer_identity_cid",
            "meter_identity_cid",
            "validator_identity_cid",
            "measurement_policy_cid",
        ):
            object.__setattr__(
                self,
                field,
                _cid(getattr(self, field), field),
            )
        identities = {
            self.producer_identity_cid,
            self.meter_identity_cid,
            self.validator_identity_cid,
        }
        if len(identities) != 3:
            raise ResourceStatisticsError(
                "producer, meter, and validator identities must be distinct"
            )
        if (
            self.measurement_policy_cid
            != RESOURCE_MEASUREMENT_POLICY_V2_CID
            or self.holdout_included is not False
        ):
            raise ResourceStatisticsError(
                "resource measurement policy or holdout boundary drifted"
            )
        components = tuple(self.components)
        if (
            not components
            or any(
                not isinstance(item, IndependentComponentResourceV2)
                for item in components
            )
        ):
            raise ResourceStatisticsError(
                "resource receipt requires typed component measurements"
            )
        replayed = tuple(
            IndependentComponentResourceV2.from_dict(item.to_dict())
            for item in components
        )
        replayed = tuple(
            sorted(replayed, key=lambda item: item.component_id)
        )
        component_ids = tuple(item.component_id for item in replayed)
        if len(component_ids) != len(set(component_ids)):
            raise ResourceStatisticsError(
                "resource receipt contains duplicate component IDs"
            )
        object.__setattr__(self, "components", replayed)

    @property
    def complete(self) -> bool:
        return all(item.complete for item in self.components)

    @property
    def lifecycle_safe(self) -> bool:
        return all(item.lifecycle_safe for item in self.components)

    def replay_identity_payload(self) -> dict[str, object]:
        """Return only immutable coordinate, policy, and component identity."""

        return {
            "schema": RESOURCE_REPLAY_IDENTITY_SCHEMA_V2,
            "measurement_policy_cid": self.measurement_policy_cid,
            "replay_coordinate_cid": self.replay_coordinate_cid,
            "component_ids": [
                item.component_id for item in self.components
            ],
            "holdout_included": self.holdout_included,
        }

    @property
    def replay_identity_cid(self) -> str:
        return cid_for_dag_json(self.replay_identity_payload())

    def measurement_payload(self) -> dict[str, object]:
        """Return volatile measurements separately from replay identity."""

        return {
            "schema": RESOURCE_REPLAY_MEASUREMENT_SCHEMA_V2,
            "replay_identity_cid": self.replay_identity_cid,
            "components": [item.to_dict() for item in self.components],
            "complete": self.complete,
            "lifecycle_safe": self.lifecycle_safe,
        }

    @property
    def measurement_cid(self) -> str:
        return cid_for_dag_json(self.measurement_payload())

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "measurement_policy_cid": self.measurement_policy_cid,
            "runtime_evidence_cid": self.runtime_evidence_cid,
            "source_cid": self.source_cid,
            "environment_identity_cid": self.environment_identity_cid,
            "run_identity_cid": self.run_identity_cid,
            "coordinate_cid": self.coordinate_cid,
            "replay_coordinate_cid": self.replay_coordinate_cid,
            "producer_identity_cid": self.producer_identity_cid,
            "meter_identity_cid": self.meter_identity_cid,
            "validator_identity_cid": self.validator_identity_cid,
            "components": [item.to_dict() for item in self.components],
            "holdout_included": self.holdout_included,
        }

    @property
    def receipt_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "receipt_cid": self.receipt_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "independent resource receipt")
        expected = {
            "schema",
            "measurement_policy_cid",
            "runtime_evidence_cid",
            "source_cid",
            "environment_identity_cid",
            "run_identity_cid",
            "coordinate_cid",
            "replay_coordinate_cid",
            "producer_identity_cid",
            "meter_identity_cid",
            "validator_identity_cid",
            "components",
            "holdout_included",
            "receipt_cid",
        }
        _exact(data, expected, "independent resource receipt")
        result = cls(
            schema=data["schema"],  # type: ignore[arg-type]
            measurement_policy_cid=data[
                "measurement_policy_cid"
            ],  # type: ignore[arg-type]
            runtime_evidence_cid=data[
                "runtime_evidence_cid"
            ],  # type: ignore[arg-type]
            source_cid=data["source_cid"],  # type: ignore[arg-type]
            environment_identity_cid=data[
                "environment_identity_cid"
            ],  # type: ignore[arg-type]
            run_identity_cid=data[
                "run_identity_cid"
            ],  # type: ignore[arg-type]
            coordinate_cid=data["coordinate_cid"],  # type: ignore[arg-type]
            replay_coordinate_cid=data[
                "replay_coordinate_cid"
            ],  # type: ignore[arg-type]
            producer_identity_cid=data[
                "producer_identity_cid"
            ],  # type: ignore[arg-type]
            meter_identity_cid=data[
                "meter_identity_cid"
            ],  # type: ignore[arg-type]
            validator_identity_cid=data[
                "validator_identity_cid"
            ],  # type: ignore[arg-type]
            components=tuple(
                IndependentComponentResourceV2.from_dict(item)
                for item in _array(data["components"], "components")
            ),
            holdout_included=data[
                "holdout_included"
            ],  # type: ignore[arg-type]
        )
        if data["receipt_cid"] != result.receipt_cid:
            raise ResourceStatisticsError(
                "independent resource receipt CID changed"
            )
        return result


def build_independent_resource_receipt_v2(
    evidence: CausalRuntimeEvidenceV2,
    components: Sequence[IndependentComponentResourceV2],
    *,
    producer_identity_cid: str,
    meter_identity_cid: str,
    validator_identity_cid: str,
) -> IndependentResourceReceiptV2:
    """Bind independent measurements to one replayed full-runtime receipt."""

    if not isinstance(evidence, CausalRuntimeEvidenceV2):
        raise ResourceStatisticsError(
            "resource receipt requires CausalRuntimeEvidenceV2"
        )
    replayed = validate_causal_runtime_evidence_v2(evidence.to_dict())
    coordinate = _runtime_coordinate_payload(replayed)
    if replayed.case_result.split not in {
        Split.PILOT,
        Split.DEVELOPMENT,
    }:
        raise ResourceStatisticsError(
            "resource receipts are limited to pilot/development"
        )
    return IndependentResourceReceiptV2(
        runtime_evidence_cid=replayed.receipt_cid,
        source_cid=replayed.compiler_exposure.source_cid,
        environment_identity_cid=(
            _runtime_environment_identity_cid(replayed)
        ),
        run_identity_cid=_runtime_run_identity_cid(replayed),
        coordinate_cid=cid_for_dag_json(coordinate),
        replay_coordinate_cid=cid_for_dag_json(
            _runtime_replay_coordinate_payload(replayed)
        ),
        producer_identity_cid=producer_identity_cid,
        meter_identity_cid=meter_identity_cid,
        validator_identity_cid=validator_identity_cid,
        components=tuple(components),
    )


def validate_independent_resource_receipt_v2(
    value: object,
    evidence: CausalRuntimeEvidenceV2 | None = None,
) -> IndependentResourceReceiptV2:
    """Replay a receipt and optionally verify its exact runtime binding."""

    result = (
        IndependentResourceReceiptV2.from_dict(value.to_dict())
        if isinstance(value, IndependentResourceReceiptV2)
        else IndependentResourceReceiptV2.from_dict(value)
    )
    if evidence is not None:
        replayed = validate_causal_runtime_evidence_v2(
            evidence.to_dict()
        )
        expected = _runtime_coordinate_payload(replayed)
        if (
            result.runtime_evidence_cid != replayed.receipt_cid
            or result.source_cid
            != replayed.compiler_exposure.source_cid
            or result.environment_identity_cid
            != _runtime_environment_identity_cid(replayed)
            or result.run_identity_cid
            != _runtime_run_identity_cid(replayed)
            or result.coordinate_cid != cid_for_dag_json(expected)
            or result.replay_coordinate_cid
            != cid_for_dag_json(
                _runtime_replay_coordinate_payload(replayed)
            )
        ):
            raise ResourceStatisticsError(
                "resource receipt is stale or bound to another runtime"
            )
    return result


def compare_resource_replay_measurements_v2(
    source: IndependentResourceReceiptV2 | Mapping[str, object],
    replay: IndependentResourceReceiptV2 | Mapping[str, object],
) -> dict[str, object]:
    """Build paired replay evidence without requiring byte-equal telemetry.

    Immutable coordinate, measurement-policy, and component identities join
    exactly.  Independently measured values are evaluated under the frozen
    metric-specific bounds, producing a CID-addressed comparison receipt.
    Missing measurements remain incomplete and lifecycle safety remains exact.
    """

    source_receipt = validate_independent_resource_receipt_v2(source)
    replay_receipt = validate_independent_resource_receipt_v2(replay)
    policy = resource_replay_comparison_policy_v2()
    tolerances = _mapping(
        policy["metric_tolerances"],
        "resource replay metric tolerances",
    )
    source_components = {
        item.component_id: item for item in source_receipt.components
    }
    replay_components = {
        item.component_id: item for item in replay_receipt.components
    }
    component_ids = sorted(
        set(source_components) | set(replay_components)
    )
    comparisons: list[dict[str, object]] = []
    missing_count = 0
    out_of_tolerance_count = 0
    within_tolerance_count = 0

    for component_id in component_ids:
        source_component = source_components.get(component_id)
        replay_component = replay_components.get(component_id)
        for metric_id in _COST_METRICS:
            source_value = (
                None
                if source_component is None
                else getattr(source_component, metric_id)
            )
            replay_value = (
                None
                if replay_component is None
                else getattr(replay_component, metric_id)
            )
            tolerance = _mapping(
                tolerances[metric_id],
                f"resource replay tolerance {metric_id}",
            )
            absolute_tolerance = _nonnegative_number(
                tolerance["absolute"],
                f"{metric_id}.absolute tolerance",
            )
            relative_millionths = _nonnegative_number(
                tolerance["relative_millionths"],
                f"{metric_id}.relative tolerance",
                integer=True,
            )
            measured = (
                source_value is not None and replay_value is not None
            )
            absolute_delta: float | None = None
            allowed_delta: float | None = None
            relative_delta_millionths: int | None = None
            within_tolerance = False
            if measured:
                absolute_delta = abs(
                    float(replay_value) - float(source_value)
                )
                allowed_delta = max(
                    float(absolute_tolerance),
                    abs(float(source_value))
                    * float(relative_millionths)
                    / 1_000_000.0,
                )
                if absolute_delta == 0:
                    relative_delta_millionths = 0
                elif float(source_value) != 0:
                    relative_delta_millionths = int(
                        round(
                            absolute_delta
                            / abs(float(source_value))
                            * 1_000_000.0
                        )
                    )
                within_tolerance = absolute_delta <= allowed_delta
                if within_tolerance:
                    within_tolerance_count += 1
                else:
                    out_of_tolerance_count += 1
            else:
                missing_count += 1
            row: dict[str, object] = {
                "component_id": component_id,
                "metric_id": metric_id,
                "source_value": source_value,
                "replay_value": replay_value,
                "measured": measured,
                "absolute_delta": absolute_delta,
                "relative_delta_millionths": (
                    relative_delta_millionths
                ),
                "allowed_absolute_delta": allowed_delta,
                "within_tolerance": within_tolerance,
            }
            row["comparison_cid"] = cid_for_dag_json(row)
            comparisons.append(row)

        for lifecycle_field in ("released", "process_group_reaped"):
            source_value = (
                None
                if source_component is None
                else getattr(source_component, lifecycle_field)
            )
            replay_value = (
                None
                if replay_component is None
                else getattr(replay_component, lifecycle_field)
            )
            measured = (
                type(source_value) is bool
                and type(replay_value) is bool
            )
            within_tolerance = bool(
                measured
                and source_value is True
                and replay_value is True
            )
            if not measured:
                missing_count += 1
            elif within_tolerance:
                within_tolerance_count += 1
            else:
                out_of_tolerance_count += 1
            row = {
                "component_id": component_id,
                "metric_id": lifecycle_field,
                "source_value": source_value,
                "replay_value": replay_value,
                "measured": measured,
                "absolute_delta": None,
                "relative_delta_millionths": None,
                "allowed_absolute_delta": 0,
                "within_tolerance": within_tolerance,
            }
            row["comparison_cid"] = cid_for_dag_json(row)
            comparisons.append(row)

    identity_equal = (
        source_receipt.replay_identity_cid
        == replay_receipt.replay_identity_cid
    )
    failures: list[str] = []
    if not identity_equal:
        failures.append("resource_replay_identity_mismatch")
    if missing_count:
        failures.append("resource_replay_measurement_missing")
    if out_of_tolerance_count:
        failures.append("resource_replay_measurement_out_of_tolerance")
    if (
        not source_receipt.lifecycle_safe
        or not replay_receipt.lifecycle_safe
    ):
        failures.append("resource_replay_lifecycle_mismatch")
    failure_codes = sorted(set(failures))
    body: dict[str, object] = {
        "schema": RESOURCE_REPLAY_COMPARISON_SCHEMA_V2,
        "comparison_policy_cid": (
            RESOURCE_REPLAY_COMPARISON_POLICY_V2_CID
        ),
        "source_resource_receipt_cid": source_receipt.receipt_cid,
        "replay_resource_receipt_cid": replay_receipt.receipt_cid,
        "source_resource_identity_cid": (
            source_receipt.replay_identity_cid
        ),
        "replay_resource_identity_cid": (
            replay_receipt.replay_identity_cid
        ),
        "source_measurement_cid": source_receipt.measurement_cid,
        "replay_measurement_cid": replay_receipt.measurement_cid,
        "identity_equal": identity_equal,
        "paired_observation_count": len(comparisons),
        "measured_observation_count": (
            within_tolerance_count + out_of_tolerance_count
        ),
        "within_tolerance_count": within_tolerance_count,
        "out_of_tolerance_count": out_of_tolerance_count,
        "missing_observation_count": missing_count,
        "comparisons": comparisons,
        "complete": not failure_codes,
        "passed": not failure_codes,
        "failure_codes": failure_codes,
        "holdout_included": False,
    }
    return {
        **body,
        "comparison_receipt_cid": cid_for_dag_json(body),
    }


def validate_resource_replay_comparison_v2(
    value: object,
    source: IndependentResourceReceiptV2 | Mapping[str, object],
    replay: IndependentResourceReceiptV2 | Mapping[str, object],
) -> str:
    """Source-recompute one resource replay comparison receipt."""

    data = _mapping(value, "resource replay comparison")
    rebuilt = compare_resource_replay_measurements_v2(source, replay)
    _exact(data, set(rebuilt), "resource replay comparison")
    if _plain(data) != rebuilt:
        raise ResourceStatisticsError(
            "resource replay comparison did not source-recompute"
        )
    return _cid(
        data["comparison_receipt_cid"],
        "comparison_receipt_cid",
    )


def _resource_evidence_set_cid_from_replayed(
    source_runtime_matrix_cid: str,
    candidates: Sequence[str],
    receipts: Sequence[IndependentResourceReceiptV2],
) -> str:
    body = {
        "schema": RESOURCE_EVIDENCE_SET_SCHEMA_V2,
        "source_runtime_matrix_cid": source_runtime_matrix_cid,
        "candidate_variant_ids": list(candidates),
        "resource_receipt_cids": sorted(
            item.receipt_cid for item in receipts
        ),
        "holdout_included": False,
    }
    return cid_for_dag_json(body)


def _candidate_ids(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ResourceStatisticsError(
            "candidate_variant_ids must be a sequence"
        )
    candidates = tuple(value)
    if not candidates or len(candidates) != len(set(candidates)):
        raise ResourceStatisticsError(
            "candidate_variant_ids must be nonempty and unique"
        )
    for candidate in candidates:
        profile = VARIANT_REGISTRY.get(candidate)
        if (
            profile is None
            or candidate in {"A0", "S1"}
            or profile.paired_against != "A0"
            or profile.primary_candidate is not True
            or profile.safety_diagnostic_only is True
        ):
            raise ResourceStatisticsError(
                "candidate_variant_ids must be registered primary A0 pairs"
            )
    candidate_set = set(candidates)
    return tuple(
        variant_id
        for variant_id in G210_VARIANT_IDS
        if variant_id in candidate_set
    )


def resource_evidence_set_cid_v2(
    source_runtime_matrix_cid: str,
    candidate_variant_ids: Sequence[str],
    receipts: Sequence[IndependentResourceReceiptV2],
) -> str:
    """Freeze the exact externally approved resource-receipt population."""

    matrix_cid = _cid(
        source_runtime_matrix_cid,
        "source_runtime_matrix_cid",
    )
    candidates = _candidate_ids(candidate_variant_ids)
    replayed = tuple(
        validate_independent_resource_receipt_v2(item)
        for item in receipts
    )
    return _resource_evidence_set_cid_from_replayed(
        matrix_cid,
        candidates,
        replayed,
    )


def _runtime_key(
    evidence: CausalRuntimeEvidenceV2,
) -> tuple[str, str, str, str]:
    result = evidence.case_result
    return (
        result.split.value,
        result.cache_mode.value,
        result.case_id,
        result.variant_id,
    )


def _pair_key(
    evidence: CausalRuntimeEvidenceV2,
) -> tuple[str, str, str]:
    result = evidence.case_result
    return (
        result.split.value,
        result.cache_mode.value,
        result.case_id,
    )


def _aggregate_resource_receipt(
    receipt: IndependentResourceReceiptV2 | None,
) -> tuple[dict[str, int | float | None], dict[str, list[str]], bool | None]:
    if receipt is None:
        return (
            {metric: None for metric in _COST_METRICS},
            {
                metric: ["independent_resource_receipt_missing"]
                for metric in _COST_METRICS
            },
            None,
        )
    values: dict[str, int | float | None] = {}
    reasons: dict[str, list[str]] = {}
    for metric in _COST_METRICS:
        components = [
            getattr(component, metric)
            for component in receipt.components
        ]
        missing = [
            (
                f"{component.component_id}:"
                f"{component.missing_reasons[metric]}"
            )
            for component in receipt.components
            if getattr(component, metric) is None
        ]
        if missing:
            values[metric] = None
            reasons[metric] = sorted(missing)
        elif metric == "peak_memory_bytes":
            values[metric] = max(
                int(value) for value in components
                if value is not None
            )
        elif metric in {
            "model_calls",
            "retries",
            "solver_processes",
        }:
            values[metric] = sum(
                int(value) for value in components
                if value is not None
            )
        else:
            values[metric] = math.fsum(
                float(value) for value in components
                if value is not None
            )
    return values, reasons, receipt.lifecycle_safe


def _logic_family(evidence: CausalRuntimeEvidenceV2) -> str:
    context = evidence.proof_context
    obligation = context.get("proof_obligation")
    logic = (
        obligation.get("logic")
        if isinstance(obligation, Mapping)
        else None
    )
    if isinstance(logic, str) and _SAFE_ID.fullmatch(logic):
        return logic
    return f"context-{evidence.proof_context_cid[:24]}"


def _stratum_payload(
    evidence: CausalRuntimeEvidenceV2,
) -> dict[str, object]:
    return {
        "schema": RESOURCE_STRATUM_SCHEMA_V2,
        "split": evidence.case_result.split.value,
        "cache_mode": evidence.case_result.cache_mode.value,
        "logic_family": _logic_family(evidence),
        "holdout_included": False,
    }


def _pair_identity_valid(
    baseline: CausalRuntimeEvidenceV2,
    candidate: CausalRuntimeEvidenceV2,
) -> bool:
    left = baseline.case_result
    right = candidate.case_result
    return (
        left.variant_id == "A0"
        and VARIANT_REGISTRY[right.variant_id].paired_against == "A0"
        and left.run_id == right.run_id
        and left.case_id == right.case_id
        and left.split is right.split
        and left.cache_mode is right.cache_mode
        and left.protocol_sha256 == right.protocol_sha256
        and left.case_manifest_sha256
        == right.case_manifest_sha256
        and baseline.compiler_exposure.source_cid
        == candidate.compiler_exposure.source_cid
        and baseline.compiler_exposure.receipt_cid
        == candidate.compiler_exposure.receipt_cid
        and baseline.proof_context_cid
        == candidate.proof_context_cid
        and _runtime_environment_identity_cid(baseline)
        == _runtime_environment_identity_cid(candidate)
    )


def _paired_cost_observation(
    *,
    source_runtime_matrix_cid: str,
    baseline: CausalRuntimeEvidenceV2,
    candidate: CausalRuntimeEvidenceV2,
    baseline_receipt: IndependentResourceReceiptV2 | None,
    candidate_receipt: IndependentResourceReceiptV2 | None,
    metric_id: str,
) -> dict[str, object]:
    baseline_values, baseline_reasons, _ = (
        _aggregate_resource_receipt(baseline_receipt)
    )
    candidate_values, candidate_reasons, _ = (
        _aggregate_resource_receipt(candidate_receipt)
    )
    identity_valid = _pair_identity_valid(baseline, candidate)
    baseline_value = baseline_values[metric_id]
    candidate_value = candidate_values[metric_id]
    missing_reasons: list[str] = []
    missing_reasons.extend(
        f"baseline:{reason}"
        for reason in baseline_reasons.get(metric_id, ())
    )
    missing_reasons.extend(
        f"candidate:{reason}"
        for reason in candidate_reasons.get(metric_id, ())
    )
    if not identity_valid:
        missing_reasons.append("pair_identity_mismatch")
    measured = (
        identity_valid
        and baseline_value is not None
        and candidate_value is not None
    )
    stratum = _stratum_payload(baseline)
    body = {
        "schema": PAIRED_COST_OBSERVATION_SCHEMA_V2,
        "source_runtime_matrix_cid": source_runtime_matrix_cid,
        "metric_id": metric_id,
        "baseline_variant_id": "A0",
        "candidate_variant_id": candidate.case_result.variant_id,
        "case_id": baseline.case_result.case_id,
        "split": baseline.case_result.split.value,
        "cache_mode": baseline.case_result.cache_mode.value,
        "source_cid": baseline.compiler_exposure.source_cid,
        "proof_context_cid": baseline.proof_context_cid,
        "environment_identity_cid": (
            _runtime_environment_identity_cid(baseline)
        ),
        "run_identity_cid": _runtime_run_identity_cid(baseline),
        "stratum_cid": cid_for_dag_json(stratum),
        "baseline_runtime_evidence_cid": baseline.receipt_cid,
        "candidate_runtime_evidence_cid": candidate.receipt_cid,
        "baseline_resource_receipt_cid": (
            None
            if baseline_receipt is None
            else baseline_receipt.receipt_cid
        ),
        "candidate_resource_receipt_cid": (
            None
            if candidate_receipt is None
            else candidate_receipt.receipt_cid
        ),
        "baseline_value": baseline_value,
        "candidate_value": candidate_value,
        "identity_valid": identity_valid,
        "measured": measured,
        "missing_reasons": sorted(set(missing_reasons)),
        "missing_is_never_zero": True,
    }
    return {**body, "pair_cid": cid_for_dag_json(body)}


_LEGACY_STATISTIC_SPECS: Final = {
    "wall_time_ms": (
        "end_to_end_latency_p95",
        MetricCategory.RESOURCE,
        MetricDirection.MINIMIZE,
        "milliseconds",
        AnalysisDomain.LATENCY,
    ),
    "peak_memory_bytes": (
        "peak_rss",
        MetricCategory.RESOURCE,
        MetricDirection.MINIMIZE,
        "bytes",
        AnalysisDomain.RESOURCE,
    ),
    "model_calls": (
        "model_calls",
        MetricCategory.RESOURCE,
        MetricDirection.MINIMIZE,
        "count",
        AnalysisDomain.RESOURCE,
    ),
    "accelerator_minutes": (
        "accelerator_minutes",
        MetricCategory.RESOURCE,
        MetricDirection.MINIMIZE,
        "minutes",
        AnalysisDomain.RESOURCE,
    ),
}


def _paired_cost_analysis(
    *,
    candidate_variant_id: str,
    split: str,
    cache_mode: str,
    metric_id: str,
    pair_sources: Sequence[
        tuple[
            CausalRuntimeEvidenceV2,
            CausalRuntimeEvidenceV2,
            Mapping[str, object],
        ]
    ],
    plan: StatisticalPlan,
) -> dict[str, object]:
    (
        legacy_metric_id,
        category,
        direction,
        unit,
        domain,
    ) = _LEGACY_STATISTIC_SPECS[metric_id]
    spec = ComparisonSpec(
        comparison_id=(
            f"g237.{candidate_variant_id}.{split}."
            f"{cache_mode}.{metric_id}"
        ),
        metric_id=legacy_metric_id,
        category=category,
        direction=direction,
        unit=unit,
        kind=MetricKind.CONTINUOUS,
        estimator=Estimator.MEAN,
        baseline_variant_id="A0",
        candidate_variant_id=candidate_variant_id,
        domain=domain,
        stratum_dimension=StratumDimension.JOINT,
    )
    observations = []
    for baseline, candidate, pair in pair_sources:
        measured = pair["measured"] is True
        reasons = pair["missing_reasons"]
        reason = (
            None
            if measured
            else ";".join(str(item) for item in reasons) or "unpaired"
        )
        observations.append(
            PairedCaseObservation(
                # Explicit frozen compatibility joins used only to drive the
                # existing statistical primitive.  These SHA identities are
                # deliberately absent from the CID-native projection below.
                protocol_sha256=baseline.case_result.protocol_sha256,
                run_id=baseline.case_result.run_id,
                case_id=baseline.case_result.case_id,
                case_manifest_sha256=(
                    baseline.case_result.case_manifest_sha256
                ),
                split=Split(split),
                cache_mode=CacheMode(cache_mode),
                stratum=(
                    "stratum-"
                    + str(pair["stratum_cid"])[:32]
                ),
                baseline_variant_id="A0",
                candidate_variant_id=candidate_variant_id,
                baseline_result_sha256=baseline.case_result.digest,
                candidate_result_sha256=candidate.case_result.digest,
                baseline_value=(
                    float(pair["baseline_value"])
                    if measured
                    else None
                ),
                candidate_value=(
                    float(pair["candidate_value"])
                    if measured
                    else None
                ),
                missing_kind=(
                    None
                    if measured
                    else MissingKind.INFRASTRUCTURE_FAILURE
                ),
                missing_reason=reason,
            )
        )
    analysis = analyze_paired(spec, observations, plan=plan)
    spec_body = _plain(spec.to_dict())
    plan_body = _plain(plan.to_dict())
    body = {
        "schema": PAIRED_COST_ANALYSIS_SCHEMA_V2,
        "statistical_plan_cid": cid_for_dag_json(plan_body),
        "comparison_spec_cid": cid_for_dag_json(spec_body),
        "metric_id": metric_id,
        "legacy_frozen_metric_id": legacy_metric_id,
        "baseline_variant_id": "A0",
        "candidate_variant_id": candidate_variant_id,
        "split": split,
        "cache_mode": cache_mode,
        "scheduled_pair_count": analysis.scheduled_count,
        "measured_pair_count": analysis.measured_count,
        "missing_pair_count": analysis.missing_count,
        "summary": _plain(analysis.summary),
        "strata": _plain(analysis.strata),
        "missingness": _plain(analysis.missingness),
        "pair_cids": [
            str(pair["pair_cid"])
            for _, _, pair in pair_sources
        ],
        "statistical_primitive": (
            "statistics.analyze_paired:"
            "paired_stratified_percentile"
        ),
        "source_recomputed": True,
        "missing_is_never_zero": True,
    }
    return {**body, "analysis_cid": cid_for_dag_json(body)}


def _cost_aggregate(
    variant_id: str,
    rows: Sequence[
        tuple[
            CausalRuntimeEvidenceV2,
            IndependentResourceReceiptV2 | None,
        ]
    ],
) -> dict[str, object]:
    metric_values: dict[str, int | float | None] = {}
    missing_reasons: dict[str, list[str]] = {}
    for metric in _COST_METRICS:
        values: list[int | float] = []
        reasons: list[str] = []
        for evidence, receipt in rows:
            aggregate, aggregate_reasons, _ = (
                _aggregate_resource_receipt(receipt)
            )
            value = aggregate[metric]
            if value is None:
                reasons.extend(
                    f"{evidence.receipt_cid}:{reason}"
                    for reason in aggregate_reasons[metric]
                )
            else:
                values.append(value)
        if reasons or len(values) != len(rows):
            metric_values[metric] = None
            missing_reasons[metric] = sorted(reasons)
        elif metric == "peak_memory_bytes":
            metric_values[metric] = max(int(item) for item in values)
        else:
            metric_values[metric] = math.fsum(
                float(item) for item in values
            ) / len(values)
    body = {
        "schema": RESOURCE_COST_AGGREGATE_SCHEMA_V2,
        "variant_id": variant_id,
        "runtime_receipt_cids": sorted(
            evidence.receipt_cid for evidence, _ in rows
        ),
        "resource_receipt_cids": sorted(
            receipt.receipt_cid
            for _, receipt in rows
            if receipt is not None
        ),
        "scheduled_count": len(rows),
        "measured_count": sum(receipt is not None for _, receipt in rows),
        "metrics": metric_values,
        "missing_reasons": missing_reasons,
        "aggregation": {
            "peak_memory_bytes": "maximum",
            **{
                metric: "arithmetic_mean"
                for metric in _COST_METRICS
                if metric != "peak_memory_bytes"
            },
        },
        "missing_is_never_zero": True,
    }
    return {**body, "aggregate_cid": cid_for_dag_json(body)}


def _efficacy_projection(
    gate: Mapping[str, object],
    candidates: Sequence[str],
) -> dict[str, object]:
    evidence = _mapping(gate["evidence"], "efficacy gate evidence")
    comparisons = evidence["comparisons"]
    if not isinstance(comparisons, (list, tuple)):
        raise ResourceStatisticsError(
            "efficacy comparisons must be an array"
        )
    records: list[dict[str, object]] = [
        {
            "variant_id": "A0",
            "paired_verified_delta_vs_a0": 0.0,
            "scheduled_pair_count": sum(
                int(_mapping(item, "comparison")["scheduled_pair_count"])
                for item in comparisons
            ) // max(1, len(candidates)),
            "measured_pair_count": sum(
                int(_mapping(item, "comparison")["measured_pair_count"])
                for item in comparisons
            ) // max(1, len(candidates)),
            "missing_reason": None,
            "comparison_cids": [],
        }
    ]
    for candidate in candidates:
        selected = [
            _mapping(item, "efficacy comparison")
            for item in comparisons
            if _mapping(item, "efficacy comparison").get(
                "candidate_variant_id"
            )
            == candidate
        ]
        scheduled = sum(
            int(item["scheduled_pair_count"]) for item in selected
        )
        measured = sum(
            int(item["measured_pair_count"]) for item in selected
        )
        net = sum(
            int(item["net_verified_gain_count"]) for item in selected
        )
        value = (
            net / scheduled
            if selected and scheduled and measured == scheduled
            else None
        )
        records.append(
            {
                "variant_id": candidate,
                "paired_verified_delta_vs_a0": value,
                "scheduled_pair_count": scheduled,
                "measured_pair_count": measured,
                "missing_reason": (
                    None
                    if value is not None
                    else "paired_efficacy_incomplete"
                ),
                "comparison_cids": sorted(
                    str(item["comparison_cid"])
                    for item in selected
                ),
            }
        )
    body = {
        "schema": RESOURCE_EFFICACY_PROJECTION_SCHEMA_V2,
        "upstream_efficacy_gate_cid": gate["receipt_cid"],
        "metric_id": "paired_verified_delta_vs_a0",
        "direction": MetricDirection.MAXIMIZE.value,
        "variants": records,
        "resource_receipt_cids_included": False,
        "source_recomputed": True,
    }
    return {**body, "projection_cid": cid_for_dag_json(body)}


def _validate_safety_gate_reference(
    value: object,
    expected_receipt_cid: str,
) -> tuple[str | None, bool | None, list[str]]:
    """Check a pinned, upstream-source-validated G236 receipt reference."""

    issues: list[str] = []
    try:
        expected = _cid(
            expected_receipt_cid,
            "expected_safety_gate_receipt_cid",
        )
        data = _mapping(value, "reviewed-control safety gate")
        if data.get("schema") != REVIEWED_CONTROL_SAFETY_GATE_SCHEMA_V2:
            issues.append("safety_gate_schema_mismatch")
        receipt_cid = _cid(data.get("receipt_cid"), "safety receipt_cid")
        body = {
            key: _plain(member)
            for key, member in data.items()
            if key != "receipt_cid"
        }
        if cid_for_dag_json(body) != receipt_cid:
            issues.append("safety_gate_cid_mismatch")
        if receipt_cid != expected:
            issues.append("safety_gate_rebased")
        complete = data.get("complete")
        passed = data.get("passed")
        fatal = data.get("fatal")
        status = data.get("status")
        holdout = data.get("holdout_included")
        if (
            not isinstance(complete, bool)
            or not isinstance(passed, bool)
            or not isinstance(fatal, bool)
            or status not in {"passed", "failed", "incomplete"}
            or holdout is not False
        ):
            issues.append("safety_gate_state_invalid")
            return receipt_cid, None, issues
        if status == "passed" and not (
            complete and passed and not fatal
        ):
            issues.append("safety_gate_state_invalid")
        if status == "failed" and not fatal:
            issues.append("safety_gate_state_invalid")
        if status == "incomplete" and complete:
            issues.append("safety_gate_state_invalid")
        feasible = (
            not issues
            and complete
            and passed
            and not fatal
            and status == "passed"
        )
        return receipt_cid, feasible, issues
    except (ResourceStatisticsError, KeyError, TypeError, ValueError):
        return None, None, ["safety_gate_reference_invalid"]


def _dominates(
    left: Mapping[str, object],
    right: Mapping[str, object],
    objectives: Sequence[Mapping[str, str]],
) -> bool:
    no_worse = True
    strictly_better = False
    left_metrics = _mapping(left["metrics"], "left metrics")
    right_metrics = _mapping(right["metrics"], "right metrics")
    for objective in objectives:
        metric_id = objective["metric_id"]
        left_value = left_metrics[metric_id]
        right_value = right_metrics[metric_id]
        if left_value is None or right_value is None:
            return False
        left_number = float(left_value)
        right_number = float(right_value)
        if objective["direction"] == MetricDirection.MAXIMIZE.value:
            no_worse &= left_number >= right_number
            strictly_better |= left_number > right_number
        else:
            no_worse &= left_number <= right_number
            strictly_better |= left_number < right_number
    return no_worse and strictly_better


def _pareto_frontier(
    *,
    efficacy: Mapping[str, object],
    costs: Sequence[Mapping[str, object]],
    analyses: Sequence[Mapping[str, object]],
    safety_gate_cid: str | None,
    safety_feasible: bool | None,
) -> dict[str, object]:
    objectives = [
        {
            "metric_id": "paired_verified_delta_vs_a0",
            "direction": MetricDirection.MAXIMIZE.value,
            "evidence_domain": "efficacy",
        },
        *[
            {
                "metric_id": metric,
                "direction": MetricDirection.MINIMIZE.value,
                "evidence_domain": "cost",
            }
            for metric in _COST_METRICS
        ],
    ]
    efficacy_by_variant = {
        str(_mapping(item, "efficacy record")["variant_id"]): _mapping(
            item, "efficacy record"
        )
        for item in efficacy["variants"]  # type: ignore[union-attr]
    }
    cost_by_variant = {
        str(item["variant_id"]): item for item in costs
    }
    records: list[dict[str, object]] = []
    for variant_id in sorted(cost_by_variant):
        cost = cost_by_variant[variant_id]
        efficacy_record = efficacy_by_variant[variant_id]
        metrics = {
            "paired_verified_delta_vs_a0": efficacy_record[
                "paired_verified_delta_vs_a0"
            ],
            **dict(_mapping(cost["metrics"], "cost metrics")),
        }
        missing = sorted(
            metric
            for metric, value in metrics.items()
            if value is None
        )
        safe = safety_feasible is True
        eligible = safe and not missing
        reason = (
            None
            if eligible
            else (
                "safety_gate_not_feasible"
                if not safe
                else "missing_objectives:" + ",".join(missing)
            )
        )
        records.append(
            {
                "variant_id": variant_id,
                "metrics": metrics,
                "safety_feasible": safe,
                "eligible": eligible,
                "ineligible_reason": reason,
                "cost_aggregate_cid": cost["aggregate_cid"],
                "efficacy_projection_cid": efficacy["projection_cid"],
                "paired_analysis_cids": sorted(
                    str(item["analysis_cid"])
                    for item in analyses
                    if item["candidate_variant_id"] == variant_id
                ),
                "safety_gate_receipt_cid": safety_gate_cid,
                "dominated_by": [],
                "on_frontier": False,
            }
        )
    active = tuple(
        {
            "metric_id": str(item["metric_id"]),
            "direction": str(item["direction"]),
        }
        for item in objectives
    )
    frontier: list[str] = []
    for record in records:
        if not record["eligible"]:
            continue
        dominators = sorted(
            str(other["variant_id"])
            for other in records
            if (
                other["variant_id"] != record["variant_id"]
                and other["eligible"]
                and _dominates(other, record, active)
            )
        )
        record["dominated_by"] = dominators
        record["on_frontier"] = not dominators
        if not dominators:
            frontier.append(str(record["variant_id"]))
    body = {
        "schema": RESOURCE_PARETO_FRONTIER_SCHEMA_V2,
        "objectives": objectives,
        "candidates": records,
        "frontier_variant_ids": sorted(frontier),
        "dominance_rule": (
            "no worse on every direction-aware objective and strictly "
            "better on at least one"
        ),
        "safety_policy": (
            "reviewed-control safety is a hard feasibility constraint "
            "and is never scalarized"
        ),
        "efficacy_and_cost_separate": True,
        "source_recomputed": True,
    }
    return {**body, "pareto_cid": cid_for_dag_json(body)}


def build_resource_statistics_gate_v2(
    matrix: G210RuntimeReceiptMatrixV2,
    candidate_variant_ids: Sequence[str],
    resource_receipts: Sequence[IndependentResourceReceiptV2],
    efficacy_gate: object,
    safety_gate: object,
    *,
    expected_resource_evidence_set_cid: str,
    expected_safety_gate_receipt_cid: str,
    statistical_plan: StatisticalPlan = StatisticalPlan(),
) -> Mapping[str, object]:
    """Source-recompute the bounded G237 cost/statistics/Pareto gate."""

    if not isinstance(matrix, G210RuntimeReceiptMatrixV2):
        raise ResourceStatisticsError(
            "G237 requires a G210RuntimeReceiptMatrixV2"
        )
    candidates = _candidate_ids(candidate_variant_ids)
    if not isinstance(statistical_plan, StatisticalPlan):
        raise ResourceStatisticsError(
            "statistical_plan must be StatisticalPlan"
        )
    plan = StatisticalPlan.from_dict(statistical_plan.to_dict())
    selected_variants = {"A0", *candidates}
    try:
        evidence = tuple(
            validate_causal_runtime_evidence_v2(item.to_dict())
            for item in matrix.runtime_evidence
            if item.case_result.variant_id in selected_variants
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise ResourceStatisticsError(
            "selected full-runtime evidence failed replay"
        ) from exc
    source_runtime_matrix_cid = matrix.runtime_matrix_cid
    evidence_by_cid = {item.receipt_cid: item for item in evidence}
    issues: set[str] = set()
    if not matrix.complete:
        issues.add("source_runtime_matrix_incomplete")
    if any(
        item.case_result.split not in {
            Split.PILOT,
            Split.DEVELOPMENT,
        }
        for item in evidence
    ):
        issues.add("holdout_runtime_forbidden")
    coordinates = [_runtime_key(item) for item in evidence]
    if (
        len(coordinates) != len(set(coordinates))
        or len(evidence_by_cid) != len(evidence)
    ):
        issues.add("duplicate_runtime_evidence")

    replayed_receipts: list[IndependentResourceReceiptV2] = []
    for value in resource_receipts:
        if not isinstance(value, IndependentResourceReceiptV2):
            issues.add("resource_receipt_not_typed")
            continue
        try:
            replayed_receipts.append(
                validate_independent_resource_receipt_v2(value)
            )
        except (ResourceStatisticsError, TypeError, ValueError, KeyError):
            issues.add("resource_receipt_failed_replay")
    receipt_cids = [item.receipt_cid for item in replayed_receipts]
    if len(receipt_cids) != len(set(receipt_cids)):
        issues.add("duplicate_resource_receipt")
    by_runtime: dict[str, list[IndependentResourceReceiptV2]] = {}
    for receipt in replayed_receipts:
        by_runtime.setdefault(
            receipt.runtime_evidence_cid, []
        ).append(receipt)
        source = evidence_by_cid.get(receipt.runtime_evidence_cid)
        if source is None:
            issues.add("resource_receipt_unexpected_runtime")
            continue
        expected_coordinate = _runtime_coordinate_payload(source)
        if (
            receipt.source_cid
            != source.compiler_exposure.source_cid
            or receipt.environment_identity_cid
            != _runtime_environment_identity_cid(source)
            or receipt.run_identity_cid
            != _runtime_run_identity_cid(source)
            or receipt.coordinate_cid
            != cid_for_dag_json(expected_coordinate)
        ):
            issues.add("resource_receipt_stale_binding")
    if any(len(values) != 1 for values in by_runtime.values()):
        issues.add("duplicate_resource_runtime_binding")
    missing_runtime_cids = sorted(
        set(evidence_by_cid) - set(by_runtime)
    )
    if missing_runtime_cids:
        issues.add("resource_receipt_population_incomplete")
    unexpected_runtime_cids = sorted(
        set(by_runtime) - set(evidence_by_cid)
    )
    if unexpected_runtime_cids:
        issues.add("resource_receipt_population_rebased")
    receipt_by_runtime = {
        runtime_cid: values[0]
        for runtime_cid, values in by_runtime.items()
        if len(values) == 1 and runtime_cid in evidence_by_cid
    }
    null_resource_receipt_cids = sorted(
        receipt.receipt_cid
        for receipt in replayed_receipts
        if not receipt.complete
    )
    unsafe_lifecycle_receipt_cids = sorted(
        receipt.receipt_cid
        for receipt in replayed_receipts
        if receipt.complete and not receipt.lifecycle_safe
    )
    if null_resource_receipt_cids:
        issues.add("resource_measurement_incomplete")
    if unsafe_lifecycle_receipt_cids:
        issues.add("resource_release_or_reap_failed")

    observed_resource_set_cid = _resource_evidence_set_cid_from_replayed(
        source_runtime_matrix_cid,
        candidates,
        tuple(replayed_receipts),
    )
    expected_resource_set = _cid(
        expected_resource_evidence_set_cid,
        "expected_resource_evidence_set_cid",
    )
    if observed_resource_set_cid != expected_resource_set:
        issues.add("resource_evidence_set_rebased")

    try:
        validated_efficacy = validate_g234_efficacy_gate_v2(
            efficacy_gate, matrix
        )
    except (
        RevisedPilotAuthorizationError,
        TypeError,
        ValueError,
        KeyError,
    ):
        validated_efficacy = None
        issues.add("efficacy_gate_failed_source_replay")
    if validated_efficacy is not None:
        if tuple(validated_efficacy["candidate_variant_ids"]) != candidates:
            issues.add("efficacy_candidate_set_mismatch")
        if (
            validated_efficacy["complete"] is not True
            or validated_efficacy["passed"] is not True
            or validated_efficacy["status"] != "passed"
        ):
            issues.add("efficacy_gate_incomplete")

    safety_gate_cid, safety_feasible, safety_issues = (
        _validate_safety_gate_reference(
            safety_gate,
            expected_safety_gate_receipt_cid,
        )
    )
    issues.update(safety_issues)
    if safety_feasible is None:
        issues.add("safety_gate_incomplete")
    elif not safety_feasible:
        safety_data = (
            _mapping(safety_gate, "safety gate")
            if isinstance(safety_gate, Mapping)
            else {}
        )
        if safety_data.get("status") == "failed":
            issues.add("reviewed_control_safety_failed")
        else:
            issues.add("safety_gate_incomplete")

    runtime_by_key = {_runtime_key(item): item for item in evidence}
    pair_sources: list[
        tuple[
            CausalRuntimeEvidenceV2,
            CausalRuntimeEvidenceV2,
            dict[str, object],
        ]
    ] = []
    for candidate_id in candidates:
        candidate_rows = sorted(
            (
                item for item in evidence
                if item.case_result.variant_id == candidate_id
            ),
            key=_runtime_key,
        )
        for candidate in candidate_rows:
            split, cache_mode, case_id = _pair_key(candidate)
            baseline = runtime_by_key.get(
                (split, cache_mode, case_id, "A0")
            )
            if baseline is None:
                issues.add("paired_cost_baseline_missing")
                continue
            for metric in _COST_METRICS:
                pair_sources.append(
                    (
                        baseline,
                        candidate,
                        _paired_cost_observation(
                            source_runtime_matrix_cid=(
                                source_runtime_matrix_cid
                            ),
                            baseline=baseline,
                            candidate=candidate,
                            baseline_receipt=receipt_by_runtime.get(
                                baseline.receipt_cid
                            ),
                            candidate_receipt=receipt_by_runtime.get(
                                candidate.receipt_cid
                            ),
                            metric_id=metric,
                        ),
                    )
                )
    expected_pairs = (
        len(candidates)
        * sum(
            len(manifest.cases)
            for manifest in matrix.receipt_matrix.rescue_manifests
        )
        * 2
        * len(_COST_METRICS)
    )
    if len(pair_sources) != expected_pairs:
        issues.add("paired_cost_population_incomplete")
    if any(pair["identity_valid"] is not True for _, _, pair in pair_sources):
        issues.add("paired_cost_identity_mismatch")
    if any(pair["measured"] is not True for _, _, pair in pair_sources):
        issues.add("paired_cost_measurement_incomplete")

    analyses: list[dict[str, object]] = []
    for candidate_id in candidates:
        for split in (Split.PILOT.value, Split.DEVELOPMENT.value):
            for cache_mode in (
                CacheMode.COLD.value,
                CacheMode.WARM.value,
            ):
                for metric in _STATISTIC_METRICS:
                    selected_pairs = [
                        (baseline, candidate, pair)
                        for baseline, candidate, pair in pair_sources
                        if (
                            candidate.case_result.variant_id
                            == candidate_id
                            and candidate.case_result.split.value == split
                            and candidate.case_result.cache_mode.value
                            == cache_mode
                            and pair["metric_id"] == metric
                        )
                    ]
                    if not selected_pairs:
                        issues.add("paired_statistics_population_incomplete")
                        continue
                    analyses.append(
                        _paired_cost_analysis(
                            candidate_variant_id=candidate_id,
                            split=split,
                            cache_mode=cache_mode,
                            metric_id=metric,
                            pair_sources=selected_pairs,
                            plan=plan,
                        )
                    )
    if any(
        item["missing_pair_count"] != 0 for item in analyses
    ):
        issues.add("paired_statistics_unpaired")

    rows_by_variant = {
        variant_id: [
            (
                item,
                receipt_by_runtime.get(item.receipt_cid),
            )
            for item in evidence
            if item.case_result.variant_id == variant_id
        ]
        for variant_id in ("A0", *candidates)
    }
    costs = [
        _cost_aggregate(variant_id, rows_by_variant[variant_id])
        for variant_id in ("A0", *candidates)
    ]
    if any(
        value is None
        for item in costs
        for value in _mapping(item["metrics"], "cost metrics").values()
    ):
        issues.add("cost_aggregate_incomplete")

    efficacy = (
        _efficacy_projection(validated_efficacy, candidates)
        if validated_efficacy is not None
        else {
            "schema": RESOURCE_EFFICACY_PROJECTION_SCHEMA_V2,
            "upstream_efficacy_gate_cid": None,
            "metric_id": "paired_verified_delta_vs_a0",
            "direction": MetricDirection.MAXIMIZE.value,
            "variants": [
                {
                    "variant_id": variant_id,
                    "paired_verified_delta_vs_a0": None,
                    "scheduled_pair_count": 0,
                    "measured_pair_count": 0,
                    "missing_reason": "efficacy_gate_failed_source_replay",
                    "comparison_cids": [],
                }
                for variant_id in ("A0", *candidates)
            ],
            "resource_receipt_cids_included": False,
            "source_recomputed": False,
        }
    )
    if "projection_cid" not in efficacy:
        efficacy = {
            **efficacy,
            "projection_cid": cid_for_dag_json(efficacy),
        }
    pareto = _pareto_frontier(
        efficacy=efficacy,
        costs=costs,
        analyses=analyses,
        safety_gate_cid=safety_gate_cid,
        safety_feasible=safety_feasible,
    )
    if (
        safety_feasible is True
        and not pareto["frontier_variant_ids"]
    ):
        issues.add("pareto_frontier_incomplete")

    incomplete_codes = {
        code for code in issues
        if code not in {
            "resource_release_or_reap_failed",
            "reviewed_control_safety_failed",
        }
    }
    failed = bool(
        issues.intersection(
            {
                "resource_release_or_reap_failed",
                "reviewed_control_safety_failed",
            }
        )
    )
    complete = not incomplete_codes
    passed = complete and not failed
    status = (
        "incomplete"
        if incomplete_codes
        else ("failed" if failed else "passed")
    )
    plan_body = _plain(plan.to_dict())
    body = {
        "schema": RESOURCE_STATISTICS_GATE_SCHEMA_V2,
        "source_runtime_matrix_cid": source_runtime_matrix_cid,
        "candidate_variant_ids": list(candidates),
        "runtime_evidence_cids": sorted(evidence_by_cid),
        "resource_measurement_policy_cid": (
            RESOURCE_MEASUREMENT_POLICY_V2_CID
        ),
        "expected_resource_evidence_set_cid": expected_resource_set,
        "observed_resource_evidence_set_cid": (
            observed_resource_set_cid
        ),
        "resource_receipt_cids": sorted(receipt_cids),
        "missing_runtime_evidence_cids": missing_runtime_cids,
        "unexpected_runtime_evidence_cids": unexpected_runtime_cids,
        "null_resource_receipt_cids": null_resource_receipt_cids,
        "unsafe_lifecycle_resource_receipt_cids": (
            unsafe_lifecycle_receipt_cids
        ),
        "upstream_efficacy_gate_cid": (
            None
            if validated_efficacy is None
            else validated_efficacy["receipt_cid"]
        ),
        "expected_safety_gate_receipt_cid": (
            _cid(
                expected_safety_gate_receipt_cid,
                "expected_safety_gate_receipt_cid",
            )
        ),
        "observed_safety_gate_receipt_cid": safety_gate_cid,
        "statistical_plan": plan_body,
        "statistical_plan_cid": cid_for_dag_json(plan_body),
        "paired_cost_observations": [
            pair for _, _, pair in pair_sources
        ],
        "paired_cost_analyses": analyses,
        "cost_evidence": costs,
        "efficacy_evidence": efficacy,
        "pareto_evidence": pareto,
        "efficacy_and_cost_separate": True,
        "missing_is_never_zero": True,
        "source_recomputed": True,
        "failure_codes": sorted(issues),
        "complete": complete,
        "passed": passed,
        "status": status,
        "holdout_included": False,
    }
    result = {**body, "receipt_cid": cid_for_dag_json(body)}
    frozen = _freeze(result)
    assert isinstance(frozen, Mapping)
    return frozen


def validate_resource_statistics_gate_v2(
    value: object,
    matrix: G210RuntimeReceiptMatrixV2,
    resource_receipts: Sequence[IndependentResourceReceiptV2],
    efficacy_gate: object,
    safety_gate: object,
    *,
    expected_resource_evidence_set_cid: str,
    expected_safety_gate_receipt_cid: str,
    statistical_plan: StatisticalPlan = StatisticalPlan(),
) -> Mapping[str, object]:
    """Rebuild every G237 pair, statistic, aggregate, frontier, and CID."""

    data = _mapping(value, "resource statistics gate")
    rebuilt = build_resource_statistics_gate_v2(
        matrix,
        tuple(str(item) for item in _array(
            _plain(data.get("candidate_variant_ids")),
            "candidate_variant_ids",
        )),
        resource_receipts,
        efficacy_gate,
        safety_gate,
        expected_resource_evidence_set_cid=(
            expected_resource_evidence_set_cid
        ),
        expected_safety_gate_receipt_cid=(
            expected_safety_gate_receipt_cid
        ),
        statistical_plan=statistical_plan,
    )
    if _plain(data) != _plain(rebuilt):
        raise ResourceStatisticsError(
            "resource/statistics/Pareto gate did not source-recompute"
        )
    body = {
        key: _plain(member)
        for key, member in data.items()
        if key != "receipt_cid"
    }
    if data.get("receipt_cid") != cid_for_dag_json(body):
        raise ResourceStatisticsError(
            "resource/statistics/Pareto gate receipt CID changed"
        )
    return rebuilt


__all__ = [
    "HSSLEV2374E49",
    "INDEPENDENT_COMPONENT_RESOURCE_SCHEMA_V2",
    "INDEPENDENT_RESOURCE_RECEIPT_SCHEMA_V2",
    "IndependentComponentResourceV2",
    "IndependentResourceReceiptV2",
    "PAIRED_COST_ANALYSIS_SCHEMA_V2",
    "PAIRED_COST_OBSERVATION_SCHEMA_V2",
    "RESOURCE_COORDINATE_SCHEMA_V2",
    "RESOURCE_COST_AGGREGATE_SCHEMA_V2",
    "RESOURCE_EFFICACY_PROJECTION_SCHEMA_V2",
    "RESOURCE_ENVIRONMENT_COMPATIBILITY_SCHEMA_V2",
    "RESOURCE_EVIDENCE_SET_SCHEMA_V2",
    "RESOURCE_MEASUREMENT_POLICY_SCHEMA_V2",
    "RESOURCE_MEASUREMENT_POLICY_V2_CID",
    "RESOURCE_PARETO_FRONTIER_SCHEMA_V2",
    "RESOURCE_REPLAY_COMPARISON_POLICY_SCHEMA_V2",
    "RESOURCE_REPLAY_COMPARISON_POLICY_V2_CID",
    "RESOURCE_REPLAY_COMPARISON_SCHEMA_V2",
    "RESOURCE_REPLAY_COORDINATE_SCHEMA_V2",
    "RESOURCE_REPLAY_IDENTITY_SCHEMA_V2",
    "RESOURCE_REPLAY_MEASUREMENT_SCHEMA_V2",
    "RESOURCE_RUN_IDENTITY_SCHEMA_V2",
    "RESOURCE_STATISTICS_GATE_SCHEMA_V2",
    "RESOURCE_STRATUM_SCHEMA_V2",
    "ResourceStatisticsError",
    "build_independent_resource_receipt_v2",
    "build_resource_statistics_gate_v2",
    "compare_resource_replay_measurements_v2",
    "resource_evidence_set_cid_v2",
    "resource_measurement_policy_v2",
    "resource_replay_comparison_policy_v2",
    "runtime_resource_coordinate_cid_v2",
    "runtime_resource_replay_coordinate_cid_v2",
    "validate_independent_resource_receipt_v2",
    "validate_resource_replay_comparison_v2",
    "validate_resource_statistics_gate_v2",
]
