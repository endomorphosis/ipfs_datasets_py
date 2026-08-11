"""Legacy logic import boundary with shared artifacts (LFP2-015).

Interfaces:

* ``LegacyLogicBoundary@2`` — admit modal, temporal, resource, TDFOL, and
  CEC/DCEC surfaces only under a declared ``LogicProfileCatalog@2`` profile,
  emitting ``ParseArtifact@2`` / ``ElaborationArtifact@2`` plus explicit
  ambiguity/loss receipts for every approximation.

This module does not rewrite legacy islands (``legacy_modal``, modal/temporal/
resource parsers).  It is the compatibility importer that refuses profile-free
overloaded operators and silent legacy approximations.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.parsers import legacy_modal as legacy_v1
from ipfs_datasets_py.logic.parsers import modal as modal_v1
from ipfs_datasets_py.logic.parsers import resource as resource_v1
from ipfs_datasets_py.logic.parsers import temporal as temporal_v1
from ipfs_datasets_py.logic.parsers.frontend_contract import (
    FrontendLimits,
    LogicFrontendDescriptor,
    SharedFrontendConformance,
    validate_frontend_descriptor,
)
from ipfs_datasets_py.logic.parsers.profile_catalog_v2 import (
    DEFAULT_FRONTEND_LIMITS,
    LOGIC_PROFILE_CATALOG_V2_INTERFACE,
    PROFILE_CATALOG_GOAL_ID,
    PROFILE_CATALOG_TASK_ID,
    LossReceiptRequiredError,
    LogicProfileCatalog,
    ProfileCatalogEntry,
    ProfileFamilyKind,
    ProfileRequiredError,
    ProfileSourceKind,
    UnknownProfileError,
    default_profile_catalog,
)
from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
    ELABORATION_ARTIFACT_V2_INTERFACE,
    PARSE_ARTIFACT_V2_INTERFACE,
    ElaborationArtifactStatus,
    ElaborationArtifactV2,
    ParseArtifactV2,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    LogicNode,
    TypedExpression,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    CSTNodeRole,
    DiagnosticSeverity,
    LogicCST,
    LogicCSTNode,
    ParseStatus,
    SourceDocument,
    SourceRange,
    SurfaceASTRef,
    SyntaxContractError,
    SyntaxDiagnostic,
)
from ipfs_datasets_py.logic.syntax_core.registry import ParserKey
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LEGACY_LOGIC_BOUNDARY_V2_INTERFACE: Final = "LegacyLogicBoundary@2"
LEGACY_LOGIC_BOUNDARY_V2_SCHEMA_VERSION: Final = "legacy-logic-boundary/v2"
LEGACY_LOGIC_BOUNDARY_V2_MODULE_VERSION: Final = "2.0.0"
LEGACY_IMPORT_RESULT_V2_SCHEMA: Final = "legacy-import-result/v2"
LEGACY_LOSS_RECEIPT_V2_SCHEMA: Final = "legacy-loss-receipt/v2"
LEGACY_AMBIGUITY_V2_SCHEMA: Final = "legacy-ambiguity/v2"

LEGACY_BOUNDARY_TASK_ID: Final = PROFILE_CATALOG_TASK_ID
LEGACY_BOUNDARY_GOAL_ID: Final = PROFILE_CATALOG_GOAL_ID

# Diagnostic codes (namespaced; extend v1 + catalog gates).
CODE_PROFILE_REQUIRED: Final = "legacy_v2.profile_required"
CODE_PROFILE_UNKNOWN: Final = "legacy_v2.profile_unknown"
CODE_LOSS_RECEIPT_REQUIRED: Final = "legacy_v2.loss_receipt_required"
CODE_OVERLOADED_OPERATOR: Final = "legacy_v2.overloaded_operator"
CODE_FAMILY_MISMATCH: Final = "legacy_v2.family_mismatch"
CODE_EMPTY_INPUT: Final = "legacy_v2.empty_input"
CODE_PARSE_FAILED: Final = "legacy_v2.parse_failed"
CODE_UNSUPPORTED_SURFACE: Final = "legacy_v2.unsupported_surface"
CODE_LEGACY_APPROXIMATION: Final = "legacy_v2.legacy_approximation"
CODE_SHARED_ARTIFACT: Final = "legacy_v2.shared_artifact"

# Re-export stable v1 codes used on receipts.
CODE_UNKNOWN_CHARACTER: Final = legacy_v1.CODE_UNKNOWN_CHARACTER
CODE_UNKNOWN_SORT: Final = legacy_v1.CODE_UNKNOWN_SORT
CODE_OPF_AMBIGUITY: Final = legacy_v1.CODE_OPF_AMBIGUITY
CODE_LOSS: Final = legacy_v1.CODE_LOSS
CODE_IMPLIES_ASSOC: Final = legacy_v1.CODE_IMPLIES_ASSOC

_ALL_LEGACY_V2_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_PROFILE_REQUIRED,
        CODE_PROFILE_UNKNOWN,
        CODE_LOSS_RECEIPT_REQUIRED,
        CODE_OVERLOADED_OPERATOR,
        CODE_FAMILY_MISMATCH,
        CODE_EMPTY_INPUT,
        CODE_PARSE_FAILED,
        CODE_UNSUPPORTED_SURFACE,
        CODE_LEGACY_APPROXIMATION,
        CODE_SHARED_ARTIFACT,
        CODE_UNKNOWN_CHARACTER,
        CODE_UNKNOWN_SORT,
        CODE_OPF_AMBIGUITY,
        CODE_LOSS,
        CODE_IMPLIES_ASSOC,
    }
)

LEGACY_BOUNDARY_DESCRIPTOR_ID: Final = "frontend:legacy_logic_boundary:v2:join"


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class LegacyImportFamily(StrEnum):
    """Declared import family for the v2 boundary."""

    TEMPORAL = "temporal"
    MODAL = "modal"
    RESOURCE = "resource"
    TDFOL = "tdfol"
    DCEC = "dcec"
    CEC = "cec"
    LEGAL = "legal"
    EVENT_CALCULUS = "event_calculus"
    AUTO = "auto"


class LossKindV2(StrEnum):
    """Kinds of explicit loss recorded on the v2 receipt."""

    NONE = "none"
    LEGACY_APPROXIMATION = "legacy_approximation"
    AMBIGUITY_RESOLUTION = "ambiguity_resolution"
    UNSUPPORTED_SURFACE = "unsupported_surface"
    SORT_REJECTION = "sort_rejection"
    CHARACTER_REJECTION = "character_rejection"
    PARTIAL_LOWERING = "partial_lowering"
    PROFILE_GATE = "profile_gate"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LegacyLogicBoundaryError(SyntaxContractError):
    """Base class for LegacyLogicBoundary@2 failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_PARSE_FAILED,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: "LegacyImportResultV2 | None" = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = tuple(diagnostics)
        self.result = result


class ProfileGateError(LegacyLogicBoundaryError):
    """Raised when a declared profile is missing or unknown."""


class LossReceiptGateError(LegacyLogicBoundaryError):
    """Raised when a required loss receipt is absent."""


# ---------------------------------------------------------------------------
# Receipts / result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LossReceiptV2:
    """Explicit loss receipt for a legacy approximation or partial lower.

    Interface fragment: ``legacy-loss-receipt/v2``.
    """

    receipt_id: str
    profile_id: str
    loss_kind: LossKindV2 | str
    message: str
    construct: str = ""
    bounds: Mapping[str, Any] = field(default_factory=dict)
    authority_ceiling: str = "advisory"
    recoverable: bool = False
    features_dropped: tuple[str, ...] = ()
    features_retained: tuple[str, ...] = ()
    schema_version: str = LEGACY_LOSS_RECEIPT_V2_SCHEMA

    def __post_init__(self) -> None:
        rid = str(self.receipt_id or "").strip()
        if not rid:
            raise SyntaxContractError("LossReceiptV2.receipt_id is required")
        object.__setattr__(self, "receipt_id", rid)
        pid = str(self.profile_id or "").strip()
        if not pid:
            raise SyntaxContractError("LossReceiptV2.profile_id is required")
        object.__setattr__(self, "profile_id", pid)
        kind = self.loss_kind
        if not isinstance(kind, LossKindV2):
            try:
                kind = LossKindV2(str(kind))
            except ValueError as error:
                raise SyntaxContractError(
                    f"unknown loss_kind {self.loss_kind!r}"
                ) from error
        object.__setattr__(self, "loss_kind", kind)
        object.__setattr__(self, "message", str(self.message or "").strip())
        object.__setattr__(self, "construct", str(self.construct or "").strip())
        object.__setattr__(self, "bounds", dict(self.bounds or {}))
        object.__setattr__(
            self,
            "features_dropped",
            tuple(str(item) for item in self.features_dropped),
        )
        object.__setattr__(
            self,
            "features_retained",
            tuple(str(item) for item in self.features_retained),
        )
        if self.schema_version != LEGACY_LOSS_RECEIPT_V2_SCHEMA:
            raise SyntaxContractError(
                f"unsupported LossReceiptV2 schema {self.schema_version!r}"
            )

    @property
    def has_loss(self) -> bool:
        return self.loss_kind is not LossKindV2.NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "bounds": dict(self.bounds),
            "construct": self.construct,
            "features_dropped": list(self.features_dropped),
            "features_retained": list(self.features_retained),
            "has_loss": self.has_loss,
            "loss_kind": (
                self.loss_kind.value
                if isinstance(self.loss_kind, LossKindV2)
                else str(self.loss_kind)
            ),
            "message": self.message,
            "profile_id": self.profile_id,
            "receipt_id": self.receipt_id,
            "recoverable": self.recoverable,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LossReceiptV2":
        if not isinstance(value, Mapping):
            raise SyntaxContractError("LossReceiptV2 must be a mapping")
        return cls(
            receipt_id=str(value.get("receipt_id") or ""),
            profile_id=str(value.get("profile_id") or ""),
            loss_kind=str(value.get("loss_kind") or LossKindV2.NONE.value),
            message=str(value.get("message") or ""),
            construct=str(value.get("construct") or ""),
            bounds=dict(value.get("bounds") or {}),
            authority_ceiling=str(value.get("authority_ceiling") or "advisory"),
            recoverable=bool(value.get("recoverable", False)),
            features_dropped=tuple(value.get("features_dropped") or ()),
            features_retained=tuple(value.get("features_retained") or ()),
            schema_version=str(
                value.get("schema_version") or LEGACY_LOSS_RECEIPT_V2_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class AmbiguityReceiptV2:
    """Explicit ambiguity resolution under a declared profile."""

    code: str
    message: str
    span: tuple[int, int] = (0, 0)
    candidates: tuple[str, ...] = ()
    resolution: str = ""
    profile_id: str = ""
    schema_version: str = LEGACY_AMBIGUITY_V2_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": list(self.candidates),
            "code": self.code,
            "message": self.message,
            "profile_id": self.profile_id,
            "resolution": self.resolution,
            "schema_version": self.schema_version,
            "span": list(self.span),
        }


@dataclass(frozen=True, slots=True)
class LegacyImportResultV2:
    """Result of a LegacyLogicBoundary@2 import attempt.

    Always carries parse/elaboration artifact slots (possibly failed) so
    callers never receive an untyped raw formula.
    """

    status: ParseStatus
    family: str
    profile_id: str
    root: LogicNode | None = None
    typed_expression: TypedExpression | None = None
    parse_artifact: ParseArtifactV2 | None = None
    elaboration_artifact: ElaborationArtifactV2 | None = None
    loss_receipts: tuple[LossReceiptV2, ...] = ()
    ambiguities: tuple[AmbiguityReceiptV2, ...] = ()
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    source_document: SourceDocument | None = None
    printed: str = ""
    legacy_receipt: Mapping[str, Any] | None = None
    schema_version: str = LEGACY_IMPORT_RESULT_V2_SCHEMA

    interface: ClassVar[str] = LEGACY_LOGIC_BOUNDARY_V2_INTERFACE

    @property
    def ok(self) -> bool:
        return (
            self.status is ParseStatus.OK
            and self.root is not None
            and self.parse_artifact is not None
            and self.elaboration_artifact is not None
        )

    @property
    def emits_shared_artifacts(self) -> bool:
        return (
            self.parse_artifact is not None
            and self.elaboration_artifact is not None
        )

    @property
    def has_loss_receipt(self) -> bool:
        return any(item.has_loss for item in self.loss_receipts) or bool(
            self.loss_receipts
        )

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguities": [item.to_dict() for item in self.ambiguities],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "elaboration_artifact": (
                None
                if self.elaboration_artifact is None
                else self.elaboration_artifact.to_dict()
            ),
            "emits_shared_artifacts": self.emits_shared_artifacts,
            "family": self.family,
            "has_loss_receipt": self.has_loss_receipt,
            "interface": self.interface,
            "legacy_receipt": (
                None if self.legacy_receipt is None else dict(self.legacy_receipt)
            ),
            "loss_receipts": [item.to_dict() for item in self.loss_receipts],
            "parse_artifact": (
                None
                if self.parse_artifact is None
                else self.parse_artifact.to_dict()
            ),
            "printed": self.printed,
            "profile_id": self.profile_id,
            "root": None if self.root is None else self.root.to_dict(),
            "schema_version": self.schema_version,
            "status": (
                self.status.value
                if isinstance(self.status, ParseStatus)
                else str(self.status)
            ),
            "typed_expression": (
                None
                if self.typed_expression is None
                else self.typed_expression.to_dict()
            ),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _surface_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _diag(
    *,
    code: str,
    message: str,
    diagnostic_id: str,
    range: SourceRange | None = None,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    remediation: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    return SyntaxDiagnostic(
        diagnostic_id=diagnostic_id,
        code=code,
        message=message,
        severity=severity,
        range=range,
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


def _unique_diagnostics(
    diagnostics: Sequence[SyntaxDiagnostic],
    *,
    prefix: str,
) -> tuple[SyntaxDiagnostic, ...]:
    out: list[SyntaxDiagnostic] = []
    for index, item in enumerate(diagnostics, start=1):
        if not isinstance(item, SyntaxDiagnostic):
            continue
        out.append(
            SyntaxDiagnostic(
                diagnostic_id=f"{prefix}:{index}",
                code=item.code,
                message=item.message,
                severity=item.severity,
                range=item.range,
                remediation=item.remediation,
                related_diagnostic_ids=(),
                metadata={
                    **dict(item.metadata),
                    "original_diagnostic_id": item.diagnostic_id,
                },
            )
        )
    return tuple(out)


def _covering_cst(document: SourceDocument, *, cst_id: str) -> LogicCST:
    root = LogicCSTNode(
        node_id="node:root",
        kind="source_file",
        range=document.full_range(),
        role=CSTNodeRole.ROOT,
        children=(
            LogicCSTNode(
                node_id="node:body",
                kind="formula",
                range=document.full_range(),
                role=CSTNodeRole.INNER,
            ),
        ),
    )
    return LogicCST(
        cst_id=cst_id,
        document_id=document.document_id,
        root=root,
        source_length=document.byte_length,
    )


def _surface_ast(
    *,
    family: str,
    profile_id: str,
    full_range: SourceRange,
) -> tuple[SurfaceASTRef, ...]:
    safe_family = "".join(
        ch if ch.isalnum() or ch in "._-" else "_"
        for ch in str(family).lower()
    ) or "unknown"
    return (
        SurfaceASTRef(
            node_id="ast:root",
            kind=f"legacy.{safe_family}.formula",
            range=full_range,
            metadata={"profile_id": profile_id, "family": family},
        ),
    )


def _typed_expression_for(
    root: LogicNode,
    *,
    expression_id: str,
    family: str,
    profile_id: str,
    existing: TypedExpression | None = None,
) -> TypedExpression:
    if existing is not None:
        return existing
    signature = propositional_signature(
        f"sig:legacy-v2:{expression_id}",
        (),
        family=family,
        profile=profile_id,
    )
    return TypedExpression(
        expression_id=expression_id,
        root=root,
        signature=signature,
        family=family,
        profile=profile_id,
        elaborate_on_init=False,
        metadata={"legacy_boundary": True},
    )


def _resolve_family(
    family: LegacyImportFamily | str,
    text: str,
) -> LegacyImportFamily:
    fam = (
        family
        if isinstance(family, LegacyImportFamily)
        else LegacyImportFamily(str(family))
    )
    if fam is not LegacyImportFamily.AUTO:
        return fam

    stripped = text.strip()
    if not stripped:
        return LegacyImportFamily.TDFOL

    # Prefer native temporal/modal/resource cues before legacy detection.
    if any(
        token in stripped
        for token in ("emp", "|->", "points_to", " -* ", " wand ", " sep ")
    ) or " * " in stripped:
        return LegacyImportFamily.RESOURCE
    if any(
        token in stripped
        for token in (
            "eventually",
            "always",
            "next",
            "until",
            "release",
            "historically",
            "previous",
        )
    ):
        return LegacyImportFamily.TEMPORAL
    if any(
        token in stripped.lower()
        for token in (
            "box ",
            "diamond ",
            "necessary",
            "possible",
            "knows",
            "believes",
            "intends",
        )
    ):
        return LegacyImportFamily.MODAL

    detected = legacy_v1.detect_legacy_family(text)
    mapping = {
        legacy_v1.LegacyFamilyKind.TDFOL: LegacyImportFamily.TDFOL,
        legacy_v1.LegacyFamilyKind.DCEC: LegacyImportFamily.DCEC,
        legacy_v1.LegacyFamilyKind.CEC: LegacyImportFamily.CEC,
        legacy_v1.LegacyFamilyKind.MODAL: LegacyImportFamily.MODAL,
        legacy_v1.LegacyFamilyKind.LEGAL: LegacyImportFamily.LEGAL,
        legacy_v1.LegacyFamilyKind.EVENT_CALCULUS: LegacyImportFamily.EVENT_CALCULUS,
    }
    return mapping.get(detected, LegacyImportFamily.TDFOL)


def _default_profile_id_for_family(
    family: LegacyImportFamily,
    catalog: LogicProfileCatalog,
) -> str:
    """Pick a stable default profile id for *family* from the catalog."""

    preferred: dict[LegacyImportFamily, tuple[str, ...]] = {
        LegacyImportFamily.TEMPORAL: ("ltl_infinite_discrete",),
        LegacyImportFamily.MODAL: ("kripke_k",),
        LegacyImportFamily.RESOURCE: ("separation_classical", "separation:classical"),
        LegacyImportFamily.TDFOL: ("tdfol_default",),
        LegacyImportFamily.DCEC: ("dcec_default",),
        LegacyImportFamily.CEC: ("cec_classical_import",),
        LegacyImportFamily.LEGAL: ("deontic_monadic_strong",),
        LegacyImportFamily.EVENT_CALCULUS: ("cec_classical_import", "dcec_default"),
    }
    for candidate in preferred.get(family, ()):
        try:
            return catalog.get(candidate).profile_id
        except UnknownProfileError:
            continue

    family_map = {
        LegacyImportFamily.TEMPORAL: ProfileFamilyKind.TEMPORAL,
        LegacyImportFamily.MODAL: ProfileFamilyKind.MODAL,
        LegacyImportFamily.RESOURCE: ProfileFamilyKind.RESOURCE,
        LegacyImportFamily.TDFOL: ProfileFamilyKind.TDFOL,
        LegacyImportFamily.DCEC: ProfileFamilyKind.DCEC,
        LegacyImportFamily.CEC: ProfileFamilyKind.CEC,
        LegacyImportFamily.LEGAL: ProfileFamilyKind.DEONTIC,
        LegacyImportFamily.EVENT_CALCULUS: ProfileFamilyKind.CEC,
    }
    kind = family_map.get(family)
    if kind is not None:
        matches = catalog.by_family(kind)
        if matches:
            return matches[0].profile_id
    raise ProfileGateError(
        f"no catalog profile available for family {family.value!r}",
        code=CODE_PROFILE_REQUIRED,
    )


def _family_matches_entry(
    family: LegacyImportFamily,
    entry: ProfileCatalogEntry,
) -> bool:
    fam = entry.family
    if family is LegacyImportFamily.TEMPORAL:
        return fam is ProfileFamilyKind.TEMPORAL
    if family is LegacyImportFamily.MODAL:
        return fam in {
            ProfileFamilyKind.MODAL,
            ProfileFamilyKind.DEONTIC,
            ProfileFamilyKind.EPISTEMIC,
            ProfileFamilyKind.DOXASTIC,
            ProfileFamilyKind.INTENTION,
        }
    if family is LegacyImportFamily.RESOURCE:
        return fam in {
            ProfileFamilyKind.RESOURCE,
            ProfileFamilyKind.SESSION,
            ProfileFamilyKind.REFINEMENT,
        }
    if family is LegacyImportFamily.TDFOL:
        return fam is ProfileFamilyKind.TDFOL
    if family is LegacyImportFamily.DCEC:
        return fam is ProfileFamilyKind.DCEC
    if family is LegacyImportFamily.CEC:
        return fam in {ProfileFamilyKind.CEC, ProfileFamilyKind.DCEC}
    if family is LegacyImportFamily.LEGAL:
        return fam is ProfileFamilyKind.DEONTIC
    if family is LegacyImportFamily.EVENT_CALCULUS:
        return fam in {ProfileFamilyKind.CEC, ProfileFamilyKind.DCEC}
    return True


def _loss_from_legacy_losses(
    *,
    profile_id: str,
    losses: Sequence[Any],
    seq: int,
) -> list[LossReceiptV2]:
    receipts: list[LossReceiptV2] = []
    for index, loss in enumerate(losses, start=1):
        if hasattr(loss, "to_dict"):
            payload = loss.to_dict()
        elif isinstance(loss, Mapping):
            payload = dict(loss)
        else:
            continue
        code = str(payload.get("code") or CODE_LOSS)
        kind = LossKindV2.LEGACY_APPROXIMATION
        if code == CODE_UNKNOWN_SORT:
            kind = LossKindV2.SORT_REJECTION
        elif code == CODE_UNKNOWN_CHARACTER:
            kind = LossKindV2.CHARACTER_REJECTION
        elif code == CODE_OPF_AMBIGUITY:
            kind = LossKindV2.AMBIGUITY_RESOLUTION
        receipts.append(
            LossReceiptV2(
                receipt_id=f"loss:legacy-v2:{seq}:{index}",
                profile_id=profile_id,
                loss_kind=kind,
                message=str(payload.get("message") or code),
                construct=str(payload.get("construct") or ""),
                bounds={"legacy_code": code},
                authority_ceiling="advisory",
                recoverable=bool(payload.get("recoverable", False)),
                features_dropped=(code,),
            )
        )
    return receipts


def _ambiguities_from_legacy(
    *,
    profile_id: str,
    ambiguities: Sequence[Any],
) -> tuple[AmbiguityReceiptV2, ...]:
    out: list[AmbiguityReceiptV2] = []
    for item in ambiguities:
        if hasattr(item, "to_dict"):
            payload = item.to_dict()
        elif isinstance(item, Mapping):
            payload = dict(item)
        else:
            continue
        span_raw = payload.get("span") or (0, 0)
        if isinstance(span_raw, Sequence) and len(span_raw) >= 2:
            span = (int(span_raw[0]), int(span_raw[1]))
        else:
            span = (0, 0)
        out.append(
            AmbiguityReceiptV2(
                code=str(payload.get("code") or CODE_OPF_AMBIGUITY),
                message=str(payload.get("message") or "ambiguity"),
                span=span,
                candidates=tuple(payload.get("candidates") or ()),
                resolution=str(payload.get("resolution") or ""),
                profile_id=profile_id,
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Boundary implementation
# ---------------------------------------------------------------------------


class LegacyLogicBoundary:
    """Import modal/temporal/resource/TDFOL/DCEC under declared profiles.

    Interface: ``LegacyLogicBoundary@2``.
    """

    interface: ClassVar[str] = LEGACY_LOGIC_BOUNDARY_V2_INTERFACE
    schema_version: ClassVar[str] = LEGACY_LOGIC_BOUNDARY_V2_SCHEMA_VERSION
    module_version: ClassVar[str] = LEGACY_LOGIC_BOUNDARY_V2_MODULE_VERSION
    task_id: ClassVar[str] = LEGACY_BOUNDARY_TASK_ID
    goal_id: ClassVar[str] = LEGACY_BOUNDARY_GOAL_ID

    def __init__(
        self,
        *,
        catalog: LogicProfileCatalog | None = None,
        limits: FrontendLimits | None = None,
        require_explicit_profile: bool = True,
    ) -> None:
        self.catalog = catalog if catalog is not None else default_profile_catalog()
        self.limits = limits if limits is not None else DEFAULT_FRONTEND_LIMITS
        self.require_explicit_profile = bool(require_explicit_profile)
        self._legacy = legacy_v1.LegacyLogicImporter()
        self._seq = 0

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}:{self._seq}"

    def _failed(
        self,
        *,
        family: str,
        profile_id: str,
        document: SourceDocument,
        diagnostics: Sequence[SyntaxDiagnostic],
        loss_receipts: Sequence[LossReceiptV2] = (),
        ambiguities: Sequence[AmbiguityReceiptV2] = (),
        legacy_receipt: Mapping[str, Any] | None = None,
        status: ParseStatus = ParseStatus.FAILED,
    ) -> LegacyImportResultV2:
        request_id = self._next_id("req:legacy-v2")
        diags = _unique_diagnostics(
            diagnostics, prefix=f"diag:legacy-v2:{request_id}"
        )
        parse_artifact = ParseArtifactV2.from_document(
            document,
            artifact_id=f"art:legacy-v2:parse:{request_id}",
            request_id=request_id,
            status=status,
            cst=_covering_cst(document, cst_id=f"cst:legacy-v2:{request_id}"),
            surface_ast=_surface_ast(
                family=family,
                profile_id=profile_id or "none",
                full_range=document.full_range(),
            ),
            diagnostics=diags,
            metadata={
                "interface": self.interface,
                "family": family,
                "profile_id": profile_id,
                "emits_shared_artifacts": True,
            },
        )
        elab = ElaborationArtifactV2(
            artifact_id=f"art:legacy-v2:elab:{request_id}",
            parse_artifact_id=parse_artifact.artifact_id,
            document_id=document.document_id,
            source_digest=document.content_digest,
            status=ElaborationArtifactStatus.FAILED,
            parse_content_digest=parse_artifact.content_digest,
            parse_lineage_digest=parse_artifact.lineage_digest,
            diagnostics=diags,
            metadata={
                "interface": self.interface,
                "family": family,
                "profile_id": profile_id,
                "execution_admitted": False,
            },
        )
        return LegacyImportResultV2(
            status=status,
            family=family,
            profile_id=profile_id,
            parse_artifact=parse_artifact,
            elaboration_artifact=elab,
            loss_receipts=tuple(loss_receipts),
            ambiguities=tuple(ambiguities),
            diagnostics=diags,
            source_document=document,
            legacy_receipt=legacy_receipt,
        )

    def _ok(
        self,
        *,
        family: str,
        profile_id: str,
        document: SourceDocument,
        root: LogicNode,
        typed_expression: TypedExpression | None,
        loss_receipts: Sequence[LossReceiptV2],
        ambiguities: Sequence[AmbiguityReceiptV2],
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        legacy_receipt: Mapping[str, Any] | None = None,
        printed: str = "",
    ) -> LegacyImportResultV2:
        request_id = self._next_id("req:legacy-v2")
        diags = _unique_diagnostics(
            diagnostics, prefix=f"diag:legacy-v2:{request_id}"
        )
        surface = _surface_ast(
            family=family,
            profile_id=profile_id,
            full_range=document.full_range(),
        )
        parse_artifact = ParseArtifactV2.from_document(
            document,
            artifact_id=f"art:legacy-v2:parse:{request_id}",
            request_id=request_id,
            status=ParseStatus.OK,
            cst=_covering_cst(document, cst_id=f"cst:legacy-v2:{request_id}"),
            surface_ast=surface,
            typed_roots=(root,),
            diagnostics=diags,
            ambiguity_count=len(ambiguities),
            metadata={
                "interface": self.interface,
                "family": family,
                "profile_id": profile_id,
                "emits_shared_artifacts": True,
                "loss_receipt_count": len(loss_receipts),
            },
        )
        expr = _typed_expression_for(
            root,
            expression_id=f"expr:legacy-v2:{request_id}",
            family=family,
            profile_id=profile_id,
            existing=typed_expression,
        )
        # OK elaborations cannot carry error/fatal diagnostics.
        elab_diags = tuple(
            item for item in diags if not getattr(item, "is_error", False)
        )
        elab = ElaborationArtifactV2(
            artifact_id=f"art:legacy-v2:elab:{request_id}",
            parse_artifact_id=parse_artifact.artifact_id,
            document_id=document.document_id,
            source_digest=document.content_digest,
            status=ElaborationArtifactStatus.OK,
            typed_expression=expr,
            root=root,
            normalized_root=root,
            parse_content_digest=parse_artifact.content_digest,
            parse_lineage_digest=parse_artifact.lineage_digest,
            semantic_digest=getattr(expr, "content_digest", "") or "",
            diagnostics=elab_diags,
            metadata={
                "interface": self.interface,
                "family": family,
                "profile_id": profile_id,
                "execution_admitted": False,
                "loss_receipt_count": len(loss_receipts),
                "ambiguity_count": len(ambiguities),
            },
        )
        return LegacyImportResultV2(
            status=ParseStatus.OK,
            family=family,
            profile_id=profile_id,
            root=root,
            typed_expression=expr,
            parse_artifact=parse_artifact,
            elaboration_artifact=elab,
            loss_receipts=tuple(loss_receipts),
            ambiguities=tuple(ambiguities),
            diagnostics=diags,
            source_document=document,
            printed=printed,
            legacy_receipt=legacy_receipt,
        )

    def _resolve_profile(
        self,
        *,
        family: LegacyImportFamily,
        profile_id: str | None,
        document: SourceDocument,
    ) -> ProfileCatalogEntry | LegacyImportResultV2:
        if profile_id is None or not str(profile_id).strip():
            if self.require_explicit_profile:
                diag = _diag(
                    code=CODE_PROFILE_REQUIRED,
                    message=(
                        "overloaded operators and legacy approximations require "
                        "a declared profile; fail closed"
                    ),
                    diagnostic_id=self._next_id("diag:legacy-v2"),
                    range=document.full_range(),
                    remediation=(
                        "Pass profile_id from LogicProfileCatalog@2 "
                        f"(family={family.value})"
                    ),
                    metadata={"family": family.value},
                )
                return self._failed(
                    family=family.value,
                    profile_id="",
                    document=document,
                    diagnostics=(diag,),
                    loss_receipts=(
                        LossReceiptV2(
                            receipt_id=self._next_id("loss:legacy-v2"),
                            profile_id="none",
                            loss_kind=LossKindV2.PROFILE_GATE,
                            message="import aborted: profile required",
                            construct="profile",
                            bounds={"family": family.value},
                        ),
                    ),
                )
            try:
                resolved_id = _default_profile_id_for_family(family, self.catalog)
            except ProfileGateError as error:
                diag = _diag(
                    code=CODE_PROFILE_REQUIRED,
                    message=str(error),
                    diagnostic_id=self._next_id("diag:legacy-v2"),
                    range=document.full_range(),
                )
                return self._failed(
                    family=family.value,
                    profile_id="",
                    document=document,
                    diagnostics=(diag,),
                )
            profile_id = resolved_id

        try:
            entry = self.catalog.require(profile_id)
        except (ProfileRequiredError, UnknownProfileError) as error:
            diag = _diag(
                code=CODE_PROFILE_UNKNOWN,
                message=str(error),
                diagnostic_id=self._next_id("diag:legacy-v2"),
                range=document.full_range(),
                metadata={"profile_id": profile_id},
            )
            return self._failed(
                family=family.value,
                profile_id=str(profile_id or ""),
                document=document,
                diagnostics=(diag,),
            )

        if not _family_matches_entry(family, entry):
            diag = _diag(
                code=CODE_FAMILY_MISMATCH,
                message=(
                    f"profile {entry.profile_id!r} family {entry.family_id!r} "
                    f"does not match import family {family.value!r}"
                ),
                diagnostic_id=self._next_id("diag:legacy-v2"),
                range=document.full_range(),
                metadata={
                    "profile_id": entry.profile_id,
                    "profile_family": entry.family_id,
                    "import_family": family.value,
                },
            )
            return self._failed(
                family=family.value,
                profile_id=entry.profile_id,
                document=document,
                diagnostics=(diag,),
            )
        return entry

    def import_text(
        self,
        text: str,
        *,
        family: LegacyImportFamily | str = LegacyImportFamily.AUTO,
        profile_id: str | None = None,
        document_id: str = "doc:legacy-v2:1",
    ) -> LegacyImportResultV2:
        """Import *text* under a declared catalog profile with shared artifacts."""

        if not isinstance(text, str):
            raise SyntaxContractError("import_text requires a string")

        document = SourceDocument.from_text(document_id, text)
        if not text.strip():
            diag = _diag(
                code=CODE_EMPTY_INPUT,
                message="empty legacy import input",
                diagnostic_id=self._next_id("diag:legacy-v2"),
                range=document.full_range(),
            )
            return self._failed(
                family=str(family),
                profile_id=str(profile_id or ""),
                document=document,
                diagnostics=(diag,),
            )

        fam = _resolve_family(family, text)
        resolved = self._resolve_profile(
            family=fam, profile_id=profile_id, document=document
        )
        if isinstance(resolved, LegacyImportResultV2):
            return resolved
        entry = resolved

        # Gate overloaded O/P/F when present.
        if any(ch in text for ch in ("O", "P", "F")):
            try:
                self.catalog.require_profile_for_operator("O", entry.profile_id)
            except ProfileRequiredError as error:
                diag = _diag(
                    code=CODE_OVERLOADED_OPERATOR,
                    message=str(error),
                    diagnostic_id=self._next_id("diag:legacy-v2"),
                    range=document.full_range(),
                )
                return self._failed(
                    family=fam.value,
                    profile_id=entry.profile_id,
                    document=document,
                    diagnostics=(diag,),
                )

        if fam is LegacyImportFamily.TEMPORAL:
            return self._import_temporal(text, document, entry)
        if fam is LegacyImportFamily.MODAL:
            return self._import_modal(text, document, entry)
        if fam is LegacyImportFamily.RESOURCE:
            return self._import_resource(text, document, entry)
        if fam is LegacyImportFamily.LEGAL:
            return self._import_legacy_family(
                text,
                document,
                entry,
                legacy_family=legacy_v1.LegacyFamilyKind.LEGAL,
                result_family=fam.value,
            )
        if fam is LegacyImportFamily.EVENT_CALCULUS:
            return self._import_legacy_family(
                text,
                document,
                entry,
                legacy_family=legacy_v1.LegacyFamilyKind.EVENT_CALCULUS,
                result_family=fam.value,
            )
        if fam is LegacyImportFamily.CEC:
            return self._import_legacy_family(
                text,
                document,
                entry,
                legacy_family=legacy_v1.LegacyFamilyKind.CEC,
                result_family=fam.value,
            )
        if fam is LegacyImportFamily.DCEC:
            return self._import_legacy_family(
                text,
                document,
                entry,
                legacy_family=legacy_v1.LegacyFamilyKind.DCEC,
                result_family=fam.value,
            )
        # TDFOL default.
        return self._import_legacy_family(
            text,
            document,
            entry,
            legacy_family=legacy_v1.LegacyFamilyKind.TDFOL,
            result_family=LegacyImportFamily.TDFOL.value,
        )

    def _import_temporal(
        self,
        text: str,
        document: SourceDocument,
        entry: ProfileCatalogEntry,
    ) -> LegacyImportResultV2:
        payload = dict(entry.semantic_payload)
        try:
            profile = temporal_v1.TraceSemanticsProfile.from_dict(payload)
        except Exception:
            profile = temporal_v1.profile_ltl(profile_id=entry.profile_id)

        result = temporal_v1.parse_temporal(
            text,
            profile,
            document_id=document.document_id,
            limits=self.limits.parse_limits
            if isinstance(self.limits, FrontendLimits)
            else None,
        )
        if not result.ok or result.root is None:
            diags = tuple(result.diagnostics) or (
                _diag(
                    code=CODE_PARSE_FAILED,
                    message="temporal parse failed under declared profile",
                    diagnostic_id=self._next_id("diag:legacy-v2"),
                    range=document.full_range(),
                ),
            )
            return self._failed(
                family=LegacyImportFamily.TEMPORAL.value,
                profile_id=entry.profile_id,
                document=document,
                diagnostics=diags,
                loss_receipts=(
                    LossReceiptV2(
                        receipt_id=self._next_id("loss:legacy-v2"),
                        profile_id=entry.profile_id,
                        loss_kind=LossKindV2.UNSUPPORTED_SURFACE,
                        message="temporal surface rejected under profile",
                        construct="temporal",
                        bounds={"profile_id": entry.profile_id},
                    ),
                ),
            )

        # Classic-letter admission is a profile choice; record approximation
        # when classic letters appear without admission.
        losses: list[LossReceiptV2] = []
        if any(ch in text for ch in "FGUR") and not getattr(
            profile, "admit_classic_letters", False
        ):
            # Multi-letter keywords only path succeeded; no classic-letter loss.
            pass

        # Always attach a no-loss / legacy-boundary receipt for catalog policy.
        if entry.requires_loss_receipt and not losses:
            losses.append(
                LossReceiptV2(
                    receipt_id=self._next_id("loss:legacy-v2"),
                    profile_id=entry.profile_id,
                    loss_kind=LossKindV2.NONE,
                    message="native temporal parse under declared profile; no loss",
                    construct="temporal",
                    bounds={"profile_id": entry.profile_id},
                    authority_ceiling="bounded",
                    features_retained=("temporal_parse", "shared_artifacts"),
                )
            )

        printed = ""
        try:
            printed = temporal_v1.print_temporal(result.root)
        except Exception:
            printed = ""

        return self._ok(
            family=LegacyImportFamily.TEMPORAL.value,
            profile_id=entry.profile_id,
            document=document,
            root=result.root,
            typed_expression=result.expression,
            loss_receipts=losses,
            ambiguities=(),
            diagnostics=tuple(result.diagnostics),
            printed=printed,
        )

    def _import_modal(
        self,
        text: str,
        document: SourceDocument,
        entry: ProfileCatalogEntry,
    ) -> LegacyImportResultV2:
        payload = dict(entry.semantic_payload)
        try:
            profile = modal_v1.ModalSemanticsProfile.from_dict(payload)
        except Exception:
            profile = modal_v1.profile_k(profile_id=entry.profile_id)

        result = modal_v1.parse_modal(
            text,
            profile,
            document_id=document.document_id,
            limits=self.limits.parse_limits
            if isinstance(self.limits, FrontendLimits)
            else None,
        )
        if not result.ok or result.root is None:
            diags = tuple(result.diagnostics) or (
                _diag(
                    code=CODE_PARSE_FAILED,
                    message="modal parse failed under declared profile",
                    diagnostic_id=self._next_id("diag:legacy-v2"),
                    range=document.full_range(),
                ),
            )
            return self._failed(
                family=LegacyImportFamily.MODAL.value,
                profile_id=entry.profile_id,
                document=document,
                diagnostics=diags,
                loss_receipts=(
                    LossReceiptV2(
                        receipt_id=self._next_id("loss:legacy-v2"),
                        profile_id=entry.profile_id,
                        loss_kind=LossKindV2.UNSUPPORTED_SURFACE,
                        message="modal surface rejected under profile",
                        construct="modal",
                        bounds={"profile_id": entry.profile_id},
                    ),
                ),
            )

        losses = [
            LossReceiptV2(
                receipt_id=self._next_id("loss:legacy-v2"),
                profile_id=entry.profile_id,
                loss_kind=LossKindV2.NONE,
                message="native modal parse under declared profile; no loss",
                construct="modal",
                bounds={"profile_id": entry.profile_id},
                authority_ceiling="bounded",
                features_retained=("modal_parse", "shared_artifacts"),
            )
        ]
        printed = ""
        try:
            printed = modal_v1.print_modal(result.root)
        except Exception:
            printed = ""

        return self._ok(
            family=LegacyImportFamily.MODAL.value,
            profile_id=entry.profile_id,
            document=document,
            root=result.root,
            typed_expression=result.expression,
            loss_receipts=losses,
            ambiguities=(),
            diagnostics=tuple(result.diagnostics),
            printed=printed,
        )

    def _import_resource(
        self,
        text: str,
        document: SourceDocument,
        entry: ProfileCatalogEntry,
    ) -> LegacyImportResultV2:
        payload = dict(entry.semantic_payload)
        # Restore colon-form profile ids used by resource module helpers.
        if "canonical_profile_id" in payload:
            payload = {**payload, "profile_id": payload["canonical_profile_id"]}
        try:
            profile = resource_v1.ResourceLogicProfile.from_dict(payload)
        except Exception:
            profile = resource_v1.profile_separation()

        result = resource_v1.parse_resource(
            text,
            profile,
            document_id=document.document_id,
        )
        if not getattr(result, "ok", False) or getattr(result, "root", None) is None:
            diags = tuple(getattr(result, "diagnostics", ()) or ()) or (
                _diag(
                    code=CODE_PARSE_FAILED,
                    message="resource parse failed under declared profile",
                    diagnostic_id=self._next_id("diag:legacy-v2"),
                    range=document.full_range(),
                ),
            )
            return self._failed(
                family=LegacyImportFamily.RESOURCE.value,
                profile_id=entry.profile_id,
                document=document,
                diagnostics=diags,
                loss_receipts=(
                    LossReceiptV2(
                        receipt_id=self._next_id("loss:legacy-v2"),
                        profile_id=entry.profile_id,
                        loss_kind=LossKindV2.UNSUPPORTED_SURFACE,
                        message="resource surface rejected under profile",
                        construct="resource",
                        bounds={"profile_id": entry.profile_id},
                    ),
                ),
            )

        losses: list[LossReceiptV2] = []
        # Partial lowering path: unsupported algebras require loss receipts.
        if not getattr(profile, "algebra_supported", True):
            losses.append(
                LossReceiptV2(
                    receipt_id=self._next_id("loss:legacy-v2"),
                    profile_id=entry.profile_id,
                    loss_kind=LossKindV2.PARTIAL_LOWERING,
                    message="unsupported resource algebra; partial lower only",
                    construct="resource_algebra",
                    bounds={
                        "resource_algebra": getattr(
                            profile, "resource_algebra", ""
                        ),
                        "algebra_supported": False,
                    },
                    authority_ceiling="advisory",
                    features_dropped=("full_resource_algebra",),
                    features_retained=("parse", "shared_artifacts"),
                )
            )
        else:
            losses.append(
                LossReceiptV2(
                    receipt_id=self._next_id("loss:legacy-v2"),
                    profile_id=entry.profile_id,
                    loss_kind=LossKindV2.NONE,
                    message="native resource parse under declared profile; no loss",
                    construct="resource",
                    bounds={"profile_id": entry.profile_id},
                    authority_ceiling="bounded",
                    features_retained=("resource_parse", "shared_artifacts"),
                )
            )

        # Enforce catalog loss-receipt policy.
        self.catalog.require_loss_receipt(
            entry.profile_id,
            has_loss_receipt=bool(losses),
            is_partial_lowering=any(
                item.loss_kind is LossKindV2.PARTIAL_LOWERING for item in losses
            ),
        )

        root = result.root
        expr = getattr(result, "expression", None)
        printed = ""
        try:
            printed = resource_v1.print_resource(root)
        except Exception:
            printed = ""

        return self._ok(
            family=LegacyImportFamily.RESOURCE.value,
            profile_id=entry.profile_id,
            document=document,
            root=root,
            typed_expression=expr,
            loss_receipts=losses,
            ambiguities=(),
            diagnostics=tuple(getattr(result, "diagnostics", ()) or ()),
            printed=printed,
        )

    def _import_legacy_family(
        self,
        text: str,
        document: SourceDocument,
        entry: ProfileCatalogEntry,
        *,
        legacy_family: legacy_v1.LegacyFamilyKind,
        result_family: str,
    ) -> LegacyImportResultV2:
        # Configure legacy importer profiles from catalog payload when possible.
        if entry.family is ProfileFamilyKind.TDFOL:
            try:
                self._legacy.tdfol = legacy_v1.TDFOLProfile.from_dict(
                    dict(entry.semantic_payload)
                )
            except Exception:
                self._legacy.tdfol = legacy_v1.profile_tdfol(
                    profile_id=entry.profile_id
                )
        if entry.family is ProfileFamilyKind.DCEC:
            try:
                self._legacy.dcec = legacy_v1.DCECProfile.from_dict(
                    dict(entry.semantic_payload)
                )
            except Exception:
                self._legacy.dcec = legacy_v1.profile_dcec(
                    profile_id=entry.profile_id
                )

        legacy_result = self._legacy.import_text(
            text,
            family=legacy_family,
            document_id=document.document_id,
        )
        legacy_receipt = (
            legacy_result.receipt.to_dict()
            if legacy_result.receipt is not None
            else None
        )
        ambiguities = _ambiguities_from_legacy(
            profile_id=entry.profile_id,
            ambiguities=(
                legacy_result.receipt.ambiguities
                if legacy_result.receipt is not None
                else ()
            ),
        )
        losses = _loss_from_legacy_losses(
            profile_id=entry.profile_id,
            losses=(
                legacy_result.receipt.losses
                if legacy_result.receipt is not None
                else ()
            ),
            seq=self._seq + 1,
        )

        # Legacy import is always an approximation boundary: require a receipt.
        if not losses:
            losses.append(
                LossReceiptV2(
                    receipt_id=self._next_id("loss:legacy-v2"),
                    profile_id=entry.profile_id,
                    loss_kind=LossKindV2.LEGACY_APPROXIMATION,
                    message=(
                        "legacy surface admitted under declared profile with "
                        "explicit approximation receipt"
                    ),
                    construct=result_family,
                    bounds={
                        "legacy_family": legacy_family.value,
                        "surface_sha256": _surface_digest(text),
                        "implication_associativity": (
                            legacy_result.receipt.implication_associativity
                            if legacy_result.receipt is not None
                            else "right"
                        ),
                    },
                    authority_ceiling=(
                        entry.loss_receipt_policy.authority_ceiling.value
                        if hasattr(entry.loss_receipt_policy.authority_ceiling, "value")
                        else str(entry.loss_receipt_policy.authority_ceiling)
                    ),
                    features_retained=("legacy_import", "shared_artifacts"),
                    features_dropped=("native_kernel_surface",),
                )
            )

        try:
            self.catalog.require_loss_receipt(
                entry.profile_id,
                has_loss_receipt=bool(losses),
                is_legacy_approximation=True,
            )
        except LossReceiptRequiredError as error:
            diag = _diag(
                code=CODE_LOSS_RECEIPT_REQUIRED,
                message=str(error),
                diagnostic_id=self._next_id("diag:legacy-v2"),
                range=document.full_range(),
            )
            return self._failed(
                family=result_family,
                profile_id=entry.profile_id,
                document=document,
                diagnostics=(diag,),
                loss_receipts=losses,
                ambiguities=ambiguities,
                legacy_receipt=legacy_receipt,
            )

        if not legacy_result.ok or legacy_result.root is None:
            diags = tuple(legacy_result.diagnostics) or (
                _diag(
                    code=CODE_PARSE_FAILED,
                    message="legacy import failed under declared profile",
                    diagnostic_id=self._next_id("diag:legacy-v2"),
                    range=document.full_range(),
                ),
            )
            return self._failed(
                family=result_family,
                profile_id=entry.profile_id,
                document=document,
                diagnostics=diags,
                loss_receipts=losses,
                ambiguities=ambiguities,
                legacy_receipt=legacy_receipt,
            )

        return self._ok(
            family=result_family,
            profile_id=entry.profile_id,
            document=document,
            root=legacy_result.root,
            typed_expression=legacy_result.expression,
            loss_receipts=losses,
            ambiguities=ambiguities,
            diagnostics=tuple(legacy_result.diagnostics),
            legacy_receipt=legacy_receipt,
            printed=legacy_result.printed,
        )

    def import_or_raise(self, text: str, **kwargs: Any) -> LogicNode:
        result = self.import_text(text, **kwargs)
        if not result.ok or result.root is None:
            raise LegacyLogicBoundaryError(
                "legacy import boundary failed",
                code=CODE_PARSE_FAILED,
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.root

    def build_descriptor(
        self,
        *,
        limits: FrontendLimits | None = None,
    ) -> LogicFrontendDescriptor:
        """Build the joint LegacyLogicBoundary@2 frontend descriptor."""

        # Use the tdfol_default entry for fixture/limits shape, but a unique
        # ParserKey so the joint boundary can register alongside catalog rows.
        entry = self.catalog.get("tdfol_default")
        descriptor = entry.build_frontend_descriptor(
            limits=limits if limits is not None else self.limits
        )
        return LogicFrontendDescriptor(
            descriptor_id=LEGACY_BOUNDARY_DESCRIPTOR_ID,
            key=ParserKey(
                notation_id="legacy_logic_boundary",
                notation_version="2.0.0",
                semantic_profile_id="legacy_boundary_joint",
            ),
            family_id=entry.family_id,
            features=descriptor.features,
            parse_modes=descriptor.parse_modes,
            limits=descriptor.limits,
            diagnostics=tuple(sorted(_ALL_LEGACY_V2_CODES)),
            artifact_outputs=descriptor.artifact_outputs,
            fixtures=descriptor.fixtures,
            recovery=descriptor.recovery,
            printer=descriptor.printer,
            unsupported_behavior=descriptor.unsupported_behavior,
            unsupported_nodes=descriptor.unsupported_nodes
            + (
                "profile_free_import",
                "silent_legacy_approximation",
            ),
            implementation=(
                "ipfs_datasets_py.logic.parsers.legacy_import_v2:LegacyLogicBoundary"
            ),
            metadata={
                "task_id": LEGACY_BOUNDARY_TASK_ID,
                "goal_id": LEGACY_BOUNDARY_GOAL_ID,
                "interfaces": {
                    "legacy_boundary": LEGACY_LOGIC_BOUNDARY_V2_INTERFACE,
                    "profile_catalog": LOGIC_PROFILE_CATALOG_V2_INTERFACE,
                    "parse_artifact": PARSE_ARTIFACT_V2_INTERFACE,
                    "elaboration_artifact": ELABORATION_ARTIFACT_V2_INTERFACE,
                },
                "evidence_subset": [
                    "temporal",
                    "modal",
                    "resource",
                    "tdfol",
                    "dcec",
                    "legacy",
                    "importer",
                ],
            },
        )


def build_legacy_boundary_descriptor(
    *,
    limits: FrontendLimits | None = None,
    catalog: LogicProfileCatalog | None = None,
) -> LogicFrontendDescriptor:
    boundary = LegacyLogicBoundary(catalog=catalog, limits=limits)
    return boundary.build_descriptor(limits=limits)


def register_legacy_boundary(
    registry: SharedFrontendConformance | None = None,
    *,
    limits: FrontendLimits | None = None,
    catalog: LogicProfileCatalog | None = None,
) -> tuple[SharedFrontendConformance, LogicFrontendDescriptor]:
    descriptor = build_legacy_boundary_descriptor(limits=limits, catalog=catalog)
    validate_frontend_descriptor(descriptor)
    target = registry if registry is not None else SharedFrontendConformance(
        conformance_id="conformance:legacy-logic-boundary-v2"
    )
    admitted = target.register(descriptor)
    return target, admitted


def import_legacy_v2(
    text: str,
    *,
    family: LegacyImportFamily | str = LegacyImportFamily.AUTO,
    profile_id: str | None = None,
    catalog: LogicProfileCatalog | None = None,
    require_explicit_profile: bool = True,
    **kwargs: Any,
) -> LegacyImportResultV2:
    """Convenience entry for LegacyLogicBoundary@2."""

    boundary = LegacyLogicBoundary(
        catalog=catalog,
        require_explicit_profile=require_explicit_profile,
    )
    return boundary.import_text(
        text, family=family, profile_id=profile_id, **kwargs
    )


def import_legacy_tdfol_v2(
    text: str,
    *,
    profile_id: str = "tdfol_default",
    **kwargs: Any,
) -> LegacyImportResultV2:
    return import_legacy_v2(
        text,
        family=LegacyImportFamily.TDFOL,
        profile_id=profile_id,
        **kwargs,
    )


def import_legacy_dcec_v2(
    text: str,
    *,
    profile_id: str = "dcec_default",
    **kwargs: Any,
) -> LegacyImportResultV2:
    return import_legacy_v2(
        text,
        family=LegacyImportFamily.DCEC,
        profile_id=profile_id,
        **kwargs,
    )


def import_temporal_v2(
    text: str,
    *,
    profile_id: str = "ltl_infinite_discrete",
    **kwargs: Any,
) -> LegacyImportResultV2:
    return import_legacy_v2(
        text,
        family=LegacyImportFamily.TEMPORAL,
        profile_id=profile_id,
        **kwargs,
    )


def import_modal_v2(
    text: str,
    *,
    profile_id: str = "kripke_k",
    **kwargs: Any,
) -> LegacyImportResultV2:
    return import_legacy_v2(
        text,
        family=LegacyImportFamily.MODAL,
        profile_id=profile_id,
        **kwargs,
    )


def import_resource_v2(
    text: str,
    *,
    profile_id: str = "separation_classical",
    **kwargs: Any,
) -> LegacyImportResultV2:
    return import_legacy_v2(
        text,
        family=LegacyImportFamily.RESOURCE,
        profile_id=profile_id,
        **kwargs,
    )


__all__ = [
    "LEGACY_LOGIC_BOUNDARY_V2_INTERFACE",
    "LEGACY_LOGIC_BOUNDARY_V2_SCHEMA_VERSION",
    "LEGACY_LOGIC_BOUNDARY_V2_MODULE_VERSION",
    "LEGACY_BOUNDARY_TASK_ID",
    "LEGACY_BOUNDARY_GOAL_ID",
    "LEGACY_BOUNDARY_DESCRIPTOR_ID",
    "PARSE_ARTIFACT_V2_INTERFACE",
    "ELABORATION_ARTIFACT_V2_INTERFACE",
    "CODE_PROFILE_REQUIRED",
    "CODE_PROFILE_UNKNOWN",
    "CODE_LOSS_RECEIPT_REQUIRED",
    "CODE_OVERLOADED_OPERATOR",
    "CODE_FAMILY_MISMATCH",
    "CODE_EMPTY_INPUT",
    "CODE_PARSE_FAILED",
    "CODE_UNSUPPORTED_SURFACE",
    "CODE_LEGACY_APPROXIMATION",
    "CODE_SHARED_ARTIFACT",
    "CODE_UNKNOWN_CHARACTER",
    "CODE_UNKNOWN_SORT",
    "CODE_OPF_AMBIGUITY",
    "CODE_LOSS",
    "CODE_IMPLIES_ASSOC",
    "LegacyImportFamily",
    "LossKindV2",
    "LegacyLogicBoundaryError",
    "ProfileGateError",
    "LossReceiptGateError",
    "LossReceiptV2",
    "AmbiguityReceiptV2",
    "LegacyImportResultV2",
    "LegacyLogicBoundary",
    "build_legacy_boundary_descriptor",
    "register_legacy_boundary",
    "import_legacy_v2",
    "import_legacy_tdfol_v2",
    "import_legacy_dcec_v2",
    "import_temporal_v2",
    "import_modal_v2",
    "import_resource_v2",
]
