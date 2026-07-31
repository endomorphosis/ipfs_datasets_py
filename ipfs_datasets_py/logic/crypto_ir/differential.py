"""Differential analysis across simulation providers/backends (CRYPTOIR-G330).

Provider and backend disagreement remains **explicit**.  Differential results
never collapse a disagreeing pair into a silent proof or an implicit agreement.
Simulation authority stays monitor/evidence only; disagreement never elevates.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ..ir_core.identity import CanonicalIdentity
from ..ir_core.provenance import ProvenanceValidationError, thaw_json
from .identity import crypto_ir_identity
from .model import CryptoIRValidationError
from .provenance import AuthorityKind, CryptoIRProvenanceError, freeze_json_mapping
from .schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION
from .simulation import (
    OfflineSandbox,
    SimulationError,
    SimulationOutcome,
    SimulationReceipt,
    SimulationRequest,
    run_simulation,
)
from .verdicts import AnalysisOutcome


CRYPTO_IR_DIFFERENTIAL_DOMAIN: Final[str] = "crypto-ir.differential"
CRYPTO_IR_DIFFERENTIAL_SCHEMA_VERSION: Final[str] = CRYPTO_IR_KERNEL_SCHEMA_VERSION
DIFFERENTIAL_RESULT_SCHEMA_VERSION: Final[str] = "crypto-ir.differential-result@1.0.0"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

# Fields compared for agreement between two simulation receipts.
_COMPARE_FIELDS: Final[tuple[str, ...]] = (
    "outcome",
    "authority",
    "analysis_outcome",
    "monitor_outcome",
    "post_state_digest",
    "input_digest",
    "snapshot_state_digest",
    "executed",
)


class DifferentialError(CryptoIRValidationError):
    """Raised when a differential result is malformed."""


class DifferentialStatus(str, Enum):
    """Terminal status of a differential comparison.

    ``DISAGREE`` is a first-class result: it is never collapsed into agreement
    or elevated into theorem authority.
    """

    AGREE = "agree"
    DISAGREE = "disagree"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DifferentialError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise DifferentialError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise DifferentialError(f"{name} must not have surrounding whitespace")
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _ID_RE.fullmatch(normalized):
        raise DifferentialError(f"{name} is not a stable identifier")
    return normalized


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DifferentialError(f"{name} must be a mapping")
    return value


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (
        ProvenanceValidationError,
        CryptoIRProvenanceError,
        TypeError,
        ValueError,
    ) as exc:
        raise DifferentialError(str(exc)) from exc


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise DifferentialError(f"unsupported {name}: {value!r}") from exc


def _unique_texts(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise DifferentialError(f"{name} must be a sequence")
    result = tuple(_text(item, name) for item in values)
    if len(result) != len(set(result)):
        raise DifferentialError(f"{name} values must be unique")
    return result


def _field_value(receipt: SimulationReceipt, name: str) -> Any:
    value = getattr(receipt, name)
    if isinstance(value, Enum):
        return value.value
    return value


@dataclass(frozen=True, slots=True)
class DifferentialResult:
    """Explicit comparison of two simulation (or backend) evidence artifacts.

    Disagreement is recorded field-by-field and never silently discarded.
    The result carries no theorem-proof authority.
    """

    result_id: str
    left_receipt_id: str
    right_receipt_id: str
    status: DifferentialStatus
    left_provider_id: str = ""
    right_provider_id: str = ""
    left_outcome: str = ""
    right_outcome: str = ""
    agreement_fields: tuple[str, ...] = ()
    disagreement_fields: tuple[str, ...] = ()
    compared_fields: tuple[str, ...] = _COMPARE_FIELDS
    reason: str = ""
    request_id: str = ""
    obligation_id: str = ""
    analysis_outcome: AnalysisOutcome = AnalysisOutcome.UNKNOWN
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = DIFFERENTIAL_RESULT_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_id", _identifier(self.result_id, "result_id"))
        object.__setattr__(
            self, "left_receipt_id", _identifier(self.left_receipt_id, "left_receipt_id")
        )
        object.__setattr__(
            self,
            "right_receipt_id",
            _identifier(self.right_receipt_id, "right_receipt_id"),
        )
        object.__setattr__(
            self, "status", _enum(DifferentialStatus, self.status, "status")
        )
        for name in (
            "left_provider_id",
            "right_provider_id",
            "left_outcome",
            "right_outcome",
            "reason",
            "request_id",
            "obligation_id",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(
            self,
            "agreement_fields",
            _unique_texts(self.agreement_fields, "agreement_fields"),
        )
        object.__setattr__(
            self,
            "disagreement_fields",
            _unique_texts(self.disagreement_fields, "disagreement_fields"),
        )
        object.__setattr__(
            self,
            "compared_fields",
            _unique_texts(self.compared_fields or _COMPARE_FIELDS, "compared_fields"),
        )
        # Disjoint agreement/disagreement.
        overlap = set(self.agreement_fields) & set(self.disagreement_fields)
        if overlap:
            raise DifferentialError(
                f"agreement_fields and disagreement_fields overlap: {sorted(overlap)}"
            )
        object.__setattr__(
            self,
            "analysis_outcome",
            _enum(AnalysisOutcome, self.analysis_outcome, "analysis_outcome"),
        )
        if self.analysis_outcome is AnalysisOutcome.PROVED:
            raise DifferentialError(
                "differential result cannot claim analysis PROVED"
            )
        # Status consistency with disagreement set.
        if self.status is DifferentialStatus.AGREE and self.disagreement_fields:
            raise DifferentialError(
                "AGREE status cannot list disagreement_fields"
            )
        if self.status is DifferentialStatus.DISAGREE and not self.disagreement_fields:
            raise DifferentialError(
                "DISAGREE status requires non-empty disagreement_fields"
            )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def is_explicit_disagreement(self) -> bool:
        return self.status is DifferentialStatus.DISAGREE

    @property
    def is_non_proof(self) -> bool:
        return self.analysis_outcome is not AnalysisOutcome.PROVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "agreement_fields": list(self.agreement_fields),
            "analysis_outcome": (
                self.analysis_outcome.value
                if isinstance(self.analysis_outcome, AnalysisOutcome)
                else self.analysis_outcome
            ),
            "attributes": thaw_json(self.attributes),
            "compared_fields": list(self.compared_fields),
            "disagreement_fields": list(self.disagreement_fields),
            "left_outcome": self.left_outcome,
            "left_provider_id": self.left_provider_id,
            "left_receipt_id": self.left_receipt_id,
            "obligation_id": self.obligation_id,
            "reason": self.reason,
            "request_id": self.request_id,
            "result_id": self.result_id,
            "right_outcome": self.right_outcome,
            "right_provider_id": self.right_provider_id,
            "right_receipt_id": self.right_receipt_id,
            "schema_version": self.schema_version,
            "status": (
                self.status.value
                if isinstance(self.status, DifferentialStatus)
                else self.status
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DifferentialResult":
        value = _as_mapping(value, "DifferentialResult")
        return cls(
            result_id=value.get("result_id", ""),
            left_receipt_id=value.get("left_receipt_id", ""),
            right_receipt_id=value.get("right_receipt_id", ""),
            status=value.get("status", DifferentialStatus.ERROR),
            left_provider_id=value.get("left_provider_id", ""),
            right_provider_id=value.get("right_provider_id", ""),
            left_outcome=value.get("left_outcome", ""),
            right_outcome=value.get("right_outcome", ""),
            agreement_fields=tuple(value.get("agreement_fields", ())),
            disagreement_fields=tuple(value.get("disagreement_fields", ())),
            compared_fields=tuple(value.get("compared_fields", _COMPARE_FIELDS)),
            reason=value.get("reason", ""),
            request_id=value.get("request_id", ""),
            obligation_id=value.get("obligation_id", ""),
            analysis_outcome=value.get(
                "analysis_outcome", AnalysisOutcome.UNKNOWN
            ),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", DIFFERENTIAL_RESULT_SCHEMA_VERSION
            ),
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_DIFFERENTIAL_DOMAIN}.result",
        )


def compare_receipts(
    left: SimulationReceipt,
    right: SimulationReceipt,
    *,
    result_id: str,
    fields: Sequence[str] | None = None,
) -> DifferentialResult:
    """Compare two receipts field-by-field; disagreement stays explicit."""

    if not isinstance(left, SimulationReceipt) or not isinstance(
        right, SimulationReceipt
    ):
        raise DifferentialError("left and right must be SimulationReceipt instances")

    compared = tuple(fields) if fields is not None else _COMPARE_FIELDS
    agreement: list[str] = []
    disagreement: list[str] = []
    detail: dict[str, Any] = {}

    for name in compared:
        try:
            lv = _field_value(left, name)
            rv = _field_value(right, name)
        except AttributeError as exc:
            raise DifferentialError(f"unknown compare field: {name}") from exc
        if lv == rv:
            agreement.append(name)
        else:
            disagreement.append(name)
            detail[name] = {"left": lv, "right": rv}

    left_unavail = left.outcome in {
        SimulationOutcome.UNAVAILABLE,
        SimulationOutcome.REFUSED,
    }
    right_unavail = right.outcome in {
        SimulationOutcome.UNAVAILABLE,
        SimulationOutcome.REFUSED,
    }
    left_error = left.outcome is SimulationOutcome.ERROR
    right_error = right.outcome is SimulationOutcome.ERROR

    if left_error or right_error:
        status = DifferentialStatus.ERROR
        analysis = AnalysisOutcome.ERROR
        reason = "one or both receipts reported error"
    elif left_unavail or right_unavail:
        status = DifferentialStatus.UNAVAILABLE
        analysis = AnalysisOutcome.UNKNOWN
        reason = "one or both providers unavailable/refused"
    elif not disagreement:
        status = DifferentialStatus.AGREE
        analysis = AnalysisOutcome.UNKNOWN
        reason = "all compared fields agree"
    elif set(disagreement) == set(compared):
        status = DifferentialStatus.DISAGREE
        analysis = AnalysisOutcome.INCONCLUSIVE
        reason = "providers disagree on all compared fields"
    elif "outcome" in disagreement or "post_state_digest" in disagreement:
        status = DifferentialStatus.DISAGREE
        analysis = AnalysisOutcome.INCONCLUSIVE
        reason = "provider/backend disagreement on outcome or post-state"
    else:
        status = DifferentialStatus.PARTIAL
        analysis = AnalysisOutcome.INCONCLUSIVE
        reason = "partial agreement across compared fields"

    return DifferentialResult(
        result_id=result_id,
        left_receipt_id=left.receipt_id,
        right_receipt_id=right.receipt_id,
        status=status,
        left_provider_id=left.provider_id,
        right_provider_id=right.provider_id,
        left_outcome=(
            left.outcome.value
            if isinstance(left.outcome, SimulationOutcome)
            else str(left.outcome)
        ),
        right_outcome=(
            right.outcome.value
            if isinstance(right.outcome, SimulationOutcome)
            else str(right.outcome)
        ),
        agreement_fields=tuple(agreement),
        disagreement_fields=tuple(disagreement),
        compared_fields=tuple(compared),
        reason=reason,
        request_id=left.request_id,
        obligation_id=left.obligation_id or right.obligation_id,
        analysis_outcome=analysis,
        attributes={"field_detail": detail},
    )


def run_differential(
    request: SimulationRequest,
    left: OfflineSandbox,
    right: OfflineSandbox,
    *,
    result_id: str,
    left_receipt_id: str | None = None,
    right_receipt_id: str | None = None,
) -> tuple[SimulationReceipt, SimulationReceipt, DifferentialResult]:
    """Run the same request on two sandboxes and compare receipts."""

    try:
        left_receipt = run_simulation(
            request,
            left,
            receipt_id=left_receipt_id or f"receipt.sim.left.{request.request_id}",
        )
        right_receipt = run_simulation(
            request,
            right,
            receipt_id=right_receipt_id or f"receipt.sim.right.{request.request_id}",
        )
    except SimulationError as exc:
        raise DifferentialError(str(exc)) from exc

    result = compare_receipts(
        left_receipt,
        right_receipt,
        result_id=result_id,
    )
    return left_receipt, right_receipt, result


__all__ = [
    "CRYPTO_IR_DIFFERENTIAL_DOMAIN",
    "CRYPTO_IR_DIFFERENTIAL_SCHEMA_VERSION",
    "DIFFERENTIAL_RESULT_SCHEMA_VERSION",
    "DifferentialError",
    "DifferentialResult",
    "DifferentialStatus",
    "compare_receipts",
    "run_differential",
]
