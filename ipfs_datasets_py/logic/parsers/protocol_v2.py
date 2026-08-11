"""Protocol, Tamarin, and joint protocol-program frontends (LFP2-014).

Interfaces:

* ``ProtocolFrontend@2`` — applied-pi / symbolic protocol surface with shared
  ``ParseArtifact@2`` / ``ElaborationArtifact@2`` envelopes over terms, equations,
  roles, events, processes, and claims
* ``TamarinFrontend@2`` — multiset-rewriting specialization (facts, rules,
  restrictions, lemmas) with the same artifact pipeline
* ``ProtocolProgramFrontend@2`` — joint convergence facade that never admits
  raw protocol rules, target source strings, or untyped backend lowers without
  typed parse/elaboration artifacts

The v1 modules (``protocol.py``, ``tamarin.py``) remain the controlled surface
syntax.  This module converges them onto the Wave-2 shared artifact pipeline
and ``LogicFrontendDescriptor@1`` contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.parsers import protocol as protocol_v1
from ipfs_datasets_py.logic.parsers import tamarin as tamarin_v1
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
from ipfs_datasets_py.logic.software_verification.protocol import ProtocolIR

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PROTOCOL_FRONTEND_V2_INTERFACE: Final = "ProtocolFrontend@2"
TAMARIN_FRONTEND_V2_INTERFACE: Final = "TamarinFrontend@2"
PROTOCOL_PROGRAM_FRONTEND_INTERFACE: Final = "ProtocolProgramFrontend@2"

PROTOCOL_V2_NOTATION_ID: Final = protocol_v1.SYMBOLIC_PROTOCOL_NOTATION_ID
PROTOCOL_V2_NOTATION_VERSION: Final = "2.0.0"
PROTOCOL_V2_PROFILE_ID: Final = protocol_v1.SYMBOLIC_PROTOCOL_PROFILE_ID
PROTOCOL_V2_FAMILY_ID: Final = protocol_v1.SYMBOLIC_PROTOCOL_FAMILY_ID

TAMARIN_V2_NOTATION_ID: Final = tamarin_v1.TAMARIN_NOTATION_ID
TAMARIN_V2_NOTATION_VERSION: Final = "2.0.0"
TAMARIN_V2_PROFILE_ID: Final = tamarin_v1.TAMARIN_PROFILE_ID
TAMARIN_V2_FAMILY_ID: Final = tamarin_v1.TAMARIN_FAMILY_ID

PROTOCOL_V2_MODULE_VERSION: Final = "2.0.0"
PROTOCOL_V2_TASK_ID: Final = "LFP2-014"
PROTOCOL_V2_GOAL_ID: Final = FRONTEND_CONTRACT_GOAL_ID
PROTOCOL_V2_PARSE_RESULT_SCHEMA: Final = "protocol-v2-parse-result/v1"
TAMARIN_V2_PARSE_RESULT_SCHEMA: Final = "tamarin-v2-parse-result/v1"

PROTOCOL_V2_DESCRIPTOR_ID: Final = "frontend:symbolic_protocol:v2:applied_pi"
TAMARIN_V2_DESCRIPTOR_ID: Final = "frontend:tamarin_spthy:v2:multiset_rewriting"
PROTOCOL_PROGRAM_DESCRIPTOR_ID: Final = "frontend:protocol_program:v2:joint"

PROTOCOL_DOCUMENT_PAYLOAD_SCHEMA: Final = "protocol.document/v1"
TAMARIN_DOCUMENT_PAYLOAD_SCHEMA: Final = "tamarin.document/v1"
PROTOCOL_PROCESS_PAYLOAD_SCHEMA: Final = "protocol.process/v1"
TAMARIN_RULE_PAYLOAD_SCHEMA: Final = "tamarin.rule/v1"

# Diagnostic codes (namespaced; include v1 codes plus v2 gate codes).
CODE_EMPTY_INPUT: Final = protocol_v1.CODE_EMPTY_INPUT
CODE_MALFORMED_JSON: Final = protocol_v1.CODE_MALFORMED_JSON
CODE_INVALID_DOCUMENT: Final = protocol_v1.CODE_INVALID_DOCUMENT
CODE_MISSING_PROTOCOL: Final = protocol_v1.CODE_MISSING_PROTOCOL
CODE_UNSUPPORTED_PROCESS: Final = protocol_v1.CODE_UNSUPPORTED_PROCESS
CODE_UNSUPPORTED_THEORY: Final = protocol_v1.CODE_UNSUPPORTED_THEORY
CODE_UNSUPPORTED_CLAIM: Final = protocol_v1.CODE_UNSUPPORTED_CLAIM
CODE_IDENTITY_MISMATCH: Final = protocol_v1.CODE_IDENTITY_MISMATCH
CODE_ELABORATION_FAILED: Final = "protocol.elaboration_failed"
CODE_RAW_RULE: Final = "protocol.raw_rule_rejected"
CODE_RAW_TARGET_SOURCE: Final = "protocol.raw_target_source_rejected"
CODE_BYPASS_BLOCKED: Final = "protocol.artifact_bypass_blocked"
CODE_INPUT_LIMIT: Final = "protocol.input_limit"
CODE_TAMARIN_UNSUPPORTED_RULE: Final = tamarin_v1.CODE_UNSUPPORTED_RULE
CODE_TAMARIN_UNSUPPORTED_THEORY: Final = tamarin_v1.CODE_UNSUPPORTED_THEORY
CODE_TAMARIN_INVALID_RULE: Final = tamarin_v1.CODE_INVALID_RULE
CODE_TAMARIN_EMPTY: Final = tamarin_v1.CODE_EMPTY_INPUT
CODE_TAMARIN_MALFORMED: Final = tamarin_v1.CODE_MALFORMED_JSON

_ALL_PROTOCOL_V2_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_EMPTY_INPUT,
        CODE_MALFORMED_JSON,
        CODE_INVALID_DOCUMENT,
        CODE_MISSING_PROTOCOL,
        CODE_UNSUPPORTED_PROCESS,
        CODE_UNSUPPORTED_THEORY,
        CODE_UNSUPPORTED_CLAIM,
        CODE_IDENTITY_MISMATCH,
        CODE_ELABORATION_FAILED,
        CODE_RAW_RULE,
        CODE_RAW_TARGET_SOURCE,
        CODE_BYPASS_BLOCKED,
        CODE_INPUT_LIMIT,
        CODE_TAMARIN_UNSUPPORTED_RULE,
        CODE_TAMARIN_UNSUPPORTED_THEORY,
        CODE_TAMARIN_INVALID_RULE,
        CODE_TAMARIN_EMPTY,
        CODE_TAMARIN_MALFORMED,
        tamarin_v1.CODE_INVALID_DOCUMENT,
        tamarin_v1.CODE_MISSING_PROTOCOL,
        tamarin_v1.CODE_PROVENANCE,
        tamarin_v1.CODE_RESULT_AUTHORITY,
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
ProcessKind = protocol_v1.ProcessKind
ProcessNode = protocol_v1.ProcessNode
SymbolicProtocolDocument = protocol_v1.SymbolicProtocolDocument
ProVerifControlledSourceArtifact = protocol_v1.ProVerifControlledSourceArtifact
ProtocolRewritingDocument = tamarin_v1.ProtocolRewritingDocument
MultisetRule = tamarin_v1.MultisetRule
MultisetFact = tamarin_v1.MultisetFact
TamarinControlledSourceArtifact = tamarin_v1.TamarinControlledSourceArtifact
UNSUPPORTED_PROCESS_CONSTRUCTS = protocol_v1.UNSUPPORTED_PROCESS_CONSTRUCTS
UNSUPPORTED_RULE_FEATURES = tamarin_v1.UNSUPPORTED_RULE_FEATURES
UNSUPPORTED_THEORY_FEATURES = tamarin_v1.UNSUPPORTED_THEORY_FEATURES


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProtocolFrontendV2Error(SyntaxContractError):
    """Base class for ProtocolFrontend@2 / TamarinFrontend@2 failures."""

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


class TamarinFrontendV2Error(ProtocolFrontendV2Error):
    """Raised for TamarinFrontend@2 failures."""


class ProtocolArtifactBypassError(ProtocolFrontendV2Error):
    """Raised when raw rules, target source, or lowers bypass artifacts."""


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
    prefix: str = "diag:protocol-v2",
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
    kind: str = "json_document",
) -> LogicCST:
    root = LogicCSTNode(
        node_id="node:root",
        kind=kind,
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
            raise ProtocolFrontendV2Error(
                "protocol/tamarin source must be non-empty text",
                code=CODE_EMPTY_INPUT,
            )
        return value
    if not isinstance(value, Mapping):
        raise ProtocolFrontendV2Error(
            "protocol/tamarin source must be a mapping or JSON text",
            code=CODE_INVALID_DOCUMENT,
        )
    return canonical_json_bytes(dict(value)).decode("utf-8")


def _source_from_text(
    text: str,
    *,
    document_id: str,
    language_hint: str,
    interface: str,
    notation_id: str,
    limits: ParseLimits,
) -> SourceDocument:
    encoded = text.encode("utf-8")
    if len(encoded) > limits.max_input_bytes:
        raise ProtocolFrontendV2Error(
            f"input exceeds max_input_bytes={limits.max_input_bytes}",
            code=CODE_INPUT_LIMIT,
        )
    return SourceDocument.from_text(
        document_id,
        text,
        encoding="utf-8",
        language_hint=language_hint,
        metadata={
            "interface": interface,
            "notation_id": notation_id,
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


def _protocol_signature(
    *,
    signature_id: str,
    family: str,
    profile: str,
) -> LogicSignature:
    return LogicSignature(
        signature_id=signature_id,
        family=family,
        profile=profile,
        sorts=(BOOL_SORT,),
        symbols=(),
        features=("protocol", "parse", "elaborate"),
    )


def _project_protocol_document(
    document: protocol_v1.SymbolicProtocolDocument,
    *,
    expression_id: str,
    full_range: SourceRange | None = None,
) -> tuple[TypedExpression, LogicSignature]:
    protocol = document.protocol
    process_children: list[LogicNode] = []
    for index, (role_id, process) in enumerate(document.process_nodes):
        process_children.append(
            mk_extension(
                f"node:protocol:process:{index + 1}",
                family=PROTOCOL_V2_FAMILY_ID,
                profile=PROTOCOL_V2_PROFILE_ID,
                features=("protocol", "process", "role"),
                payload_schema=PROTOCOL_PROCESS_PAYLOAD_SCHEMA,
                payload={
                    "kind": "process",
                    "schema_version": "protocol.process/v1",
                    "role_id": role_id,
                    "process_kind": (
                        process.kind.value
                        if hasattr(process.kind, "value")
                        else str(process.kind)
                    ),
                    "typed": True,
                    "raw_rejected": True,
                },
                range=full_range,
            )
        )
    payload: dict[str, Any] = {
        "kind": "symbolic_protocol_document",
        "schema_version": "protocol.document/v1",
        "protocol_document_id": protocol.document_id,
        "symbolic_document_id": document.document_id,
        "equational_theories": [item.value for item in protocol.equational_theories],
        "adversary_kind": protocol.adversary.kind.value,
        "role_ids": [role.role_id for role in protocol.roles],
        "event_ids": [event.event_id for event in protocol.events],
        "claim_ids": [claim.claim_id for claim in protocol.claims],
        "process_role_ids": [role_id for role_id, _ in document.process_nodes],
        "process_count": len(document.process_nodes),
        "raw_rules_admitted": False,
        "raw_target_source_admitted": False,
        "typed": True,
    }
    root = mk_extension(
        "node:protocol:document",
        family=PROTOCOL_V2_FAMILY_ID,
        profile=PROTOCOL_V2_PROFILE_ID,
        features=(
            "protocol",
            "parse",
            "elaborate",
            "roles",
            "events",
            "equations",
            "process",
        ),
        payload_schema=PROTOCOL_DOCUMENT_PAYLOAD_SCHEMA,
        payload=payload,
        children=tuple(process_children),
        range=full_range,
    )
    signature = _protocol_signature(
        signature_id=f"sig:protocol:{expression_id}",
        family=PROTOCOL_V2_FAMILY_ID,
        profile=PROTOCOL_V2_PROFILE_ID,
    )
    expression = TypedExpression(
        expression_id=expression_id,
        root=root,
        signature=signature,
        family=PROTOCOL_V2_FAMILY_ID,
        profile=PROTOCOL_V2_PROFILE_ID,
        range=full_range,
        elaborate_on_init=False,
        metadata={
            "notation_id": PROTOCOL_V2_NOTATION_ID,
            "notation_version": PROTOCOL_V2_NOTATION_VERSION,
            "raw_rules_admitted": False,
            "raw_target_source_admitted": False,
        },
    )
    return expression, signature


def _project_tamarin_document(
    document: tamarin_v1.ProtocolRewritingDocument,
    *,
    expression_id: str,
    full_range: SourceRange | None = None,
) -> tuple[TypedExpression, LogicSignature]:
    rule_children: list[LogicNode] = []
    for index, rule in enumerate(document.rules):
        rule_children.append(
            mk_extension(
                f"node:tamarin:rule:{index + 1}",
                family=TAMARIN_V2_FAMILY_ID,
                profile=TAMARIN_V2_PROFILE_ID,
                features=("tamarin", "rule", "multiset"),
                payload_schema=TAMARIN_RULE_PAYLOAD_SCHEMA,
                payload={
                    "kind": "multiset_rule",
                    "schema_version": "tamarin.rule/v1",
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "premise_count": len(rule.premises),
                    "conclusion_count": len(rule.conclusions),
                    "action_count": len(rule.actions),
                    "typed": True,
                    "raw_rejected": True,
                },
                range=full_range,
            )
        )
    payload: dict[str, Any] = {
        "kind": "protocol_rewriting_document",
        "schema_version": "tamarin.document/v1",
        "protocol_document_id": document.protocol.document_id,
        "rewriting_document_id": document.document_id,
        "equational_theories": [
            item.value for item in document.protocol.equational_theories
        ],
        "adversary_kind": document.protocol.adversary.kind.value,
        "fact_ids": [item.fact_id for item in document.facts],
        "rule_ids": [item.rule_id for item in document.rules],
        "restriction_ids": [item.restriction_id for item in document.restrictions],
        "lemma_ids": [item.lemma_id for item in document.lemmas],
        "theory_features": list(document.theory_features),
        "raw_rules_admitted": False,
        "raw_target_source_admitted": False,
        "typed": True,
    }
    root = mk_extension(
        "node:tamarin:document",
        family=TAMARIN_V2_FAMILY_ID,
        profile=TAMARIN_V2_PROFILE_ID,
        features=(
            "tamarin",
            "parse",
            "elaborate",
            "rules",
            "facts",
            "restrictions",
            "lemmas",
        ),
        payload_schema=TAMARIN_DOCUMENT_PAYLOAD_SCHEMA,
        payload=payload,
        children=tuple(rule_children),
        range=full_range,
    )
    signature = _protocol_signature(
        signature_id=f"sig:tamarin:{expression_id}",
        family=TAMARIN_V2_FAMILY_ID,
        profile=TAMARIN_V2_PROFILE_ID,
    )
    expression = TypedExpression(
        expression_id=expression_id,
        root=root,
        signature=signature,
        family=TAMARIN_V2_FAMILY_ID,
        profile=TAMARIN_V2_PROFILE_ID,
        range=full_range,
        elaborate_on_init=False,
        metadata={
            "notation_id": TAMARIN_V2_NOTATION_ID,
            "notation_version": TAMARIN_V2_NOTATION_VERSION,
            "raw_rules_admitted": False,
            "raw_target_source_admitted": False,
        },
    )
    return expression, signature


def _surface_protocol(
    document: protocol_v1.SymbolicProtocolDocument,
    *,
    full_range: SourceRange,
) -> tuple[SurfaceASTRef, ...]:
    refs: list[SurfaceASTRef] = []
    child_ids: list[str] = []
    for index, (role_id, process) in enumerate(document.process_nodes):
        node_id = f"ast:process:{index + 1}"
        child_ids.append(node_id)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind="process",
                range=full_range,
                metadata={
                    "role_id": role_id,
                    "process_kind": (
                        process.kind.value
                        if hasattr(process.kind, "value")
                        else str(process.kind)
                    ),
                    "typed": True,
                },
            )
        )
    for index, claim in enumerate(document.protocol.claims):
        node_id = f"ast:claim:{index + 1}"
        child_ids.append(node_id)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind="claim",
                range=full_range,
                metadata={
                    "claim_id": claim.claim_id,
                    "kind": claim.kind.value,
                    "typed": True,
                },
            )
        )
    refs.append(
        SurfaceASTRef(
            node_id="ast:document",
            kind="symbolic_protocol_document",
            range=full_range,
            child_ids=tuple(child_ids),
            metadata={
                "protocol_document_id": document.protocol.document_id,
                "process_count": len(document.process_nodes),
                "claim_count": len(document.protocol.claims),
                "raw_rules_admitted": False,
            },
        )
    )
    return tuple(refs)


def _surface_tamarin(
    document: tamarin_v1.ProtocolRewritingDocument,
    *,
    full_range: SourceRange,
) -> tuple[SurfaceASTRef, ...]:
    refs: list[SurfaceASTRef] = []
    child_ids: list[str] = []
    for index, rule in enumerate(document.rules):
        node_id = f"ast:rule:{index + 1}"
        child_ids.append(node_id)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind="multiset_rule",
                range=full_range,
                metadata={
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "typed": True,
                },
            )
        )
    for index, lemma in enumerate(document.lemmas):
        node_id = f"ast:lemma:{index + 1}"
        child_ids.append(node_id)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind="trace_lemma",
                range=full_range,
                metadata={
                    "lemma_id": lemma.lemma_id,
                    "name": lemma.name,
                    "typed": True,
                },
            )
        )
    refs.append(
        SurfaceASTRef(
            node_id="ast:document",
            kind="protocol_rewriting_document",
            range=full_range,
            child_ids=tuple(child_ids),
            metadata={
                "protocol_document_id": document.protocol.document_id,
                "rule_count": len(document.rules),
                "lemma_count": len(document.lemmas),
                "raw_rules_admitted": False,
            },
        )
    )
    return tuple(refs)


# ---------------------------------------------------------------------------
# Parse results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtocolFrontendV2Result:
    """Typed result of a ProtocolFrontend@2 parse/elaborate attempt."""

    status: ParseStatus
    document: protocol_v1.SymbolicProtocolDocument | None = None
    source_document: SourceDocument | None = None
    parse_artifact: ParseArtifactV2 | None = None
    elaboration_artifact: ElaborationArtifactV2 | None = None
    typed_expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    printed: str = ""
    controlled_source: protocol_v1.ProVerifControlledSourceArtifact | None = None
    schema_version: str = PROTOCOL_V2_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = PROTOCOL_FRONTEND_V2_INTERFACE

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
    def raw_rules_admitted(self) -> bool:
        return False

    @property
    def raw_target_source_admitted(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "controlled_source": (
                None
                if self.controlled_source is None
                else self.controlled_source.to_dict()
            ),
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
            "raw_rules_admitted": False,
            "raw_target_source_admitted": False,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "typed_expression": (
                None
                if self.typed_expression is None
                else self.typed_expression.to_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class TamarinFrontendV2Result:
    """Typed result of a TamarinFrontend@2 parse/elaborate attempt."""

    status: ParseStatus
    document: tamarin_v1.ProtocolRewritingDocument | None = None
    source_document: SourceDocument | None = None
    parse_artifact: ParseArtifactV2 | None = None
    elaboration_artifact: ElaborationArtifactV2 | None = None
    typed_expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    printed: str = ""
    controlled_source: tamarin_v1.TamarinControlledSourceArtifact | None = None
    schema_version: str = TAMARIN_V2_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = TAMARIN_FRONTEND_V2_INTERFACE

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
    def raw_rules_admitted(self) -> bool:
        return False

    @property
    def raw_target_source_admitted(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "controlled_source": (
                None
                if self.controlled_source is None
                else self.controlled_source.to_dict()
            ),
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
            "raw_rules_admitted": False,
            "raw_target_source_admitted": False,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "typed_expression": (
                None
                if self.typed_expression is None
                else self.typed_expression.to_dict()
            ),
        }


# ---------------------------------------------------------------------------
# Descriptor builders
# ---------------------------------------------------------------------------


def build_protocol_v2_descriptor(
    *,
    limits: FrontendLimits | None = None,
) -> LogicFrontendDescriptor:
    """Build the shared frontend descriptor for ProtocolFrontend@2."""

    bounds = limits if limits is not None else DEFAULT_FRONTEND_LIMITS
    features = (
        FrontendFeature.PARSE.value,
        FrontendFeature.PRINT.value,
        FrontendFeature.ELABORATE.value,
        FrontendFeature.SOURCE_MAP.value,
        FrontendFeature.TYPECHECK.value,
    )
    fixtures = build_baseline_fixture_set(features=features, prefix="protocol-v2")
    extra = (
        FeatureScopedFixture(
            fixture_id="fixture:protocol-v2:roles-events",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description="Roles, events, equations, and processes elaborate typed.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:protocol-v2:unsupported-process",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.TYPECHECK.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Unsupported process constructs reject with exact codes.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:protocol-v2:raw-target-blocked",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Raw ProVerif target source cannot bypass artifacts.",
        ),
    )
    return LogicFrontendDescriptor(
        descriptor_id=PROTOCOL_V2_DESCRIPTOR_ID,
        key=ParserKey(
            notation_id=PROTOCOL_V2_NOTATION_ID,
            notation_version=PROTOCOL_V2_NOTATION_VERSION,
            semantic_profile_id=PROTOCOL_V2_PROFILE_ID,
        ),
        family_id=PROTOCOL_V2_FAMILY_ID,
        features=features,
        parse_modes=(ParseMode.STRICT,),
        limits=bounds,
        diagnostics=tuple(sorted(_ALL_PROTOCOL_V2_CODES)),
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
                    "raw_protocol_rule",
                    "raw_target_source",
                    "raw_proverif_source",
                    *{f"process_{item}" for item in UNSUPPORTED_PROCESS_CONSTRUCTS},
                }
            )
        ),
        implementation="ipfs_datasets_py.logic.parsers.protocol_v2:ProtocolFrontendV2",
        metadata={
            "task_id": PROTOCOL_V2_TASK_ID,
            "goal_id": PROTOCOL_V2_GOAL_ID,
            "interfaces": {
                "protocol": PROTOCOL_FRONTEND_V2_INTERFACE,
                "tamarin": TAMARIN_FRONTEND_V2_INTERFACE,
                "protocol_program": PROTOCOL_PROGRAM_FRONTEND_INTERFACE,
                "parse_artifact": PARSE_ARTIFACT_V2_INTERFACE,
                "elaboration_artifact": ELABORATION_ARTIFACT_V2_INTERFACE,
            },
        },
    )


def build_tamarin_v2_descriptor(
    *,
    limits: FrontendLimits | None = None,
) -> LogicFrontendDescriptor:
    """Build the shared frontend descriptor for TamarinFrontend@2."""

    bounds = limits if limits is not None else DEFAULT_FRONTEND_LIMITS
    features = (
        FrontendFeature.PARSE.value,
        FrontendFeature.PRINT.value,
        FrontendFeature.ELABORATE.value,
        FrontendFeature.SOURCE_MAP.value,
        FrontendFeature.TYPECHECK.value,
    )
    fixtures = build_baseline_fixture_set(features=features, prefix="tamarin-v2")
    extra = (
        FeatureScopedFixture(
            fixture_id="fixture:tamarin-v2:typed-rules",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description="Multiset rules elaborate as typed artifacts, not raw text.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:tamarin-v2:unsupported-rule",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.TYPECHECK.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Unsupported rule features reject closed with diagnostics.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:tamarin-v2:raw-rule-blocked",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Raw protocol rules cannot bypass parse/elaboration.",
        ),
    )
    return LogicFrontendDescriptor(
        descriptor_id=TAMARIN_V2_DESCRIPTOR_ID,
        key=ParserKey(
            notation_id=TAMARIN_V2_NOTATION_ID,
            notation_version=TAMARIN_V2_NOTATION_VERSION,
            semantic_profile_id=TAMARIN_V2_PROFILE_ID,
        ),
        family_id=TAMARIN_V2_FAMILY_ID,
        features=features,
        parse_modes=(ParseMode.STRICT,),
        limits=bounds,
        diagnostics=tuple(sorted(_ALL_PROTOCOL_V2_CODES)),
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
                    "raw_protocol_rule",
                    "raw_target_source",
                    "raw_tamarin_source",
                    *{f"rule_{item}" for item in UNSUPPORTED_RULE_FEATURES},
                    *{f"theory_{item}" for item in UNSUPPORTED_THEORY_FEATURES},
                }
            )
        ),
        implementation="ipfs_datasets_py.logic.parsers.protocol_v2:TamarinFrontendV2",
        metadata={
            "task_id": PROTOCOL_V2_TASK_ID,
            "goal_id": PROTOCOL_V2_GOAL_ID,
            "interfaces": {
                "tamarin": TAMARIN_FRONTEND_V2_INTERFACE,
                "protocol": PROTOCOL_FRONTEND_V2_INTERFACE,
                "parse_artifact": PARSE_ARTIFACT_V2_INTERFACE,
                "elaboration_artifact": ELABORATION_ARTIFACT_V2_INTERFACE,
            },
        },
    )


def build_protocol_program_descriptor(
    *,
    limits: FrontendLimits | None = None,
) -> LogicFrontendDescriptor:
    """Build the joint ProtocolProgramFrontend@2 descriptor."""

    bounds = limits if limits is not None else DEFAULT_FRONTEND_LIMITS
    base = build_protocol_v2_descriptor(limits=bounds)
    fixtures = tuple(base.fixtures) + (
        FeatureScopedFixture(
            fixture_id="fixture:protocol-program:joint-artifacts",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description=(
                "Joint protocol/tamarin/program path emits ParseArtifact@2 and "
                "ElaborationArtifact@2; raw rules and target source never bypass."
            ),
        ),
        FeatureScopedFixture(
            fixture_id="fixture:protocol-program:raw-bypass",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description=(
                "Raw protocol rule, target source, or program assertion cannot "
                "bypass parse/elaboration artifacts."
            ),
        ),
    )
    return LogicFrontendDescriptor(
        descriptor_id=PROTOCOL_PROGRAM_DESCRIPTOR_ID,
        key=ParserKey(
            notation_id=PROTOCOL_V2_NOTATION_ID,
            notation_version=PROTOCOL_V2_NOTATION_VERSION,
            semantic_profile_id="protocol_program_joint",
        ),
        family_id=PROTOCOL_V2_FAMILY_ID,
        features=base.features,
        parse_modes=(ParseMode.STRICT,),
        limits=bounds,
        diagnostics=tuple(sorted(_ALL_PROTOCOL_V2_CODES)),
        artifact_outputs=(
            make_parse_artifact_output(),
            make_elaboration_artifact_output(),
        ),
        fixtures=fixtures,
        recovery=RecoveryPolicy.NONE,
        printer=PrinterContract(
            guarantee=PrinterGuarantee.SEMANTIC,
            features=(FrontendFeature.PRINT.value,),
            deterministic=True,
        ),
        unsupported_behavior=UnsupportedBehavior.REJECT_WITH_DIAGNOSTIC,
        unsupported_nodes=base.unsupported_nodes
        + (
            "raw_program_assertion",
            "raw_hoare_assertion",
            "backend_execution",
        ),
        implementation=(
            "ipfs_datasets_py.logic.parsers.protocol_v2:ProtocolProgramFrontend"
        ),
        metadata={
            "task_id": PROTOCOL_V2_TASK_ID,
            "goal_id": PROTOCOL_V2_GOAL_ID,
            "interfaces": {
                "protocol_program": PROTOCOL_PROGRAM_FRONTEND_INTERFACE,
                "protocol": PROTOCOL_FRONTEND_V2_INTERFACE,
                "tamarin": TAMARIN_FRONTEND_V2_INTERFACE,
                "program": "ProgramFrontend@2",
            },
            "evidence_subset": [
                "protocol",
                "tamarin",
                "program",
                "hoare",
                "contract",
                "verification_condition",
            ],
        },
    )


def register_protocol_v2_frontend(
    registry: SharedFrontendConformance | None = None,
    *,
    limits: FrontendLimits | None = None,
) -> tuple[SharedFrontendConformance, LogicFrontendDescriptor]:
    descriptor = build_protocol_v2_descriptor(limits=limits)
    validate_frontend_descriptor(descriptor)
    target = registry if registry is not None else SharedFrontendConformance()
    admitted = target.register(descriptor)
    return target, admitted


def register_tamarin_v2_frontend(
    registry: SharedFrontendConformance | None = None,
    *,
    limits: FrontendLimits | None = None,
) -> tuple[SharedFrontendConformance, LogicFrontendDescriptor]:
    descriptor = build_tamarin_v2_descriptor(limits=limits)
    validate_frontend_descriptor(descriptor)
    target = registry if registry is not None else SharedFrontendConformance()
    admitted = target.register(descriptor)
    return target, admitted


def register_protocol_program_frontend(
    registry: SharedFrontendConformance | None = None,
    *,
    limits: FrontendLimits | None = None,
) -> tuple[SharedFrontendConformance, LogicFrontendDescriptor]:
    descriptor = build_protocol_program_descriptor(limits=limits)
    validate_frontend_descriptor(descriptor)
    target = registry if registry is not None else SharedFrontendConformance()
    admitted = target.register(descriptor)
    return target, admitted


# ---------------------------------------------------------------------------
# Frontends
# ---------------------------------------------------------------------------


class ProtocolFrontendV2:
    """Shared-artifact symbolic protocol frontend.

    Interface: ``ProtocolFrontend@2``.
    """

    interface: ClassVar[str] = PROTOCOL_FRONTEND_V2_INTERFACE
    notation_id: ClassVar[str] = PROTOCOL_V2_NOTATION_ID
    notation_version: ClassVar[str] = PROTOCOL_V2_NOTATION_VERSION
    profile_id: ClassVar[str] = PROTOCOL_V2_PROFILE_ID
    family_id: ClassVar[str] = PROTOCOL_V2_FAMILY_ID
    module_version: ClassVar[str] = PROTOCOL_V2_MODULE_VERSION
    task_id: ClassVar[str] = PROTOCOL_V2_TASK_ID
    goal_id: ClassVar[str] = PROTOCOL_V2_GOAL_ID

    def __init__(
        self,
        *,
        limits: FrontendLimits | ParseLimits | None = None,
    ) -> None:
        if isinstance(limits, FrontendLimits):
            self.limits = limits
        elif isinstance(limits, ParseLimits):
            self.limits = FrontendLimits(parse_limits=limits)
        else:
            self.limits = DEFAULT_FRONTEND_LIMITS
        self._v1 = protocol_v1.SymbolicProtocolSyntax()
        self._descriptor = build_protocol_v2_descriptor(limits=self.limits)

    @property
    def descriptor(self) -> LogicFrontendDescriptor:
        return self._descriptor

    def parse_limits(self) -> ParseLimits:
        return self.limits.parse_limits

    def parse(
        self,
        value: Mapping[str, Any] | str | ProtocolIR,
        *,
        document_id: str = "doc:protocol:v2:1",
        request_id: str = "req:protocol:v2:1",
        limits: ParseLimits | None = None,
        elaborate: bool = True,
        lower_proverif: bool = False,
    ) -> ProtocolFrontendV2Result:
        bounds = limits if limits is not None else self.parse_limits()

        if isinstance(value, ProtocolIR):
            try:
                text = protocol_v1.SymbolicProtocolDocument(protocol=value).to_json()
            except protocol_v1.ProtocolSyntaxError as error:
                diag = _diag(
                    code=_error_code_from_v1(error),
                    message=str(error),
                    range=SourceRange(0, 0),
                    diagnostic_id="diag:protocol-v2:ir",
                )
                return ProtocolFrontendV2Result(
                    status=ParseStatus.FAILED, diagnostics=(diag,)
                )
        else:
            try:
                text = _json_text(value)
            except ProtocolFrontendV2Error as error:
                diag = _diag(
                    code=error.code,
                    message=error.message,
                    range=SourceRange(0, 0),
                    diagnostic_id="diag:protocol-v2:input",
                    remediation=error.remediation,
                )
                return ProtocolFrontendV2Result(
                    status=ParseStatus.FAILED, diagnostics=(diag,)
                )

        try:
            source = _source_from_text(
                text,
                document_id=document_id,
                language_hint="symbolic_protocol",
                interface=self.interface,
                notation_id=self.notation_id,
                limits=bounds,
            )
        except ProtocolFrontendV2Error as error:
            diag = _diag(
                code=error.code,
                message=error.message,
                range=SourceRange(0, 0),
                diagnostic_id="diag:protocol-v2:source",
            )
            return ProtocolFrontendV2Result(
                status=ParseStatus.REJECTED, diagnostics=(diag,)
            )
        except SyntaxContractError as error:
            diag = _diag(
                code=CODE_INPUT_LIMIT,
                message=str(error),
                range=SourceRange(0, 0),
                diagnostic_id="diag:protocol-v2:source",
            )
            return ProtocolFrontendV2Result(
                status=ParseStatus.REJECTED, diagnostics=(diag,)
            )

        try:
            document = self._v1.parse_json(text)
        except protocol_v1.ProtocolSyntaxError as error:
            diagnostics = _unique_diagnostics(
                (
                    _diag(
                        code=_error_code_from_v1(error),
                        message=str(error),
                        range=source.full_range(),
                        diagnostic_id="diag:protocol-v2:parse",
                        remediation=getattr(error, "remediation", "") or "",
                    ),
                )
            )
            cst = _covering_cst(source, cst_id=f"cst:protocol:{request_id}")
            artifact = ParseArtifactV2.from_document(
                source,
                artifact_id=f"art:protocol:parse:{request_id}",
                request_id=request_id,
                status=ParseStatus.FAILED,
                cst=cst,
                diagnostics=diagnostics,
                metadata={
                    "interface": self.interface,
                    "stage": "parse_failed",
                    "raw_rules_admitted": False,
                    "raw_target_source_admitted": False,
                    "execution_admitted": False,
                },
            )
            elab = ElaborationArtifactV2(
                artifact_id=f"art:protocol:elab:{request_id}",
                parse_artifact_id=artifact.artifact_id,
                document_id=source.document_id,
                source_digest=source.content_digest,
                status=ElaborationArtifactStatus.FAILED,
                parse_content_digest=artifact.content_digest,
                parse_lineage_digest=artifact.lineage_digest,
                diagnostics=diagnostics,
                metadata={
                    "interface": self.interface,
                    "raw_rules_admitted": False,
                    "raw_target_source_admitted": False,
                    "execution_admitted": False,
                },
            )
            return ProtocolFrontendV2Result(
                status=ParseStatus.FAILED,
                source_document=source,
                parse_artifact=artifact,
                elaboration_artifact=elab,
                diagnostics=diagnostics,
            )

        printed = document.to_json()
        surface = _surface_protocol(document, full_range=source.full_range())
        cst = _covering_cst(source, cst_id=f"cst:protocol:{request_id}")
        parse_artifact = ParseArtifactV2.from_document(
            source,
            artifact_id=f"art:protocol:parse:{request_id}",
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
                "protocol_document_id": document.protocol.document_id,
                "symbolic_document_id": document.document_id,
                "process_count": len(document.process_nodes),
                "claim_count": len(document.protocol.claims),
                "printed": printed,
                "raw_rules_admitted": False,
                "raw_target_source_admitted": False,
                "execution_admitted": False,
            },
        )
        parse_artifact.validate_against(source)

        typed_expression: TypedExpression | None = None
        elaboration_artifact: ElaborationArtifactV2 | None = None
        if elaborate:
            try:
                typed_expression, signature = _project_protocol_document(
                    document,
                    expression_id=f"expr:protocol:{request_id}",
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
                    artifact_id=f"art:protocol:elab:{request_id}",
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
                        "protocol_document_id": document.protocol.document_id,
                        "raw_rules_admitted": False,
                        "raw_target_source_admitted": False,
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
                    message=f"protocol elaboration failed: {error}",
                    range=source.full_range(),
                    diagnostic_id="diag:protocol-v2:elab",
                )
                diagnostics = (diag,)
                elaboration_artifact = ElaborationArtifactV2(
                    artifact_id=f"art:protocol:elab:{request_id}",
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
                return ProtocolFrontendV2Result(
                    status=ParseStatus.FAILED,
                    document=document,
                    source_document=source,
                    parse_artifact=parse_artifact,
                    elaboration_artifact=elaboration_artifact,
                    diagnostics=diagnostics,
                    printed=printed,
                )

        controlled: protocol_v1.ProVerifControlledSourceArtifact | None = None
        if lower_proverif:
            # Lowering is only allowed once typed artifacts exist.
            if not elaborate or typed_expression is None or elaboration_artifact is None:
                raise ProtocolArtifactBypassError(
                    "ProVerif lowering requires typed parse/elaboration artifacts",
                    code=CODE_BYPASS_BLOCKED,
                    remediation="Call parse(..., elaborate=True) before lowering.",
                )
            controlled = self._v1.lower_to_proverif(document)

        return ProtocolFrontendV2Result(
            status=ParseStatus.OK,
            document=document,
            source_document=source,
            parse_artifact=parse_artifact,
            elaboration_artifact=elaboration_artifact,
            typed_expression=typed_expression,
            diagnostics=(),
            printed=printed,
            controlled_source=controlled,
        )

    def parse_text(self, text: str, **kwargs: Any) -> ProtocolFrontendV2Result:
        return self.parse(text, **kwargs)

    def elaborate(self, value: Mapping[str, Any] | str | ProtocolIR, **kwargs: Any) -> ProtocolFrontendV2Result:
        kwargs = dict(kwargs)
        kwargs["elaborate"] = True
        return self.parse(value, **kwargs)

    def print(self, document: protocol_v1.SymbolicProtocolDocument) -> str:
        return document.to_json()

    def lower_to_proverif(
        self,
        result: ProtocolFrontendV2Result | protocol_v1.SymbolicProtocolDocument,
    ) -> protocol_v1.ProVerifControlledSourceArtifact:
        """Lower only from a typed parse result or an already-typed document.

        Raw ProVerif target source strings are never admitted.
        """

        if isinstance(result, ProtocolFrontendV2Result):
            if not result.has_typed_artifacts or result.document is None:
                raise ProtocolArtifactBypassError(
                    "cannot lower to ProVerif without typed parse/elaboration "
                    "artifacts",
                    code=CODE_BYPASS_BLOCKED,
                )
            return self._v1.lower_to_proverif(result.document)
        if isinstance(result, protocol_v1.SymbolicProtocolDocument):
            # Document objects are already typed IR; still require explicit
            # frontend parse for artifact-bound callers via the Result path.
            return self._v1.lower_to_proverif(result)
        raise ProtocolArtifactBypassError(
            "raw target source or untyped payload cannot bypass artifacts",
            code=CODE_RAW_TARGET_SOURCE,
            remediation=(
                "Parse through ProtocolFrontend@2 and lower the typed result"
            ),
        )

    def admit_raw_protocol_rule(self, *_args: Any, **_kwargs: Any) -> None:
        """Hard-fail: raw protocol rules never enter without typed artifacts."""

        raise ProtocolArtifactBypassError(
            "raw protocol rule cannot bypass parse/elaboration artifacts",
            code=CODE_RAW_RULE,
            remediation="Parse multiset/process rules through ProtocolFrontend@2 "
            "or TamarinFrontend@2",
        )

    def admit_raw_target_source(self, *_args: Any, **_kwargs: Any) -> None:
        """Hard-fail: raw ProVerif/Tamarin source never enters as authority."""

        raise ProtocolArtifactBypassError(
            "raw target source cannot bypass parse/elaboration artifacts",
            code=CODE_RAW_TARGET_SOURCE,
            remediation="Lower only from typed ProtocolFrontend@2 / "
            "TamarinFrontend@2 results",
        )

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        raise ProtocolArtifactBypassError(
            "ProtocolFrontend@2 does not execute provers; only typed "
            "ParseArtifact@2 / ElaborationArtifact@2 are produced",
            code=CODE_BYPASS_BLOCKED,
        )


class TamarinFrontendV2:
    """Shared-artifact Tamarin multiset-rewriting frontend.

    Interface: ``TamarinFrontend@2``.
    """

    interface: ClassVar[str] = TAMARIN_FRONTEND_V2_INTERFACE
    notation_id: ClassVar[str] = TAMARIN_V2_NOTATION_ID
    notation_version: ClassVar[str] = TAMARIN_V2_NOTATION_VERSION
    profile_id: ClassVar[str] = TAMARIN_V2_PROFILE_ID
    family_id: ClassVar[str] = TAMARIN_V2_FAMILY_ID
    module_version: ClassVar[str] = PROTOCOL_V2_MODULE_VERSION
    task_id: ClassVar[str] = PROTOCOL_V2_TASK_ID
    goal_id: ClassVar[str] = PROTOCOL_V2_GOAL_ID

    def __init__(
        self,
        *,
        limits: FrontendLimits | ParseLimits | None = None,
        tool_version: str = tamarin_v1.DEFAULT_TOOL_VERSION,
    ) -> None:
        if isinstance(limits, FrontendLimits):
            self.limits = limits
        elif isinstance(limits, ParseLimits):
            self.limits = FrontendLimits(parse_limits=limits)
        else:
            self.limits = DEFAULT_FRONTEND_LIMITS
        self.tool_version = tool_version
        self._v1 = tamarin_v1.TamarinProtocolMappings(tool_version=tool_version)
        self._descriptor = build_tamarin_v2_descriptor(limits=self.limits)

    @property
    def descriptor(self) -> LogicFrontendDescriptor:
        return self._descriptor

    def parse_limits(self) -> ParseLimits:
        return self.limits.parse_limits

    def parse(
        self,
        value: Mapping[str, Any] | str | ProtocolIR,
        *,
        document_id: str = "doc:tamarin:v2:1",
        request_id: str = "req:tamarin:v2:1",
        limits: ParseLimits | None = None,
        elaborate: bool = True,
        lower_tamarin: bool = False,
    ) -> TamarinFrontendV2Result:
        bounds = limits if limits is not None else self.parse_limits()

        if isinstance(value, ProtocolIR):
            try:
                text = tamarin_v1.ProtocolRewritingDocument(protocol=value).to_json()
            except tamarin_v1.TamarinMappingError as error:
                diag = _diag(
                    code=_error_code_from_v1(error),
                    message=str(error),
                    range=SourceRange(0, 0),
                    diagnostic_id="diag:tamarin-v2:ir",
                )
                return TamarinFrontendV2Result(
                    status=ParseStatus.FAILED, diagnostics=(diag,)
                )
        else:
            try:
                text = _json_text(value)
            except ProtocolFrontendV2Error as error:
                diag = _diag(
                    code=error.code,
                    message=error.message,
                    range=SourceRange(0, 0),
                    diagnostic_id="diag:tamarin-v2:input",
                )
                return TamarinFrontendV2Result(
                    status=ParseStatus.FAILED, diagnostics=(diag,)
                )

        try:
            source = _source_from_text(
                text,
                document_id=document_id,
                language_hint="tamarin_spthy",
                interface=self.interface,
                notation_id=self.notation_id,
                limits=bounds,
            )
        except ProtocolFrontendV2Error as error:
            diag = _diag(
                code=error.code,
                message=error.message,
                range=SourceRange(0, 0),
                diagnostic_id="diag:tamarin-v2:source",
            )
            return TamarinFrontendV2Result(
                status=ParseStatus.REJECTED, diagnostics=(diag,)
            )
        except SyntaxContractError as error:
            diag = _diag(
                code=CODE_INPUT_LIMIT,
                message=str(error),
                range=SourceRange(0, 0),
                diagnostic_id="diag:tamarin-v2:source",
            )
            return TamarinFrontendV2Result(
                status=ParseStatus.REJECTED, diagnostics=(diag,)
            )

        try:
            document = self._v1.parse(text)
        except tamarin_v1.TamarinMappingError as error:
            diagnostics = _unique_diagnostics(
                (
                    _diag(
                        code=_error_code_from_v1(error),
                        message=str(error),
                        range=source.full_range(),
                        diagnostic_id="diag:tamarin-v2:parse",
                        remediation=getattr(error, "remediation", "") or "",
                    ),
                ),
                prefix="diag:tamarin-v2",
            )
            cst = _covering_cst(
                source, cst_id=f"cst:tamarin:{request_id}", kind="spthy_json"
            )
            artifact = ParseArtifactV2.from_document(
                source,
                artifact_id=f"art:tamarin:parse:{request_id}",
                request_id=request_id,
                status=ParseStatus.FAILED,
                cst=cst,
                diagnostics=diagnostics,
                metadata={
                    "interface": self.interface,
                    "stage": "parse_failed",
                    "raw_rules_admitted": False,
                    "raw_target_source_admitted": False,
                    "execution_admitted": False,
                },
            )
            elab = ElaborationArtifactV2(
                artifact_id=f"art:tamarin:elab:{request_id}",
                parse_artifact_id=artifact.artifact_id,
                document_id=source.document_id,
                source_digest=source.content_digest,
                status=ElaborationArtifactStatus.FAILED,
                parse_content_digest=artifact.content_digest,
                parse_lineage_digest=artifact.lineage_digest,
                diagnostics=diagnostics,
                metadata={
                    "interface": self.interface,
                    "raw_rules_admitted": False,
                    "raw_target_source_admitted": False,
                    "execution_admitted": False,
                },
            )
            return TamarinFrontendV2Result(
                status=ParseStatus.FAILED,
                source_document=source,
                parse_artifact=artifact,
                elaboration_artifact=elab,
                diagnostics=diagnostics,
            )

        printed = document.to_json()
        surface = _surface_tamarin(document, full_range=source.full_range())
        cst = _covering_cst(
            source, cst_id=f"cst:tamarin:{request_id}", kind="spthy_json"
        )
        parse_artifact = ParseArtifactV2.from_document(
            source,
            artifact_id=f"art:tamarin:parse:{request_id}",
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
                "protocol_document_id": document.protocol.document_id,
                "rewriting_document_id": document.document_id,
                "rule_count": len(document.rules),
                "lemma_count": len(document.lemmas),
                "printed": printed,
                "raw_rules_admitted": False,
                "raw_target_source_admitted": False,
                "execution_admitted": False,
            },
        )
        parse_artifact.validate_against(source)

        typed_expression: TypedExpression | None = None
        elaboration_artifact: ElaborationArtifactV2 | None = None
        if elaborate:
            try:
                typed_expression, signature = _project_tamarin_document(
                    document,
                    expression_id=f"expr:tamarin:{request_id}",
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
                    artifact_id=f"art:tamarin:elab:{request_id}",
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
                        "rule_ids": [item.rule_id for item in document.rules],
                        "raw_rules_admitted": False,
                        "raw_target_source_admitted": False,
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
                    message=f"tamarin elaboration failed: {error}",
                    range=source.full_range(),
                    diagnostic_id="diag:tamarin-v2:elab",
                )
                diagnostics = (diag,)
                elaboration_artifact = ElaborationArtifactV2(
                    artifact_id=f"art:tamarin:elab:{request_id}",
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
                return TamarinFrontendV2Result(
                    status=ParseStatus.FAILED,
                    document=document,
                    source_document=source,
                    parse_artifact=parse_artifact,
                    elaboration_artifact=elaboration_artifact,
                    diagnostics=diagnostics,
                    printed=printed,
                )

        controlled: tamarin_v1.TamarinControlledSourceArtifact | None = None
        if lower_tamarin:
            if not elaborate or typed_expression is None or elaboration_artifact is None:
                raise ProtocolArtifactBypassError(
                    "Tamarin lowering requires typed parse/elaboration artifacts",
                    code=CODE_BYPASS_BLOCKED,
                )
            controlled = self._v1.lower_to_tamarin(
                document, tool_version=self.tool_version
            )

        return TamarinFrontendV2Result(
            status=ParseStatus.OK,
            document=document,
            source_document=source,
            parse_artifact=parse_artifact,
            elaboration_artifact=elaboration_artifact,
            typed_expression=typed_expression,
            diagnostics=(),
            printed=printed,
            controlled_source=controlled,
        )

    def parse_text(self, text: str, **kwargs: Any) -> TamarinFrontendV2Result:
        return self.parse(text, **kwargs)

    def elaborate(
        self, value: Mapping[str, Any] | str | ProtocolIR, **kwargs: Any
    ) -> TamarinFrontendV2Result:
        kwargs = dict(kwargs)
        kwargs["elaborate"] = True
        return self.parse(value, **kwargs)

    def print(self, document: tamarin_v1.ProtocolRewritingDocument) -> str:
        return document.to_json()

    def lower_to_tamarin(
        self,
        result: TamarinFrontendV2Result | tamarin_v1.ProtocolRewritingDocument,
    ) -> tamarin_v1.TamarinControlledSourceArtifact:
        if isinstance(result, TamarinFrontendV2Result):
            if not result.has_typed_artifacts or result.document is None:
                raise ProtocolArtifactBypassError(
                    "cannot lower to Tamarin without typed parse/elaboration "
                    "artifacts",
                    code=CODE_BYPASS_BLOCKED,
                )
            return self._v1.lower_to_tamarin(
                result.document, tool_version=self.tool_version
            )
        if isinstance(result, tamarin_v1.ProtocolRewritingDocument):
            return self._v1.lower_to_tamarin(
                result, tool_version=self.tool_version
            )
        raise ProtocolArtifactBypassError(
            "raw protocol rule or target source cannot bypass artifacts",
            code=CODE_RAW_RULE,
        )

    def admit_raw_protocol_rule(self, *_args: Any, **_kwargs: Any) -> None:
        raise ProtocolArtifactBypassError(
            "raw protocol rule cannot bypass parse/elaboration artifacts",
            code=CODE_RAW_RULE,
        )

    def admit_raw_target_source(self, *_args: Any, **_kwargs: Any) -> None:
        raise ProtocolArtifactBypassError(
            "raw Tamarin target source cannot bypass parse/elaboration artifacts",
            code=CODE_RAW_TARGET_SOURCE,
        )

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        raise ProtocolArtifactBypassError(
            "TamarinFrontend@2 does not execute provers; only typed artifacts "
            "are produced",
            code=CODE_BYPASS_BLOCKED,
        )


class ProtocolProgramFrontend:
    """Joint protocol + Tamarin + program convergence facade.

    Interface: ``ProtocolProgramFrontend@2``.

    Owns the fail-closed contract that raw protocol rules, target source
    strings, and program assertions cannot reach execution or backend lowers
    without typed parse/elaboration artifacts.
    """

    interface: ClassVar[str] = PROTOCOL_PROGRAM_FRONTEND_INTERFACE
    module_version: ClassVar[str] = PROTOCOL_V2_MODULE_VERSION
    task_id: ClassVar[str] = PROTOCOL_V2_TASK_ID
    goal_id: ClassVar[str] = PROTOCOL_V2_GOAL_ID

    def __init__(
        self,
        *,
        limits: FrontendLimits | ParseLimits | None = None,
    ) -> None:
        if isinstance(limits, FrontendLimits):
            self.limits = limits
        elif isinstance(limits, ParseLimits):
            self.limits = FrontendLimits(parse_limits=limits)
        else:
            self.limits = DEFAULT_FRONTEND_LIMITS
        self.protocol = ProtocolFrontendV2(limits=self.limits)
        self.tamarin = TamarinFrontendV2(limits=self.limits)
        self._program: Any | None = None
        self._descriptor = build_protocol_program_descriptor(limits=self.limits)

    @property
    def descriptor(self) -> LogicFrontendDescriptor:
        return self._descriptor

    @property
    def program(self) -> Any:
        """Lazy ProgramFrontend@2 (avoids circular import at module load)."""

        if self._program is None:
            from ipfs_datasets_py.logic.parsers import program_v2 as _program_v2

            self._program = _program_v2.ProgramFrontendV2(limits=self.limits)
        return self._program

    def parse_protocol(
        self, value: Mapping[str, Any] | str | ProtocolIR, **kwargs: Any
    ) -> ProtocolFrontendV2Result:
        return self.protocol.parse(value, **kwargs)

    def parse_tamarin(
        self, value: Mapping[str, Any] | str | ProtocolIR, **kwargs: Any
    ) -> TamarinFrontendV2Result:
        return self.tamarin.parse(value, **kwargs)

    def parse_program(self, value: Mapping[str, Any] | str, **kwargs: Any) -> Any:
        return self.program.parse(value, **kwargs)

    def admit_raw_protocol_rule(self, *_args: Any, **_kwargs: Any) -> None:
        raise ProtocolArtifactBypassError(
            "raw protocol rule cannot bypass parse/elaboration artifacts",
            code=CODE_RAW_RULE,
        )

    def admit_raw_target_source(self, *_args: Any, **_kwargs: Any) -> None:
        raise ProtocolArtifactBypassError(
            "raw target source cannot bypass parse/elaboration artifacts",
            code=CODE_RAW_TARGET_SOURCE,
        )

    def admit_raw_program_assertion(self, *_args: Any, **_kwargs: Any) -> None:
        raise ProtocolArtifactBypassError(
            "raw program assertion cannot bypass parse/elaboration artifacts",
            code=CODE_BYPASS_BLOCKED,
            remediation="Parse through ProgramFrontend@2 before VC lowering",
        )

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        raise ProtocolArtifactBypassError(
            "ProtocolProgramFrontend@2 never executes provers or VC solvers; "
            "typed artifacts are required first",
            code=CODE_BYPASS_BLOCKED,
        )


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_protocol_v2(
    value: Mapping[str, Any] | str | ProtocolIR, **kwargs: Any
) -> ProtocolFrontendV2Result:
    """Parse symbolic protocol source into shared typed artifacts."""

    return ProtocolFrontendV2().parse(value, **kwargs)


def parse_tamarin_v2(
    value: Mapping[str, Any] | str | ProtocolIR, **kwargs: Any
) -> TamarinFrontendV2Result:
    """Parse Tamarin multiset-rewriting source into shared typed artifacts."""

    return TamarinFrontendV2().parse(value, **kwargs)


def elaborate_protocol_v2(
    value: Mapping[str, Any] | str | ProtocolIR, **kwargs: Any
) -> ProtocolFrontendV2Result:
    return ProtocolFrontendV2().elaborate(value, **kwargs)


def elaborate_tamarin_v2(
    value: Mapping[str, Any] | str | ProtocolIR, **kwargs: Any
) -> TamarinFrontendV2Result:
    return TamarinFrontendV2().elaborate(value, **kwargs)


def print_protocol_v2(document: protocol_v1.SymbolicProtocolDocument) -> str:
    return ProtocolFrontendV2().print(document)


def print_tamarin_v2(document: tamarin_v1.ProtocolRewritingDocument) -> str:
    return TamarinFrontendV2().print(document)


__all__ = [
    "CODE_BYPASS_BLOCKED",
    "CODE_ELABORATION_FAILED",
    "CODE_EMPTY_INPUT",
    "CODE_INPUT_LIMIT",
    "CODE_INVALID_DOCUMENT",
    "CODE_MALFORMED_JSON",
    "CODE_MISSING_PROTOCOL",
    "CODE_RAW_RULE",
    "CODE_RAW_TARGET_SOURCE",
    "CODE_UNSUPPORTED_PROCESS",
    "DEFAULT_FRONTEND_LIMITS",
    "ELABORATION_ARTIFACT_V2_INTERFACE",
    "PARSE_ARTIFACT_V2_INTERFACE",
    "PROTOCOL_FRONTEND_V2_INTERFACE",
    "PROTOCOL_PROGRAM_DESCRIPTOR_ID",
    "PROTOCOL_PROGRAM_FRONTEND_INTERFACE",
    "PROTOCOL_V2_DESCRIPTOR_ID",
    "PROTOCOL_V2_FAMILY_ID",
    "PROTOCOL_V2_GOAL_ID",
    "PROTOCOL_V2_MODULE_VERSION",
    "PROTOCOL_V2_NOTATION_ID",
    "PROTOCOL_V2_PROFILE_ID",
    "PROTOCOL_V2_TASK_ID",
    "ProcessKind",
    "ProcessNode",
    "ProtocolArtifactBypassError",
    "ProtocolFrontendV2",
    "ProtocolFrontendV2Error",
    "ProtocolFrontendV2Result",
    "ProtocolProgramFrontend",
    "ProtocolRewritingDocument",
    "SymbolicProtocolDocument",
    "TAMARIN_FRONTEND_V2_INTERFACE",
    "TAMARIN_V2_DESCRIPTOR_ID",
    "TAMARIN_V2_FAMILY_ID",
    "TAMARIN_V2_NOTATION_ID",
    "TAMARIN_V2_PROFILE_ID",
    "TamarinFrontendV2",
    "TamarinFrontendV2Error",
    "TamarinFrontendV2Result",
    "UNSUPPORTED_PROCESS_CONSTRUCTS",
    "UNSUPPORTED_RULE_FEATURES",
    "UNSUPPORTED_THEORY_FEATURES",
    "build_protocol_program_descriptor",
    "build_protocol_v2_descriptor",
    "build_tamarin_v2_descriptor",
    "elaborate_protocol_v2",
    "elaborate_tamarin_v2",
    "parse_protocol_v2",
    "parse_tamarin_v2",
    "print_protocol_v2",
    "print_tamarin_v2",
    "register_protocol_program_frontend",
    "register_protocol_v2_frontend",
    "register_tamarin_v2_frontend",
]
