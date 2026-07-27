"""Prover-gated Codex packet contract for plateau-break supervisor work.

Interface: ``PlateauCodexPacket@1``

Teachers (spaCy, autoencoder, Leanstral) and residual forensics produce
proposals.  Hammer/cvc5/Lean structural admission gates those proposals.
Only **accepted** admissions may mark a packet ``implementable=true`` for
agent-supervisor deterministic compiler/decompiler edits.

Fail-closed rules (normative):

* disposition ``validator_reject`` / ``timeout`` / ``error`` →
  ``implementable=false`` (edit authority denied);
* prover receipts always carry ``semantic_authority=false`` — a proof pass
  never lowers end-to-end semantic loss by itself;
* admitted ΔL1 is expressed only as ``CanonicalFieldChange`` records;
* packets are content-addressed via a stable SHA-256 digest of the
  canonical JSON payload (excluding the digest field itself).

Supervisor consumption (PLAT-070 materializer):

* ``implementable=true`` → lease a task with ``predicted_files`` limited to
  deterministic compiler/realizer/tests and run ``validation_commands``;
* ``implementable=false`` → emit obligation-only notes from
  ``proof_obligation_ids``; never silent-merge.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from benchmarks.semantic_roundtrip.constructors.autoencoder_guided import (
    CanonicalFieldChange,
    canonical_field_changes,
)
from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRuleIR,
    ContractError,
)
from benchmarks.semantic_roundtrip.evaluation_status import (
    DEFAULT_DETERMINISTIC_BASELINE_ARM_ID,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    DECLARED_STRUCTURAL_CONSTRAINTS,
    StructuralTool,
)
from benchmarks.semantic_roundtrip.structural_admission import (
    STRUCTURAL_ADMISSION_RECEIPT_INTERFACE,
    AdmissionCheckReceipt,
    AdmissionDisposition,
    StructuralAdmissionResult,
    VALIDATOR_REJECT,
)


PLATEAU_CODEX_PACKET_INTERFACE: Final = "PlateauCodexPacket@1"
PLATEAU_CODEX_PACKET_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-plateau-codex-packet.v1"
)
PLATEAU_RESIDUAL_REF_INTERFACE: Final = "PlateauResidualRef@1"
PLATEAU_TEACHER_PROPOSAL_INTERFACE: Final = "PlateauTeacherProposal@1"
PLATEAU_PROOF_OBLIGATION_INTERFACE: Final = "PlateauProofObligation@1"
PLATEAU_ADMISSION_RECEIPT_INTERFACE: Final = (
    "PlateauAdmissionReceipt@1"
)
PLATEAU_CODEX_PACKET_EVIDENCE: Final = "PLATEV020PKT"

DEFAULT_BASELINE_ARM_ID: Final = DEFAULT_DETERMINISTIC_BASELINE_ARM_ID
DEFAULT_BASELINE_E2E: Final = 0.088333333

# Closed set of teacher identities that may author proposals.
KNOWN_TEACHERS: Final = frozenset(
    {
        "leanstral",
        "symai",
        "spacy",
        "autoencoder",
        "residual_catalog",
        "manual",
        "hybrid",
    }
)

# Fail-closed dispositions that can never authorize implementable work.
NON_IMPLEMENTABLE_DISPOSITIONS: Final = frozenset(
    {
        AdmissionDisposition.VALIDATOR_REJECT,
        AdmissionDisposition.TIMEOUT,
        AdmissionDisposition.ERROR,
        AdmissionDisposition.NOT_APPLICABLE,
    }
)

# Predicted edit targets must stay inside the deterministic improvement surface.
ALLOWED_PREDICTED_FILE_PREFIXES: Final = (
    "benchmarks/semantic_roundtrip/constructors/",
    "benchmarks/semantic_roundtrip/realizers/",
    "benchmarks/semantic_roundtrip/",
    "tests/unit/benchmarks/semantic_roundtrip/",
    "docs/benchmarks/",
)

DEFAULT_PREDICTED_FILES: Final = (
    "benchmarks/semantic_roundtrip/constructors/typed_deontic.py",
    "tests/unit/benchmarks/semantic_roundtrip/",
)

DEFAULT_VALIDATION_COMMANDS: Final = (
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_structural_admission.py -q",
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py -q",
)

_OBLIGATION_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PACKET_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HEX64_RE: Final = re.compile(r"^[0-9a-f]{64}$")


class PlateauCodexPacketError(ContractError):
    """Contract violation in PlateauCodexPacket@1 construction or parsing."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlateauCodexPacketError(f"{field} must be a nonblank string")
    return value.strip()


def _optional_nonblank(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _nonblank(value, field)


def _finite_nonneg(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise PlateauCodexPacketError(
            f"{field} must be a nonnegative finite number"
        )
    return float(value)


def _string_tuple(
    value: object,
    field: str,
    *,
    allow_empty: bool = True,
    unique: bool = True,
) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise PlateauCodexPacketError(f"{field} must be a string array")
    items = tuple(_nonblank(item, f"{field}[{index}]") for index, item in enumerate(value))
    if not allow_empty and not items:
        raise PlateauCodexPacketError(f"{field} must be nonempty")
    if unique and len(set(items)) != len(items):
        raise PlateauCodexPacketError(f"{field} must not contain duplicates")
    return items


def baseline_l1_digest(baseline_l1: CanonicalRuleIR) -> str:
    """Content digest of a baseline CanonicalRuleIR payload."""

    if not isinstance(baseline_l1, CanonicalRuleIR):
        raise PlateauCodexPacketError("baseline_l1 must be CanonicalRuleIR")
    return _sha(baseline_l1.to_dict())


def field_change_from_dict(value: object) -> CanonicalFieldChange:
    """Restore a CanonicalFieldChange from a sealed dict."""

    if not isinstance(value, Mapping):
        raise PlateauCodexPacketError(
            "field change must be an object"
        )
    try:
        return CanonicalFieldChange(
            canonical_field=value["canonical_field"],  # type: ignore[arg-type]
            before=value.get("before"),
            after=value.get("after"),
            baseline_rule_index=value.get("baseline_rule_index"),  # type: ignore[arg-type]
            guided_rule_index=value.get("guided_rule_index"),  # type: ignore[arg-type]
        )
    except (KeyError, TypeError, ValueError, ContractError) as exc:
        raise PlateauCodexPacketError(
            f"invalid CanonicalFieldChange: {exc}"
        ) from exc


def field_change_path(change: CanonicalFieldChange) -> str:
    """Stable path string for a field change (prefer index form)."""

    if change.baseline_rule_index is not None:
        return (
            f"rules[{change.baseline_rule_index}].{change.canonical_field}"
        )
    return change.path


def disposition_is_implementable(disposition: AdmissionDisposition) -> bool:
    """Return whether a structural disposition may authorize implementable work."""

    if not isinstance(disposition, AdmissionDisposition):
        try:
            disposition = AdmissionDisposition(disposition)
        except (TypeError, ValueError) as exc:
            raise PlateauCodexPacketError(
                "admission disposition is invalid"
            ) from exc
    return disposition is AdmissionDisposition.ACCEPTED


def _validate_predicted_file(path: str) -> str:
    cleaned = _nonblank(path, "predicted_files item")
    if ".." in cleaned.split("/"):
        raise PlateauCodexPacketError(
            f"predicted file path must not contain '..': {cleaned!r}"
        )
    if cleaned.startswith("/") or cleaned.startswith("\\"):
        raise PlateauCodexPacketError(
            f"predicted file path must be repository-relative: {cleaned!r}"
        )
    if not any(cleaned.startswith(prefix) for prefix in ALLOWED_PREDICTED_FILE_PREFIXES):
        raise PlateauCodexPacketError(
            "predicted file must target deterministic compiler/realizer/"
            f"tests/docs surface; got {cleaned!r}"
        )
    return cleaned


class TeacherKind(str, Enum):
    """Known offline teachers that may author IR patch proposals."""

    LEANSTRAL = "leanstral"
    SYMAI = "symai"
    SPACY = "spacy"
    AUTOENCODER = "autoencoder"
    RESIDUAL_CATALOG = "residual_catalog"
    MANUAL = "manual"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class ResidualRef:
    """Reference to one residual catalog facet consumed by a packet.

    Residual refs are non-authoritative pointers: they locate case×facet
    loss contributions that motivated a proposal.  They never authorize
    production composition by themselves.
    """

    residual_id: str
    case_id: str
    field_paths: tuple[str, ...]
    facet: str | None = None
    estimated_forward_contribution: float | None = None
    catalog_digest: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "residual_id", _nonblank(self.residual_id, "residual_id")
        )
        if not _PACKET_ID_RE.match(self.residual_id):
            raise PlateauCodexPacketError(
                f"residual_id has invalid shape: {self.residual_id!r}"
            )
        object.__setattr__(
            self, "case_id", _nonblank(self.case_id, "case_id")
        )
        object.__setattr__(
            self,
            "field_paths",
            _string_tuple(self.field_paths, "field_paths", allow_empty=False),
        )
        object.__setattr__(
            self, "facet", _optional_nonblank(self.facet, "facet")
        )
        if self.estimated_forward_contribution is not None:
            object.__setattr__(
                self,
                "estimated_forward_contribution",
                _finite_nonneg(
                    self.estimated_forward_contribution,
                    "estimated_forward_contribution",
                ),
            )
        object.__setattr__(
            self,
            "catalog_digest",
            _optional_nonblank(self.catalog_digest, "catalog_digest"),
        )
        if self.catalog_digest is not None and not (
            _HEX64_RE.match(self.catalog_digest)
            or self.catalog_digest.startswith("baguqeer")
            or self.catalog_digest.startswith("bafy")
        ):
            # Allow hex digests or common CIDv1 prefixes without hard codec dep.
            if len(self.catalog_digest) < 8:
                raise PlateauCodexPacketError(
                    "catalog_digest must be a digest or CID when present"
                )
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "catalog_digest": self.catalog_digest,
            "detail": self.detail,
            "estimated_forward_contribution": (
                self.estimated_forward_contribution
            ),
            "facet": self.facet,
            "field_paths": list(self.field_paths),
            "interface": PLATEAU_RESIDUAL_REF_INTERFACE,
            "residual_id": self.residual_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ResidualRef":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError("residual ref must be an object")
        return cls(
            residual_id=value.get("residual_id"),  # type: ignore[arg-type]
            case_id=value.get("case_id"),  # type: ignore[arg-type]
            field_paths=tuple(value.get("field_paths") or ()),  # type: ignore[arg-type]
            facet=value.get("facet"),  # type: ignore[arg-type]
            estimated_forward_contribution=value.get(
                "estimated_forward_contribution"
            ),  # type: ignore[arg-type]
            catalog_digest=value.get("catalog_digest"),  # type: ignore[arg-type]
            detail=value.get("detail"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class TeacherProposal:
    """One teacher-authored candidate IR patch proposal.

    Proposals are not implementable until structural admission accepts them.
    ``semantic_authority`` is always false: teachers do not adjudicate meaning.
    """

    proposal_id: str
    teacher: str
    residual_ref_ids: tuple[str, ...]
    allowed_field_paths: tuple[str, ...]
    candidate_l1: CanonicalRuleIR | None = None
    field_changes: tuple[CanonicalFieldChange, ...] = ()
    detail: str | None = None
    semantic_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "proposal_id", _nonblank(self.proposal_id, "proposal_id")
        )
        if not _PACKET_ID_RE.match(self.proposal_id):
            raise PlateauCodexPacketError(
                f"proposal_id has invalid shape: {self.proposal_id!r}"
            )
        teacher = _nonblank(self.teacher, "teacher").lower()
        if teacher not in KNOWN_TEACHERS:
            raise PlateauCodexPacketError(
                f"unknown teacher {teacher!r}; expected one of "
                f"{sorted(KNOWN_TEACHERS)}"
            )
        object.__setattr__(self, "teacher", teacher)
        object.__setattr__(
            self,
            "residual_ref_ids",
            _string_tuple(
                self.residual_ref_ids, "residual_ref_ids", allow_empty=True
            ),
        )
        object.__setattr__(
            self,
            "allowed_field_paths",
            _string_tuple(
                self.allowed_field_paths,
                "allowed_field_paths",
                allow_empty=False,
            ),
        )
        if self.candidate_l1 is not None and not isinstance(
            self.candidate_l1, CanonicalRuleIR
        ):
            raise PlateauCodexPacketError(
                "candidate_l1 must be CanonicalRuleIR or None"
            )
        object.__setattr__(self, "field_changes", tuple(self.field_changes))
        if not all(
            isinstance(item, CanonicalFieldChange)
            for item in self.field_changes
        ):
            raise PlateauCodexPacketError(
                "field_changes must contain CanonicalFieldChange records"
            )
        if self.semantic_authority is not False:
            raise PlateauCodexPacketError(
                "teacher proposals cannot claim semantic authority"
            )
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed_field_paths": list(self.allowed_field_paths),
            "candidate_l1": (
                self.candidate_l1.to_dict()
                if self.candidate_l1 is not None
                else None
            ),
            "detail": self.detail,
            "field_changes": [item.to_dict() for item in self.field_changes],
            "interface": PLATEAU_TEACHER_PROPOSAL_INTERFACE,
            "proposal_id": self.proposal_id,
            "residual_ref_ids": list(self.residual_ref_ids),
            "semantic_authority": False,
            "teacher": self.teacher,
        }

    @classmethod
    def from_dict(cls, value: object) -> "TeacherProposal":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError("teacher proposal must be an object")
        raw_candidate = value.get("candidate_l1")
        candidate: CanonicalRuleIR | None
        if raw_candidate is None:
            candidate = None
        else:
            candidate = CanonicalRuleIR.from_dict(raw_candidate)
        raw_changes = value.get("field_changes") or ()
        if (
            not isinstance(raw_changes, Sequence)
            or isinstance(raw_changes, (str, bytes, bytearray))
        ):
            raise PlateauCodexPacketError(
                "field_changes must be an array"
            )
        changes = tuple(field_change_from_dict(item) for item in raw_changes)
        return cls(
            proposal_id=value.get("proposal_id"),  # type: ignore[arg-type]
            teacher=value.get("teacher"),  # type: ignore[arg-type]
            residual_ref_ids=tuple(value.get("residual_ref_ids") or ()),  # type: ignore[arg-type]
            allowed_field_paths=tuple(
                value.get("allowed_field_paths") or ()
            ),  # type: ignore[arg-type]
            candidate_l1=candidate,
            field_changes=changes,
            detail=value.get("detail"),  # type: ignore[arg-type]
            semantic_authority=bool(value.get("semantic_authority", False)),
        )


@dataclass(frozen=True, slots=True)
class ProverCheckReceipt:
    """One bounded prover tool receipt embedded in a packet.

    ``semantic_authority`` is always false: Hammer/cvc5/Lean cannot adjudicate
    source meaning or lower end-to-end loss by themselves.
    """

    validator_id: str
    tool: str
    passed: bool
    timed_out: bool
    elapsed_seconds: float
    constraints: tuple[str, ...] = ()
    detail: str | None = None
    semantic_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "validator_id", _nonblank(self.validator_id, "validator_id")
        )
        tool = _nonblank(self.tool, "tool")
        try:
            StructuralTool(tool)
        except (TypeError, ValueError) as exc:
            raise PlateauCodexPacketError(
                f"prover tool is invalid: {tool!r}"
            ) from exc
        object.__setattr__(self, "tool", tool)
        if not isinstance(self.passed, bool) or not isinstance(
            self.timed_out, bool
        ):
            raise PlateauCodexPacketError(
                "passed and timed_out must be booleans"
            )
        if self.timed_out and self.passed:
            raise PlateauCodexPacketError("a timed-out check cannot pass")
        object.__setattr__(
            self,
            "elapsed_seconds",
            _finite_nonneg(self.elapsed_seconds, "elapsed_seconds"),
        )
        object.__setattr__(
            self,
            "constraints",
            _string_tuple(self.constraints, "constraints", allow_empty=True),
        )
        for item in self.constraints:
            if item not in DECLARED_STRUCTURAL_CONSTRAINTS:
                raise PlateauCodexPacketError(
                    f"undeclared structural constraint: {item!r}"
                )
        if self.semantic_authority is not False:
            raise PlateauCodexPacketError(
                "prover receipts cannot claim semantic authority"
            )
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "constraints": list(self.constraints),
            "detail": self.detail,
            "elapsed_seconds": self.elapsed_seconds,
            "passed": self.passed,
            "semantic_authority": False,
            "timed_out": self.timed_out,
            "tool": self.tool,
            "validator_id": self.validator_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ProverCheckReceipt":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError(
                "prover check receipt must be an object"
            )
        return cls(
            validator_id=value.get("validator_id"),  # type: ignore[arg-type]
            tool=value.get("tool"),  # type: ignore[arg-type]
            passed=bool(value.get("passed")),
            timed_out=bool(value.get("timed_out")),
            elapsed_seconds=value.get("elapsed_seconds", 0.0),  # type: ignore[arg-type]
            constraints=tuple(value.get("constraints") or ()),  # type: ignore[arg-type]
            detail=value.get("detail"),  # type: ignore[arg-type]
            semantic_authority=bool(value.get("semantic_authority", False)),
        )

    @classmethod
    def from_admission_check(
        cls, receipt: AdmissionCheckReceipt
    ) -> "ProverCheckReceipt":
        if not isinstance(receipt, AdmissionCheckReceipt):
            raise PlateauCodexPacketError(
                "expected AdmissionCheckReceipt"
            )
        if receipt.semantic_authority is not False:
            raise PlateauCodexPacketError(
                "admission check claimed semantic authority"
            )
        return cls(
            validator_id=receipt.validator_id,
            tool=receipt.tool.value,
            passed=receipt.passed,
            timed_out=receipt.timed_out,
            elapsed_seconds=receipt.elapsed_seconds,
            constraints=tuple(receipt.constraints),
            detail=receipt.detail,
            semantic_authority=False,
        )


@dataclass(frozen=True, slots=True)
class PlateauAdmissionReceipt:
    """Packet-embedded structural admission receipt.

    Projects ``StructuralAdmission@1`` into a serializable form that always
    asserts ``semantic_authority=false`` and never treats proof pass as
    end-to-end loss.
    """

    disposition: AdmissionDisposition
    prior_l1_digest: str
    admitted_l1_digest: str
    candidate_l1_digest: str | None
    prior_l1_unchanged: bool
    policy_digest: str
    field_changes: tuple[CanonicalFieldChange, ...]
    check_receipts: tuple[ProverCheckReceipt, ...]
    proposal_id: str | None = None
    rejection_reason: str | None = None
    detail: str | None = None
    semantic_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, AdmissionDisposition):
            try:
                object.__setattr__(
                    self,
                    "disposition",
                    AdmissionDisposition(self.disposition),
                )
            except (TypeError, ValueError) as exc:
                raise PlateauCodexPacketError(
                    "admission disposition is invalid"
                ) from exc
        for name in ("prior_l1_digest", "admitted_l1_digest", "policy_digest"):
            digest = _nonblank(getattr(self, name), name)
            if not _HEX64_RE.match(digest):
                raise PlateauCodexPacketError(
                    f"{name} must be a 64-char hex digest"
                )
            object.__setattr__(self, name, digest)
        if self.candidate_l1_digest is not None:
            digest = _nonblank(
                self.candidate_l1_digest, "candidate_l1_digest"
            )
            if not _HEX64_RE.match(digest):
                raise PlateauCodexPacketError(
                    "candidate_l1_digest must be a 64-char hex digest"
                )
            object.__setattr__(self, "candidate_l1_digest", digest)
        if not isinstance(self.prior_l1_unchanged, bool):
            raise PlateauCodexPacketError(
                "prior_l1_unchanged must be boolean"
            )
        object.__setattr__(self, "field_changes", tuple(self.field_changes))
        if not all(
            isinstance(item, CanonicalFieldChange)
            for item in self.field_changes
        ):
            raise PlateauCodexPacketError(
                "field_changes must contain CanonicalFieldChange records"
            )
        object.__setattr__(
            self, "check_receipts", tuple(self.check_receipts)
        )
        if not all(
            isinstance(item, ProverCheckReceipt)
            for item in self.check_receipts
        ):
            raise PlateauCodexPacketError(
                "check_receipts must contain ProverCheckReceipt records"
            )
        for item in self.check_receipts:
            if item.semantic_authority is not False:
                raise PlateauCodexPacketError(
                    "embedded prover receipt claimed semantic authority"
                )
        object.__setattr__(
            self,
            "proposal_id",
            _optional_nonblank(self.proposal_id, "proposal_id"),
        )
        object.__setattr__(
            self,
            "rejection_reason",
            _optional_nonblank(self.rejection_reason, "rejection_reason"),
        )
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )
        if self.semantic_authority is not False:
            raise PlateauCodexPacketError(
                "admission receipts cannot claim semantic authority"
            )

        if self.disposition is AdmissionDisposition.ACCEPTED:
            if self.prior_l1_unchanged and (
                self.candidate_l1_digest is not None
                and self.candidate_l1_digest != self.prior_l1_digest
            ):
                raise PlateauCodexPacketError(
                    "accepted non-identity repair cannot claim prior unchanged"
                )
            if self.rejection_reason is not None:
                raise PlateauCodexPacketError(
                    "accepted admission cannot carry a rejection_reason"
                )
            if self.admitted_l1_digest != (
                self.candidate_l1_digest or self.prior_l1_digest
            ):
                raise PlateauCodexPacketError(
                    "accepted admission must admit the candidate L1 digest"
                )
        else:
            if self.admitted_l1_digest != self.prior_l1_digest:
                raise PlateauCodexPacketError(
                    "non-accepted admission must retain prior L1 digest"
                )
            if not self.prior_l1_unchanged:
                raise PlateauCodexPacketError(
                    "non-accepted admission must leave prior L1 unchanged"
                )

    @property
    def accepted(self) -> bool:
        return self.disposition is AdmissionDisposition.ACCEPTED

    @property
    def implementable_authority(self) -> bool:
        """Whether this receipt alone may authorize implementable edits."""

        return disposition_is_implementable(self.disposition)

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "admitted_l1_digest": self.admitted_l1_digest,
            "candidate_l1_digest": self.candidate_l1_digest,
            "check_receipts": [
                item.to_dict() for item in self.check_receipts
            ],
            "detail": self.detail,
            "disposition": self.disposition.value,
            "end_to_end_loss": None,
            "field_changes": [item.to_dict() for item in self.field_changes],
            "implementable_authority": self.implementable_authority,
            "interface": PLATEAU_ADMISSION_RECEIPT_INTERFACE,
            "policy_digest": self.policy_digest,
            "prior_l1_digest": self.prior_l1_digest,
            "prior_l1_unchanged": self.prior_l1_unchanged,
            "proof_pass_is_not_end_to_end_loss": True,
            "proposal_id": self.proposal_id,
            "rejection_reason": self.rejection_reason,
            "semantic_authority": False,
            "source_interface": STRUCTURAL_ADMISSION_RECEIPT_INTERFACE,
        }

    @classmethod
    def from_dict(cls, value: object) -> "PlateauAdmissionReceipt":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError(
                "admission receipt must be an object"
            )
        raw_changes = value.get("field_changes") or ()
        if (
            not isinstance(raw_changes, Sequence)
            or isinstance(raw_changes, (str, bytes, bytearray))
        ):
            raise PlateauCodexPacketError("field_changes must be an array")
        raw_checks = value.get("check_receipts") or ()
        if (
            not isinstance(raw_checks, Sequence)
            or isinstance(raw_checks, (str, bytes, bytearray))
        ):
            raise PlateauCodexPacketError("check_receipts must be an array")
        return cls(
            disposition=value.get("disposition"),  # type: ignore[arg-type]
            prior_l1_digest=value.get("prior_l1_digest"),  # type: ignore[arg-type]
            admitted_l1_digest=value.get("admitted_l1_digest"),  # type: ignore[arg-type]
            candidate_l1_digest=value.get("candidate_l1_digest"),  # type: ignore[arg-type]
            prior_l1_unchanged=bool(value.get("prior_l1_unchanged")),
            policy_digest=value.get("policy_digest"),  # type: ignore[arg-type]
            field_changes=tuple(
                field_change_from_dict(item) for item in raw_changes
            ),
            check_receipts=tuple(
                ProverCheckReceipt.from_dict(item) for item in raw_checks
            ),
            proposal_id=value.get("proposal_id"),  # type: ignore[arg-type]
            rejection_reason=value.get("rejection_reason"),  # type: ignore[arg-type]
            detail=value.get("detail"),  # type: ignore[arg-type]
            semantic_authority=bool(value.get("semantic_authority", False)),
        )

    @classmethod
    def from_structural_admission(
        cls,
        result: StructuralAdmissionResult,
        *,
        proposal_id: str | None = None,
    ) -> "PlateauAdmissionReceipt":
        """Project a live StructuralAdmissionResult into a packet receipt."""

        if not isinstance(result, StructuralAdmissionResult):
            raise PlateauCodexPacketError(
                "expected StructuralAdmissionResult"
            )
        payload = result.to_dict()
        if payload.get("semantic_authority") is not False:
            raise PlateauCodexPacketError(
                "structural admission claimed semantic authority"
            )
        prior_digest = baseline_l1_digest(result.prior_l1)
        admitted_digest = baseline_l1_digest(result.admitted_l1)
        candidate_digest = (
            baseline_l1_digest(result.candidate_l1)
            if result.candidate_l1 is not None
            else None
        )
        checks = tuple(
            ProverCheckReceipt.from_admission_check(item)
            for item in result.check_receipts
        )
        return cls(
            disposition=result.disposition,
            prior_l1_digest=prior_digest,
            admitted_l1_digest=admitted_digest,
            candidate_l1_digest=candidate_digest,
            prior_l1_unchanged=result.prior_l1_unchanged,
            policy_digest=result.policy_digest,
            field_changes=tuple(result.field_changes),
            check_receipts=checks,
            proposal_id=proposal_id,
            rejection_reason=result.rejection_reason,
            detail=result.detail,
            semantic_authority=False,
        )


@dataclass(frozen=True, slots=True)
class ProofObligation:
    """Deterministic-code obligation minted from a failed structural gate.

    Rejected/timeout/error admissions produce obligations that the supervisor
    materializer surfaces as notes or follow-up edit tasks — never as
    silent merges of the rejected candidate.
    """

    obligation_id: str
    constraint: str
    disposition: str
    residual_ref_ids: tuple[str, ...] = ()
    proposal_id: str | None = None
    failed_field_paths: tuple[str, ...] = ()
    detail: str | None = None
    semantic_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "obligation_id",
            _nonblank(self.obligation_id, "obligation_id"),
        )
        if not _OBLIGATION_ID_RE.match(self.obligation_id):
            raise PlateauCodexPacketError(
                f"obligation_id has invalid shape: {self.obligation_id!r}"
            )
        object.__setattr__(
            self, "constraint", _nonblank(self.constraint, "constraint")
        )
        disposition = _nonblank(self.disposition, "disposition").lower()
        allowed = {
            AdmissionDisposition.VALIDATOR_REJECT.value,
            AdmissionDisposition.TIMEOUT.value,
            AdmissionDisposition.ERROR.value,
            VALIDATOR_REJECT,
        }
        if disposition not in allowed:
            raise PlateauCodexPacketError(
                "proof obligation disposition must be reject/timeout/error; "
                f"got {disposition!r}"
            )
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(
            self,
            "residual_ref_ids",
            _string_tuple(
                self.residual_ref_ids, "residual_ref_ids", allow_empty=True
            ),
        )
        object.__setattr__(
            self,
            "proposal_id",
            _optional_nonblank(self.proposal_id, "proposal_id"),
        )
        object.__setattr__(
            self,
            "failed_field_paths",
            _string_tuple(
                self.failed_field_paths,
                "failed_field_paths",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )
        if self.semantic_authority is not False:
            raise PlateauCodexPacketError(
                "proof obligations cannot claim semantic authority"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "constraint": self.constraint,
            "detail": self.detail,
            "disposition": self.disposition,
            "failed_field_paths": list(self.failed_field_paths),
            "interface": PLATEAU_PROOF_OBLIGATION_INTERFACE,
            "obligation_id": self.obligation_id,
            "proposal_id": self.proposal_id,
            "residual_ref_ids": list(self.residual_ref_ids),
            "semantic_authority": False,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ProofObligation":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError(
                "proof obligation must be an object"
            )
        return cls(
            obligation_id=value.get("obligation_id"),  # type: ignore[arg-type]
            constraint=value.get("constraint"),  # type: ignore[arg-type]
            disposition=value.get("disposition"),  # type: ignore[arg-type]
            residual_ref_ids=tuple(value.get("residual_ref_ids") or ()),  # type: ignore[arg-type]
            proposal_id=value.get("proposal_id"),  # type: ignore[arg-type]
            failed_field_paths=tuple(
                value.get("failed_field_paths") or ()
            ),  # type: ignore[arg-type]
            detail=value.get("detail"),  # type: ignore[arg-type]
            semantic_authority=bool(value.get("semantic_authority", False)),
        )


def mint_proof_obligations(
    admission: PlateauAdmissionReceipt | StructuralAdmissionResult,
    *,
    residual_ref_ids: Sequence[str] = (),
    proposal_id: str | None = None,
    packet_id: str = "packet",
) -> tuple[ProofObligation, ...]:
    """Mint proof obligations from a non-accepted admission.

    Accepted admissions mint no obligations.  Reject/timeout/error produce
    one obligation per failed declared constraint when identifiable, else a
    single disposition-level obligation.
    """

    if isinstance(admission, StructuralAdmissionResult):
        receipt = PlateauAdmissionReceipt.from_structural_admission(
            admission, proposal_id=proposal_id
        )
    elif isinstance(admission, PlateauAdmissionReceipt):
        receipt = admission
    else:
        raise PlateauCodexPacketError(
            "admission must be PlateauAdmissionReceipt or "
            "StructuralAdmissionResult"
        )

    if receipt.disposition is AdmissionDisposition.ACCEPTED:
        return ()
    if receipt.disposition is AdmissionDisposition.NOT_APPLICABLE:
        return ()

    residual_ids = _string_tuple(
        residual_ref_ids, "residual_ref_ids", allow_empty=True
    )
    failed_paths = tuple(
        field_change_path(change) for change in receipt.field_changes
    )
    disposition = receipt.disposition.value
    constraints: list[str] = []
    for check in receipt.check_receipts:
        if not check.passed or check.timed_out:
            constraints.extend(check.constraints)
    if not constraints and receipt.detail:
        # Local structural failures encode constraint tokens in detail.
        lowered = receipt.detail.lower()
        for name in DECLARED_STRUCTURAL_CONSTRAINTS:
            token = name.replace("_", " ")
            if name in lowered or token in lowered:
                constraints.append(name)
            elif name == "non_vacuous_candidate" and "vacuous" in lowered:
                constraints.append(name)
            elif (
                name == "rule_cardinality_preserved"
                and "cardinality" in lowered
            ):
                constraints.append(name)
            elif (
                name == "untriggered_projection_preserved"
                and "untriggered" in lowered
            ):
                constraints.append(name)
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique_constraints: list[str] = []
    for item in constraints:
        if item not in seen:
            seen.add(item)
            unique_constraints.append(item)
    if not unique_constraints:
        unique_constraints = ["structural_admission_failed"]

    obligations: list[ProofObligation] = []
    for index, constraint in enumerate(unique_constraints):
        obligation_id = (
            f"PO-{packet_id}-{disposition}-{index}-{constraint}"[:128]
        )
        # Sanitize obligation id to the allowed charset.
        obligation_id = re.sub(r"[^A-Za-z0-9_.:-]", "-", obligation_id)
        obligations.append(
            ProofObligation(
                obligation_id=obligation_id,
                constraint=constraint,
                disposition=disposition,
                residual_ref_ids=residual_ids,
                proposal_id=proposal_id or receipt.proposal_id,
                failed_field_paths=failed_paths,
                detail=receipt.detail,
                semantic_authority=False,
            )
        )
    return tuple(obligations)


@dataclass(frozen=True, slots=True)
class PlateauCodexPacket:
    """Prover-gated Codex packet bound for agent-supervisor consumption.

    Required sealed fields:

    * ``baseline_l1`` / ``baseline_l1_digest`` — locked det. plateau L1;
    * ``residual_refs`` — residual catalog facet pointers;
    * ``proposals`` — teacher proposals (non-authoritative);
    * ``admission_receipts`` — structural admission results;
    * ``proof_obligation_ids`` / ``proof_obligations`` — mint from rejects;
    * ``predicted_files`` — det. compiler/realizer/test surface only;
    * ``validation_commands`` — re-run structural admit + packet tests;
    * ``implementable`` — true only when admission disposition is accepted.

    Content addressing: ``packet_digest`` is the SHA-256 of the canonical
    JSON payload with the digest field itself omitted.
    """

    packet_id: str
    baseline_l1: CanonicalRuleIR
    residual_refs: tuple[ResidualRef, ...]
    proposals: tuple[TeacherProposal, ...]
    admission_receipts: tuple[PlateauAdmissionReceipt, ...]
    proof_obligations: tuple[ProofObligation, ...]
    predicted_files: tuple[str, ...]
    validation_commands: tuple[str, ...]
    implementable: bool
    baseline_arm_id: str = DEFAULT_BASELINE_ARM_ID
    case_id: str | None = None
    admitted_field_changes: tuple[CanonicalFieldChange, ...] = ()
    detail: str | None = None
    baseline_e2e: float | None = DEFAULT_BASELINE_E2E

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "packet_id", _nonblank(self.packet_id, "packet_id")
        )
        if not _PACKET_ID_RE.match(self.packet_id):
            raise PlateauCodexPacketError(
                f"packet_id has invalid shape: {self.packet_id!r}"
            )
        if not isinstance(self.baseline_l1, CanonicalRuleIR):
            raise PlateauCodexPacketError(
                "baseline_l1 must be CanonicalRuleIR"
            )
        object.__setattr__(
            self,
            "baseline_arm_id",
            _nonblank(self.baseline_arm_id, "baseline_arm_id"),
        )
        object.__setattr__(
            self, "residual_refs", tuple(self.residual_refs)
        )
        if not all(isinstance(item, ResidualRef) for item in self.residual_refs):
            raise PlateauCodexPacketError(
                "residual_refs must contain ResidualRef records"
            )
        residual_ids = [item.residual_id for item in self.residual_refs]
        if len(set(residual_ids)) != len(residual_ids):
            raise PlateauCodexPacketError(
                "residual_ref ids must be unique within a packet"
            )

        object.__setattr__(self, "proposals", tuple(self.proposals))
        if not all(
            isinstance(item, TeacherProposal) for item in self.proposals
        ):
            raise PlateauCodexPacketError(
                "proposals must contain TeacherProposal records"
            )
        proposal_ids = [item.proposal_id for item in self.proposals]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise PlateauCodexPacketError(
                "proposal ids must be unique within a packet"
            )
        residual_id_set = set(residual_ids)
        for proposal in self.proposals:
            if proposal.semantic_authority is not False:
                raise PlateauCodexPacketError(
                    "proposal claimed semantic authority"
                )
            unknown = set(proposal.residual_ref_ids) - residual_id_set
            if unknown:
                raise PlateauCodexPacketError(
                    "proposal references unknown residual ids: "
                    + ", ".join(sorted(unknown))
                )

        object.__setattr__(
            self, "admission_receipts", tuple(self.admission_receipts)
        )
        if not all(
            isinstance(item, PlateauAdmissionReceipt)
            for item in self.admission_receipts
        ):
            raise PlateauCodexPacketError(
                "admission_receipts must contain PlateauAdmissionReceipt "
                "records"
            )
        if not self.admission_receipts:
            raise PlateauCodexPacketError(
                "packet requires at least one admission receipt"
            )
        for receipt in self.admission_receipts:
            if receipt.semantic_authority is not False:
                raise PlateauCodexPacketError(
                    "admission receipt claimed semantic authority"
                )
            for check in receipt.check_receipts:
                if check.semantic_authority is not False:
                    raise PlateauCodexPacketError(
                        "prover check claimed semantic authority"
                    )
            if (
                receipt.proposal_id is not None
                and receipt.proposal_id not in proposal_ids
                and proposal_ids
            ):
                raise PlateauCodexPacketError(
                    f"admission references unknown proposal_id "
                    f"{receipt.proposal_id!r}"
                )

        object.__setattr__(
            self, "proof_obligations", tuple(self.proof_obligations)
        )
        if not all(
            isinstance(item, ProofObligation)
            for item in self.proof_obligations
        ):
            raise PlateauCodexPacketError(
                "proof_obligations must contain ProofObligation records"
            )
        obligation_ids = [item.obligation_id for item in self.proof_obligations]
        if len(set(obligation_ids)) != len(obligation_ids):
            raise PlateauCodexPacketError(
                "proof_obligation ids must be unique within a packet"
            )
        for obligation in self.proof_obligations:
            if obligation.semantic_authority is not False:
                raise PlateauCodexPacketError(
                    "proof obligation claimed semantic authority"
                )

        predicted = tuple(
            _validate_predicted_file(path)
            for path in self.predicted_files
        )
        if not predicted:
            raise PlateauCodexPacketError(
                "predicted_files must be nonempty"
            )
        object.__setattr__(self, "predicted_files", predicted)

        commands = _string_tuple(
            self.validation_commands,
            "validation_commands",
            allow_empty=False,
            unique=False,
        )
        object.__setattr__(self, "validation_commands", commands)

        if not isinstance(self.implementable, bool):
            raise PlateauCodexPacketError("implementable must be boolean")

        object.__setattr__(
            self, "case_id", _optional_nonblank(self.case_id, "case_id")
        )
        object.__setattr__(
            self,
            "admitted_field_changes",
            tuple(self.admitted_field_changes),
        )
        if not all(
            isinstance(item, CanonicalFieldChange)
            for item in self.admitted_field_changes
        ):
            raise PlateauCodexPacketError(
                "admitted_field_changes must contain CanonicalFieldChange "
                "records"
            )
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )
        if self.baseline_e2e is not None:
            object.__setattr__(
                self,
                "baseline_e2e",
                _finite_nonneg(self.baseline_e2e, "baseline_e2e"),
            )

        self._assert_implementable_consistency()

    def _assert_implementable_consistency(self) -> None:
        accepted = [
            item
            for item in self.admission_receipts
            if item.disposition is AdmissionDisposition.ACCEPTED
        ]
        blocking = [
            item
            for item in self.admission_receipts
            if item.disposition
            in {
                AdmissionDisposition.VALIDATOR_REJECT,
                AdmissionDisposition.TIMEOUT,
                AdmissionDisposition.ERROR,
            }
        ]
        # Primary disposition: if any blocking disposition is present without
        # a separate accepted receipt for implementable authority, deny.
        # Packet-level implementable requires ≥1 accepted and is forbidden
        # when the governing admissions are exclusively non-accepted.
        if self.implementable:
            if not accepted:
                raise PlateauCodexPacketError(
                    "implementable=true requires at least one accepted "
                    "admission receipt"
                )
            # Explicit fail-closed: a packet that only records reject/timeout/
            # error cannot be implementable.  When mixed, accepted proposals
            # may still authorize implementable work; blocking ones contribute
            # obligations only.
            if not accepted and blocking:
                raise PlateauCodexPacketError(
                    "implementable=false required for reject/timeout/error"
                )
            if not self.admitted_field_changes:
                # Identity accepts are not useful implementable work.
                # Allow empty only if accepted field_changes on receipts are
                # also empty (identity) — still deny implementable.
                receipt_changes = sum(
                    (tuple(item.field_changes) for item in accepted),
                    (),
                )
                if not receipt_changes:
                    raise PlateauCodexPacketError(
                        "implementable=true requires admitted field changes"
                    )
                raise PlateauCodexPacketError(
                    "implementable packet must list admitted_field_changes"
                )
        else:
            # Non-implementable packets must not advertise admitted ΔL1 as
            # authorized edits.
            if self.admitted_field_changes and accepted:
                # Allowed: packet may carry admitted changes for audit while
                # still marking implementable=false only when no accepted?
                # Forbid advertising changes when no accept exists.
                pass
            if self.admitted_field_changes and not accepted:
                raise PlateauCodexPacketError(
                    "non-implementable packet without accepted admission "
                    "cannot list admitted_field_changes"
                )

        # Hard rule from acceptance criteria: reject/timeout/error alone
        # cannot yield implementable=true (covered above).  Additionally,
        # if *all* receipts are non-accepted, implementable must be false.
        if not accepted and self.implementable:
            raise PlateauCodexPacketError(
                "implementable=false when disposition is "
                "reject/timeout/error/not_applicable"
            )

        # baseline digest cross-check against admission prior digests when present
        baseline_digest = self.baseline_l1_digest
        for receipt in self.admission_receipts:
            if receipt.prior_l1_digest != baseline_digest:
                raise PlateauCodexPacketError(
                    "admission prior_l1_digest must match packet "
                    "baseline_l1_digest"
                )

    @property
    def baseline_l1_digest(self) -> str:
        return baseline_l1_digest(self.baseline_l1)

    @property
    def proof_obligation_ids(self) -> tuple[str, ...]:
        return tuple(item.obligation_id for item in self.proof_obligations)

    @property
    def primary_disposition(self) -> AdmissionDisposition:
        """Governing disposition for supervisor routing.

        Prefer accepted when present; otherwise the first non-accepted
        disposition (reject/timeout/error before not_applicable).
        """

        for item in self.admission_receipts:
            if item.disposition is AdmissionDisposition.ACCEPTED:
                return AdmissionDisposition.ACCEPTED
        priority = (
            AdmissionDisposition.ERROR,
            AdmissionDisposition.TIMEOUT,
            AdmissionDisposition.VALIDATOR_REJECT,
            AdmissionDisposition.NOT_APPLICABLE,
        )
        present = {item.disposition for item in self.admission_receipts}
        for disposition in priority:
            if disposition in present:
                return disposition
        return self.admission_receipts[0].disposition

    def payload_for_digest(self) -> dict[str, object]:
        """Canonical payload used for content addressing (no digest field)."""

        return {
            "admission_receipts": [
                item.to_dict() for item in self.admission_receipts
            ],
            "admitted_field_changes": [
                item.to_dict() for item in self.admitted_field_changes
            ],
            "baseline_arm_id": self.baseline_arm_id,
            "baseline_e2e": self.baseline_e2e,
            "baseline_l1": self.baseline_l1.to_dict(),
            "baseline_l1_digest": self.baseline_l1_digest,
            "case_id": self.case_id,
            "detail": self.detail,
            "evidence": PLATEAU_CODEX_PACKET_EVIDENCE,
            "implementable": self.implementable,
            "interface": PLATEAU_CODEX_PACKET_INTERFACE,
            "packet_id": self.packet_id,
            "predicted_files": list(self.predicted_files),
            "primary_disposition": self.primary_disposition.value,
            "proof_obligation_ids": list(self.proof_obligation_ids),
            "proof_obligations": [
                item.to_dict() for item in self.proof_obligations
            ],
            "proposals": [item.to_dict() for item in self.proposals],
            "residual_refs": [item.to_dict() for item in self.residual_refs],
            "schema": PLATEAU_CODEX_PACKET_SCHEMA,
            "semantic_authority": False,
            "validation_commands": list(self.validation_commands),
        }

    @property
    def packet_digest(self) -> str:
        return _sha(self.payload_for_digest())

    def to_dict(self) -> dict[str, object]:
        payload = self.payload_for_digest()
        payload["packet_digest"] = self.packet_digest
        return payload

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "PlateauCodexPacket":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError("packet must be an object")
        interface = value.get("interface")
        if interface is not None and interface != PLATEAU_CODEX_PACKET_INTERFACE:
            raise PlateauCodexPacketError(
                f"unexpected packet interface: {interface!r}"
            )
        schema = value.get("schema")
        if schema is not None and schema != PLATEAU_CODEX_PACKET_SCHEMA:
            raise PlateauCodexPacketError(
                f"unexpected packet schema: {schema!r}"
            )

        residual_raw = value.get("residual_refs") or ()
        proposals_raw = value.get("proposals") or ()
        admissions_raw = value.get("admission_receipts") or ()
        obligations_raw = value.get("proof_obligations") or ()
        admitted_raw = value.get("admitted_field_changes") or ()
        for name, raw in (
            ("residual_refs", residual_raw),
            ("proposals", proposals_raw),
            ("admission_receipts", admissions_raw),
            ("proof_obligations", obligations_raw),
            ("admitted_field_changes", admitted_raw),
        ):
            if (
                not isinstance(raw, Sequence)
                or isinstance(raw, (str, bytes, bytearray))
            ):
                raise PlateauCodexPacketError(f"{name} must be an array")

        packet = cls(
            packet_id=value.get("packet_id"),  # type: ignore[arg-type]
            baseline_l1=CanonicalRuleIR.from_dict(value.get("baseline_l1")),
            residual_refs=tuple(
                ResidualRef.from_dict(item) for item in residual_raw
            ),
            proposals=tuple(
                TeacherProposal.from_dict(item) for item in proposals_raw
            ),
            admission_receipts=tuple(
                PlateauAdmissionReceipt.from_dict(item)
                for item in admissions_raw
            ),
            proof_obligations=tuple(
                ProofObligation.from_dict(item) for item in obligations_raw
            ),
            predicted_files=tuple(value.get("predicted_files") or ()),  # type: ignore[arg-type]
            validation_commands=tuple(
                value.get("validation_commands") or ()
            ),  # type: ignore[arg-type]
            implementable=bool(value.get("implementable")),
            baseline_arm_id=value.get(
                "baseline_arm_id", DEFAULT_BASELINE_ARM_ID
            ),  # type: ignore[arg-type]
            case_id=value.get("case_id"),  # type: ignore[arg-type]
            admitted_field_changes=tuple(
                field_change_from_dict(item) for item in admitted_raw
            ),
            detail=value.get("detail"),  # type: ignore[arg-type]
            baseline_e2e=value.get("baseline_e2e", DEFAULT_BASELINE_E2E),  # type: ignore[arg-type]
        )

        sealed_digest = value.get("packet_digest")
        if sealed_digest is not None:
            sealed = _nonblank(sealed_digest, "packet_digest")
            if sealed != packet.packet_digest:
                raise PlateauCodexPacketError(
                    "packet_digest mismatch: content-address integrity failed"
                )
        sealed_baseline = value.get("baseline_l1_digest")
        if sealed_baseline is not None:
            sealed_b = _nonblank(sealed_baseline, "baseline_l1_digest")
            if sealed_b != packet.baseline_l1_digest:
                raise PlateauCodexPacketError(
                    "baseline_l1_digest mismatch"
                )
        sealed_obligation_ids = value.get("proof_obligation_ids")
        if sealed_obligation_ids is not None:
            if list(sealed_obligation_ids) != list(packet.proof_obligation_ids):
                raise PlateauCodexPacketError(
                    "proof_obligation_ids must match proof_obligations"
                )
        return packet

    @classmethod
    def from_json(cls, text: str) -> "PlateauCodexPacket":
        if not isinstance(text, str) or not text.strip():
            raise PlateauCodexPacketError("packet JSON must be nonblank")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlateauCodexPacketError(
                f"packet JSON is invalid: {exc}"
            ) from exc
        return cls.from_dict(payload)


def build_plateau_codex_packet(
    *,
    packet_id: str,
    baseline_l1: CanonicalRuleIR,
    residual_refs: Sequence[ResidualRef],
    proposals: Sequence[TeacherProposal],
    admission_results: Sequence[
        StructuralAdmissionResult | PlateauAdmissionReceipt
    ],
    predicted_files: Sequence[str] | None = None,
    validation_commands: Sequence[str] | None = None,
    baseline_arm_id: str = DEFAULT_BASELINE_ARM_ID,
    case_id: str | None = None,
    detail: str | None = None,
    baseline_e2e: float | None = DEFAULT_BASELINE_E2E,
    proposal_ids_for_admissions: Sequence[str | None] | None = None,
) -> PlateauCodexPacket:
    """Build a sealed packet from residuals, proposals, and admissions.

    ``implementable`` is derived fail-closed:

    * true only when at least one admission is ``accepted`` and yields
      nonempty admitted field changes;
    * false for reject / timeout / error / not_applicable governing paths.
    """

    if not isinstance(baseline_l1, CanonicalRuleIR):
        raise PlateauCodexPacketError("baseline_l1 must be CanonicalRuleIR")
    residual_tuple = tuple(residual_refs)
    proposal_tuple = tuple(proposals)
    if not admission_results:
        raise PlateauCodexPacketError(
            "admission_results must be nonempty"
        )

    proposal_id_hints: list[str | None]
    if proposal_ids_for_admissions is None:
        # Pair admissions to proposals by index when lengths match.
        if len(admission_results) == len(proposal_tuple):
            proposal_id_hints = [item.proposal_id for item in proposal_tuple]
        elif len(proposal_tuple) == 1:
            proposal_id_hints = [proposal_tuple[0].proposal_id] * len(
                admission_results
            )
        else:
            proposal_id_hints = [None] * len(admission_results)
    else:
        proposal_id_hints = list(proposal_ids_for_admissions)
        if len(proposal_id_hints) != len(admission_results):
            raise PlateauCodexPacketError(
                "proposal_ids_for_admissions length must match "
                "admission_results"
            )

    receipts: list[PlateauAdmissionReceipt] = []
    for index, result in enumerate(admission_results):
        hint = proposal_id_hints[index]
        if isinstance(result, PlateauAdmissionReceipt):
            if hint is not None and result.proposal_id is None:
                receipts.append(
                    PlateauAdmissionReceipt(
                        disposition=result.disposition,
                        prior_l1_digest=result.prior_l1_digest,
                        admitted_l1_digest=result.admitted_l1_digest,
                        candidate_l1_digest=result.candidate_l1_digest,
                        prior_l1_unchanged=result.prior_l1_unchanged,
                        policy_digest=result.policy_digest,
                        field_changes=result.field_changes,
                        check_receipts=result.check_receipts,
                        proposal_id=hint,
                        rejection_reason=result.rejection_reason,
                        detail=result.detail,
                        semantic_authority=False,
                    )
                )
            else:
                receipts.append(result)
        elif isinstance(result, StructuralAdmissionResult):
            receipts.append(
                PlateauAdmissionReceipt.from_structural_admission(
                    result, proposal_id=hint
                )
            )
        else:
            raise PlateauCodexPacketError(
                "admission_results must contain StructuralAdmissionResult "
                "or PlateauAdmissionReceipt records"
            )

    residual_ids = [item.residual_id for item in residual_tuple]
    obligations: list[ProofObligation] = []
    for receipt in receipts:
        linked_residual_ids: list[str] = list(residual_ids)
        if receipt.proposal_id:
            for proposal in proposal_tuple:
                if proposal.proposal_id == receipt.proposal_id:
                    linked_residual_ids = list(proposal.residual_ref_ids) or list(
                        residual_ids
                    )
                    break
        obligations.extend(
            mint_proof_obligations(
                receipt,
                residual_ref_ids=linked_residual_ids,
                proposal_id=receipt.proposal_id,
                packet_id=packet_id,
            )
        )

    accepted_receipts = [
        item
        for item in receipts
        if item.disposition is AdmissionDisposition.ACCEPTED
    ]
    admitted_changes: list[CanonicalFieldChange] = []
    for receipt in accepted_receipts:
        for change in receipt.field_changes:
            admitted_changes.append(change)
    # De-dupe by path+before+after while preserving order.
    seen_keys: set[tuple[object, ...]] = set()
    unique_changes: list[CanonicalFieldChange] = []
    for change in admitted_changes:
        key = (
            change.canonical_field,
            change.baseline_rule_index,
            change.guided_rule_index,
            json.dumps(change.before, sort_keys=True, default=str),
            json.dumps(change.after, sort_keys=True, default=str),
        )
        if key not in seen_keys:
            seen_keys.add(key)
            unique_changes.append(change)

    implementable = bool(accepted_receipts) and bool(unique_changes)
    # Fail-closed: if every receipt is reject/timeout/error, force false.
    if not accepted_receipts:
        implementable = False
    if any(
        item.disposition
        in {
            AdmissionDisposition.VALIDATOR_REJECT,
            AdmissionDisposition.TIMEOUT,
            AdmissionDisposition.ERROR,
        }
        for item in receipts
    ) and not accepted_receipts:
        implementable = False

    files = tuple(predicted_files) if predicted_files is not None else DEFAULT_PREDICTED_FILES
    commands = (
        tuple(validation_commands)
        if validation_commands is not None
        else DEFAULT_VALIDATION_COMMANDS
    )

    return PlateauCodexPacket(
        packet_id=packet_id,
        baseline_l1=baseline_l1,
        residual_refs=residual_tuple,
        proposals=proposal_tuple,
        admission_receipts=tuple(receipts),
        proof_obligations=tuple(obligations),
        predicted_files=files,
        validation_commands=commands,
        implementable=implementable,
        baseline_arm_id=baseline_arm_id,
        case_id=case_id,
        admitted_field_changes=tuple(unique_changes) if implementable else (),
        detail=detail,
        baseline_e2e=baseline_e2e,
    )


def build_packet_from_proposal_admission(
    *,
    packet_id: str,
    baseline_l1: CanonicalRuleIR,
    residual_ref: ResidualRef,
    proposal: TeacherProposal,
    admission: StructuralAdmissionResult,
    predicted_files: Sequence[str] | None = None,
    validation_commands: Sequence[str] | None = None,
    case_id: str | None = None,
    detail: str | None = None,
) -> PlateauCodexPacket:
    """Convenience builder for the common single-proposal admission path.

    When the proposal lacks field_changes but carries a candidate L1, fill
    field_changes from the canonical diff so admission receipts stay aligned.
    """

    if not isinstance(admission, StructuralAdmissionResult):
        raise PlateauCodexPacketError(
            "admission must be StructuralAdmissionResult"
        )
    active_proposal = proposal
    if (
        not proposal.field_changes
        and proposal.candidate_l1 is not None
        and proposal.candidate_l1 != baseline_l1
    ):
        changes = canonical_field_changes(baseline_l1, proposal.candidate_l1)
        active_proposal = TeacherProposal(
            proposal_id=proposal.proposal_id,
            teacher=proposal.teacher,
            residual_ref_ids=proposal.residual_ref_ids
            or (residual_ref.residual_id,),
            allowed_field_paths=proposal.allowed_field_paths,
            candidate_l1=proposal.candidate_l1,
            field_changes=changes,
            detail=proposal.detail,
            semantic_authority=False,
        )
    elif not proposal.residual_ref_ids:
        active_proposal = TeacherProposal(
            proposal_id=proposal.proposal_id,
            teacher=proposal.teacher,
            residual_ref_ids=(residual_ref.residual_id,),
            allowed_field_paths=proposal.allowed_field_paths,
            candidate_l1=proposal.candidate_l1,
            field_changes=proposal.field_changes,
            detail=proposal.detail,
            semantic_authority=False,
        )

    return build_plateau_codex_packet(
        packet_id=packet_id,
        baseline_l1=baseline_l1,
        residual_refs=(residual_ref,),
        proposals=(active_proposal,),
        admission_results=(admission,),
        predicted_files=predicted_files,
        validation_commands=validation_commands,
        case_id=case_id or residual_ref.case_id,
        detail=detail,
        proposal_ids_for_admissions=(active_proposal.proposal_id,),
    )


__all__ = [
    "ALLOWED_PREDICTED_FILE_PREFIXES",
    "DEFAULT_BASELINE_ARM_ID",
    "DEFAULT_BASELINE_E2E",
    "DEFAULT_PREDICTED_FILES",
    "DEFAULT_VALIDATION_COMMANDS",
    "KNOWN_TEACHERS",
    "NON_IMPLEMENTABLE_DISPOSITIONS",
    "PLATEAU_ADMISSION_RECEIPT_INTERFACE",
    "PLATEAU_CODEX_PACKET_EVIDENCE",
    "PLATEAU_CODEX_PACKET_INTERFACE",
    "PLATEAU_CODEX_PACKET_SCHEMA",
    "PLATEAU_PROOF_OBLIGATION_INTERFACE",
    "PLATEAU_RESIDUAL_REF_INTERFACE",
    "PLATEAU_TEACHER_PROPOSAL_INTERFACE",
    "PlateauAdmissionReceipt",
    "PlateauCodexPacket",
    "PlateauCodexPacketError",
    "ProofObligation",
    "ProverCheckReceipt",
    "ResidualRef",
    "TeacherKind",
    "TeacherProposal",
    "baseline_l1_digest",
    "build_packet_from_proposal_admission",
    "build_plateau_codex_packet",
    "disposition_is_implementable",
    "field_change_from_dict",
    "field_change_path",
    "mint_proof_obligations",
]
