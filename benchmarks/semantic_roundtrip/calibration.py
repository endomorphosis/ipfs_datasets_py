"""Oracle-reverse calibration and realizer anti-leakage controls.

The ranked experiment measures ``T0 -> C -> L1 -> R -> T1 -> C -> L2``.
This module deliberately runs a different, diagnostic-only experiment:

``adjudicated gold IR -> R -> T1 -> fixed typed recompiler -> L2``.

Feeding the adjudicated IR directly to each common realizer isolates loss in
the reverse stage from loss introduced by a candidate constructor.  These
measurements are calibration evidence only: records and summaries are
permanently marked non-ranking and cannot be mixed into matrix selection.

The leakage guard constructs the realizer request from the three public wire
fields and rejects forbidden source, native, gold-labelled, hidden, prior
outcome, and gold-derived-budget channels before an adapter is invoked.  The
oracle IR crosses the boundary only under its ordinary ``canonical_ir`` name;
the realizer is not told that it originated from adjudication.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RealizerRequest,
    RealizerResult,
    RoundTripConstructor,
    RoundTripRealizer,
)
from benchmarks.semantic_roundtrip.metrics import compare_semantic_ir


ORACLE_REVERSE_CALIBRATION_INTERFACE: Final = "OracleReverseCalibration@1"
REALIZER_LEAKAGE_GUARD_INTERFACE: Final = "RealizerLeakageGuard@1"
COMMON_REALIZER_IDS: Final = ("deterministic", "leanstral")
NON_RANKING_REASON: Final = (
    "oracle reverse-stage diagnostic has adjudicated IR as its input"
)
TYPED_RECOMPILER_IDENTITY: Final = "TypedDeonticCanonicalConstructor@1"

FORBIDDEN_BUDGET_INPUTS: Final = frozenset(
    {
        "gold_ir",
        "gold_rule_count",
        "gold_content",
        "validator_output",
        "observed_semantic_outcome",
    }
)

# These are channel names, not substrings.  For example, ``resource_limit`` is
# public configuration and must not be rejected merely because "source" is a
# substring of "resource".
_FORBIDDEN_CHANNEL_PREFIXES: Final = (
    "source",
    "t0",
    "gold",
    "native",
    "compiler_record",
    "constructor",
    "originating_constructor",
    "parse",
    "private",
    "hidden",
    "prior_reconstruction",
    "outcome",
    "validator_output",
    "observed_semantic_outcome",
)
_PROVENANCE_KEYS: Final = frozenset(
    {
        "budget_input",
        "budget_inputs",
        "budget_provenance",
        "budget_source",
        "budget_sources",
        "derived_from",
        "limit_input",
        "limit_inputs",
        "selector_input",
        "selector_inputs",
    }
)


def _normalize_name(value: object) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value).strip()),
        flags=re.IGNORECASE,
    ).strip("_").lower()


def _plain_json(value: object) -> object:
    """Detach JSON-like input so caller-owned mappings cannot be a channel."""

    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_plain_json(item) for item in value]
    return value


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(_freeze_json(item) for item in value)
    return value


def _identity(component: object, role: str) -> str:
    identity = getattr(component, "identity", None)
    if not isinstance(identity, str) or not identity.strip():
        raise ContractError(f"{role} identity must be a nonblank string")
    return identity


def _is_forbidden_channel(name: str) -> bool:
    return any(
        name == prefix or name.startswith(prefix + "_")
        for prefix in _FORBIDDEN_CHANNEL_PREFIXES
    )


def _walk_config(value: object, path: str = "config") -> None:
    """Reject labelled hidden channels, including nested/camel-case aliases."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalize_name(key)
            if _is_forbidden_channel(normalized):
                raise ContractError(
                    f"realizer calibration payload may not contain {path}.{key}"
                )
            if normalized in _PROVENANCE_KEYS:
                provenance_values: Sequence[object]
                if isinstance(item, Sequence) and not isinstance(
                    item, (str, bytes, bytearray)
                ):
                    provenance_values = item
                else:
                    provenance_values = (item,)
                forbidden = {
                    _normalize_name(entry)
                    for entry in provenance_values
                } & FORBIDDEN_BUDGET_INPUTS
                if forbidden:
                    raise ContractError(
                        "gold-derived budgets are forbidden; "
                        f"{path}.{key} names {sorted(forbidden)!r}"
                    )
            _walk_config(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            _walk_config(item, f"{path}[{index}]")


def detect_vacuous_empty_identity(
    reference: CanonicalRuleIR,
    candidate: CanonicalRuleIR,
) -> bool:
    """Return true only for the meaningless equality of two empty IRs."""

    if not isinstance(reference, CanonicalRuleIR) or not isinstance(
        candidate, CanonicalRuleIR
    ):
        raise ContractError("identity inputs must be CanonicalRuleIR")
    return reference.is_empty and candidate.is_empty


def nonvacuous_exact_identity(
    reference: CanonicalRuleIR,
    candidate: CanonicalRuleIR,
) -> bool:
    """Require content on both sides before exact identity can pass."""

    return bool(
        not detect_vacuous_empty_identity(reference, candidate)
        and not reference.is_empty
        and not candidate.is_empty
        and reference == candidate
    )


class RealizerLeakageGuard:
    """Build and invoke the exact source-withheld realizer boundary.

    The guard intentionally accepts canonical IR, vocabulary, and public
    configuration as separate typed values.  It never accepts a matrix case,
    source text, originating constructor, native record, or gold-labelled
    object.
    """

    interface: Final = REALIZER_LEAKAGE_GUARD_INTERFACE
    allowed_payload_fields: Final = frozenset(
        {"canonical_ir", "allowed_atom_vocabulary", "config"}
    )
    forbidden_budget_inputs: Final = FORBIDDEN_BUDGET_INPUTS

    @property
    def identity(self) -> str:
        return self.interface

    @classmethod
    def validate_budget_inputs(
        cls, budget_inputs: Sequence[str] = ()
    ) -> tuple[str, ...]:
        if isinstance(budget_inputs, (str, bytes, bytearray)) or not isinstance(
            budget_inputs, Sequence
        ):
            raise ContractError("budget_inputs must be a string array")
        normalized: list[str] = []
        for index, value in enumerate(budget_inputs):
            if not isinstance(value, str) or not value.strip():
                raise ContractError(
                    f"budget_inputs[{index}] must be a nonblank string"
                )
            normalized.append(_normalize_name(value))
        forbidden = set(normalized) & cls.forbidden_budget_inputs
        if forbidden:
            raise ContractError(
                "gold-derived budgets are forbidden; budget inputs include "
                f"{sorted(forbidden)!r}"
            )
        return tuple(normalized)

    @classmethod
    def request_from_payload(
        cls,
        payload: object,
        *,
        budget_inputs: Sequence[str] = (),
    ) -> RealizerRequest:
        """Validate an untrusted wire payload and return its detached request."""

        cls.validate_budget_inputs(budget_inputs)
        if not isinstance(payload, Mapping):
            raise ContractError("realizer calibration payload must be an object")
        extra = set(payload) - cls.allowed_payload_fields
        missing = cls.allowed_payload_fields - set(payload)
        if extra or missing:
            forbidden = sorted(
                str(key)
                for key in extra
                if _is_forbidden_channel(_normalize_name(key))
            )
            if forbidden:
                raise ContractError(
                    "realizer calibration payload contains forbidden "
                    f"source/native/gold fields: {forbidden!r}"
                )
            raise ContractError(
                "realizer calibration payload fields mismatch; "
                f"missing={sorted(missing)!r}, undeclared={sorted(extra)!r}"
            )
        _walk_config(payload["config"])
        detached = _plain_json(payload)
        assert isinstance(detached, Mapping)
        return RealizerRequest.from_payload(detached)

    @classmethod
    def build_request(
        cls,
        canonical_ir: CanonicalRuleIR,
        allowed_atom_vocabulary: AllowedAtomVocabulary,
        config: Mapping[str, object] | None = None,
        *,
        budget_inputs: Sequence[str] = (),
    ) -> RealizerRequest:
        if not isinstance(canonical_ir, CanonicalRuleIR):
            raise ContractError("canonical_ir must be CanonicalRuleIR")
        if not isinstance(
            allowed_atom_vocabulary, AllowedAtomVocabulary
        ):
            raise ContractError(
                "allowed_atom_vocabulary must be AllowedAtomVocabulary"
            )
        if config is None:
            config = {}
        if not isinstance(config, Mapping):
            raise ContractError("realizer config must be an object")
        return cls.request_from_payload(
            {
                "canonical_ir": canonical_ir.to_dict(),
                "allowed_atom_vocabulary": (
                    allowed_atom_vocabulary.to_dict()
                ),
                "config": _plain_json(config),
            },
            budget_inputs=budget_inputs,
        )

    @staticmethod
    def invoke(
        realizer: RoundTripRealizer,
        request: RealizerRequest,
    ) -> RealizerResult:
        if not isinstance(realizer, RoundTripRealizer):
            raise ContractError("realizer must implement RoundTripRealizer")
        if not isinstance(request, RealizerRequest):
            raise ContractError("request must be RealizerRequest")
        try:
            result = realizer.realize(request)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            return RealizerResult(
                status=ComponentStatus.FAILED,
                failure_reason=FailureReason.EXCEPTION,
                failure_detail=(
                    f"realizer raised {type(exc).__name__}"
                )[:1000],
            )
        if not isinstance(result, RealizerResult):
            return RealizerResult(
                status=ComponentStatus.FAILED,
                failure_reason=FailureReason.INVALID_OUTPUT,
                failure_detail="realizer returned a non-RealizerResult",
            )
        return result


@dataclass(frozen=True, slots=True)
class OracleCalibrationCase:
    """A source-free oracle calibration input."""

    case_id: str
    allowed_atom_vocabulary: AllowedAtomVocabulary
    gold_ir: CanonicalRuleIR

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ContractError("case_id must be a nonblank string")
        if not isinstance(
            self.allowed_atom_vocabulary, AllowedAtomVocabulary
        ):
            raise ContractError(
                "allowed_atom_vocabulary must be AllowedAtomVocabulary"
            )
        if not isinstance(self.gold_ir, CanonicalRuleIR):
            raise ContractError("gold_ir must be CanonicalRuleIR")
        if self.gold_ir.is_empty:
            raise ContractError(
                "gold_ir must be nonempty; empty/empty identity is vacuous"
            )
        self.gold_ir.validate_vocabulary(self.allowed_atom_vocabulary)

    @classmethod
    def from_dict(cls, value: object) -> "OracleCalibrationCase":
        if not isinstance(value, Mapping):
            raise ContractError("oracle calibration case must be an object")
        allowed_fields = {
            "case_id",
            "allowed_atom_vocabulary",
            "gold_ir",
        }
        if set(value) != allowed_fields:
            extra = set(value) - allowed_fields
            forbidden = sorted(
                str(key)
                for key in extra
                if _is_forbidden_channel(_normalize_name(key))
            )
            if forbidden:
                raise ContractError(
                    "oracle calibration case may not contain source/native "
                    f"fields: {forbidden!r}"
                )
            raise ContractError(
                "oracle calibration case must contain exactly case_id, "
                "allowed_atom_vocabulary, and gold_ir"
            )
        vocabulary = AllowedAtomVocabulary.from_dict(
            value["allowed_atom_vocabulary"]
        )
        return cls(
            case_id=value["case_id"],  # type: ignore[arg-type]
            allowed_atom_vocabulary=vocabulary,
            gold_ir=CanonicalRuleIR.from_dict(value["gold_ir"], vocabulary),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "allowed_atom_vocabulary": self.allowed_atom_vocabulary.to_dict(),
            "gold_ir": self.gold_ir.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OracleReverseArmRecord:
    """One terminal, permanently non-ranking calibration coordinate."""

    case_id: str
    realizer_id: str
    realizer_identity: str
    recompiler_identity: str
    status: ComponentStatus
    reconstruction: str | None
    reconstructed_ir: CanonicalRuleIR | None
    reverse_loss: float
    semantic_comparison: Mapping[str, object] | None
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None
    ranking_eligible: bool = False
    vacuous_empty_identity: bool = False

    def __post_init__(self) -> None:
        for field in (
            "case_id",
            "realizer_id",
            "realizer_identity",
            "recompiler_identity",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ContractError(
                    f"calibration {field} must be a nonblank string"
                )
        if not isinstance(self.status, ComponentStatus):
            raise ContractError("calibration status is invalid")
        if self.failure_reason is not None and not isinstance(
            self.failure_reason, FailureReason
        ):
            raise ContractError("calibration failure reason is invalid")
        if self.failure_detail is not None and (
            not isinstance(self.failure_detail, str)
            or not self.failure_detail.strip()
        ):
            raise ContractError(
                "calibration failure detail must be a nonblank string"
            )
        if (
            isinstance(self.reverse_loss, bool)
            or not isinstance(self.reverse_loss, (int, float))
            or not math.isfinite(float(self.reverse_loss))
            or not 0.0 <= float(self.reverse_loss) <= 1.0
        ):
            raise ContractError(
                "reverse_loss must be a finite number from zero to one"
            )
        object.__setattr__(self, "reverse_loss", float(self.reverse_loss))
        if self.ranking_eligible:
            raise ContractError("oracle calibration arms must be non-ranking")
        complete = (
            self.status is ComponentStatus.SUCCESS
            and isinstance(self.reconstruction, str)
            and bool(self.reconstruction.strip())
            and isinstance(self.reconstructed_ir, CanonicalRuleIR)
            and not self.reconstructed_ir.is_empty
            and self.semantic_comparison is not None
            and self.failure_reason is None
            and self.failure_detail is None
            and not self.vacuous_empty_identity
        )
        if self.status is ComponentStatus.SUCCESS and not complete:
            raise ContractError(
                "successful calibration requires nonvacuous reconstruction "
                "and recompiled IR"
            )
        if self.status is ComponentStatus.FAILED:
            if self.failure_reason is None or self.reverse_loss != 1.0:
                raise ContractError(
                    "failed calibration requires a reason and loss one"
                )
            if (
                self.reconstructed_ir is not None
                or self.semantic_comparison is not None
            ):
                raise ContractError(
                    "failed calibration cannot carry recompiled semantic "
                    "artifacts"
                )
        if self.semantic_comparison is not None:
            comparison_loss = self.semantic_comparison.get("semantic_loss")
            if (
                isinstance(comparison_loss, bool)
                or not isinstance(comparison_loss, (int, float))
                or float(comparison_loss) != self.reverse_loss
            ):
                raise ContractError(
                    "reverse_loss must equal semantic comparison loss"
                )
            object.__setattr__(
                self,
                "semantic_comparison",
                _freeze_json(_plain_json(self.semantic_comparison)),
            )

    @property
    def primary_loss(self) -> None:
        """Calibration diagnostics intentionally have no ranking loss."""

        return None

    @property
    def non_ranking(self) -> bool:
        return True

    def to_dict(self) -> dict[str, object]:
        return {
            "interface": ORACLE_REVERSE_CALIBRATION_INTERFACE,
            "case_id": self.case_id,
            "arm_id": self.realizer_id,
            "realizer": {
                "id": self.realizer_id,
                "identity": self.realizer_identity,
            },
            "recompiler": {
                "identity": self.recompiler_identity,
                "fixed_for_all_arms": True,
                "originating_constructor_available": False,
            },
            "status": self.status.value,
            "failure": (
                None
                if self.failure_reason is None
                else {
                    "reason": self.failure_reason.value,
                    "detail": self.failure_detail,
                }
            ),
            "artifacts": {
                "t1": self.reconstruction,
                "l2": (
                    self.reconstructed_ir.to_dict()
                    if self.reconstructed_ir is not None
                    else None
                ),
            },
            "reverse_loss": self.reverse_loss,
            "semantic_comparison": _plain_json(self.semantic_comparison),
            "vacuous_empty_identity": self.vacuous_empty_identity,
            "ranking": {
                "eligible": False,
                "primary_loss": None,
                "reason": NON_RANKING_REASON,
            },
        }


@dataclass(frozen=True, slots=True)
class OracleReverseCalibrationReceipt:
    """Immutable receipt for all oracle cases and common realizer arms."""

    cases: tuple[tuple[OracleReverseArmRecord, ...], ...]
    summaries: Mapping[str, Mapping[str, object]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "cases",
            tuple(tuple(records) for records in self.cases),
        )
        if not self.cases or any(not records for records in self.cases):
            raise ContractError("calibration receipt requires nonempty cases")
        if any(
            not isinstance(record, OracleReverseArmRecord)
            for records in self.cases
            for record in records
        ):
            raise ContractError("calibration receipt contains invalid records")
        object.__setattr__(
            self,
            "summaries",
            _freeze_json(_plain_json(self.summaries)),
        )

    @property
    def ranking_eligible(self) -> bool:
        return False

    @property
    def rankable_arm_ids(self) -> tuple[str, ...]:
        return ()

    @property
    def records(self) -> tuple[OracleReverseArmRecord, ...]:
        return tuple(record for case in self.cases for record in case)

    def to_dict(self) -> dict[str, object]:
        return {
            "interface": ORACLE_REVERSE_CALIBRATION_INTERFACE,
            "experiment": "oracle_reverse_stage_calibration",
            "input": "adjudicated_gold_ir_as_unlabelled_canonical_ir",
            "ranking": {
                "eligible": False,
                "rankable_arm_ids": [],
                "reason": NON_RANKING_REASON,
            },
            "anti_leakage": {
                "guard_interface": REALIZER_LEAKAGE_GUARD_INTERFACE,
                "realizer_inputs": [
                    "canonical_ir",
                    "allowed_atom_vocabulary",
                    "frozen_realizer_config",
                ],
                "source_native_gold_labelled_channels_rejected": True,
                "gold_derived_budgets_rejected": True,
                "originating_constructor_available": False,
                "empty_empty_identity_is_vacuous": True,
            },
            "cases": [
                [record.to_dict() for record in records]
                for records in self.cases
            ],
            "summaries": _plain_json(self.summaries),
        }


def _safe_construct(
    constructor: RoundTripConstructor,
    request: ConstructorRequest,
) -> ConstructorResult:
    try:
        result = constructor.construct(request)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        return ConstructorResult(
            status=ComponentStatus.FAILED,
            failure_reason=FailureReason.EXCEPTION,
            failure_detail=(
                f"typed recompiler raised {type(exc).__name__}"
            )[:1000],
        )
    if not isinstance(result, ConstructorResult):
        return ConstructorResult(
            status=ComponentStatus.FAILED,
            failure_reason=FailureReason.INVALID_OUTPUT,
            failure_detail=(
                "typed recompiler returned a non-ConstructorResult"
            ),
        )
    return result


class OracleReverseCalibration:
    """Measure both common realizers against one fixed typed recompiler."""

    interface: Final = ORACLE_REVERSE_CALIBRATION_INTERFACE

    def __init__(
        self,
        realizers: Mapping[str, RoundTripRealizer] | None = None,
        *,
        typed_recompiler: RoundTripConstructor | None = None,
        realizer_configs: Mapping[str, Mapping[str, object]] | None = None,
        realizer_budget_inputs: Mapping[str, Sequence[str]] | None = None,
        recompiler_config: Mapping[str, object] | None = None,
        recompiler_budget_inputs: Sequence[str] = (),
        require_common_realizers: bool = True,
    ) -> None:
        if realizers is None:
            from benchmarks.semantic_roundtrip.realizers.deterministic import (
                CanonicalDeterministicRealizer,
            )
            from benchmarks.semantic_roundtrip.realizers.leanstral import (
                LeanstralCanonicalRealizer,
            )

            realizers = {
                "deterministic": CanonicalDeterministicRealizer(),
                "leanstral": LeanstralCanonicalRealizer(),
            }
        supplied = dict(realizers)
        if not supplied:
            raise ContractError(
                "oracle calibration requires nonempty realizers"
            )
        if require_common_realizers and set(supplied) != set(
            COMMON_REALIZER_IDS
        ):
            raise ContractError(
                "oracle calibration requires deterministic and leanstral arms"
            )
        ordered_ids = (
            COMMON_REALIZER_IDS
            if require_common_realizers
            else tuple(supplied)
        )
        self._realizers = {
            realizer_id: supplied[realizer_id] for realizer_id in ordered_ids
        }
        for realizer in self._realizers.values():
            if not isinstance(realizer, RoundTripRealizer):
                raise ContractError(
                    "realizers must implement RoundTripRealizer"
                )
            _identity(realizer, "realizer")

        if typed_recompiler is None:
            from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
                TypedDeonticCanonicalConstructor,
            )

            typed_recompiler = TypedDeonticCanonicalConstructor()
        if not isinstance(typed_recompiler, RoundTripConstructor):
            raise ContractError(
                "typed_recompiler must implement RoundTripConstructor"
            )
        if _identity(typed_recompiler, "typed recompiler") != (
            TYPED_RECOMPILER_IDENTITY
        ):
            raise ContractError(
                "oracle calibration must use the fixed typed deontic "
                "recompiler"
            )
        self._typed_recompiler = typed_recompiler
        self._recompiler_identity = TYPED_RECOMPILER_IDENTITY

        configs = dict(realizer_configs or {})
        extra_configs = set(configs) - set(self._realizers)
        if extra_configs:
            raise ContractError(
                "realizer configs contain unknown ids: "
                f"{sorted(extra_configs)!r}"
            )
        budget_inputs = dict(realizer_budget_inputs or {})
        extra_budget_inputs = set(budget_inputs) - set(self._realizers)
        if extra_budget_inputs:
            raise ContractError(
                "realizer budget inputs contain unknown ids: "
                f"{sorted(extra_budget_inputs)!r}"
            )
        self._realizer_configs: dict[str, Mapping[str, object]] = {}
        self._realizer_budget_inputs: dict[str, tuple[str, ...]] = {}
        for realizer_id in self._realizers:
            config = configs.get(realizer_id, {})
            if not isinstance(config, Mapping):
                raise ContractError(
                    f"realizer config {realizer_id!r} must be an object"
                )
            _walk_config(config)
            detached = _plain_json(config)
            assert isinstance(detached, Mapping)
            self._realizer_configs[realizer_id] = detached
            self._realizer_budget_inputs[realizer_id] = (
                RealizerLeakageGuard.validate_budget_inputs(
                    budget_inputs.get(realizer_id, ())
                )
            )

        if recompiler_config is None:
            recompiler_config = {}
        if not isinstance(recompiler_config, Mapping):
            raise ContractError("recompiler_config must be an object")
        _walk_config(recompiler_config, "recompiler_config")
        detached_recompiler_config = _plain_json(recompiler_config)
        assert isinstance(detached_recompiler_config, Mapping)
        self._recompiler_config = detached_recompiler_config
        RealizerLeakageGuard.validate_budget_inputs(
            recompiler_budget_inputs
        )

    @property
    def identity(self) -> str:
        return self.interface

    @property
    def realizer_ids(self) -> tuple[str, ...]:
        return tuple(self._realizers)

    @property
    def ranking_eligible(self) -> bool:
        return False

    def _failed_record(
        self,
        *,
        case_id: str,
        realizer_id: str,
        realizer_identity: str,
        reconstruction: str | None,
        reason: FailureReason,
        detail: str | None,
    ) -> OracleReverseArmRecord:
        return OracleReverseArmRecord(
            case_id=case_id,
            realizer_id=realizer_id,
            realizer_identity=realizer_identity,
            recompiler_identity=self._recompiler_identity,
            status=ComponentStatus.FAILED,
            reconstruction=reconstruction,
            reconstructed_ir=None,
            reverse_loss=1.0,
            semantic_comparison=None,
            failure_reason=reason,
            failure_detail=detail,
        )

    def run_case(
        self, case: OracleCalibrationCase
    ) -> tuple[OracleReverseArmRecord, ...]:
        if not isinstance(case, OracleCalibrationCase):
            raise ContractError("case must be OracleCalibrationCase")

        records: list[OracleReverseArmRecord] = []
        for realizer_id, realizer in self._realizers.items():
            realizer_identity = _identity(realizer, "realizer")
            # The request is rebuilt through the wire contract.  No matrix
            # case, source, originating constructor, or private record exists
            # in the adapter's reachable request graph.
            request = RealizerLeakageGuard.build_request(
                case.gold_ir,
                case.allowed_atom_vocabulary,
                self._realizer_configs[realizer_id],
                budget_inputs=self._realizer_budget_inputs[realizer_id],
            )
            realized = RealizerLeakageGuard.invoke(realizer, request)
            if _identity(realizer, "realizer") != realizer_identity:
                realized = RealizerResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.INVALID_OUTPUT,
                    failure_detail=(
                        "realizer identity changed during calibration"
                    ),
                )
            if realized.status is ComponentStatus.FAILED:
                assert realized.failure_reason is not None
                records.append(
                    self._failed_record(
                        case_id=case.case_id,
                        realizer_id=realizer_id,
                        realizer_identity=realizer_identity,
                        reconstruction=None,
                        reason=realized.failure_reason,
                        detail=realized.failure_detail,
                    )
                )
                continue

            reconstruction = realized.text
            assert reconstruction is not None
            second_request = ConstructorRequest(
                source_text=reconstruction,
                allowed_atom_vocabulary=case.allowed_atom_vocabulary,
                config=self._recompiler_config,
            )
            recompiled = _safe_construct(
                self._typed_recompiler, second_request
            )
            if _identity(
                self._typed_recompiler, "typed recompiler"
            ) != self._recompiler_identity:
                recompiled = ConstructorResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.INVALID_OUTPUT,
                    failure_detail=(
                        "typed recompiler identity changed during calibration"
                    ),
                )
            if recompiled.status is ComponentStatus.FAILED:
                reason = recompiled.failure_reason
                assert reason is not None
                if reason is FailureReason.EMPTY_L1:
                    reason = FailureReason.EMPTY_L2
                records.append(
                    self._failed_record(
                        case_id=case.case_id,
                        realizer_id=realizer_id,
                        realizer_identity=realizer_identity,
                        reconstruction=reconstruction,
                        reason=reason,
                        detail=recompiled.failure_detail,
                    )
                )
                continue

            l2 = recompiled.canonical_ir
            assert l2 is not None
            vacuous = detect_vacuous_empty_identity(case.gold_ir, l2)
            if vacuous or l2.is_empty:
                records.append(
                    OracleReverseArmRecord(
                        case_id=case.case_id,
                        realizer_id=realizer_id,
                        realizer_identity=realizer_identity,
                        recompiler_identity=self._recompiler_identity,
                        status=ComponentStatus.FAILED,
                        reconstruction=reconstruction,
                        reconstructed_ir=None,
                        reverse_loss=1.0,
                        semantic_comparison=None,
                        failure_reason=FailureReason.EMPTY_L2,
                        failure_detail=(
                            "empty/empty identity is vacuous"
                            if vacuous
                            else "typed recompiler returned empty IR"
                        ),
                        vacuous_empty_identity=vacuous,
                    )
                )
                continue

            comparison = compare_semantic_ir(case.gold_ir, l2)
            records.append(
                OracleReverseArmRecord(
                    case_id=case.case_id,
                    realizer_id=realizer_id,
                    realizer_identity=realizer_identity,
                    recompiler_identity=self._recompiler_identity,
                    status=ComponentStatus.SUCCESS,
                    reconstruction=reconstruction,
                    reconstructed_ir=l2,
                    reverse_loss=float(comparison["semantic_loss"]),
                    semantic_comparison=comparison,
                )
            )

        return tuple(records)

    def run(
        self, cases: Sequence[OracleCalibrationCase]
    ) -> OracleReverseCalibrationReceipt:
        if (
            not isinstance(cases, Sequence)
            or isinstance(cases, (str, bytes, bytearray))
            or not cases
        ):
            raise ContractError("cases must be a nonempty sequence")
        seen: set[str] = set()
        case_records: list[tuple[OracleReverseArmRecord, ...]] = []
        for case in cases:
            if not isinstance(case, OracleCalibrationCase):
                raise ContractError(
                    "cases must contain OracleCalibrationCase values"
                )
            if case.case_id in seen:
                raise ContractError("calibration case ids must be unique")
            seen.add(case.case_id)
            case_records.append(self.run_case(case))

        summaries: dict[str, Mapping[str, object]] = {}
        for realizer_id in self._realizers:
            records = [
                record
                for group in case_records
                for record in group
                if record.realizer_id == realizer_id
            ]
            summaries[realizer_id] = {
                "scheduled_case_count": len(records),
                "success_count": sum(
                    record.status is ComponentStatus.SUCCESS
                    for record in records
                ),
                "failure_count": sum(
                    record.status is ComponentStatus.FAILED
                    for record in records
                ),
                "mean_reverse_loss": round(
                    sum(record.reverse_loss for record in records)
                    / len(records),
                    9,
                ),
                "denominator_policy": (
                    "all_scheduled_cases_including_failures"
                ),
                "ranking_eligible": False,
                "selection_effect": "none",
                "non_ranking_reason": NON_RANKING_REASON,
            }
        return OracleReverseCalibrationReceipt(
            cases=tuple(case_records),
            summaries=summaries,
        )


def run_oracle_reverse_calibration(
    cases: Sequence[OracleCalibrationCase],
    realizers: Mapping[str, RoundTripRealizer] | None = None,
    *,
    typed_recompiler: RoundTripConstructor | None = None,
    realizer_configs: Mapping[str, Mapping[str, object]] | None = None,
    realizer_budget_inputs: Mapping[str, Sequence[str]] | None = None,
    recompiler_config: Mapping[str, object] | None = None,
) -> OracleReverseCalibrationReceipt:
    """Convenience entry point for the frozen two-arm calibration."""

    return OracleReverseCalibration(
        realizers,
        typed_recompiler=typed_recompiler,
        realizer_configs=realizer_configs,
        realizer_budget_inputs=realizer_budget_inputs,
        recompiler_config=recompiler_config,
    ).run(cases)


__all__ = [
    "ORACLE_REVERSE_CALIBRATION_INTERFACE",
    "REALIZER_LEAKAGE_GUARD_INTERFACE",
    "COMMON_REALIZER_IDS",
    "NON_RANKING_REASON",
    "TYPED_RECOMPILER_IDENTITY",
    "FORBIDDEN_BUDGET_INPUTS",
    "RealizerLeakageGuard",
    "OracleCalibrationCase",
    "OracleReverseArmRecord",
    "OracleReverseCalibrationReceipt",
    "OracleReverseCalibration",
    "detect_vacuous_empty_identity",
    "nonvacuous_exact_identity",
    "run_oracle_reverse_calibration",
]
