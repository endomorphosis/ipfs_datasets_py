"""Typed, persistable receipts for Legal IR hammer translation.

The generic hammer objects contain the solver input and reconstruction object
needed while a proof search is running.  This module projects those objects to
stable records suitable for reports, telemetry, and training artifacts.  The
projection deliberately stores hashes and byte counts instead of copied legal
statements or complete solver/proof payloads.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Mapping, Optional, Sequence

from .hammer import HammerResult, HammerStatus, HammerTranslation


LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION: Final = "legal-ir-hammer-translation-v1"
LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION: Final = (
    "legal-ir-hammer-reconstruction-receipt-v1"
)


class HammerTranslationSurface(str, Enum):
    """Typed translation surfaces retained by the Legal IR hammer."""

    SMT_LIB = "smt-lib"
    TPTP = "tptp"
    LEAN = "lean"
    OTHER = "other"


class HammerTranslationDecisionStatus(str, Enum):
    """Whether a semantics-changing translation decision was taken."""

    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


class HammerReconstructionOutcome(str, Enum):
    """Mutually exclusive headline outcome for one hammer obligation."""

    TRANSLATION_FAILURE = "translation_failure"
    NO_BACKEND_PROOF = "no_backend_proof"
    BACKEND_PROOF = "backend_proof"
    NATIVE_RECONSTRUCTION = "native_reconstruction"
    NATIVE_RECONSTRUCTION_FAILED = "native_reconstruction_failed"


class HammerTrustStatus(str, Enum):
    """Persisted trust decision, kept separate from proof-search success."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _content_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _surface_for_format(target_format: str) -> HammerTranslationSurface:
    normalized = str(target_format or "").strip().lower()
    if normalized in {"smt", "smt-lib", "smt2", "z3", "cvc5"}:
        return HammerTranslationSurface.SMT_LIB
    if normalized in {"tptp", "tptp-fof", "fof", "vampire", "e", "e_prover"}:
        return HammerTranslationSurface.TPTP
    if normalized in {"lean", "lean4"}:
        return HammerTranslationSurface.LEAN
    return HammerTranslationSurface.OTHER


def _status(
    value: Any,
    default: HammerTranslationDecisionStatus,
) -> HammerTranslationDecisionStatus:
    if isinstance(value, HammerTranslationDecisionStatus):
        return value
    normalized = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "applied": HammerTranslationDecisionStatus.APPLIED,
        "enabled": HammerTranslationDecisionStatus.APPLIED,
        "true": HammerTranslationDecisionStatus.APPLIED,
        "not_applied": HammerTranslationDecisionStatus.NOT_APPLIED,
        "disabled": HammerTranslationDecisionStatus.NOT_APPLIED,
        "false": HammerTranslationDecisionStatus.NOT_APPLIED,
        "skipped": HammerTranslationDecisionStatus.NOT_APPLIED,
        "not_applicable": HammerTranslationDecisionStatus.NOT_APPLICABLE,
        "n/a": HammerTranslationDecisionStatus.NOT_APPLICABLE,
        "failed": HammerTranslationDecisionStatus.FAILED,
        "error": HammerTranslationDecisionStatus.FAILED,
    }
    return aliases.get(normalized, default)


@dataclass(frozen=True)
class HammerTranslationDecision:
    """Auditable decision for one encoding transformation."""

    name: str
    status: HammerTranslationDecisionStatus
    applicable: bool
    applied: bool
    rationale: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "applicable": bool(self.applicable),
            "applied": bool(self.applied),
            "details": dict(sorted(self.details.items())),
            "name": self.name,
            "rationale": self.rationale,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HammerTranslationDecision":
        status = _status(data.get("status"), HammerTranslationDecisionStatus.NOT_APPLIED)
        return cls(
            name=str(data.get("name") or ""),
            status=status,
            applicable=bool(
                data.get(
                    "applicable",
                    status != HammerTranslationDecisionStatus.NOT_APPLICABLE,
                )
            ),
            applied=bool(data.get("applied", status == HammerTranslationDecisionStatus.APPLIED)),
            rationale=str(data.get("rationale") or ""),
            details=dict(data.get("details") or {}),
        )


def _default_decision(name: str) -> HammerTranslationDecision:
    return HammerTranslationDecision(
        name=name,
        status=HammerTranslationDecisionStatus.NOT_APPLICABLE,
        applicable=False,
        applied=False,
        rationale="decision_not_recorded",
    )


@dataclass(frozen=True)
class HammerTranslationRecord:
    """Source-free record for an SMT-LIB, TPTP, or Lean artifact."""

    translation_id: str
    obligation_id: str
    input_formula_id: str
    surface: HammerTranslationSurface
    target_format: str
    success: bool
    artifact_sha256: str
    artifact_size_bytes: int
    selected_premises: tuple[str, ...] = ()
    monomorphization: HammerTranslationDecision = field(
        default_factory=lambda: _default_decision("monomorphization")
    )
    type_encoding: HammerTranslationDecision = field(
        default_factory=lambda: _default_decision("type_encoding")
    )
    lambda_elimination: HammerTranslationDecision = field(
        default_factory=lambda: _default_decision("lambda_elimination")
    )
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION

    @property
    def record_id(self) -> str:
        """Compatibility alias for callers that call every persisted object a record."""

        return self.translation_id

    @property
    def transformation_decisions(self) -> tuple[HammerTranslationDecision, ...]:
        return (self.monomorphization, self.type_encoding, self.lambda_elimination)

    @property
    def decisions(self) -> Mapping[str, HammerTranslationDecision]:
        return {decision.name: decision for decision in self.transformation_decisions}

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "artifact_size_bytes": int(self.artifact_size_bytes),
            "decisions": {
                decision.name: decision.to_dict()
                for decision in self.transformation_decisions
            },
            "errors": list(self.errors),
            "input_formula_id": self.input_formula_id,
            "metadata": dict(sorted(self.metadata.items())),
            "obligation_id": self.obligation_id,
            "schema_version": self.schema_version,
            "selected_premises": list(self.selected_premises),
            "success": bool(self.success),
            "surface": self.surface.value,
            "target_format": self.target_format,
            "translation_id": self.translation_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HammerTranslationRecord":
        decisions = dict(data.get("decisions") or {})

        def decision(name: str) -> HammerTranslationDecision:
            value = decisions.get(name)
            if isinstance(value, Mapping):
                return HammerTranslationDecision.from_dict({"name": name, **dict(value)})
            return _default_decision(name)

        surface_text = str(data.get("surface") or HammerTranslationSurface.OTHER.value)
        try:
            surface = HammerTranslationSurface(surface_text)
        except ValueError:
            surface = _surface_for_format(surface_text)
        return cls(
            translation_id=str(data.get("translation_id") or data.get("record_id") or ""),
            obligation_id=str(data.get("obligation_id") or ""),
            input_formula_id=str(data.get("input_formula_id") or ""),
            surface=surface,
            target_format=str(data.get("target_format") or surface_text),
            success=bool(data.get("success")),
            artifact_sha256=str(data.get("artifact_sha256") or ""),
            artifact_size_bytes=int(data.get("artifact_size_bytes") or 0),
            selected_premises=tuple(str(item) for item in data.get("selected_premises", []) or []),
            monomorphization=decision("monomorphization"),
            type_encoding=decision("type_encoding"),
            lambda_elimination=decision("lambda_elimination"),
            errors=tuple(str(item) for item in data.get("errors", []) or []),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(
                data.get("schema_version") or LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True)
class HammerReconstructionReceipt:
    """Proof/trust receipt for one obligation, independent of solver success."""

    receipt_id: str
    obligation_id: str
    input_formula_id: str
    outcome: HammerReconstructionOutcome
    translation_succeeded: bool
    translation_failed: bool
    backend_proved: bool
    native_reconstruction: bool
    native_reconstruction_verified: bool
    trusted: bool
    trust_status: HammerTrustStatus
    trust_reason: str
    backend: str = ""
    backend_statuses: Mapping[str, str] = field(default_factory=dict)
    reconstruction_status: str = ""
    checker: str = ""
    translation_record_ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION

    @property
    def native_reconstructed(self) -> bool:
        """Readable alias retained for consumers that use past-tense fields."""

        return self.native_reconstruction

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "backend_proved": bool(self.backend_proved),
            "backend_statuses": dict(sorted(self.backend_statuses.items())),
            "checker": self.checker,
            "errors": list(self.errors),
            "input_formula_id": self.input_formula_id,
            "metadata": dict(sorted(self.metadata.items())),
            "native_reconstruction": bool(self.native_reconstruction),
            "native_reconstruction_verified": bool(self.native_reconstruction_verified),
            "obligation_id": self.obligation_id,
            "outcome": self.outcome.value,
            "receipt_id": self.receipt_id,
            "reconstruction_status": self.reconstruction_status,
            "schema_version": self.schema_version,
            "translation_failed": bool(self.translation_failed),
            "translation_record_ids": list(self.translation_record_ids),
            "translation_succeeded": bool(self.translation_succeeded),
            "trust_reason": self.trust_reason,
            "trust_status": self.trust_status.value,
            "trusted": bool(self.trusted),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HammerReconstructionReceipt":
        try:
            outcome = HammerReconstructionOutcome(str(data.get("outcome") or ""))
        except ValueError:
            outcome = HammerReconstructionOutcome.NO_BACKEND_PROOF
        try:
            trust_status = HammerTrustStatus(str(data.get("trust_status") or ""))
        except ValueError:
            trust_status = (
                HammerTrustStatus.TRUSTED if data.get("trusted") else HammerTrustStatus.UNTRUSTED
            )
        return cls(
            receipt_id=str(data.get("receipt_id") or ""),
            obligation_id=str(data.get("obligation_id") or ""),
            input_formula_id=str(data.get("input_formula_id") or ""),
            outcome=outcome,
            translation_succeeded=bool(data.get("translation_succeeded")),
            translation_failed=bool(data.get("translation_failed")),
            backend_proved=bool(data.get("backend_proved")),
            native_reconstruction=bool(
                data.get("native_reconstruction", data.get("native_reconstructed", False))
            ),
            native_reconstruction_verified=bool(data.get("native_reconstruction_verified")),
            trusted=bool(data.get("trusted")),
            trust_status=trust_status,
            trust_reason=str(data.get("trust_reason") or ""),
            backend=str(data.get("backend") or ""),
            backend_statuses={
                str(key): str(value)
                for key, value in dict(data.get("backend_statuses") or {}).items()
            },
            reconstruction_status=str(data.get("reconstruction_status") or ""),
            checker=str(data.get("checker") or ""),
            translation_record_ids=tuple(
                str(item) for item in data.get("translation_record_ids", []) or []
            ),
            errors=tuple(str(item) for item in data.get("errors", []) or []),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(
                data.get("schema_version")
                or LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION
            ),
        )


def _decision_from_translation(
    translation: HammerTranslation,
    name: str,
    *,
    applicable: bool,
) -> HammerTranslationDecision:
    metadata = dict(translation.metadata or {})
    explicit_decisions = metadata.get("translation_decisions")
    explicit = explicit_decisions.get(name) if isinstance(explicit_decisions, Mapping) else None
    details: dict[str, Any] = {}
    rationale = ""

    if isinstance(explicit, Mapping):
        explicit_map = dict(explicit)
        explicit_status = explicit_map.pop("status", None)
        explicit_applied = explicit_map.pop("applied", None)
        explicit_applicable = explicit_map.pop("applicable", applicable)
        rationale = str(explicit_map.pop("rationale", "explicit_translation_decision"))
        details = explicit_map
        if explicit_status is None and explicit_applied is not None:
            explicit_status = "applied" if explicit_applied else "not_applied"
        default = (
            HammerTranslationDecisionStatus.APPLIED
            if name in translation.transformations
            else HammerTranslationDecisionStatus.NOT_APPLIED
        )
        status = _status(explicit_status, default)
        applicable = bool(explicit_applicable)
    elif explicit is not None:
        status = _status(
            explicit,
            HammerTranslationDecisionStatus.APPLIED
            if bool(explicit)
            else HammerTranslationDecisionStatus.NOT_APPLIED,
        )
        rationale = "explicit_translation_decision"
    elif not applicable:
        status = HammerTranslationDecisionStatus.NOT_APPLICABLE
        rationale = "native_surface_preserves_source_types"
    elif not translation.success:
        status = HammerTranslationDecisionStatus.FAILED
        rationale = "translation_failed_before_decision_completed"
    else:
        applied = name in {str(item) for item in translation.transformations}
        status = (
            HammerTranslationDecisionStatus.APPLIED
            if applied
            else HammerTranslationDecisionStatus.NOT_APPLIED
        )
        rationale = "recorded_by_hammer_translator" if applied else "not_requested_by_translator"

    if not applicable:
        status = HammerTranslationDecisionStatus.NOT_APPLICABLE
    return HammerTranslationDecision(
        name=name,
        status=status,
        applicable=applicable,
        applied=status == HammerTranslationDecisionStatus.APPLIED,
        rationale=rationale,
        details=details,
    )


def _translation_record(
    result: HammerResult,
    translation: HammerTranslation,
    *,
    obligation_id: str,
    input_formula_id: str,
) -> HammerTranslationRecord:
    surface = _surface_for_format(translation.target_format)
    content = str(translation.problem or "")
    premise_names = tuple(premise.name for premise in translation.selected_premises)
    decisions = {
        name: _decision_from_translation(
            translation,
            name,
            applicable=surface != HammerTranslationSurface.LEAN,
        )
        for name in ("monomorphization", "type_encoding", "lambda_elimination")
    }
    record_payload = {
        "artifact_sha256": _content_hash(content),
        "decisions": {
            name: decision.to_dict()
            for name, decision in sorted(decisions.items())
        },
        "errors": [str(item) for item in translation.errors],
        "input_formula_id": input_formula_id,
        "obligation_id": obligation_id,
        "success": bool(translation.success),
        "surface": surface.value,
        "target_format": translation.target_format,
    }
    return HammerTranslationRecord(
        translation_id=f"hammer-translation-{_stable_hash(record_payload)[:20]}",
        obligation_id=obligation_id,
        input_formula_id=input_formula_id,
        surface=surface,
        target_format=str(translation.target_format),
        success=bool(translation.success),
        artifact_sha256=record_payload["artifact_sha256"],
        artifact_size_bytes=len(content.encode("utf-8")),
        selected_premises=premise_names,
        monomorphization=decisions["monomorphization"],
        type_encoding=decisions["type_encoding"],
        lambda_elimination=decisions["lambda_elimination"],
        errors=tuple(str(item) for item in translation.errors),
        metadata={
            "goal_name": result.goal.name,
            "goal_statement_sha256": _content_hash(result.goal.statement),
        },
    )


def _lean_reconstruction_record(
    result: HammerResult,
    *,
    obligation_id: str,
    input_formula_id: str,
) -> Optional[HammerTranslationRecord]:
    reconstruction = result.reconstruction
    if reconstruction is None or str(reconstruction.itp_system or "").strip().lower() not in {
        "lean",
        "lean4",
    }:
        return None
    content = str(reconstruction.proof_script or "")
    artifact_hash = _content_hash(content)
    record_payload = {
        "artifact_sha256": artifact_hash,
        "backend": reconstruction.backend,
        "input_formula_id": input_formula_id,
        "obligation_id": obligation_id,
        "surface": HammerTranslationSurface.LEAN.value,
    }
    decision_values = {
        name: HammerTranslationDecision(
            name=name,
            status=HammerTranslationDecisionStatus.NOT_APPLICABLE,
            applicable=False,
            applied=False,
            rationale="native_lean_reconstruction_preserves_source_types",
        )
        for name in ("monomorphization", "type_encoding", "lambda_elimination")
    }
    return HammerTranslationRecord(
        translation_id=f"hammer-translation-{_stable_hash(record_payload)[:20]}",
        obligation_id=obligation_id,
        input_formula_id=input_formula_id,
        surface=HammerTranslationSurface.LEAN,
        target_format="lean",
        success=bool(content),
        artifact_sha256=artifact_hash,
        artifact_size_bytes=len(content.encode("utf-8")),
        selected_premises=tuple(str(item) for item in reconstruction.used_premises),
        monomorphization=decision_values["monomorphization"],
        type_encoding=decision_values["type_encoding"],
        lambda_elimination=decision_values["lambda_elimination"],
        errors=(str(reconstruction.error),) if reconstruction.error else (),
        metadata={
            "backend": reconstruction.backend,
            "goal_name": result.goal.name,
            "native_reconstruction_verified": bool(reconstruction.verified),
            "reconstruction_status": reconstruction.status,
        },
    )


def translation_records_from_hammer_result(
    result: HammerResult,
    *,
    obligation_id: str = "",
    input_formula_id: str = "",
) -> list[HammerTranslationRecord]:
    """Project all solver translations and a generated Lean script to records."""

    resolved_obligation_id = str(
        obligation_id
        or result.goal.metadata.get("obligation_id")
        or result.goal.name
    )
    resolved_formula_id = str(
        input_formula_id
        or result.goal.metadata.get("input_formula_id")
        or result.goal.metadata.get("formula_id")
        or ""
    )
    records = [
        _translation_record(
            result,
            translation,
            obligation_id=resolved_obligation_id,
            input_formula_id=resolved_formula_id,
        )
        for _, translation in sorted(result.translations.items(), key=lambda item: str(item[0]))
    ]
    lean_record = _lean_reconstruction_record(
        result,
        obligation_id=resolved_obligation_id,
        input_formula_id=resolved_formula_id,
    )
    if lean_record is not None:
        records.append(lean_record)
    return records


def reconstruction_receipt_from_hammer_result(
    result: HammerResult,
    *,
    translation_records: Optional[Sequence[HammerTranslationRecord]] = None,
    obligation_id: str = "",
    input_formula_id: str = "",
    trusted_requires_reconstruction: bool = False,
    trusted: Optional[bool] = None,
) -> HammerReconstructionReceipt:
    """Build one explicit proof/reconstruction/trust receipt for ``result``."""

    records = list(
        translation_records
        if translation_records is not None
        else translation_records_from_hammer_result(
            result,
            obligation_id=obligation_id,
            input_formula_id=input_formula_id,
        )
    )
    resolved_obligation_id = str(
        obligation_id
        or result.goal.metadata.get("obligation_id")
        or result.goal.name
    )
    resolved_formula_id = str(
        input_formula_id
        or result.goal.metadata.get("input_formula_id")
        or result.goal.metadata.get("formula_id")
        or ""
    )
    statuses = {
        str(item.backend): _enum_value(item.status)
        for item in result.backend_results
    }
    winner = next((item for item in result.backend_results if item.proved), None)
    backend_proved = winner is not None
    reconstruction = result.reconstruction
    native_reconstruction = reconstruction is not None
    native_verified = bool(reconstruction and reconstruction.verified)
    translation_failed = result.status == HammerStatus.TRANSLATION_FAILED or (
        bool(result.translations)
        and not any(item.success for item in result.translations.values())
    )
    translation_succeeded = bool(result.translations) and any(
        item.success for item in result.translations.values()
    )

    if translation_failed:
        outcome = HammerReconstructionOutcome.TRANSLATION_FAILURE
    elif result.status == HammerStatus.RECONSTRUCTION_FAILED:
        outcome = HammerReconstructionOutcome.NATIVE_RECONSTRUCTION_FAILED
    elif native_verified:
        outcome = HammerReconstructionOutcome.NATIVE_RECONSTRUCTION
    elif backend_proved:
        outcome = HammerReconstructionOutcome.BACKEND_PROOF
    else:
        outcome = HammerReconstructionOutcome.NO_BACKEND_PROOF

    policy_trusted = bool(
        result.status == HammerStatus.PROVED
        and backend_proved
        and (native_verified or not trusted_requires_reconstruction)
    )
    # An upstream sanitizer may revoke trust (for example, after detecting a
    # copied source span), but it may never elevate a result beyond this proof
    # and reconstruction policy.
    trusted_value = policy_trusted if trusted is None else policy_trusted and bool(trusted)

    if trusted_value and native_verified:
        trust_reason = "native_reconstruction_verified"
    elif trusted_value:
        trust_reason = "backend_proof_accepted_by_policy"
    elif translation_failed:
        trust_reason = "translation_failed"
    elif result.status == HammerStatus.RECONSTRUCTION_FAILED:
        trust_reason = "native_reconstruction_failed"
    elif backend_proved and trusted_requires_reconstruction:
        trust_reason = "native_reconstruction_required"
    elif not backend_proved:
        trust_reason = "backend_proof_missing"
    else:
        trust_reason = "proof_not_trusted"

    errors: list[str] = []
    for translation in result.translations.values():
        errors.extend(str(item) for item in translation.errors if str(item))
    errors.extend(str(item.error) for item in result.backend_results if str(item.error))
    if reconstruction is not None and reconstruction.error:
        errors.append(str(reconstruction.error))
    verification = getattr(reconstruction, "verification", None)
    checker = str(getattr(verification, "checker", "") or "")
    receipt_payload = {
        "backend_statuses": statuses,
        "obligation_id": resolved_obligation_id,
        "outcome": outcome.value,
        "translation_record_ids": [item.translation_id for item in records],
        "trust_status": (
            HammerTrustStatus.TRUSTED.value
            if trusted_value
            else HammerTrustStatus.UNTRUSTED.value
        ),
    }
    return HammerReconstructionReceipt(
        receipt_id=f"hammer-receipt-{_stable_hash(receipt_payload)[:20]}",
        obligation_id=resolved_obligation_id,
        input_formula_id=resolved_formula_id,
        outcome=outcome,
        translation_succeeded=translation_succeeded,
        translation_failed=translation_failed,
        backend_proved=backend_proved,
        native_reconstruction=native_reconstruction,
        native_reconstruction_verified=native_verified,
        trusted=trusted_value,
        trust_status=(
            HammerTrustStatus.TRUSTED if trusted_value else HammerTrustStatus.UNTRUSTED
        ),
        trust_reason=trust_reason,
        backend=str(getattr(winner, "backend", "") or result.metadata.get("winner_backend") or ""),
        backend_statuses=statuses,
        reconstruction_status=str(getattr(reconstruction, "status", "") or ""),
        checker=checker,
        translation_record_ids=tuple(item.translation_id for item in records),
        errors=tuple(dict.fromkeys(errors)),
        metadata={
            "hammer_status": _enum_value(result.status),
            "trusted_requires_reconstruction": bool(trusted_requires_reconstruction),
        },
    )


# Legal-IR-prefixed names and builder spellings are exported for callers that
# prefer domain-specific symbols over the shorter receipt names.
LegalIRHammerTranslationSurface = HammerTranslationSurface
LegalIRHammerTranslationDecision = HammerTranslationDecision
LegalIRHammerTranslationRecord = HammerTranslationRecord
LegalIRHammerReconstructionOutcome = HammerReconstructionOutcome
LegalIRHammerReconstructionReceipt = HammerReconstructionReceipt
LegalIRHammerTrustStatus = HammerTrustStatus
build_legal_ir_hammer_translation_records = translation_records_from_hammer_result
build_legal_ir_hammer_reconstruction_receipt = reconstruction_receipt_from_hammer_result


__all__ = [
    "LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION",
    "LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION",
    "HammerReconstructionOutcome",
    "HammerReconstructionReceipt",
    "HammerTranslationDecision",
    "HammerTranslationDecisionStatus",
    "HammerTranslationRecord",
    "HammerTranslationSurface",
    "HammerTrustStatus",
    "LegalIRHammerReconstructionOutcome",
    "LegalIRHammerReconstructionReceipt",
    "LegalIRHammerTranslationDecision",
    "LegalIRHammerTranslationRecord",
    "LegalIRHammerTranslationSurface",
    "LegalIRHammerTrustStatus",
    "build_legal_ir_hammer_reconstruction_receipt",
    "build_legal_ir_hammer_translation_records",
    "reconstruction_receipt_from_hammer_result",
    "translation_records_from_hammer_result",
]
