"""Immutable compliance decision receipts (CRYPTOIR-G440).

Receipts bind a :class:`ComplianceDecision` (and optional explanation) into a
canonical byte sequence that reproduces **byte-for-byte** across re-issue from
the same decision payload.  Receipts are evidence of what was decided under
which bindings; they are not transaction authorization and not legal
certification.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.crypto_ir.identity import crypto_ir_identity
from ipfs_datasets_py.logic.crypto_ir.provenance import AuthorityKind
from ipfs_datasets_py.logic.crypto_ir.schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes

from .decisions import (
    COMPLIANCE_DECISION_SCHEMA_VERSION,
    ComplianceDecision,
    DecisionError,
    SanctionsPolicyOutcome,
    _digest,
    _identifier,
    _instant,
    _known,
    _mapping,
    _text,
)
from .explain import (
    COMPLIANCE_EXPLAIN_SCHEMA_VERSION,
    ComplianceExplanation,
    explain_decision,
)
from .models import CRYPTO_IR_COMPLIANCE_DOMAIN


COMPLIANCE_RECEIPT_SCHEMA_VERSION: Final[str] = (
    "ipfs-datasets.crypto-ir.compliance-receipt@1.0.0"
)


class ReceiptError(DecisionError):
    """Raised when a receipt is malformed or fails byte reproduction."""


@dataclass(frozen=True, slots=True)
class ComplianceReceipt:
    """Immutable, content-addressed receipt for one compliance decision.

    The receipt body is defined solely by the canonical JSON of
    :meth:`receipt_body`.  :attr:`content_digest` and :attr:`canonical_bytes`
    are pure functions of that body.  Re-issuing from the same decision (and
    explanation digest inputs) yields identical bytes.
    """

    receipt_id: str
    decision_id: str
    outcome: SanctionsPolicyOutcome
    decision: ComplianceDecision
    decision_content_digest: str
    evidentiary_boundary_digest: str
    explanation_digest: str
    issued_at: str
    schema_version: str = COMPLIANCE_RECEIPT_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.RESULT

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self, "decision_id", _identifier(self.decision_id, "decision_id")
        )
        if not isinstance(self.outcome, SanctionsPolicyOutcome):
            object.__setattr__(
                self, "outcome", SanctionsPolicyOutcome(self.outcome)
            )
        if not isinstance(self.decision, ComplianceDecision):
            object.__setattr__(
                self,
                "decision",
                ComplianceDecision.from_dict(_mapping(self.decision, "decision")),
            )
        if self.decision.decision_id != self.decision_id:
            raise ReceiptError("receipt decision_id does not match decision")
        if self.decision.outcome is not self.outcome:
            raise ReceiptError("receipt outcome does not match decision outcome")
        object.__setattr__(
            self,
            "decision_content_digest",
            _digest(self.decision_content_digest, "decision_content_digest"),
        )
        if self.decision_content_digest != self.decision.content_digest:
            raise ReceiptError(
                "decision_content_digest does not match decision.content_digest"
            )
        object.__setattr__(
            self,
            "evidentiary_boundary_digest",
            _digest(
                self.evidentiary_boundary_digest, "evidentiary_boundary_digest"
            ),
        )
        if (
            self.evidentiary_boundary_digest
            != self.decision.evidentiary_boundary_digest
        ):
            raise ReceiptError(
                "evidentiary_boundary_digest does not match decision bindings"
            )
        object.__setattr__(
            self,
            "explanation_digest",
            _digest(self.explanation_digest, "explanation_digest"),
        )
        object.__setattr__(self, "issued_at", _instant(self.issued_at, "issued_at"))
        if self.schema_version != COMPLIANCE_RECEIPT_SCHEMA_VERSION:
            raise ReceiptError(
                f"unsupported compliance receipt schema: {self.schema_version}"
            )

    def receipt_body(self) -> dict[str, Any]:
        """Canonical receipt body (excludes derived receipt_id/digest fields).

        ``issued_at`` is included so that time-bound audit copies are explicit;
        for pure content reproduction of the *decision*, compare
        ``decision_content_digest`` and ``canonical_decision_bytes``.
        """

        return {
            "decision": self.decision.to_dict(),
            "decision_content_digest": self.decision_content_digest,
            "decision_id": self.decision_id,
            "evidentiary_boundary_digest": self.evidentiary_boundary_digest,
            "explanation_digest": self.explanation_digest,
            "issued_at": self.issued_at,
            "outcome": self.outcome.value,
            "schema_version": self.schema_version,
        }

    @property
    def canonical_bytes(self) -> bytes:
        """Canonical JSON UTF-8 bytes of the receipt body (byte-stable)."""

        return canonical_json_bytes(self.receipt_body())

    @property
    def content_digest(self) -> str:
        digest = hashlib.sha256(self.canonical_bytes).hexdigest()
        return f"sha256:{digest}"

    @property
    def canonical_decision_bytes(self) -> bytes:
        """Canonical bytes of the embedded decision alone."""

        return canonical_json_bytes(self.decision.to_dict())

    @property
    def is_legal_certification(self) -> bool:
        return False

    def can_authorize_transaction(self) -> bool:
        return False

    @property
    def identity(self):
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=f"{CRYPTO_IR_COMPLIANCE_DOMAIN}.receipt",
        )

    def to_dict(self) -> dict[str, Any]:
        body = self.receipt_body()
        body["receipt_id"] = self.receipt_id
        body["content_digest"] = self.content_digest
        body["is_legal_certification"] = self.is_legal_certification
        body["can_authorize_transaction"] = self.can_authorize_transaction()
        return body

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComplianceReceipt":
        value = _mapping(value, "ComplianceReceipt")
        fields = frozenset(
            {
                "receipt_id",
                "decision_id",
                "outcome",
                "decision",
                "decision_content_digest",
                "evidentiary_boundary_digest",
                "explanation_digest",
                "issued_at",
                "schema_version",
                "content_digest",
                "is_legal_certification",
                "can_authorize_transaction",
            }
        )
        _known(value, fields, "ComplianceReceipt")
        return cls(
            receipt_id=value.get("receipt_id", ""),
            decision_id=value.get("decision_id", ""),
            outcome=value.get("outcome", ""),
            decision=ComplianceDecision.from_dict(value.get("decision", {})),
            decision_content_digest=value.get("decision_content_digest", ""),
            evidentiary_boundary_digest=value.get(
                "evidentiary_boundary_digest", ""
            ),
            explanation_digest=value.get("explanation_digest", ""),
            issued_at=value.get("issued_at", ""),
            schema_version=value.get(
                "schema_version", COMPLIANCE_RECEIPT_SCHEMA_VERSION
            ),
        )

    def verify_bytes(self, other: bytes) -> bool:
        """True when ``other`` matches this receipt's canonical bytes exactly."""

        return other == self.canonical_bytes

    def verify_decision_digest(self) -> bool:
        """Recompute and check the embedded decision content digest."""

        return self.decision.content_digest == self.decision_content_digest


def _explanation_digest(explanation: ComplianceExplanation) -> str:
    payload = explanation.to_dict()
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return f"sha256:{digest}"


def _receipt_id(
    *,
    decision: ComplianceDecision,
    explanation_digest: str,
    issued_at: str,
) -> str:
    material = "\x00".join(
        (
            decision.decision_id,
            decision.content_digest,
            decision.evidentiary_boundary_digest,
            explanation_digest,
            issued_at,
            COMPLIANCE_RECEIPT_SCHEMA_VERSION,
        )
    ).encode("utf-8")
    return f"compliance-receipt:{hashlib.sha256(material).hexdigest()}"


def issue_compliance_receipt(
    decision: ComplianceDecision,
    *,
    issued_at: str,
    explanation: ComplianceExplanation | None = None,
) -> ComplianceReceipt:
    """Issue an immutable receipt for a decision.

    When ``explanation`` is omitted, one is derived via
    :func:`explain_decision`.  The same decision + issued_at + explanation
    payload always yields the same receipt id and canonical bytes.
    """

    if not isinstance(decision, ComplianceDecision):
        raise ReceiptError("decision must be a ComplianceDecision")
    issued_at = _instant(issued_at, "issued_at")
    if explanation is None:
        explanation = explain_decision(decision)
    elif not isinstance(explanation, ComplianceExplanation):
        raise ReceiptError("explanation must be a ComplianceExplanation")
    if explanation.decision_id != decision.decision_id:
        raise ReceiptError("explanation decision_id does not match decision")
    if explanation.outcome is not decision.outcome:
        raise ReceiptError("explanation outcome does not match decision")

    expl_digest = _explanation_digest(explanation)
    receipt_id = _receipt_id(
        decision=decision,
        explanation_digest=expl_digest,
        issued_at=issued_at,
    )
    return ComplianceReceipt(
        receipt_id=receipt_id,
        decision_id=decision.decision_id,
        outcome=decision.outcome,
        decision=decision,
        decision_content_digest=decision.content_digest,
        evidentiary_boundary_digest=decision.evidentiary_boundary_digest,
        explanation_digest=expl_digest,
        issued_at=issued_at,
    )


def reproduce_receipt_bytes(receipt: ComplianceReceipt) -> bytes:
    """Recompute canonical receipt bytes (must match ``receipt.canonical_bytes``)."""

    if not isinstance(receipt, ComplianceReceipt):
        raise ReceiptError("receipt must be a ComplianceReceipt")
    # Rebuild from dict and compare identity of body encoding.
    rebuilt = ComplianceReceipt.from_dict(receipt.to_dict())
    return rebuilt.canonical_bytes


def assert_receipt_byte_identical(
    left: ComplianceReceipt, right: ComplianceReceipt
) -> None:
    """Fail closed unless two receipts produce identical canonical bytes."""

    if left.canonical_bytes != right.canonical_bytes:
        raise ReceiptError(
            "receipts are not byte-identical: "
            f"{left.content_digest} != {right.content_digest}"
        )


__all__ = [
    "COMPLIANCE_RECEIPT_SCHEMA_VERSION",
    "COMPLIANCE_DECISION_SCHEMA_VERSION",
    "COMPLIANCE_EXPLAIN_SCHEMA_VERSION",
    "ComplianceReceipt",
    "ReceiptError",
    "assert_receipt_byte_identical",
    "issue_compliance_receipt",
    "reproduce_receipt_bytes",
]
