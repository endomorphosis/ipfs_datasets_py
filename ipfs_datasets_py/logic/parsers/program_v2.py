"""Program / Hoare / contract frontend on shared artifacts (LFP2-014).

Interfaces:

* ``ProgramFrontend@2`` — controlled Hoare, contract, dynamic-logic, and
  verification-condition surface with shared ``ParseArtifact@2`` /
  ``ElaborationArtifact@2`` envelopes
* ``VerificationConditionBridge@2`` — VC lowering that admits only typed
  program-logic documents bound to parse/elaboration artifacts

The v1 module (``program.py``) remains the controlled surface syntax.  This
module converges it onto the Wave-2 shared artifact pipeline and
``LogicFrontendDescriptor@1`` contract.

Acceptance: raw program assertions cannot bypass parse/elaboration artifacts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.parsers import program as program_v1
from ipfs_datasets_py.logic.parsers.frontend_contract import (
    FRONTEND_CONTRACT_GOAL_ID,
    ExpectedDisposition,
    FeatureScopedFixture,
    FixtureKind,
    FrontendFeature,
    FrontendLimits,
    LogicFrontendDescriptor,
    PrinterContract,
    PrinterGuarantee,
    RecoveryPolicy,
    SharedFrontendConformance,
    UnsupportedBehavior,
    build_baseline_fixture_set,
    make_elaboration_artifact_output,
    make_parse_artifact_output,
    validate_frontend_descriptor,
)
from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
    ELABORATION_ARTIFACT_V2_INTERFACE,
    PARSE_ARTIFACT_V2_INTERFACE,
    ElaborationArtifactStatus,
    ElaborationArtifactV2,
    ParseArtifactV2,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    AstError,
    LogicNode,
    TypedExpression,
    mk_extension,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    CSTNodeRole,
    DiagnosticSeverity,
    LogicCST,
    LogicCSTNode,
    ParseLimits,
    ParseMode,
    ParseStatus,
    SourceDocument,
    SourceRange,
    SurfaceASTRef,
    SyntaxContractError,
    SyntaxDiagnostic,
)
from ipfs_datasets_py.logic.syntax_core.registry import ParserKey
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSignature,
)
from ipfs_datasets_py.logic.software_verification.program import ProgramIR
from ipfs_datasets_py.logic.software_verification.vc import LoopVariantPolicy

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PROGRAM_FRONTEND_V2_INTERFACE: Final = "ProgramFrontend@2"
VC_BRIDGE_V2_INTERFACE: Final = "VerificationConditionBridge@2"

PROGRAM_V2_NOTATION_ID: Final = program_v1.PROGRAM_LOGIC_NOTATION_ID
PROGRAM_V2_NOTATION_VERSION: Final = "2.0.0"
PROGRAM_V2_PROFILE_ID: Final = program_v1.PROGRAM_LOGIC_PROFILE_ID
PROGRAM_V2_FAMILY_ID: Final = program_v1.PROGRAM_LOGIC_FAMILY_ID
PROGRAM_V2_BINDING_VERSION: Final = program_v1.PROGRAM_LOGIC_BINDING_VERSION
PROGRAM_V2_STATE_VERSION: Final = program_v1.PROGRAM_LOGIC_STATE_VERSION
VC_VIEW_ROLE: Final = program_v1.VC_VIEW_ROLE

PROGRAM_V2_MODULE_VERSION: Final = "2.0.0"
PROGRAM_V2_TASK_ID: Final = "LFP2-014"
PROGRAM_V2_GOAL_ID: Final = FRONTEND_CONTRACT_GOAL_ID
PROGRAM_V2_PARSE_RESULT_SCHEMA: Final = "program-v2-parse-result/v1"
PROGRAM_V2_DESCRIPTOR_ID: Final = "frontend:canonical_program_logic:v2:dynamic_hoare"

PROGRAM_DOCUMENT_PAYLOAD_SCHEMA: Final = "program.document/v1"
PROGRAM_HOARE_PAYLOAD_SCHEMA: Final = "program.hoare/v1"
PROGRAM_CONTRACT_PAYLOAD_SCHEMA: Final = "program.contract/v1"
PROGRAM_ASSERTION_PAYLOAD_SCHEMA: Final = "program.assertion/v1"

# Diagnostic codes.
CODE_EMPTY_INPUT: Final = program_v1.CODE_EMPTY_INPUT
CODE_MALFORMED_JSON: Final = program_v1.CODE_MALFORMED_JSON
CODE_INVALID_DOCUMENT: Final = program_v1.CODE_INVALID_DOCUMENT
CODE_MISSING_PROGRAM: Final = program_v1.CODE_MISSING_PROGRAM
CODE_INVALID_CONTRACT: Final = program_v1.CODE_INVALID_CONTRACT
CODE_INVALID_HOARE: Final = program_v1.CODE_INVALID_HOARE
CODE_INVALID_DYNAMIC: Final = program_v1.CODE_INVALID_DYNAMIC
CODE_INVALID_LOOP: Final = program_v1.CODE_INVALID_LOOP
CODE_UNSUPPORTED_LOOP: Final = program_v1.CODE_UNSUPPORTED_LOOP
CODE_UNSUPPORTED_EFFECT: Final = program_v1.CODE_UNSUPPORTED_EFFECT
CODE_FAMILY_NAMESPACE: Final = program_v1.CODE_FAMILY_NAMESPACE
CODE_VERSION_MISMATCH: Final = program_v1.CODE_VERSION_MISMATCH
CODE_SOURCE_MAP: Final = program_v1.CODE_SOURCE_MAP
CODE_BRIDGE: Final = program_v1.CODE_BRIDGE
CODE_IDENTITY_MISMATCH: Final = program_v1.CODE_IDENTITY_MISMATCH
CODE_ELABORATION_FAILED: Final = "program.elaboration_failed"
CODE_RAW_ASSERTION: Final = "program.raw_assertion_rejected"
CODE_BYPASS_BLOCKED: Final = "program.artifact_bypass_blocked"
CODE_INPUT_LIMIT: Final = "program.input_limit"
CODE_VC_WITHOUT_ARTIFACTS: Final = "program.vc_requires_artifacts"

_ALL_PROGRAM_V2_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_EMPTY_INPUT,
        CODE_MALFORMED_JSON,
        CODE_INVALID_DOCUMENT,
        CODE_MISSING_PROGRAM,
        CODE_INVALID_CONTRACT,
        CODE_INVALID_HOARE,
        CODE_INVALID_DYNAMIC,
        CODE_INVALID_LOOP,
        CODE_UNSUPPORTED_LOOP,
        CODE_UNSUPPORTED_EFFECT,
        CODE_FAMILY_NAMESPACE,
        CODE_VERSION_MISMATCH,
        CODE_SOURCE_MAP,
        CODE_BRIDGE,
        CODE_IDENTITY_MISMATCH,
        CODE_ELABORATION_FAILED,
        CODE_RAW_ASSERTION,
        CODE_BYPASS_BLOCKED,
        CODE_INPUT_LIMIT,
        CODE_VC_WITHOUT_ARTIFACTS,
    }
)

DEFAULT_PARSE_LIMITS: Final = ParseLimits(
    max_input_bytes=524_288,
    max_tokens=65_536,
    max_depth=1_024,
    max_diagnostics=1_024,
    max_time_ms=30_000,
    max_memory_bytes=67_108_864,
)
DEFAULT_FRONTEND_LIMITS: Final = FrontendLimits(
    parse_limits=DEFAULT_PARSE_LIMITS,
    max_output_bytes=524_288,
    max_print_depth=1_024,
)

# Re-export commonly used v1 vocabulary.
ProgramLogicDocument = program_v1.ProgramLogicDocument
SurfaceForm = program_v1.SurfaceForm
SurfaceKind = program_v1.SurfaceKind
SourceMapBinding = program_v1.SourceMapBinding
StrongestPostcondition = program_v1.StrongestPostcondition
VerificationConditionBridgeResult = program_v1.VerificationConditionBridgeResult
UNSUPPORTED_LOOP_CONSTRUCTS = program_v1.UNSUPPORTED_LOOP_CONSTRUCTS


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProgramFrontendV2Error(SyntaxContractError):
    """Base class for ProgramFrontend@2 failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_INVALID_DOCUMENT,
        remediation: str = "",
        range: SourceRange | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.remediation = remediation
        self.range = range
        self.message = message


class ProgramArtifactBypassError(ProgramFrontendV2Error):
    """Raised when raw assertions or VC lowers bypass typed artifacts."""


# ---------------------------------------------------------------------------
# Diagnostics / CST helpers
# ---------------------------------------------------------------------------


def _diag(
    *,
    code: str,
    message: str,
    range: SourceRange | None = None,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    remediation: str = "",
    diagnostic_id: str,
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
    prefix: str = "diag:program-v2",
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


def _covering_cst(
    document: SourceDocument,
    *,
    cst_id: str,
) -> LogicCST:
    root = LogicCSTNode(
        node_id="node:root",
        kind="program_logic_json",
        range=document.full_range(),
        role=CSTNodeRole.ROOT,
        children=(),
    )
    return LogicCST(
        cst_id=cst_id,
        document_id=document.document_id,
        root=root,
        source_length=document.byte_length,
    )


def _json_text(value: Mapping[str, Any] | str) -> str:
    if isinstance(value, str):
        if not value.strip():
            raise ProgramFrontendV2Error(
                "program-logic source must be non-empty text",
                code=CODE_EMPTY_INPUT,
            )
        return value
    if not isinstance(value, Mapping):
        raise ProgramFrontendV2Error(
            "program-logic source must be a mapping or JSON text",
            code=CODE_INVALID_DOCUMENT,
        )
    return canonical_json_bytes(dict(value)).decode("utf-8")


def _source_from_text(
    text: str,
    *,
    document_id: str,
    limits: ParseLimits,
) -> SourceDocument:
    encoded = text.encode("utf-8")
    if len(encoded) > limits.max_input_bytes:
        raise ProgramFrontendV2Error(
            f"input exceeds max_input_bytes={limits.max_input_bytes}",
            code=CODE_INPUT_LIMIT,
        )
    return SourceDocument.from_text(
        document_id,
        text,
        encoding="utf-8",
        language_hint="program_logic",
        metadata={
            "interface": PROGRAM_FRONTEND_V2_INTERFACE,
            "notation_id": PROGRAM_V2_NOTATION_ID,
        },
    )


def _error_code_from_v1(error: Exception) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code
    return CODE_INVALID_DOCUMENT


# ---------------------------------------------------------------------------
# Typed expression projection
# ---------------------------------------------------------------------------


def _program_signature(*, signature_id: str) -> LogicSignature:
    return LogicSignature(
        signature_id=signature_id,
        family=PROGRAM_V2_FAMILY_ID,
        profile=PROGRAM_V2_PROFILE_ID,
        sorts=(BOOL_SORT,),
        symbols=(),
        features=("program", "hoare", "contract", "parse", "elaborate"),
    )


def _project_program_document(
    document: program_v1.ProgramLogicDocument,
    *,
    expression_id: str,
    full_range: SourceRange | None = None,
) -> tuple[TypedExpression, LogicSignature]:
    children: list[LogicNode] = []
    for index, contract in enumerate(document.contracts):
        children.append(
            mk_extension(
                f"node:program:contract:{index + 1}",
                family=PROGRAM_V2_FAMILY_ID,
                profile=PROGRAM_V2_PROFILE_ID,
                features=("program", "contract"),
                payload_schema=PROGRAM_CONTRACT_PAYLOAD_SCHEMA,
                payload={
                    "kind": "contract",
                    "schema_version": "program.contract/v1",
                    "contract_id": contract.contract_id,
                    "function_id": contract.function_id,
                    "precondition_count": len(contract.preconditions),
                    "postcondition_count": len(contract.postconditions),
                    "typed": True,
                    "raw_rejected": True,
                },
                range=full_range,
            )
        )
    for index, triple in enumerate(document.hoare_triples):
        children.append(
            mk_extension(
                f"node:program:hoare:{index + 1}",
                family=PROGRAM_V2_FAMILY_ID,
                profile=PROGRAM_V2_PROFILE_ID,
                features=("program", "hoare"),
                payload_schema=PROGRAM_HOARE_PAYLOAD_SCHEMA,
                payload={
                    "kind": "hoare_triple",
                    "schema_version": "program.hoare/v1",
                    "triple_id": triple.triple_id,
                    "command_id": triple.command_id,
                    "precondition_ids": list(triple.precondition_ids),
                    "postcondition_ids": list(triple.normal_postcondition_ids),
                    "typed": True,
                    "raw_rejected": True,
                },
                range=full_range,
            )
        )
    for index, formula in enumerate(document.dynamic_formulas):
        children.append(
            mk_extension(
                f"node:program:dynamic:{index + 1}",
                family=PROGRAM_V2_FAMILY_ID,
                profile=PROGRAM_V2_PROFILE_ID,
                features=("program", "dynamic_logic"),
                payload_schema=PROGRAM_ASSERTION_PAYLOAD_SCHEMA,
                payload={
                    "kind": "dynamic_logic",
                    "schema_version": "program.assertion/v1",
                    "formula_id": formula.formula_id,
                    "modality": formula.modality.value,
                    "program_ref_id": formula.program_ref_id,
                    "postcondition_expression_id": formula.postcondition_expression_id,
                    "typed": True,
                    "raw_rejected": True,
                },
                range=full_range,
            )
        )
    for index, surface in enumerate(document.surfaces):
        children.append(
            mk_extension(
                f"node:program:surface:{index + 1}",
                family=PROGRAM_V2_FAMILY_ID,
                profile=PROGRAM_V2_PROFILE_ID,
                features=("program", "surface", "assertion"),
                payload_schema=PROGRAM_ASSERTION_PAYLOAD_SCHEMA,
                payload={
                    "kind": "surface_form",
                    "schema_version": "program.assertion/v1",
                    "form_id": surface.form_id,
                    "surface_kind": (
                        surface.kind.value
                        if hasattr(surface.kind, "value")
                        else str(surface.kind)
                    ),
                    "typed": True,
                    "raw_rejected": True,
                },
                range=full_range,
            )
        )

    payload: dict[str, Any] = {
        "kind": "program_logic_document",
        "schema_version": "program.document/v1",
        "program_id": document.program.program_id,
        "document_id": document.document_id,
        "family_id": document.family_id,
        "profile_id": document.profile_id,
        "binding_version": document.binding_version,
        "state_version": document.state_version,
        "view_roles": [VC_VIEW_ROLE],
        "contract_ids": [item.contract_id for item in document.contracts],
        "hoare_ids": [item.triple_id for item in document.hoare_triples],
        "dynamic_ids": [item.formula_id for item in document.dynamic_formulas],
        "loop_ids": [item.loop_id for item in document.loop_contracts],
        "surface_ids": [item.form_id for item in document.surfaces],
        "raw_assertions_admitted": False,
        "typed": True,
    }
    root = mk_extension(
        "node:program:document",
        family=PROGRAM_V2_FAMILY_ID,
        profile=PROGRAM_V2_PROFILE_ID,
        features=(
            "program",
            "parse",
            "elaborate",
            "hoare",
            "contract",
            "dynamic_logic",
            "verification_condition",
        ),
        payload_schema=PROGRAM_DOCUMENT_PAYLOAD_SCHEMA,
        payload=payload,
        children=tuple(children),
        range=full_range,
    )
    signature = _program_signature(signature_id=f"sig:program:{expression_id}")
    expression = TypedExpression(
        expression_id=expression_id,
        root=root,
        signature=signature,
        family=PROGRAM_V2_FAMILY_ID,
        profile=PROGRAM_V2_PROFILE_ID,
        range=full_range,
        elaborate_on_init=False,
        metadata={
            "notation_id": PROGRAM_V2_NOTATION_ID,
            "notation_version": PROGRAM_V2_NOTATION_VERSION,
            "binding_version": document.binding_version,
            "state_version": document.state_version,
            "raw_assertions_admitted": False,
            "view_role": VC_VIEW_ROLE,
        },
    )
    return expression, signature


def _surface_program(
    document: program_v1.ProgramLogicDocument,
    *,
    full_range: SourceRange,
) -> tuple[SurfaceASTRef, ...]:
    refs: list[SurfaceASTRef] = []
    child_ids: list[str] = []
    for index, contract in enumerate(document.contracts):
        node_id = f"ast:contract:{index + 1}"
        child_ids.append(node_id)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind="contract",
                range=full_range,
                metadata={
                    "contract_id": contract.contract_id,
                    "function_id": contract.function_id,
                    "typed": True,
                },
            )
        )
    for index, triple in enumerate(document.hoare_triples):
        node_id = f"ast:hoare:{index + 1}"
        child_ids.append(node_id)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind="hoare_triple",
                range=full_range,
                metadata={
                    "triple_id": triple.triple_id,
                    "command_id": triple.command_id,
                    "typed": True,
                },
            )
        )
    for index, surface in enumerate(document.surfaces):
        node_id = f"ast:surface:{index + 1}"
        child_ids.append(node_id)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind="surface_form",
                range=full_range,
                metadata={
                    "form_id": surface.form_id,
                    "kind": (
                        surface.kind.value
                        if hasattr(surface.kind, "value")
                        else str(surface.kind)
                    ),
                    "typed": True,
                },
            )
        )
    refs.append(
        SurfaceASTRef(
            node_id="ast:document",
            kind="program_logic_document",
            range=full_range,
            child_ids=tuple(child_ids),
            metadata={
                "program_id": document.program.program_id,
                "binding_version": document.binding_version,
                "state_version": document.state_version,
                "family_id": document.family_id,
                "view_roles": [VC_VIEW_ROLE],
                "raw_assertions_admitted": False,
            },
        )
    )
    return tuple(refs)


# ---------------------------------------------------------------------------
# Parse result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProgramFrontendV2Result:
    """Typed result of a ProgramFrontend@2 parse/elaborate attempt."""

    status: ParseStatus
    document: program_v1.ProgramLogicDocument | None = None
    source_document: SourceDocument | None = None
    parse_artifact: ParseArtifactV2 | None = None
    elaboration_artifact: ElaborationArtifactV2 | None = None
    typed_expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    printed: str = ""
    vc_result: program_v1.VerificationConditionBridgeResult | None = None
    schema_version: str = PROGRAM_V2_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = PROGRAM_FRONTEND_V2_INTERFACE

    @property
    def ok(self) -> bool:
        return (
            self.status is ParseStatus.OK
            and self.document is not None
            and self.parse_artifact is not None
            and self.elaboration_artifact is not None
            and self.typed_expression is not None
            and self.elaboration_artifact.status is ElaborationArtifactStatus.OK
        )

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    @property
    def has_typed_artifacts(self) -> bool:
        return (
            self.parse_artifact is not None
            and self.elaboration_artifact is not None
            and self.typed_expression is not None
            and self.ok
        )

    @property
    def raw_assertions_admitted(self) -> bool:
        return False

    @property
    def assertions_typed(self) -> bool:
        if self.document is None:
            return False
        # Every surface/hoare/contract is a typed IR record, never a raw string.
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertions_typed": self.assertions_typed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "document": None if self.document is None else self.document.to_dict(),
            "elaboration_artifact": (
                None
                if self.elaboration_artifact is None
                else self.elaboration_artifact.to_dict()
            ),
            "has_typed_artifacts": self.has_typed_artifacts,
            "interface": self.interface,
            "parse_artifact": (
                None if self.parse_artifact is None else self.parse_artifact.to_dict()
            ),
            "printed": self.printed,
            "raw_assertions_admitted": False,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "typed_expression": (
                None
                if self.typed_expression is None
                else self.typed_expression.to_dict()
            ),
            "vc_result": None if self.vc_result is None else self.vc_result.to_dict(),
        }


# ---------------------------------------------------------------------------
# Descriptor builders
# ---------------------------------------------------------------------------


def build_program_v2_descriptor(
    *,
    limits: FrontendLimits | None = None,
) -> LogicFrontendDescriptor:
    """Build the shared frontend descriptor for ProgramFrontend@2."""

    bounds = limits if limits is not None else DEFAULT_FRONTEND_LIMITS
    features = (
        FrontendFeature.PARSE.value,
        FrontendFeature.PRINT.value,
        FrontendFeature.ELABORATE.value,
        FrontendFeature.SOURCE_MAP.value,
        FrontendFeature.TYPECHECK.value,
    )
    fixtures = build_baseline_fixture_set(features=features, prefix="program-v2")
    extra = (
        FeatureScopedFixture(
            fixture_id="fixture:program-v2:hoare-contract",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description="Hoare triples and contracts elaborate as typed artifacts.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:program-v2:vc-view",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description=(
                "VC is a view role over family program; binding/state versions "
                "are explicit."
            ),
        ),
        FeatureScopedFixture(
            fixture_id="fixture:program-v2:raw-assertion-blocked",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Raw program assertions cannot bypass parse/elaboration.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:program-v2:unsupported-loop",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.TYPECHECK.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Unsupported loop constructs reject with exact diagnostics.",
        ),
    )
    return LogicFrontendDescriptor(
        descriptor_id=PROGRAM_V2_DESCRIPTOR_ID,
        key=ParserKey(
            notation_id=PROGRAM_V2_NOTATION_ID,
            notation_version=PROGRAM_V2_NOTATION_VERSION,
            semantic_profile_id=PROGRAM_V2_PROFILE_ID,
        ),
        family_id=PROGRAM_V2_FAMILY_ID,
        features=features,
        parse_modes=(ParseMode.STRICT,),
        limits=bounds,
        diagnostics=tuple(sorted(_ALL_PROGRAM_V2_CODES)),
        artifact_outputs=(
            make_parse_artifact_output(),
            make_elaboration_artifact_output(),
        ),
        fixtures=tuple(fixtures) + extra,
        recovery=RecoveryPolicy.NONE,
        printer=PrinterContract(
            guarantee=PrinterGuarantee.SEMANTIC,
            features=(FrontendFeature.PRINT.value,),
            deterministic=True,
        ),
        unsupported_behavior=UnsupportedBehavior.REJECT_WITH_DIAGNOSTIC,
        unsupported_nodes=tuple(
            sorted(
                {
                    "raw_program_assertion",
                    "raw_hoare_assertion",
                    "raw_contract_string",
                    "verification_condition_as_family",
                    *{f"loop_{item}" for item in UNSUPPORTED_LOOP_CONSTRUCTS},
                }
            )
        ),
        implementation="ipfs_datasets_py.logic.parsers.program_v2:ProgramFrontendV2",
        metadata={
            "task_id": PROGRAM_V2_TASK_ID,
            "goal_id": PROGRAM_V2_GOAL_ID,
            "interfaces": {
                "program": PROGRAM_FRONTEND_V2_INTERFACE,
                "vc_bridge": VC_BRIDGE_V2_INTERFACE,
                "parse_artifact": PARSE_ARTIFACT_V2_INTERFACE,
                "elaboration_artifact": ELABORATION_ARTIFACT_V2_INTERFACE,
            },
            "binding_version": PROGRAM_V2_BINDING_VERSION,
            "state_version": PROGRAM_V2_STATE_VERSION,
            "view_role": VC_VIEW_ROLE,
        },
    )


def register_program_v2_frontend(
    registry: SharedFrontendConformance | None = None,
    *,
    limits: FrontendLimits | None = None,
) -> tuple[SharedFrontendConformance, LogicFrontendDescriptor]:
    descriptor = build_program_v2_descriptor(limits=limits)
    validate_frontend_descriptor(descriptor)
    target = registry if registry is not None else SharedFrontendConformance()
    admitted = target.register(descriptor)
    return target, admitted


# ---------------------------------------------------------------------------
# VC bridge v2
# ---------------------------------------------------------------------------


class VerificationConditionBridgeV2:
    """VC lowering gated on typed ProgramFrontend@2 artifacts.

    Interface: ``VerificationConditionBridge@2``.
    """

    interface: ClassVar[str] = VC_BRIDGE_V2_INTERFACE
    family_id: ClassVar[str] = PROGRAM_V2_FAMILY_ID
    view_role: ClassVar[str] = VC_VIEW_ROLE
    binding_version: ClassVar[str] = PROGRAM_V2_BINDING_VERSION
    state_version: ClassVar[str] = PROGRAM_V2_STATE_VERSION

    def __init__(
        self,
        *,
        loop_variant_policy: LoopVariantPolicy | str = LoopVariantPolicy.OPTIONAL,
    ) -> None:
        self._v1 = program_v1.VerificationConditionBridge(
            loop_variant_policy=loop_variant_policy
        )

    def lower(
        self,
        result: ProgramFrontendV2Result | program_v1.ProgramLogicDocument,
        *,
        function_id: str | None = None,
    ) -> program_v1.VerificationConditionBridgeResult:
        """Lower only from typed results or already-typed documents.

        Raw assertion strings are never admitted.
        """

        if isinstance(result, ProgramFrontendV2Result):
            if not result.has_typed_artifacts or result.document is None:
                raise ProgramArtifactBypassError(
                    "VC lowering requires typed parse/elaboration artifacts",
                    code=CODE_VC_WITHOUT_ARTIFACTS,
                    remediation="Parse through ProgramFrontend@2 first.",
                )
            bridge_result = self._v1.lower(result.document, function_id=function_id)
        elif isinstance(result, program_v1.ProgramLogicDocument):
            bridge_result = self._v1.lower(result, function_id=function_id)
        else:
            raise ProgramArtifactBypassError(
                "raw program assertion cannot bypass parse/elaboration artifacts",
                code=CODE_RAW_ASSERTION,
            )
        # Namespace invariants: family is program; VC is view role only.
        if bridge_result.family_id != PROGRAM_V2_FAMILY_ID:
            raise ProgramArtifactBypassError(
                "VC bridge family_id must remain 'program'",
                code=CODE_FAMILY_NAMESPACE,
            )
        if bridge_result.view_role != VC_VIEW_ROLE:
            raise ProgramArtifactBypassError(
                "VC bridge view_role must be 'verification_condition'",
                code=CODE_FAMILY_NAMESPACE,
            )
        return bridge_result


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------


class ProgramFrontendV2:
    """Shared-artifact program-logic frontend.

    Interface: ``ProgramFrontend@2``.
    """

    interface: ClassVar[str] = PROGRAM_FRONTEND_V2_INTERFACE
    notation_id: ClassVar[str] = PROGRAM_V2_NOTATION_ID
    notation_version: ClassVar[str] = PROGRAM_V2_NOTATION_VERSION
    profile_id: ClassVar[str] = PROGRAM_V2_PROFILE_ID
    family_id: ClassVar[str] = PROGRAM_V2_FAMILY_ID
    binding_version: ClassVar[str] = PROGRAM_V2_BINDING_VERSION
    state_version: ClassVar[str] = PROGRAM_V2_STATE_VERSION
    module_version: ClassVar[str] = PROGRAM_V2_MODULE_VERSION
    task_id: ClassVar[str] = PROGRAM_V2_TASK_ID
    goal_id: ClassVar[str] = PROGRAM_V2_GOAL_ID
    view_role: ClassVar[str] = VC_VIEW_ROLE

    def __init__(
        self,
        *,
        limits: FrontendLimits | ParseLimits | None = None,
        loop_variant_policy: LoopVariantPolicy | str = LoopVariantPolicy.OPTIONAL,
    ) -> None:
        if isinstance(limits, FrontendLimits):
            self.limits = limits
        elif isinstance(limits, ParseLimits):
            self.limits = FrontendLimits(parse_limits=limits)
        else:
            self.limits = DEFAULT_FRONTEND_LIMITS
        self._v1 = program_v1.ProgramLogicSyntax(
            loop_variant_policy=loop_variant_policy
        )
        self.vc_bridge = VerificationConditionBridgeV2(
            loop_variant_policy=loop_variant_policy
        )
        self._descriptor = build_program_v2_descriptor(limits=self.limits)

    @property
    def descriptor(self) -> LogicFrontendDescriptor:
        return self._descriptor

    def parse_limits(self) -> ParseLimits:
        return self.limits.parse_limits

    def parse(
        self,
        value: Mapping[str, Any] | str | ProgramIR,
        *,
        document_id: str = "doc:program:v2:1",
        request_id: str = "req:program:v2:1",
        limits: ParseLimits | None = None,
        elaborate: bool = True,
        lower_vc: bool = False,
        function_id: str | None = None,
        contracts: Sequence[Any] = (),
        loop_contracts: Sequence[Any] = (),
        hoare_triples: Sequence[Any] = (),
        dynamic_formulas: Sequence[Any] = (),
    ) -> ProgramFrontendV2Result:
        bounds = limits if limits is not None else self.parse_limits()

        if isinstance(value, ProgramIR):
            try:
                document = self._v1.parse_program_ir(
                    value,
                    contracts=contracts,
                    loop_contracts=loop_contracts,
                    hoare_triples=hoare_triples,
                    dynamic_formulas=dynamic_formulas,
                )
                text = document.to_json()
            except program_v1.ProgramLogicError as error:
                diag = _diag(
                    code=_error_code_from_v1(error),
                    message=str(error),
                    range=SourceRange(0, 0),
                    diagnostic_id="diag:program-v2:ir",
                )
                return ProgramFrontendV2Result(
                    status=ParseStatus.FAILED, diagnostics=(diag,)
                )
        else:
            try:
                text = _json_text(value)
            except ProgramFrontendV2Error as error:
                diag = _diag(
                    code=error.code,
                    message=error.message,
                    range=SourceRange(0, 0),
                    diagnostic_id="diag:program-v2:input",
                )
                return ProgramFrontendV2Result(
                    status=ParseStatus.FAILED, diagnostics=(diag,)
                )
            document = None  # parsed below from text

        try:
            source = _source_from_text(text, document_id=document_id, limits=bounds)
        except ProgramFrontendV2Error as error:
            diag = _diag(
                code=error.code,
                message=error.message,
                range=SourceRange(0, 0),
                diagnostic_id="diag:program-v2:source",
            )
            return ProgramFrontendV2Result(
                status=ParseStatus.REJECTED, diagnostics=(diag,)
            )
        except SyntaxContractError as error:
            diag = _diag(
                code=CODE_INPUT_LIMIT,
                message=str(error),
                range=SourceRange(0, 0),
                diagnostic_id="diag:program-v2:source",
            )
            return ProgramFrontendV2Result(
                status=ParseStatus.REJECTED, diagnostics=(diag,)
            )

        if document is None:
            try:
                document = self._v1.parse_json(text)
            except program_v1.ProgramLogicError as error:
                diagnostics = _unique_diagnostics(
                    (
                        _diag(
                            code=_error_code_from_v1(error),
                            message=str(error),
                            range=source.full_range(),
                            diagnostic_id="diag:program-v2:parse",
                            remediation=getattr(error, "remediation", "") or "",
                        ),
                    )
                )
                cst = _covering_cst(source, cst_id=f"cst:program:{request_id}")
                artifact = ParseArtifactV2.from_document(
                    source,
                    artifact_id=f"art:program:parse:{request_id}",
                    request_id=request_id,
                    status=ParseStatus.FAILED,
                    cst=cst,
                    diagnostics=diagnostics,
                    metadata={
                        "interface": self.interface,
                        "stage": "parse_failed",
                        "raw_assertions_admitted": False,
                        "execution_admitted": False,
                    },
                )
                elab = ElaborationArtifactV2(
                    artifact_id=f"art:program:elab:{request_id}",
                    parse_artifact_id=artifact.artifact_id,
                    document_id=source.document_id,
                    source_digest=source.content_digest,
                    status=ElaborationArtifactStatus.FAILED,
                    parse_content_digest=artifact.content_digest,
                    parse_lineage_digest=artifact.lineage_digest,
                    diagnostics=diagnostics,
                    metadata={
                        "interface": self.interface,
                        "raw_assertions_admitted": False,
                        "execution_admitted": False,
                    },
                )
                return ProgramFrontendV2Result(
                    status=ParseStatus.FAILED,
                    source_document=source,
                    parse_artifact=artifact,
                    elaboration_artifact=elab,
                    diagnostics=diagnostics,
                )

        printed = document.to_json()
        surface = _surface_program(document, full_range=source.full_range())
        cst = _covering_cst(source, cst_id=f"cst:program:{request_id}")
        parse_artifact = ParseArtifactV2.from_document(
            source,
            artifact_id=f"art:program:parse:{request_id}",
            request_id=request_id,
            status=ParseStatus.OK,
            cst=cst,
            surface_ast=surface,
            diagnostics=(),
            metadata={
                "interface": self.interface,
                "notation_id": self.notation_id,
                "notation_version": self.notation_version,
                "profile_id": self.profile_id,
                "family_id": self.family_id,
                "binding_version": document.binding_version,
                "state_version": document.state_version,
                "program_id": document.program.program_id,
                "document_id": document.document_id,
                "view_role": VC_VIEW_ROLE,
                "contract_count": len(document.contracts),
                "hoare_count": len(document.hoare_triples),
                "printed": printed,
                "raw_assertions_admitted": False,
                "execution_admitted": False,
            },
        )
        parse_artifact.validate_against(source)

        typed_expression: TypedExpression | None = None
        elaboration_artifact: ElaborationArtifactV2 | None = None
        if elaborate:
            try:
                typed_expression, signature = _project_program_document(
                    document,
                    expression_id=f"expr:program:{request_id}",
                    full_range=source.full_range(),
                )
                parse_artifact = ParseArtifactV2.from_document(
                    source,
                    artifact_id=parse_artifact.artifact_id,
                    request_id=request_id,
                    status=ParseStatus.OK,
                    cst=cst,
                    surface_ast=surface,
                    typed_roots=(typed_expression.root,),
                    diagnostics=(),
                    metadata=dict(parse_artifact.metadata),
                )
                parse_artifact.validate_against(source)
                elaboration_artifact = ElaborationArtifactV2(
                    artifact_id=f"art:program:elab:{request_id}",
                    parse_artifact_id=parse_artifact.artifact_id,
                    document_id=source.document_id,
                    source_digest=source.content_digest,
                    status=ElaborationArtifactStatus.OK,
                    typed_expression=typed_expression,
                    root=typed_expression.root,
                    normalized_root=typed_expression.root,
                    signature=signature,
                    parse_content_digest=parse_artifact.content_digest,
                    parse_lineage_digest=parse_artifact.lineage_digest,
                    semantic_digest=typed_expression.content_digest,
                    diagnostics=(),
                    metadata={
                        "interface": self.interface,
                        "binding_version": document.binding_version,
                        "state_version": document.state_version,
                        "view_role": VC_VIEW_ROLE,
                        "raw_assertions_admitted": False,
                        "execution_admitted": False,
                        "typed": True,
                    },
                )
                elaboration_artifact.validate_lineage(
                    parse_artifact=parse_artifact, document=source
                )
            except (AstError, SyntaxContractError, ValueError, TypeError) as error:
                diag = _diag(
                    code=CODE_ELABORATION_FAILED,
                    message=f"program elaboration failed: {error}",
                    range=source.full_range(),
                    diagnostic_id="diag:program-v2:elab",
                )
                diagnostics = (diag,)
                elaboration_artifact = ElaborationArtifactV2(
                    artifact_id=f"art:program:elab:{request_id}",
                    parse_artifact_id=parse_artifact.artifact_id,
                    document_id=source.document_id,
                    source_digest=source.content_digest,
                    status=ElaborationArtifactStatus.FAILED,
                    parse_content_digest=parse_artifact.content_digest,
                    parse_lineage_digest=parse_artifact.lineage_digest,
                    diagnostics=diagnostics,
                    metadata={
                        "interface": self.interface,
                        "execution_admitted": False,
                    },
                )
                return ProgramFrontendV2Result(
                    status=ParseStatus.FAILED,
                    document=document,
                    source_document=source,
                    parse_artifact=parse_artifact,
                    elaboration_artifact=elaboration_artifact,
                    diagnostics=diagnostics,
                    printed=printed,
                )

        vc_result: program_v1.VerificationConditionBridgeResult | None = None
        if lower_vc:
            if not elaborate or typed_expression is None or elaboration_artifact is None:
                raise ProgramArtifactBypassError(
                    "VC lowering requires typed parse/elaboration artifacts",
                    code=CODE_VC_WITHOUT_ARTIFACTS,
                )
            provisional = ProgramFrontendV2Result(
                status=ParseStatus.OK,
                document=document,
                source_document=source,
                parse_artifact=parse_artifact,
                elaboration_artifact=elaboration_artifact,
                typed_expression=typed_expression,
                printed=printed,
            )
            vc_result = self.vc_bridge.lower(provisional, function_id=function_id)

        return ProgramFrontendV2Result(
            status=ParseStatus.OK,
            document=document,
            source_document=source,
            parse_artifact=parse_artifact,
            elaboration_artifact=elaboration_artifact,
            typed_expression=typed_expression,
            diagnostics=(),
            printed=printed,
            vc_result=vc_result,
        )

    def parse_text(self, text: str, **kwargs: Any) -> ProgramFrontendV2Result:
        return self.parse(text, **kwargs)

    def elaborate(
        self, value: Mapping[str, Any] | str | ProgramIR, **kwargs: Any
    ) -> ProgramFrontendV2Result:
        kwargs = dict(kwargs)
        kwargs["elaborate"] = True
        return self.parse(value, **kwargs)

    def print(self, document: program_v1.ProgramLogicDocument) -> str:
        return document.to_json()

    def lower_to_vc(
        self,
        result: ProgramFrontendV2Result | program_v1.ProgramLogicDocument,
        *,
        function_id: str | None = None,
    ) -> program_v1.VerificationConditionBridgeResult:
        return self.vc_bridge.lower(result, function_id=function_id)

    def admit_raw_assertion(self, *_args: Any, **_kwargs: Any) -> None:
        """Hard-fail: raw program assertions never enter without typed artifacts."""

        raise ProgramArtifactBypassError(
            "raw program assertion cannot bypass parse/elaboration artifacts",
            code=CODE_RAW_ASSERTION,
            remediation="Parse through ProgramFrontend@2 before VC lowering",
        )

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        raise ProgramArtifactBypassError(
            "ProgramFrontend@2 does not execute solvers; only typed "
            "ParseArtifact@2 / ElaborationArtifact@2 are produced",
            code=CODE_BYPASS_BLOCKED,
        )


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_program_v2(
    value: Mapping[str, Any] | str | ProgramIR, **kwargs: Any
) -> ProgramFrontendV2Result:
    """Parse program-logic source into shared typed artifacts."""

    return ProgramFrontendV2().parse(value, **kwargs)


def elaborate_program_v2(
    value: Mapping[str, Any] | str | ProgramIR, **kwargs: Any
) -> ProgramFrontendV2Result:
    return ProgramFrontendV2().elaborate(value, **kwargs)


def print_program_v2(document: program_v1.ProgramLogicDocument) -> str:
    return ProgramFrontendV2().print(document)


def lower_to_vc_v2(
    result: ProgramFrontendV2Result | program_v1.ProgramLogicDocument,
    *,
    function_id: str | None = None,
    loop_variant_policy: LoopVariantPolicy | str = LoopVariantPolicy.OPTIONAL,
) -> program_v1.VerificationConditionBridgeResult:
    return VerificationConditionBridgeV2(
        loop_variant_policy=loop_variant_policy
    ).lower(result, function_id=function_id)


__all__ = [
    "CODE_BYPASS_BLOCKED",
    "CODE_ELABORATION_FAILED",
    "CODE_EMPTY_INPUT",
    "CODE_FAMILY_NAMESPACE",
    "CODE_INPUT_LIMIT",
    "CODE_INVALID_DOCUMENT",
    "CODE_INVALID_HOARE",
    "CODE_RAW_ASSERTION",
    "CODE_UNSUPPORTED_LOOP",
    "CODE_VC_WITHOUT_ARTIFACTS",
    "CODE_VERSION_MISMATCH",
    "DEFAULT_FRONTEND_LIMITS",
    "ELABORATION_ARTIFACT_V2_INTERFACE",
    "PARSE_ARTIFACT_V2_INTERFACE",
    "PROGRAM_FRONTEND_V2_INTERFACE",
    "PROGRAM_V2_BINDING_VERSION",
    "PROGRAM_V2_DESCRIPTOR_ID",
    "PROGRAM_V2_FAMILY_ID",
    "PROGRAM_V2_GOAL_ID",
    "PROGRAM_V2_MODULE_VERSION",
    "PROGRAM_V2_NOTATION_ID",
    "PROGRAM_V2_PROFILE_ID",
    "PROGRAM_V2_STATE_VERSION",
    "PROGRAM_V2_TASK_ID",
    "ProgramArtifactBypassError",
    "ProgramFrontendV2",
    "ProgramFrontendV2Error",
    "ProgramFrontendV2Result",
    "ProgramLogicDocument",
    "SurfaceForm",
    "SurfaceKind",
    "UNSUPPORTED_LOOP_CONSTRUCTS",
    "VC_BRIDGE_V2_INTERFACE",
    "VC_VIEW_ROLE",
    "VerificationConditionBridgeResult",
    "VerificationConditionBridgeV2",
    "build_program_v2_descriptor",
    "elaborate_program_v2",
    "lower_to_vc_v2",
    "parse_program_v2",
    "print_program_v2",
    "register_program_v2_frontend",
]
