"""Disjoint evaluation-status taxonomy for semantic round-trip coordinates.

Interface: ``SemanticRoundTripEvaluationStatus@1``

Coordinates fall into exactly one of three statuses:

* ``not_measured`` — the arm was never fairly measured
  (``terminal_unsupported`` or ``preflight_blocked``);
* ``runtime_failed`` — execution was attempted and failed at the runtime or
  provider boundary (``retry_exhausted``, provider error);
* ``semantic_scored`` — terminal success with the defined selection gates
  evaluated on real artifacts.

Default leaderboard rankings and paired baseline comparisons admit only
``semantic_scored`` coordinates plus the preregistered deterministic baseline
arm.  Loss ``1.0`` on an unsupported guided arm therefore cannot masquerade
as a measured semantic defeat of the baseline.

Matrix launch is fail-closed: every scheduled arm must present the preflight
evidence its class requires (live model smoke for model-backed routes;
causal qualification for guided arms) before scored execution begins.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final

from benchmarks.semantic_roundtrip.contracts import (
    ComponentStatus,
    ContractError,
    FailureReason,
)

EVALUATION_STATUS_INTERFACE: Final = "SemanticRoundTripEvaluationStatus@1"
EVALUATION_STATUS_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-evaluation-status.v1"
)

DEFAULT_DETERMINISTIC_BASELINE_ARM_ID: Final = (
    "typed_deontic__no_guidance__no_repair__not_applicable__deterministic"
)

REPLACEMENT_2026_07_27_FAILURE_REASON_COUNTS: Final[Mapping[str, int]] = (
    MappingProxyType(
        {
            "post_schedule_capability_unavailable": 260,
            "retry_exhausted": 210,
        }
    )
)
REPLACEMENT_2026_07_27_SUCCESS_COUNT: Final = 200
REPLACEMENT_2026_07_27_SCHEDULED_COUNT: Final = 670
REPLACEMENT_2026_07_27_GUIDED_ARM_COUNT: Final = 12
REPLACEMENT_2026_07_27_GUIDED_COORDINATE_COUNT: Final = 260

TERMINAL_UNSUPPORTED: Final = "terminal_unsupported"
PREFLIGHT_BLOCKED: Final = "preflight_blocked"
QUALIFIED_CANDIDATE: Final = "qualified_candidate"
CAPABILITY_UNAVAILABLE: Final = "capability_unavailable"

PREFLIGHT_LIVE_SMOKE: Final = "live_smoke"
PREFLIGHT_CAUSAL_QUALIFICATION: Final = "causal_qualification"

GUIDANCE_GUIDED: Final = "guided"
GUIDANCE_NO_GUIDANCE: Final = "no_guidance"

MODEL_ROUTES_REQUIRING_LIVE_SMOKE: Final = frozenset({"direct", "symai"})
PROVIDER_ERROR_TOKENS: Final = frozenset(
    {
        "provider_error",
        "endpoint_error",
        "connection_error",
        "http_error",
        "service_unavailable",
        "provider_unavailable",
        "provider_timeout",
        "model_provider_error",
    }
)


class EvaluationStatus(str, Enum):
    """Top-level, mutually exclusive evaluation disposition."""

    NOT_MEASURED = "not_measured"
    RUNTIME_FAILED = "runtime_failed"
    SEMANTIC_SCORED = "semantic_scored"


class NotMeasuredReason(str, Enum):
    """Why a coordinate was never fairly measured."""

    TERMINAL_UNSUPPORTED = "terminal_unsupported"
    PREFLIGHT_BLOCKED = "preflight_blocked"


class RuntimeFailedReason(str, Enum):
    """Why a coordinate failed at the runtime / provider boundary."""

    RETRY_EXHAUSTED = "retry_exhausted"
    PROVIDER_ERROR = "provider_error"


class LaunchPreflightError(ValueError):
    """Raised when matrix launch preflight fails closed."""


@dataclass(frozen=True, slots=True)
class EvaluationStatusRecord:
    """Sealed classification for one coordinate or arm outcome."""

    status: EvaluationStatus
    reason: str
    detail: str | None = None
    arm_id: str | None = None
    coordinate_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, EvaluationStatus):
            raise ContractError("status must be an EvaluationStatus")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ContractError("reason must be a nonblank string")
        if self.detail is not None:
            if not isinstance(self.detail, str) or not self.detail.strip():
                raise ContractError(
                    "detail must be a nonblank string or None"
                )
        if self.arm_id is not None:
            if not isinstance(self.arm_id, str) or not self.arm_id.strip():
                raise ContractError("arm_id must be a nonblank string or None")
        if self.coordinate_key is not None:
            if (
                not isinstance(self.coordinate_key, str)
                or not self.coordinate_key.strip()
            ):
                raise ContractError(
                    "coordinate_key must be a nonblank string or None"
                )
        _assert_reason_matches_status(self.status, self.reason)

    @property
    def include_in_default_leaderboard(self) -> bool:
        """Whether this outcome may enter default semantic rankings."""
        return self.status is EvaluationStatus.SEMANTIC_SCORED

    @property
    def include_in_paired_baseline(self) -> bool:
        """Whether this outcome may enter default paired baseline deltas."""
        return self.status is EvaluationStatus.SEMANTIC_SCORED

    @property
    def loss_is_semantic(self) -> bool:
        """Whether a numeric loss is a fair semantic measurement."""
        return self.status is EvaluationStatus.SEMANTIC_SCORED

    def to_dict(self) -> dict[str, object]:
        return {
            "interface": EVALUATION_STATUS_INTERFACE,
            "schema_version": EVALUATION_STATUS_SCHEMA,
            "status": self.status.value,
            "reason": self.reason,
            "detail": self.detail,
            "arm_id": self.arm_id,
            "coordinate_key": self.coordinate_key,
            "include_in_default_leaderboard": (
                self.include_in_default_leaderboard
            ),
            "include_in_paired_baseline": self.include_in_paired_baseline,
            "loss_is_semantic": self.loss_is_semantic,
        }


def _assert_reason_matches_status(
    status: EvaluationStatus, reason: str
) -> None:
    if status is EvaluationStatus.NOT_MEASURED:
        allowed = {item.value for item in NotMeasuredReason}
        if reason not in allowed:
            raise ContractError(
                "not_measured reason must be one of "
                f"{sorted(allowed)}; got {reason!r}"
            )
        return
    if status is EvaluationStatus.RUNTIME_FAILED:
        allowed = {item.value for item in RuntimeFailedReason}
        if reason not in allowed:
            raise ContractError(
                "runtime_failed reason must be one of "
                f"{sorted(allowed)}; got {reason!r}"
            )
        return
    if status is EvaluationStatus.SEMANTIC_SCORED:
        if reason != "success":
            raise ContractError(
                "semantic_scored reason must be 'success'; got "
                f"{reason!r}"
            )
        return
    raise ContractError(f"unknown evaluation status: {status!r}")


def _normalize_token(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _failure_reason_token(
    failure_reason: object,
    *,
    failure: Mapping[str, object] | None = None,
) -> str | None:
    token = _normalize_token(failure_reason)
    if token is not None:
        return token
    if failure is None:
        return None
    for key in ("reason", "failure_reason", "code"):
        token = _normalize_token(failure.get(key))
        if token is not None:
            return token
    return None


def _qualification_status_token(qualification_status: object) -> str | None:
    return _normalize_token(qualification_status)


def _is_provider_error_token(token: str) -> bool:
    lowered = token.lower()
    if lowered in PROVIDER_ERROR_TOKENS:
        return True
    if lowered in {
        FailureReason.TIMEOUT.value,
        FailureReason.EXCEPTION.value,
    }:
        return True
    if "provider" in lowered and "error" in lowered:
        return True
    return False


def classify_evaluation_status(
    *,
    status: object = None,
    failure_reason: object = None,
    failure: Mapping[str, object] | None = None,
    qualification_status: object = None,
    qualification_reason: object = None,
    preflight_blocked: bool = False,
    arm_id: str | None = None,
    coordinate_key: str | None = None,
    detail: str | None = None,
) -> EvaluationStatusRecord:
    """Classify one coordinate or arm outcome into a disjoint status.

    Precedence (first match wins):

    1. explicit preflight block → ``not_measured`` / ``preflight_blocked``
    2. qualification ``terminal_unsupported`` → ``not_measured`` /
       ``terminal_unsupported``
    3. qualification or reason ``preflight_blocked`` → ``not_measured`` /
       ``preflight_blocked``
    4. failure ``post_schedule_capability_unavailable`` (historical guided /
       unsupported path) → ``not_measured`` / ``terminal_unsupported``
    5. failure ``retry_exhausted`` → ``runtime_failed`` / ``retry_exhausted``
    6. provider-boundary failure → ``runtime_failed`` / ``provider_error``
    7. terminal component success → ``semantic_scored`` / ``success``
    8. any other terminal failure → ``runtime_failed`` / ``provider_error``
       (conservative: do not invent a semantic score for an incomplete path)
    """
    qual = _qualification_status_token(qualification_status)
    qual_reason = _normalize_token(qualification_reason)
    reason_token = _failure_reason_token(failure_reason, failure=failure)
    component = _normalize_token(status)
    resolved_detail = detail
    if resolved_detail is None and failure is not None:
        resolved_detail = _normalize_token(failure.get("detail"))
    if resolved_detail is None:
        resolved_detail = qual_reason

    if component in {ComponentStatus.SUCCESS.value, "success"}:
        if reason_token is not None:
            raise ContractError(
                "success status cannot carry a failure_reason ("
                f"{reason_token!r})"
            )

    if (
        preflight_blocked
        or qual == PREFLIGHT_BLOCKED
        or qual_reason == PREFLIGHT_BLOCKED
    ):
        return EvaluationStatusRecord(
            status=EvaluationStatus.NOT_MEASURED,
            reason=NotMeasuredReason.PREFLIGHT_BLOCKED.value,
            detail=resolved_detail or "required preflight missing",
            arm_id=arm_id,
            coordinate_key=coordinate_key,
        )

    if qual == TERMINAL_UNSUPPORTED or qual_reason == TERMINAL_UNSUPPORTED:
        return EvaluationStatusRecord(
            status=EvaluationStatus.NOT_MEASURED,
            reason=NotMeasuredReason.TERMINAL_UNSUPPORTED.value,
            detail=resolved_detail,
            arm_id=arm_id,
            coordinate_key=coordinate_key,
        )

    if reason_token == FailureReason.CAPABILITY_UNAVAILABLE.value:
        return EvaluationStatusRecord(
            status=EvaluationStatus.NOT_MEASURED,
            reason=NotMeasuredReason.TERMINAL_UNSUPPORTED.value,
            detail=resolved_detail
            or FailureReason.CAPABILITY_UNAVAILABLE.value,
            arm_id=arm_id,
            coordinate_key=coordinate_key,
        )

    if reason_token == FailureReason.RETRY_EXHAUSTED.value:
        return EvaluationStatusRecord(
            status=EvaluationStatus.RUNTIME_FAILED,
            reason=RuntimeFailedReason.RETRY_EXHAUSTED.value,
            detail=resolved_detail,
            arm_id=arm_id,
            coordinate_key=coordinate_key,
        )

    if reason_token is not None and _is_provider_error_token(reason_token):
        return EvaluationStatusRecord(
            status=EvaluationStatus.RUNTIME_FAILED,
            reason=RuntimeFailedReason.PROVIDER_ERROR.value,
            detail=resolved_detail or reason_token,
            arm_id=arm_id,
            coordinate_key=coordinate_key,
        )

    if component in {ComponentStatus.SUCCESS.value, "success"}:
        return EvaluationStatusRecord(
            status=EvaluationStatus.SEMANTIC_SCORED,
            reason="success",
            detail=resolved_detail,
            arm_id=arm_id,
            coordinate_key=coordinate_key,
        )

    if reason_token is not None or component in {
        ComponentStatus.FAILED.value,
        "failed",
    }:
        return EvaluationStatusRecord(
            status=EvaluationStatus.RUNTIME_FAILED,
            reason=RuntimeFailedReason.PROVIDER_ERROR.value,
            detail=resolved_detail or reason_token or "runtime failure",
            arm_id=arm_id,
            coordinate_key=coordinate_key,
        )

    raise ContractError(
        "cannot classify evaluation status without status, failure_reason, "
        "or qualification_status"
    )


def classify_coordinate_record(
    record: Mapping[str, object],
    *,
    qualification_status: object = None,
    qualification_reason: object = None,
    preflight_blocked: bool = False,
) -> EvaluationStatusRecord:
    """Classify a sealed matrix / replacement coordinate record."""
    if not isinstance(record, Mapping):
        raise ContractError("coordinate record must be a mapping")
    failure = record.get("failure")
    if failure is None:
        failure_map: Mapping[str, object] | None = None
        failure_reason = record.get("failure_reason")
    elif isinstance(failure, Mapping):
        failure_map = failure
        failure_reason = failure.get("reason", failure.get("failure_reason"))
    else:
        raise ContractError("failure must be an object or null")

    arm_id = _normalize_token(record.get("arm_id", record.get("cell_id")))
    coordinate_key = _normalize_token(
        record.get("coordinate_key", record.get("key"))
    )
    qual = qualification_status
    if qual is None:
        qual = record.get("qualification_status")
    qual_reason = qualification_reason
    if qual_reason is None:
        qual_reason = record.get("qualification_reason")
    blocked = preflight_blocked or bool(record.get("preflight_blocked"))

    return classify_evaluation_status(
        status=record.get("status"),
        failure_reason=failure_reason,
        failure=failure_map,
        qualification_status=qual,
        qualification_reason=qual_reason,
        preflight_blocked=blocked,
        arm_id=arm_id,
        coordinate_key=coordinate_key,
    )


def is_deterministic_baseline_arm(
    arm_id: object,
    *,
    baseline_arm_id: str = DEFAULT_DETERMINISTIC_BASELINE_ARM_ID,
) -> bool:
    """Return whether ``arm_id`` is the preregistered deterministic baseline."""
    token = _normalize_token(arm_id)
    baseline = _normalize_token(baseline_arm_id)
    if token is None or baseline is None:
        return False
    return token == baseline


def is_default_leaderboard_eligible(
    classification: EvaluationStatusRecord,
    *,
    baseline_arm_id: str = DEFAULT_DETERMINISTIC_BASELINE_ARM_ID,
) -> bool:
    """Default leaderboard admits semantic_scored plus the baseline arm.

    The baseline is always retained as the comparison anchor even when a
    particular baseline coordinate is being re-ranked; non-baseline arms
    require ``semantic_scored``.
    """
    if classification.status is EvaluationStatus.SEMANTIC_SCORED:
        return True
    # Unscored baseline coordinates must not pollute default rankings;
    # the baseline identity is the comparison anchor, not an auto-admit path.
    if is_deterministic_baseline_arm(
        classification.arm_id, baseline_arm_id=baseline_arm_id
    ):
        return False
    return False


def filter_leaderboard_classifications(
    classifications: Iterable[EvaluationStatusRecord],
    *,
    baseline_arm_id: str = DEFAULT_DETERMINISTIC_BASELINE_ARM_ID,
) -> tuple[EvaluationStatusRecord, ...]:
    """Retain only default-leaderboard-eligible classifications."""
    return tuple(
        item
        for item in classifications
        if is_default_leaderboard_eligible(
            item, baseline_arm_id=baseline_arm_id
        )
    )


def filter_paired_baseline_classifications(
    classifications: Iterable[EvaluationStatusRecord],
    *,
    baseline_arm_id: str = DEFAULT_DETERMINISTIC_BASELINE_ARM_ID,
) -> tuple[EvaluationStatusRecord, ...]:
    """Retain classifications usable in default paired baseline comparisons.

    A paired comparison requires the candidate to be ``semantic_scored``.
    The baseline arm is the fixed anchor identity and is not filtered as a
    candidate; callers pair candidate rows against baseline aggregates
    computed only from the baseline's ``semantic_scored`` coordinates.
    """
    del baseline_arm_id
    return tuple(
        item
        for item in classifications
        if item.status is EvaluationStatus.SEMANTIC_SCORED
    )


def classify_replacement_report_coordinates(
    records: Sequence[Mapping[str, object]],
    *,
    arm_qualifications: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[EvaluationStatusRecord, ...]:
    """Classify a sequence of replacement-report coordinate records."""
    qualifications = arm_qualifications or {}
    classified: list[EvaluationStatusRecord] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ContractError("each coordinate record must be a mapping")
        arm_id = _normalize_token(
            record.get("arm_id", record.get("cell_id"))
        )
        qual_payload = qualifications.get(arm_id or "", {})
        classified.append(
            classify_coordinate_record(
                record,
                qualification_status=qual_payload.get(
                    "qualification_status",
                    record.get("qualification_status"),
                ),
                qualification_reason=qual_payload.get(
                    "qualification_reason",
                    record.get("qualification_reason"),
                ),
            )
        )
    return tuple(classified)


def count_statuses(
    classifications: Iterable[EvaluationStatusRecord],
) -> dict[str, int]:
    """Return sorted status counts for a classification multiset."""
    counts = {status.value: 0 for status in EvaluationStatus}
    for item in classifications:
        counts[item.status.value] += 1
    return counts


def count_reasons(
    classifications: Iterable[EvaluationStatusRecord],
) -> dict[str, int]:
    """Return sorted reason counts for a classification multiset."""
    counts: dict[str, int] = {}
    for item in classifications:
        counts[item.reason] = counts.get(item.reason, 0) + 1
    return dict(sorted(counts.items()))


@dataclass(frozen=True, slots=True)
class ArmPreflightRequirement:
    """Preflight kinds required before an arm may be scheduled for scoring."""

    arm_id: str
    requirements: tuple[str, ...]
    routes: tuple[str, ...]
    guided: bool
    model_backed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "arm_id": self.arm_id,
            "requirements": list(self.requirements),
            "routes": list(self.routes),
            "guided": self.guided,
            "model_backed": self.model_backed,
        }


@dataclass(frozen=True, slots=True)
class LaunchPreflightVerdict:
    """Result of fail-closed matrix launch preflight."""

    authorized: bool
    scheduled_arm_ids: tuple[str, ...]
    missing: tuple[dict[str, object], ...]
    requirements: tuple[ArmPreflightRequirement, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "interface": EVALUATION_STATUS_INTERFACE,
            "schema_version": EVALUATION_STATUS_SCHEMA,
            "authorized": self.authorized,
            "scheduled_arm_ids": list(self.scheduled_arm_ids),
            "missing": list(self.missing),
            "requirements": [item.to_dict() for item in self.requirements],
        }


def _arm_id_from_spec(arm: Mapping[str, object]) -> str:
    for key in ("arm_id", "cell_id", "id"):
        token = _normalize_token(arm.get(key))
        if token is not None:
            return token
    raise ContractError("scheduled arm is missing arm_id/cell_id")


def _composition_mapping(arm: Mapping[str, object]) -> Mapping[str, object]:
    composition = arm.get("composition")
    if composition is None:
        return arm
    if not isinstance(composition, Mapping):
        raise ContractError("arm composition must be an object")
    return composition


def _realizer_mapping(arm: Mapping[str, object]) -> Mapping[str, object]:
    realizer = arm.get("realizer")
    if realizer is None:
        return {}
    if not isinstance(realizer, Mapping):
        raise ContractError("arm realizer must be an object")
    return realizer


def _is_guided_arm(arm: Mapping[str, object]) -> bool:
    composition = _composition_mapping(arm)
    guidance = _normalize_token(
        composition.get("guidance", arm.get("guidance"))
    )
    if guidance == GUIDANCE_GUIDED:
        return True
    arm_id = _normalize_token(arm.get("arm_id", arm.get("cell_id"))) or ""
    return "__guided__" in arm_id


def _is_model_backed_arm(arm: Mapping[str, object]) -> bool:
    if arm.get("model_backed") is True:
        return True
    if arm.get("deterministic") is True:
        return False
    realizer = _realizer_mapping(arm)
    mode = _normalize_token(
        realizer.get("mode", arm.get("realizer_mode"))
    )
    if mode == "model":
        return True
    route = _normalize_token(realizer.get("route", arm.get("route")))
    if route in MODEL_ROUTES_REQUIRING_LIVE_SMOKE:
        return True
    composition = _composition_mapping(arm)
    constructor_route = _normalize_token(
        composition.get("constructor_route", arm.get("constructor_route"))
    )
    return constructor_route in MODEL_ROUTES_REQUIRING_LIVE_SMOKE


def _arm_routes(arm: Mapping[str, object]) -> tuple[str, ...]:
    routes: list[str] = []
    declared = arm.get("route_requirements")
    if isinstance(declared, Sequence) and not isinstance(
        declared, (str, bytes, bytearray)
    ):
        for item in declared:
            token = _normalize_token(item)
            if token is None or token in routes:
                continue
            routes.append(token)
    realizer = _realizer_mapping(arm)
    for key in ("route", "realizer_route"):
        token = _normalize_token(realizer.get(key, arm.get(key)))
        if token is None or token in routes:
            continue
        if token == "not_applicable":
            continue
        routes.append(token)
    composition = _composition_mapping(arm)
    constructor_route = _normalize_token(
        composition.get("constructor_route", arm.get("constructor_route"))
    )
    if (
        constructor_route is not None
        and constructor_route not in routes
        and constructor_route != "not_applicable"
    ):
        routes.append(constructor_route)
    return tuple(routes)


def required_preflights_for_arm(
    arm: Mapping[str, object],
) -> ArmPreflightRequirement:
    """Return the preflight kinds required before an arm may be scheduled."""
    if not isinstance(arm, Mapping):
        raise ContractError("arm must be a mapping")
    arm_id = _arm_id_from_spec(arm)
    guided = _is_guided_arm(arm)
    model_backed = _is_model_backed_arm(arm)
    routes = tuple(
        route
        for route in _arm_routes(arm)
        if route in MODEL_ROUTES_REQUIRING_LIVE_SMOKE
    )
    requirements: list[str] = []
    if guided:
        requirements.append(PREFLIGHT_CAUSAL_QUALIFICATION)
    if model_backed or routes:
        requirements.append(PREFLIGHT_LIVE_SMOKE)
    return ArmPreflightRequirement(
        arm_id=arm_id,
        requirements=tuple(requirements),
        routes=routes,
        guided=guided,
        model_backed=model_backed or bool(routes),
    )


def _smoke_passed(
    smokes: Mapping[str, object] | None, route: str
) -> bool:
    if smokes is None:
        return False
    records = smokes
    if isinstance(smokes, Mapping):
        nested = smokes.get("records", smokes.get("routes", smokes))
        if isinstance(nested, Mapping) or (
            isinstance(nested, Sequence)
            and not isinstance(nested, (str, bytes, bytearray))
        ):
            records = nested  # type: ignore[assignment]
    if isinstance(records, Mapping):
        payload = records.get(route)
        if isinstance(payload, Mapping):
            return _receipt_is_live_smoke_pass(payload)
    if isinstance(records, Sequence) and not isinstance(
        records, (str, bytes, bytearray)
    ):
        for item in records:
            if not isinstance(item, Mapping):
                continue
            item_route = _normalize_token(
                item.get("route", item.get("route_id"))
            )
            if item_route != route:
                continue
            if _receipt_is_live_smoke_pass(item):
                return True
    return False


def _receipt_is_live_smoke_pass(receipt: Mapping[str, object]) -> bool:
    status = _normalize_token(receipt.get("status"))
    if status not in frozenset({"ok", "passed", "success", "pass"}):
        return False
    inference = receipt.get("model_inference_performed")
    if inference is False:
        return False
    if inference is None and receipt.get("health_only") is True:
        return False
    return True


def _causal_qualification_passed(
    causal: Mapping[str, object] | None,
    *,
    arm_id: str,
) -> bool:
    if not causal:
        return False
    disposition = _normalize_token(causal.get("disposition"))
    guided = causal.get("guided_coordinates")
    if disposition is None and isinstance(guided, Mapping):
        disposition = _normalize_token(guided.get("disposition"))
    status = _normalize_token(causal.get("status"))
    if disposition == "scored_supported" or status == "scored_supported":
        return True
    if status in frozenset({"passed", "qualified"}) and disposition not in {
        TERMINAL_UNSUPPORTED,
        "unavailable",
        "unavailable_no_reviewed_causal_l1_adapter",
    }:
        contract = causal.get("causal_contract")
        if isinstance(contract, Mapping) and contract.get("preregistered"):
            return True
    arms = causal.get("arms")
    if isinstance(arms, Mapping):
        payload = arms.get(arm_id)
        if isinstance(payload, Mapping):
            arm_status = _normalize_token(
                payload.get("status", payload.get("disposition"))
            )
            if arm_status == "scored_supported":
                return True
    return False


def evaluate_matrix_launch_preflight(
    scheduled_arms: Sequence[Mapping[str, object]],
    *,
    live_smokes: Mapping[str, object] | None = None,
    causal_qualification: Mapping[str, object] | None = None,
) -> LaunchPreflightVerdict:
    """Evaluate whether every scheduled arm has required preflight evidence.

    Returns a verdict; does not raise.  Use
    :func:`assert_matrix_launch_preflight` for fail-closed launch gates.
    """
    if not isinstance(scheduled_arms, Sequence) or isinstance(
        scheduled_arms, (str, bytes, bytearray)
    ):
        raise ContractError("scheduled_arms must be a sequence of arm specs")

    requirements: list[ArmPreflightRequirement] = []
    missing: list[dict[str, object]] = []
    arm_ids: list[str] = []

    for arm in scheduled_arms:
        if not isinstance(arm, Mapping):
            raise ContractError("each scheduled arm must be a mapping")
        req = required_preflights_for_arm(arm)
        requirements.append(req)
        arm_ids.append(req.arm_id)

        for kind in req.requirements:
            if kind == PREFLIGHT_CAUSAL_QUALIFICATION:
                if _causal_qualification_passed(
                    causal_qualification, arm_id=req.arm_id
                ):
                    continue
                missing.append(
                    {
                        "arm_id": req.arm_id,
                        "preflight": PREFLIGHT_CAUSAL_QUALIFICATION,
                        "reason": (
                            "guided arm lacks scored_supported "
                            "causal qualification"
                        ),
                    }
                )
                continue

            if kind == PREFLIGHT_LIVE_SMOKE:
                routes = req.routes or tuple(
                    sorted(MODEL_ROUTES_REQUIRING_LIVE_SMOKE)
                )
                if not req.routes and req.model_backed:
                    arm_lower = req.arm_id.lower()
                    inferred: list[str] = []
                    if "symai" in arm_lower:
                        inferred.append("symai")
                    if "leanstral_direct" in arm_lower or (
                        "direct" in arm_lower and "symai" not in arm_lower
                    ):
                        inferred.append("direct")
                    routes = tuple(inferred) or ("direct",)
                for route in routes:
                    if _smoke_passed(live_smokes, route):
                        continue
                    missing.append(
                        {
                            "arm_id": req.arm_id,
                            "preflight": PREFLIGHT_LIVE_SMOKE,
                            "route": route,
                            "reason": (
                                "model-backed arm lacks passing live smoke "
                                f"for route {route!r}"
                            ),
                        }
                    )
                continue

            missing.append(
                {
                    "arm_id": req.arm_id,
                    "preflight": kind,
                    "reason": f"unknown preflight kind {kind!r}",
                }
            )

    return LaunchPreflightVerdict(
        authorized=not missing,
        scheduled_arm_ids=tuple(arm_ids),
        missing=tuple(missing),
        requirements=tuple(requirements),
    )


def assert_matrix_launch_preflight(
    scheduled_arms: Sequence[Mapping[str, object]],
    *,
    live_smokes: Mapping[str, object] | None = None,
    causal_qualification: Mapping[str, object] | None = None,
) -> LaunchPreflightVerdict:
    """Fail closed if any scheduled arm lacks required preflight evidence."""
    verdict = evaluate_matrix_launch_preflight(
        scheduled_arms,
        live_smokes=live_smokes,
        causal_qualification=causal_qualification,
    )
    if verdict.authorized:
        return verdict
    arms = sorted({str(item.get("arm_id")) for item in verdict.missing})
    raise LaunchPreflightError(
        "matrix launch blocked: scheduled arms lack required preflight "
        f"evidence: {arms}; missing={list(verdict.missing)}"
    )


def classify_historical_replacement_failure_reason(
    failure_reason: str,
    *,
    arm_id: str | None = None,
    detail: str | None = None,
    coordinate_key: str | None = None,
) -> EvaluationStatusRecord:
    """Classify a bare failure-reason token from the 2026-07-27 run.

    Convenience wrapper used by report re-interpretation and unit tests so
    that guided ``post_schedule_capability_unavailable`` rows and Leanstral
    ``retry_exhausted`` rows map onto the disjoint taxonomy without
    replaying the full matrix.
    """
    return classify_evaluation_status(
        failure_reason=failure_reason,
        arm_id=arm_id,
        detail=detail,
        coordinate_key=coordinate_key,
    )


__all__ = (
    "EVALUATION_STATUS_INTERFACE",
    "EVALUATION_STATUS_SCHEMA",
    "DEFAULT_DETERMINISTIC_BASELINE_ARM_ID",
    "REPLACEMENT_2026_07_27_FAILURE_REASON_COUNTS",
    "REPLACEMENT_2026_07_27_SUCCESS_COUNT",
    "REPLACEMENT_2026_07_27_SCHEDULED_COUNT",
    "REPLACEMENT_2026_07_27_GUIDED_ARM_COUNT",
    "REPLACEMENT_2026_07_27_GUIDED_COORDINATE_COUNT",
    "TERMINAL_UNSUPPORTED",
    "PREFLIGHT_BLOCKED",
    "QUALIFIED_CANDIDATE",
    "CAPABILITY_UNAVAILABLE",
    "PREFLIGHT_LIVE_SMOKE",
    "PREFLIGHT_CAUSAL_QUALIFICATION",
    "EvaluationStatus",
    "NotMeasuredReason",
    "RuntimeFailedReason",
    "LaunchPreflightError",
    "EvaluationStatusRecord",
    "ArmPreflightRequirement",
    "LaunchPreflightVerdict",
    "classify_evaluation_status",
    "classify_coordinate_record",
    "classify_replacement_report_coordinates",
    "classify_historical_replacement_failure_reason",
    "is_deterministic_baseline_arm",
    "is_default_leaderboard_eligible",
    "filter_leaderboard_classifications",
    "filter_paired_baseline_classifications",
    "count_statuses",
    "count_reasons",
    "required_preflights_for_arm",
    "evaluate_matrix_launch_preflight",
    "assert_matrix_launch_preflight",
)
