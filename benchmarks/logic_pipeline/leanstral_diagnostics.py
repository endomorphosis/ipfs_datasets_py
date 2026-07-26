"""Source-recomputed Leanstral reliability diagnostics.

The frozen matrix-v1 wire contract intentionally retains its historical,
collapsed Leanstral ``FailureCode``.  This additive projection recovers the
exact, already-recorded safe failure class and generation phase without
changing that contract or serializing prompts, responses, case identifiers,
or source text.

The returned receipt contains only aggregate counters, bounded aggregate
failure wall time, and one CID that binds the complete validated source-result
set.  Validation always recomputes the projection from those sources.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
import re
from typing import Final, Mapping, Sequence

from .adapters import LEANSTRAL_GENERATION_FAILURE_SCHEMA
from .content_addressing import cid_for_dag_json, validate_cid
from .contracts import (
    CaseResultRecord,
    FailureCode,
    StageName,
    StageRecord,
    StageStatus,
    canonical_json,
)


LEANSTRAL_DIAGNOSTIC_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "leanstral-diagnostic-projection.v1"
)
LEANSTRAL_DIAGNOSTIC_SOURCE_SET_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "leanstral-diagnostic-source-set.v1"
)
LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES: Final = (
    "inadmissible_proposal",
    "length_exhausted",
    "malformed_request",
    "malformed_response",
    "provider_error",
    "resource_exhausted",
    "timed_out",
    "unavailable",
)
LEANSTRAL_DIAGNOSTIC_FAILURE_PHASES: Final = (
    "completion_pre_dispatch",
    "completion_request",
    "completion_response",
    "model_registry",
    "proposal_validation",
    "provider",
    "request_validation",
)
LEANSTRAL_DIAGNOSTIC_MAX_SOURCE_RESULTS: Final = 100_000
LEANSTRAL_DIAGNOSTIC_MAX_STAGE_WALL_TIME_MS: Final = 86_400_000.0

_DIGEST = re.compile(r"[0-9a-f]{64}")
_PROJECTION_FIELDS: Final = frozenset(
    {
        "schema",
        "source_recomputed",
        "source_result_count",
        "source_results_cid",
        "invocation_count",
        "success_count",
        "failure_count",
        "recovered_failure_count",
        "terminal_failure_count",
        "safe_failure_class_counts",
        "failure_phase_counts",
        "wall_time_ms_by_safe_failure_class",
        "receipt_cid",
    }
)


class LeanstralDiagnosticError(ValueError):
    """Raised when source evidence or a diagnostic receipt is inconsistent."""


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise LeanstralDiagnosticError(f"{field} must be an object")
    return value


def _exact_fields(
    value: Mapping[str, object],
    expected: set[str] | frozenset[str],
    field: str,
) -> None:
    if set(value) != set(expected):
        raise LeanstralDiagnosticError(
            f"{field} fields changed: "
            f"missing={sorted(set(expected) - set(value))}, "
            f"extra={sorted(set(value) - set(expected))}"
        )


def _count(value: object, field: str, *, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= maximum
    ):
        raise LeanstralDiagnosticError(
            f"{field} must be an integer from 0 to {maximum}"
        )
    return value


def _fixed_count_map(
    value: object,
    keys: Sequence[str],
    field: str,
    *,
    maximum: int,
) -> dict[str, int]:
    data = _mapping(value, field)
    _exact_fields(data, set(keys), field)
    return {
        key: _count(data[key], f"{field}.{key}", maximum=maximum)
        for key in keys
    }


def _fixed_wall_time_map(
    value: object,
    *,
    class_counts: Mapping[str, int],
    maximum_source_results: int,
) -> dict[str, float]:
    field = "wall_time_ms_by_safe_failure_class"
    data = _mapping(value, field)
    _exact_fields(
        data,
        set(LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES),
        field,
    )
    maximum_total = (
        maximum_source_results
        * LEANSTRAL_DIAGNOSTIC_MAX_STAGE_WALL_TIME_MS
    )
    normalized: dict[str, float] = {}
    for safe_class in LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES:
        raw = data[safe_class]
        if (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or not math.isfinite(float(raw))
            or not 0.0 <= float(raw) <= maximum_total
        ):
            raise LeanstralDiagnosticError(
                f"{field}.{safe_class} is outside the aggregate bound"
            )
        measured = float(raw)
        if class_counts[safe_class] == 0 and measured != 0.0:
            raise LeanstralDiagnosticError(
                f"{field}.{safe_class} has time without a failure"
            )
        if (
            measured
            > class_counts[safe_class]
            * LEANSTRAL_DIAGNOSTIC_MAX_STAGE_WALL_TIME_MS
        ):
            raise LeanstralDiagnosticError(
                f"{field}.{safe_class} exceeds its per-stage bound"
            )
        normalized[safe_class] = measured
    return normalized


def _result_cid(result: CaseResultRecord) -> str:
    # Normalize enum- and tuple-bearing wire values to the strict IPLD JSON
    # data model before content addressing them.
    normalized = json.loads(canonical_json(result.to_dict()))
    return cid_for_dag_json(normalized)


def _validated_sources(
    sources: Sequence[CaseResultRecord],
) -> tuple[tuple[str, CaseResultRecord], ...]:
    if isinstance(sources, (str, bytes, bytearray)) or not isinstance(
        sources, Sequence
    ):
        raise LeanstralDiagnosticError(
            "sources must be a bounded sequence of CaseResultRecord values"
        )
    if not 0 < len(sources) <= LEANSTRAL_DIAGNOSTIC_MAX_SOURCE_RESULTS:
        raise LeanstralDiagnosticError(
            "sources must be nonempty and within the diagnostic result bound"
        )

    restored: list[tuple[str, CaseResultRecord]] = []
    source_identities: set[tuple[str, str, str]] = set()
    environments: set[str | None] = set()
    for source in sources:
        if not isinstance(source, CaseResultRecord):
            raise LeanstralDiagnosticError(
                "sources must contain CaseResultRecord values"
            )
        try:
            validated = CaseResultRecord.from_dict(source.to_dict())
        except (TypeError, ValueError) as exc:
            raise LeanstralDiagnosticError(
                "source result did not survive strict wire validation"
            ) from exc
        if validated != source:
            raise LeanstralDiagnosticError(
                "source result changed during strict wire validation"
            )
        source_identities.add(
            (
                source.protocol_sha256,
                source.run_id,
                source.case_manifest_sha256,
            )
        )
        environments.update(
            stage.provenance.environment_sha256 for stage in source.stages
        )
        restored.append((_result_cid(source), source))

    if len(source_identities) != 1:
        raise LeanstralDiagnosticError(
            "source results do not share one protocol/run/manifest identity"
        )
    if None in environments or len(environments) != 1:
        raise LeanstralDiagnosticError(
            "source results do not share one explicit environment identity"
        )
    cids = [cid for cid, _source in restored]
    if len(set(cids)) != len(cids):
        raise LeanstralDiagnosticError(
            "source results contain duplicate content identities"
        )
    return tuple(sorted(restored, key=lambda item: item[0]))


def _failure_class_and_phase(stage: StageRecord) -> tuple[str, str]:
    data = _mapping(stage.data, "Leanstral failure data")
    _exact_fields(
        data,
        {
            "schema",
            "safe_failure_class",
            "request_input_sha256",
            "generation_failure_boundary",
        },
        "Leanstral failure data",
    )
    safe_class = data["safe_failure_class"]
    if safe_class not in LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES:
        raise LeanstralDiagnosticError(
            "Leanstral failure class is not allow-listed"
        )
    if data["schema"] != LEANSTRAL_GENERATION_FAILURE_SCHEMA:
        raise LeanstralDiagnosticError(
            "Leanstral failure data uses the wrong schema"
        )
    if data["request_input_sha256"] != stage.provenance.input_sha256:
        raise LeanstralDiagnosticError(
            "Leanstral failure input identity changed"
        )

    boundary = _mapping(
        data["generation_failure_boundary"],
        "Leanstral failure boundary",
    )
    required_boundary_fields = {
        "schema",
        "safe_failure_class",
        "phase",
        "http_status",
        "request_payload_sha256",
        "receipt_sha256",
    }
    if not required_boundary_fields.issubset(boundary):
        raise LeanstralDiagnosticError(
            "Leanstral failure boundary is incomplete"
        )
    phase = boundary["phase"]
    if (
        boundary["schema"] != LEANSTRAL_GENERATION_FAILURE_SCHEMA
        or boundary["safe_failure_class"] != safe_class
        or phase not in LEANSTRAL_DIAGNOSTIC_FAILURE_PHASES
    ):
        raise LeanstralDiagnosticError(
            "Leanstral failure boundary class or phase changed"
        )
    http_status = boundary["http_status"]
    if (
        http_status is not None
        and (
            isinstance(http_status, bool)
            or not isinstance(http_status, int)
            or not 100 <= http_status <= 599
        )
    ):
        raise LeanstralDiagnosticError(
            "Leanstral failure HTTP status is invalid"
        )
    request_digest = boundary["request_payload_sha256"]
    if request_digest is not None and (
        not isinstance(request_digest, str)
        or _DIGEST.fullmatch(request_digest) is None
    ):
        raise LeanstralDiagnosticError(
            "Leanstral failure request digest is invalid"
        )
    receipt_digest = boundary["receipt_sha256"]
    boundary_body = {
        key: value for key, value in boundary.items() if key != "receipt_sha256"
    }
    expected_receipt_digest = hashlib.sha256(
        canonical_json(boundary_body).encode("utf-8")
    ).hexdigest()
    if (
        not isinstance(receipt_digest, str)
        or _DIGEST.fullmatch(receipt_digest) is None
        or receipt_digest != expected_receipt_digest
    ):
        raise LeanstralDiagnosticError(
            "Leanstral failure boundary content address changed"
        )

    identity = stage.provenance.effective_identity
    if (
        identity.get("leanstral_safe_failure_class") != safe_class
        or identity.get("leanstral_failure_boundary_sha256")
        != receipt_digest
    ):
        raise LeanstralDiagnosticError(
            "Leanstral failure provenance differs from its boundary"
        )
    if safe_class == "unavailable":
        expected_status = StageStatus.UNAVAILABLE
        expected_code = FailureCode.CAPABILITY_UNAVAILABLE
    else:
        expected_status = StageStatus.FAILED
        expected_code = (
            FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
        )
    if stage.status is not expected_status or stage.failure_code is not expected_code:
        raise LeanstralDiagnosticError(
            "Leanstral safe class differs from its legacy failure contract"
        )
    return str(safe_class), str(phase)


def _projection_body(
    sources: Sequence[CaseResultRecord],
) -> dict[str, object]:
    validated_sources = _validated_sources(sources)
    source_cids = [cid for cid, _source in validated_sources]
    source_results_cid = cid_for_dag_json(
        {
            "schema": LEANSTRAL_DIAGNOSTIC_SOURCE_SET_SCHEMA,
            "result_cids": source_cids,
        }
    )

    invocation_count = 0
    success_count = 0
    failure_count = 0
    recovered_failure_count = 0
    terminal_failure_count = 0
    class_counts: Counter[str] = Counter()
    phase_counts: Counter[str] = Counter()
    wall_times: defaultdict[str, list[float]] = defaultdict(list)

    for _source_cid, source in validated_sources:
        stage = next(
            (
                candidate
                for candidate in source.stages
                if candidate.stage is StageName.LEANSTRAL
            ),
            None,
        )
        if stage is None:
            continue
        graph_invoked = stage.provenance.effective_identity.get(
            "graph_invoked"
        )
        if type(graph_invoked) is not bool:
            raise LeanstralDiagnosticError(
                "Leanstral source omitted its graph invocation decision"
            )
        if not graph_invoked:
            if (
                stage.status is not StageStatus.SUCCESS
                or stage.failure_code is not None
            ):
                raise LeanstralDiagnosticError(
                    "suppressed Leanstral stage carries a failure"
                )
            continue

        invocation_count += 1
        if stage.status is StageStatus.SUCCESS:
            success_count += 1
            continue
        if stage.status not in {StageStatus.FAILED, StageStatus.UNAVAILABLE}:
            raise LeanstralDiagnosticError(
                "invoked Leanstral stage has an unsupported terminal status"
            )

        failure_count += 1
        safe_class, phase = _failure_class_and_phase(stage)
        class_counts[safe_class] += 1
        phase_counts[phase] += 1
        wall_times[safe_class].append(float(stage.telemetry.wall_time_ms))
        if stage in source.recovered_failures:
            recovered_failure_count += 1
        else:
            terminal_failure_count += 1

    return {
        "schema": LEANSTRAL_DIAGNOSTIC_SCHEMA,
        "source_recomputed": True,
        "source_result_count": len(validated_sources),
        "source_results_cid": source_results_cid,
        "invocation_count": invocation_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "recovered_failure_count": recovered_failure_count,
        "terminal_failure_count": terminal_failure_count,
        "safe_failure_class_counts": {
            safe_class: class_counts[safe_class]
            for safe_class in LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES
        },
        "failure_phase_counts": {
            phase: phase_counts[phase]
            for phase in LEANSTRAL_DIAGNOSTIC_FAILURE_PHASES
        },
        "wall_time_ms_by_safe_failure_class": {
            safe_class: round(math.fsum(wall_times[safe_class]), 6)
            for safe_class in LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES
        },
    }


def _validate_receipt_shape(value: object) -> dict[str, object]:
    data = _mapping(value, "Leanstral diagnostic projection")
    _exact_fields(data, _PROJECTION_FIELDS, "Leanstral diagnostic projection")
    if data["schema"] != LEANSTRAL_DIAGNOSTIC_SCHEMA:
        raise LeanstralDiagnosticError(
            "unsupported Leanstral diagnostic projection schema"
        )
    if data["source_recomputed"] is not True:
        raise LeanstralDiagnosticError(
            "Leanstral diagnostics must be source-recomputed"
        )
    source_result_count = _count(
        data["source_result_count"],
        "source_result_count",
        maximum=LEANSTRAL_DIAGNOSTIC_MAX_SOURCE_RESULTS,
    )
    if source_result_count == 0:
        raise LeanstralDiagnosticError(
            "Leanstral diagnostics require source results"
        )
    try:
        source_results_cid = validate_cid(
            data["source_results_cid"],
            codecs=("dag-json",),
        )
        receipt_cid = validate_cid(
            data["receipt_cid"],
            codecs=("dag-json",),
        )
    except (TypeError, ValueError) as exc:
        raise LeanstralDiagnosticError(
            "Leanstral diagnostic provenance CID is invalid"
        ) from exc

    invocation_count = _count(
        data["invocation_count"],
        "invocation_count",
        maximum=source_result_count,
    )
    success_count = _count(
        data["success_count"],
        "success_count",
        maximum=invocation_count,
    )
    failure_count = _count(
        data["failure_count"],
        "failure_count",
        maximum=invocation_count,
    )
    recovered_count = _count(
        data["recovered_failure_count"],
        "recovered_failure_count",
        maximum=failure_count,
    )
    terminal_count = _count(
        data["terminal_failure_count"],
        "terminal_failure_count",
        maximum=failure_count,
    )
    if success_count + failure_count != invocation_count:
        raise LeanstralDiagnosticError(
            "Leanstral success/failure totals do not cover invocations"
        )
    if recovered_count + terminal_count != failure_count:
        raise LeanstralDiagnosticError(
            "Leanstral recovered/terminal totals do not cover failures"
        )

    class_counts = _fixed_count_map(
        data["safe_failure_class_counts"],
        LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES,
        "safe_failure_class_counts",
        maximum=failure_count,
    )
    phase_counts = _fixed_count_map(
        data["failure_phase_counts"],
        LEANSTRAL_DIAGNOSTIC_FAILURE_PHASES,
        "failure_phase_counts",
        maximum=failure_count,
    )
    if sum(class_counts.values()) != failure_count:
        raise LeanstralDiagnosticError(
            "Leanstral failure classes do not cover failures"
        )
    if sum(phase_counts.values()) != failure_count:
        raise LeanstralDiagnosticError(
            "Leanstral failure phases do not cover failures"
        )
    wall_times = _fixed_wall_time_map(
        data["wall_time_ms_by_safe_failure_class"],
        class_counts=class_counts,
        maximum_source_results=source_result_count,
    )

    normalized: dict[str, object] = {
        "schema": LEANSTRAL_DIAGNOSTIC_SCHEMA,
        "source_recomputed": True,
        "source_result_count": source_result_count,
        "source_results_cid": source_results_cid,
        "invocation_count": invocation_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "recovered_failure_count": recovered_count,
        "terminal_failure_count": terminal_count,
        "safe_failure_class_counts": class_counts,
        "failure_phase_counts": phase_counts,
        "wall_time_ms_by_safe_failure_class": wall_times,
    }
    if receipt_cid != cid_for_dag_json(normalized):
        raise LeanstralDiagnosticError(
            "Leanstral diagnostic receipt content address changed"
        )
    return {**normalized, "receipt_cid": receipt_cid}


def build_leanstral_diagnostic_projection(
    sources: Sequence[CaseResultRecord],
) -> dict[str, object]:
    """Build one non-sensitive aggregate receipt from validated case results."""

    body = _projection_body(sources)
    receipt = {**body, "receipt_cid": cid_for_dag_json(body)}
    return _validate_receipt_shape(receipt)


def validate_leanstral_diagnostic_projection(
    value: object,
    sources: Sequence[CaseResultRecord],
) -> dict[str, object]:
    """Validate shape, content address, and exact source recomputation."""

    supplied = _validate_receipt_shape(value)
    expected = build_leanstral_diagnostic_projection(sources)
    if supplied != expected:
        raise LeanstralDiagnosticError(
            "Leanstral diagnostic projection differs from its source results"
        )
    return supplied


__all__ = [
    "LEANSTRAL_DIAGNOSTIC_FAILURE_PHASES",
    "LEANSTRAL_DIAGNOSTIC_MAX_SOURCE_RESULTS",
    "LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES",
    "LEANSTRAL_DIAGNOSTIC_SCHEMA",
    "LEANSTRAL_DIAGNOSTIC_SOURCE_SET_SCHEMA",
    "LeanstralDiagnosticError",
    "build_leanstral_diagnostic_projection",
    "validate_leanstral_diagnostic_projection",
]
