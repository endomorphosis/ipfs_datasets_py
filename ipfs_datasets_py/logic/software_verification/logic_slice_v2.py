"""End-to-end software-verification domain logic slice (``SoftwareVerificationLogicSlice@2``).

Connects base software-verification and contract obligations through a single
typed vertical path:

    typed origin → semantics → translation → request → result → replay
    → authority lineage

Base obligations admitted here (Wave-2, before LFP2-044 overlays):

* program contracts and verification conditions
* program and state/transition obligations
* separation / heap-resource obligations
* concurrency and refinement obligations
* temporal properties and counterexample discharge
* controlled kernel target-theory compilation candidates

Session/process overlays attach only in LFP2-044 after LFP2-043.  This module
composes existing syntax-bridge routes, translation catalog edges, and v2
request/artifact/evidence contracts.  It does not weaken rich domain IRs and
never treats free-form text as a typed origin.

Hermetic fixtures supply provider execution and replay without requiring live
provers.  Tool absence remains an availability result, not a mock proof.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.artifacts_v2 import (
    CompiledLogicArtifact,
    ParsedTargetArtifact,
    admit_compiled_target,
    admit_parsed_result,
)
from ipfs_datasets_py.logic.backends.evidence_v2 import (
    EvidenceReplayReceipt,
    ExecutionOutcome,
    ExecutionRecordKind,
    ProviderExecutionReceiptV2,
    ReplayDisposition,
)
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BackendRequestV2,
    LogicObligationV2,
    RequestAuthorityCeiling,
    RequestBounds,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    encoding_id,
    evidence_id,
    notation_id,
    property_id,
    provider_id,
    view_id,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import (
    DomainLogicSliceV2,
)
from ipfs_datasets_py.logic.software_verification.syntax_bridge import (
    BRIDGE_DOMAIN_ID,
    SoftwareVerificationIRKind,
    SoftwareVerificationSyntaxBridge,
    default_ir_routes,
)
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression, mk_extension
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SourceDocument,
    SourceMap,
    SourceMapEntry,
    SourceRange,
    content_sha256,
    canonical_json_bytes,
)
from ipfs_datasets_py.logic.syntax_core.signatures import LogicSignature
from ipfs_datasets_py.logic.translations.catalog import (
    LogicTranslationGraph,
    build_logic_translation_graph,
)
from ipfs_datasets_py.logic.translations.kernel_targets import (
    build_kernel_target_translation_edges,
)
from ipfs_datasets_py.logic.translations.program import (
    build_program_translation_edges,
)
from ipfs_datasets_py.logic.translations.state_temporal import (
    build_state_temporal_edges,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

SOFTWARE_VERIFICATION_LOGIC_SLICE_INTERFACE: Final = (
    "SoftwareVerificationLogicSlice@2"
)
SOFTWARE_VERIFICATION_LOGIC_SLICE_SCHEMA: Final = (
    "software-verification-logic-slice/v2"
)
SOFTWARE_VERIFICATION_LOGIC_SLICE_VERSION: Final = "2.0.0"
OBLIGATION_LINEAGE_SCHEMA: Final = "software-verification-obligation-lineage/v2"
DOMAIN_ID: Final = BRIDGE_DOMAIN_ID

# Required lineage stages for every supported obligation (acceptance criterion).
LINEAGE_STAGES: Final[tuple[str, ...]] = (
    "typed_origin",
    "semantics",
    "translation",
    "request",
    "result",
    "replay",
    "authority_lineage",
)

# Deferred until LFP2-044 (session/process overlays after LFP2-043).
DEFERRED_OBLIGATION_KINDS: Final[frozenset[str]] = frozenset(
    {
        "session",
        "process",
        "linear_session",
        "session_process",
    }
)


class SoftwareVerificationSliceError(ValueError):
    """Raised when a software-verification logic slice cannot be admitted."""


class ObligationLineageError(SoftwareVerificationSliceError):
    """Raised when required lineage stages are missing or inconsistent."""


class UnsupportedObligationError(SoftwareVerificationSliceError):
    """Raised for obligations outside the base Wave-2 set."""


class SoftwareVerificationObligationKind(StrEnum):
    """Base obligation classes connected end to end by this slice."""

    CONTRACT = "contract"
    VC = "vc"
    PROGRAM = "program"
    STATE = "state"
    SEPARATION = "separation"
    CONCURRENCY = "concurrency"
    REFINEMENT = "refinement"
    TEMPORAL = "temporal"
    COUNTEREXAMPLE = "counterexample"
    KERNEL_TARGET = "kernel_target"


SUPPORTED_OBLIGATION_KINDS: Final[tuple[SoftwareVerificationObligationKind, ...]] = (
    SoftwareVerificationObligationKind.CONTRACT,
    SoftwareVerificationObligationKind.VC,
    SoftwareVerificationObligationKind.PROGRAM,
    SoftwareVerificationObligationKind.STATE,
    SoftwareVerificationObligationKind.SEPARATION,
    SoftwareVerificationObligationKind.CONCURRENCY,
    SoftwareVerificationObligationKind.REFINEMENT,
    SoftwareVerificationObligationKind.TEMPORAL,
    SoftwareVerificationObligationKind.COUNTEREXAMPLE,
    SoftwareVerificationObligationKind.KERNEL_TARGET,
)


@dataclass(frozen=True, slots=True)
class ObligationRouteDescriptor:
    """Static routing metadata for one supported obligation class."""

    kind: SoftwareVerificationObligationKind
    ir_kind: SoftwareVerificationIRKind
    property_name: str
    view_name: str
    notation_name: str
    encoding_name: str
    evidence_name: str
    provider_name: str
    authority_ceiling: RequestAuthorityCeiling
    result_authority: ResultAuthority
    translation_edge_id: str
    translation_family: str
    compiler_id: str
    result_kind: str
    statement: str
    target_text: str
    result_output: str
    features: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SoftwareVerificationObligationKind):
            object.__setattr__(
                self, "kind", SoftwareVerificationObligationKind(self.kind)
            )
        if not isinstance(self.ir_kind, SoftwareVerificationIRKind):
            object.__setattr__(
                self, "ir_kind", SoftwareVerificationIRKind(self.ir_kind)
            )
        if not isinstance(self.authority_ceiling, RequestAuthorityCeiling):
            object.__setattr__(
                self,
                "authority_ceiling",
                RequestAuthorityCeiling(self.authority_ceiling),
            )
        if not isinstance(self.result_authority, ResultAuthority):
            object.__setattr__(
                self, "result_authority", ResultAuthority(self.result_authority)
            )


def default_obligation_routes() -> Mapping[
    SoftwareVerificationObligationKind, ObligationRouteDescriptor
]:
    """Return the sealed base-obligation route table."""

    rows: tuple[ObligationRouteDescriptor, ...] = (
        ObligationRouteDescriptor(
            kind=SoftwareVerificationObligationKind.CONTRACT,
            ir_kind=SoftwareVerificationIRKind.CONTRACT,
            property_name="postcondition",
            view_name="source",
            notation_name="program_contract",
            encoding_name="smtlib2",
            evidence_name="model",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
            result_authority=ResultAuthority.SATISFIABILITY,
            translation_edge_id="program_to_smt",
            translation_family="program",
            compiler_id="program.contract.smtlib2",
            result_kind="satisfiability.unsat",
            statement="Discharge program-contract postcondition under framed preconditions.",
            target_text="(assert (not postcondition))",
            result_output="unsat",
            features=("software_verification.contract", "program.contract"),
            assumption_ids=("assumption:frame_closed",),
            notes="Contract obligations lower through program→SMT edges.",
        ),
        ObligationRouteDescriptor(
            kind=SoftwareVerificationObligationKind.VC,
            ir_kind=SoftwareVerificationIRKind.VC,
            property_name="validity",
            view_name="verification_condition",
            notation_name="vc_surface",
            encoding_name="smtlib2",
            evidence_name="model",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
            result_authority=ResultAuthority.SATISFIABILITY,
            translation_edge_id="vc_to_smt",
            translation_family="program",
            compiler_id="program.vc.smtlib2",
            result_kind="satisfiability.unsat",
            statement="Discharge verification-condition by theorem-by-negation SMT query.",
            target_text="(assert (not vc_goal))",
            result_output="unsat",
            features=(
                "software_verification.vc",
                "program.verification_condition",
            ),
            assumption_ids=("assumption:wp_fragment",),
            notes="VC is a view role, never a family.",
        ),
        ObligationRouteDescriptor(
            kind=SoftwareVerificationObligationKind.PROGRAM,
            ir_kind=SoftwareVerificationIRKind.PROGRAM,
            property_name="partial_correctness",
            view_name="source",
            notation_name="program_ir",
            encoding_name="smtlib2",
            evidence_name="model",
            provider_name="cvc5",
            authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
            result_authority=ResultAuthority.SATISFIABILITY,
            translation_edge_id="program_to_smt",
            translation_family="program",
            compiler_id="program.ir.smtlib2",
            result_kind="satisfiability.unsat",
            statement="Prove partial correctness of the closed program fragment.",
            target_text="(assert (not partial_correctness))",
            result_output="unsat",
            features=("software_verification.program", "program.ir"),
            assumption_ids=("assumption:bounded_integers",),
        ),
        ObligationRouteDescriptor(
            kind=SoftwareVerificationObligationKind.STATE,
            ir_kind=SoftwareVerificationIRKind.STATE,
            property_name="invariant",
            view_name="source",
            notation_name="state_schema",
            encoding_name="smtlib2",
            evidence_name="model",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.MODEL_CHECK,
            translation_edge_id="transition_system_to_bounded_smt",
            translation_family="state_temporal",
            compiler_id="state.schema.bounded_smt",
            result_kind="model_check.satisfied",
            statement="Check finite-state invariant under declared domain bounds.",
            target_text="(assert (not invariant))",
            result_output="unsat",
            features=("software_verification.state", "transition_system.state"),
            assumption_ids=("assumption:finite_domain", "bound:state_space"),
            notes="Finite/infinite bounds must remain explicit.",
        ),
        ObligationRouteDescriptor(
            kind=SoftwareVerificationObligationKind.SEPARATION,
            ir_kind=SoftwareVerificationIRKind.SEPARATION,
            property_name="frame",
            view_name="separation",
            notation_name="separation_surface",
            encoding_name="smtlib2",
            evidence_name="model",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
            result_authority=ResultAuthority.SATISFIABILITY,
            translation_edge_id="separation_to_smt",
            translation_family="program",
            compiler_id="separation.heap.smtlib2",
            result_kind="satisfiability.unsat",
            statement="Preserve frame formula outside the command footprint.",
            target_text="(assert (not frame_preserved))",
            result_output="unsat",
            features=("software_verification.separation", "separation_logic.ir"),
            assumption_ids=(
                "assumption:heap_as_array",
                "assumption:locations_disjoint",
            ),
            notes="Heap/resource loss remains explicit on the translation edge.",
        ),
        ObligationRouteDescriptor(
            kind=SoftwareVerificationObligationKind.CONCURRENCY,
            ir_kind=SoftwareVerificationIRKind.CONCURRENCY,
            property_name="rely_guarantee",
            view_name="source",
            notation_name="concurrency_ir",
            encoding_name="smtlib2",
            evidence_name="bounded",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.MODEL_CHECK,
            translation_edge_id="concurrency_to_bounded_smt",
            translation_family="state_temporal",
            compiler_id="concurrency.rg.bounded_smt",
            result_kind="model_check.satisfied",
            statement="Check rely/guarantee under explicit interference and fairness.",
            target_text="(assert (not rely_guarantee))",
            result_output="unsat",
            features=("software_verification.concurrency", "concurrency.ir"),
            assumption_ids=(
                "assumption:interference_declared",
                "assumption:weak_fairness",
                "bound:interleavings",
            ),
        ),
        ObligationRouteDescriptor(
            kind=SoftwareVerificationObligationKind.REFINEMENT,
            ir_kind=SoftwareVerificationIRKind.REFINEMENT,
            property_name="forward_simulation",
            view_name="source",
            notation_name="refinement_ir",
            encoding_name="smtlib2",
            evidence_name="bounded",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.MODEL_CHECK,
            translation_edge_id="refinement_forward_to_bounded_smt",
            translation_family="state_temporal",
            compiler_id="refinement.forward.bounded_smt",
            result_kind="model_check.satisfied",
            statement="Check forward simulation under declared step/state bounds.",
            target_text="(assert (not forward_simulation))",
            result_output="unsat",
            features=("software_verification.refinement", "refinement.ir"),
            assumption_ids=(
                "assumption:refinement_direction_forward",
                "bound:refinement_steps",
            ),
            notes="Refinement direction cannot be omitted.",
        ),
        ObligationRouteDescriptor(
            kind=SoftwareVerificationObligationKind.TEMPORAL,
            ir_kind=SoftwareVerificationIRKind.TEMPORAL,
            property_name="safety",
            view_name="source",
            notation_name="ltl_surface",
            encoding_name="smtlib2",
            evidence_name="trace",
            provider_name="runtime_mtl",
            authority_ceiling=RequestAuthorityCeiling.FINITE_TRACE,
            result_authority=ResultAuthority.MONITOR,
            translation_edge_id="temporal_mtl_to_runtime_mtl",
            translation_family="state_temporal",
            compiler_id="temporal.mtl.runtime",
            result_kind="monitor.satisfied",
            statement="Monitor finite-trace temporal safety property.",
            target_text="G ready",
            result_output="satisfied",
            features=("software_verification.temporal", "temporal.formula"),
            assumption_ids=("assumption:finite_trace", "bound:trace_length"),
        ),
        ObligationRouteDescriptor(
            kind=SoftwareVerificationObligationKind.COUNTEREXAMPLE,
            ir_kind=SoftwareVerificationIRKind.VC,
            property_name="counterexample",
            view_name="verification_condition",
            notation_name="vc_surface",
            encoding_name="smtlib2",
            evidence_name="model",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
            result_authority=ResultAuthority.SATISFIABILITY,
            translation_edge_id="vc_to_smt",
            translation_family="program",
            compiler_id="program.vc.counterexample",
            result_kind="satisfiability.sat",
            statement="Replay a source-bound counterexample model for a violated VC.",
            target_text="(assert (not vc_goal))",
            result_output="sat\n((x 0))",
            features=(
                "software_verification.vc",
                "program.verification_condition",
            ),
            assumption_ids=("assumption:model_is_counterexample",),
            notes="Counterexample replay remains bound to exact request digests.",
        ),
        ObligationRouteDescriptor(
            kind=SoftwareVerificationObligationKind.KERNEL_TARGET,
            ir_kind=SoftwareVerificationIRKind.VC,
            property_name="theorem",
            view_name="verification_condition",
            notation_name="target_theory",
            encoding_name="lean4",
            evidence_name="candidate",
            provider_name="lean",
            authority_ceiling=RequestAuthorityCeiling.CANDIDATE,
            result_authority=ResultAuthority.CANDIDATE,
            translation_edge_id="target_theory_to_lean",
            translation_family="kernel_target",
            compiler_id="kernel.target.lean",
            result_kind="candidate.theorem",
            statement=(
                "Compile controlled target theory to Lean as a candidate until "
                "official kernel acceptance."
            ),
            target_text="theorem candidate : True := by trivial",
            result_output="candidate",
            features=(
                "software_verification.vc",
                "program.verification_condition",
            ),
            assumption_ids=(
                "assumption:official_kernel_sole_authority",
                "assumption:candidate_until_acceptance",
            ),
            notes="Kernel targets remain candidates until official acceptance.",
        ),
    )
    return MappingProxyType({item.kind: item for item in rows})


# ---------------------------------------------------------------------------
# Lineage records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedOriginLineage:
    """Exact source and typed-expression identity for one obligation."""

    document_id: str
    source_digest: str
    expression_id: str
    expression_digest: str
    domain_slice_id: str
    domain_slice_digest: str
    ir_kind: str
    source_range: SourceRange | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "domain_slice_digest": self.domain_slice_digest,
            "domain_slice_id": self.domain_slice_id,
            "expression_digest": self.expression_digest,
            "expression_id": self.expression_id,
            "ir_kind": self.ir_kind,
            "source_digest": self.source_digest,
            "source_range": None
            if self.source_range is None
            else self.source_range.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SemanticsLineage:
    """Typed semantic namespaces for one obligation."""

    family: str
    profile: str
    property: str
    view: str
    notation: str
    features: tuple[str, ...]
    assumption_ids: tuple[str, ...]
    statement: str
    domain: str = DOMAIN_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "domain": self.domain,
            "family": self.family,
            "features": list(self.features),
            "notation": self.notation,
            "profile": self.profile,
            "property": self.property,
            "statement": self.statement,
            "view": self.view,
        }


@dataclass(frozen=True, slots=True)
class TranslationLineage:
    """Reviewed translation edge binding for one obligation."""

    edge_id: str
    family_key: str
    source_family_id: str
    target_family_id: str
    preservation: str
    authority_ceiling: str
    compiler_id: str
    content_id: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "compiler_id": self.compiler_id,
            "content_id": self.content_id,
            "description": self.description,
            "edge_id": self.edge_id,
            "family_key": self.family_key,
            "preservation": self.preservation,
            "source_family_id": self.source_family_id,
            "target_family_id": self.target_family_id,
        }


@dataclass(frozen=True, slots=True)
class RequestLineage:
    """BackendRequest@2 / LogicObligation@2 identities."""

    obligation_id: str
    obligation_digest: str
    request_id: str
    request_digest: str
    encoding: str
    evidence_kind: str
    provider: str
    authority_ceiling: str
    bounds: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "bounds": dict(self.bounds),
            "encoding": self.encoding,
            "evidence_kind": self.evidence_kind,
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "provider": self.provider,
            "request_digest": self.request_digest,
            "request_id": self.request_id,
        }


@dataclass(frozen=True, slots=True)
class ResultLineage:
    """Compiled/parsed result identities and authority."""

    compiled_artifact_id: str
    compiled_artifact_digest: str
    parsed_artifact_id: str
    parsed_artifact_digest: str
    result_kind: str
    result_authority: str
    output_digest: str
    result_digest: str
    decoded_evidence_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiled_artifact_digest": self.compiled_artifact_digest,
            "compiled_artifact_id": self.compiled_artifact_id,
            "decoded_evidence_digest": self.decoded_evidence_digest,
            "output_digest": self.output_digest,
            "parsed_artifact_digest": self.parsed_artifact_digest,
            "parsed_artifact_id": self.parsed_artifact_id,
            "result_authority": self.result_authority,
            "result_digest": self.result_digest,
            "result_kind": self.result_kind,
        }


@dataclass(frozen=True, slots=True)
class ReplayLineage:
    """Execution and evidence-replay receipt identities."""

    execution_receipt_id: str
    execution_receipt_digest: str
    replay_receipt_id: str
    replay_receipt_digest: str
    record_kind: str
    disposition: str
    replay_claimed: bool
    match_digest: str
    launch_id: str
    tool_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition,
            "execution_receipt_digest": self.execution_receipt_digest,
            "execution_receipt_id": self.execution_receipt_id,
            "launch_id": self.launch_id,
            "match_digest": self.match_digest,
            "record_kind": self.record_kind,
            "replay_claimed": self.replay_claimed,
            "replay_receipt_digest": self.replay_receipt_digest,
            "replay_receipt_id": self.replay_receipt_id,
            "tool_id": self.tool_id,
        }


@dataclass(frozen=True, slots=True)
class AuthorityStage:
    """One stage in the ordered authority lineage chain."""

    stage: str
    identity: str
    digest: str
    authority_ceiling: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "digest": self.digest,
            "identity": self.identity,
            "stage": self.stage,
        }


@dataclass(frozen=True, slots=True)
class AuthorityLineage:
    """Ordered authority chain from origin through replay."""

    stages: tuple[AuthorityStage, ...]
    terminal_authority: str
    never_upgrades: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "never_upgrades": self.never_upgrades,
            "stages": [item.to_dict() for item in self.stages],
            "terminal_authority": self.terminal_authority,
        }


@dataclass(frozen=True, slots=True)
class ObligationLineageBundle:
    """Complete end-to-end lineage for one supported obligation."""

    obligation_kind: SoftwareVerificationObligationKind | str
    typed_origin: TypedOriginLineage
    semantics: SemanticsLineage
    translation: TranslationLineage
    request: RequestLineage
    result: ResultLineage
    replay: ReplayLineage
    authority_lineage: AuthorityLineage
    domain_slice: DomainLogicSliceV2
    obligation: LogicObligationV2
    backend_request: BackendRequestV2
    compiled: CompiledLogicArtifact
    parsed: ParsedTargetArtifact
    execution: ProviderExecutionReceiptV2
    replay_receipt: EvidenceReplayReceipt
    expression: TypedExpression
    document: SourceDocument
    content_digest: str = ""
    schema_version: str = OBLIGATION_LINEAGE_SCHEMA
    notes: str = ""

    interface: ClassVar[str] = SOFTWARE_VERIFICATION_LOGIC_SLICE_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.obligation_kind, SoftwareVerificationObligationKind):
            object.__setattr__(
                self,
                "obligation_kind",
                SoftwareVerificationObligationKind(self.obligation_kind),
            )
        if self.schema_version != OBLIGATION_LINEAGE_SCHEMA:
            raise ObligationLineageError(
                f"unsupported obligation lineage schema {self.schema_version!r}"
            )
        missing = [
            stage
            for stage in LINEAGE_STAGES
            if getattr(self, stage if stage != "typed_origin" else "typed_origin")
            is None
        ]
        if missing:
            raise ObligationLineageError(
                f"obligation lineage missing stages: {', '.join(missing)}"
            )
        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            if self.content_digest != content:
                raise ObligationLineageError(
                    "content_digest does not match obligation lineage payload"
                )
            object.__setattr__(self, "content_digest", self.content_digest)
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "authority_lineage": self.authority_lineage.to_dict(),
            "interface": self.interface,
            "notes": self.notes,
            "obligation_kind": self.obligation_kind.value,
            "replay": self.replay.to_dict(),
            "request": self.request.to_dict(),
            "result": self.result.to_dict(),
            "schema_version": self.schema_version,
            "semantics": self.semantics.to_dict(),
            "translation": self.translation.to_dict(),
            "typed_origin": self.typed_origin.to_dict(),
        }

    def require_complete_lineage(self) -> "ObligationLineageBundle":
        """Fail closed when any required lineage stage is empty or unbound."""

        stages = {
            "typed_origin": self.typed_origin,
            "semantics": self.semantics,
            "translation": self.translation,
            "request": self.request,
            "result": self.result,
            "replay": self.replay,
            "authority_lineage": self.authority_lineage,
        }
        for name, value in stages.items():
            if value is None:
                raise ObligationLineageError(f"missing lineage stage {name!r}")
        if not self.typed_origin.source_digest or not self.typed_origin.expression_digest:
            raise ObligationLineageError(
                "typed origin requires source_digest and expression_digest"
            )
        if not self.translation.edge_id or not self.translation.content_id:
            raise ObligationLineageError(
                "translation lineage requires edge_id and content_id"
            )
        if not self.request.request_digest or not self.request.obligation_digest:
            raise ObligationLineageError(
                "request lineage requires request and obligation digests"
            )
        if not self.result.parsed_artifact_digest:
            raise ObligationLineageError(
                "result lineage requires parsed artifact digest"
            )
        if not self.replay.replay_receipt_digest:
            raise ObligationLineageError(
                "replay lineage requires replay receipt digest"
            )
        if len(self.authority_lineage.stages) < len(LINEAGE_STAGES):
            raise ObligationLineageError(
                "authority lineage must cover every required stage"
            )
        stage_names = tuple(item.stage for item in self.authority_lineage.stages)
        for required in LINEAGE_STAGES:
            if required not in stage_names:
                raise ObligationLineageError(
                    f"authority lineage missing stage {required!r}"
                )
        # Source → request → result digests must remain coherent.
        if self.backend_request.source_digest != self.typed_origin.source_digest:
            raise ObligationLineageError(
                "backend request source_digest diverged from typed origin"
            )
        if self.backend_request.expression_digest != self.typed_origin.expression_digest:
            raise ObligationLineageError(
                "backend request expression_digest diverged from typed origin"
            )
        if self.execution.request_digest != self.backend_request.content_digest:
            raise ObligationLineageError(
                "execution receipt request_digest diverged from backend request"
            )
        if self.replay_receipt.execution_receipt_digest != self.execution.content_digest:
            raise ObligationLineageError(
                "replay receipt is not bound to the execution receipt"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["domain_slice_id"] = self.domain_slice.slice_id
        payload["expression_id"] = self.expression.expression_id
        payload["request_id"] = self.backend_request.request_id
        return payload


@dataclass(frozen=True, slots=True)
class SoftwareVerificationLogicSlice:
    """Compose base software-verification obligations end to end.

    Interface: ``SoftwareVerificationLogicSlice@2``.
    """

    INTERFACE: ClassVar[str] = SOFTWARE_VERIFICATION_LOGIC_SLICE_INTERFACE
    VERSION: ClassVar[str] = SOFTWARE_VERIFICATION_LOGIC_SLICE_VERSION
    SCHEMA_VERSION: ClassVar[str] = SOFTWARE_VERIFICATION_LOGIC_SLICE_SCHEMA

    routes: Mapping[
        SoftwareVerificationObligationKind, ObligationRouteDescriptor
    ] = field(default_factory=default_obligation_routes)
    translation_graph: LogicTranslationGraph | None = None
    bounds: RequestBounds | None = None

    def __post_init__(self) -> None:
        routes = dict(self.routes)
        expected = set(SUPPORTED_OBLIGATION_KINDS)
        known = set(routes)
        if known != expected:
            missing = sorted(item.value for item in expected - known)
            extra = sorted(
                item.value
                if isinstance(item, SoftwareVerificationObligationKind)
                else str(item)
                for item in known - expected
            )
            raise SoftwareVerificationSliceError(
                f"route table must cover every supported obligation; "
                f"missing={missing} extra={extra}"
            )
        object.__setattr__(self, "routes", MappingProxyType(routes))
        if self.bounds is None:
            object.__setattr__(self, "bounds", RequestBounds.default())
        # translation_graph is optional; family-specific builders resolve edges.

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def domain_id(self) -> str:
        return DOMAIN_ID

    def supported_obligation_kinds(self) -> tuple[str, ...]:
        return tuple(item.value for item in SUPPORTED_OBLIGATION_KINDS)

    def deferred_obligation_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(DEFERRED_OBLIGATION_KINDS))

    def route_for(
        self, kind: SoftwareVerificationObligationKind | str
    ) -> ObligationRouteDescriptor:
        resolved = self._coerce_kind(kind)
        try:
            return self.routes[resolved]
        except KeyError as error:
            raise UnsupportedObligationError(
                f"unsupported obligation kind {resolved.value!r}"
            ) from error

    def connect_obligation(
        self,
        kind: SoftwareVerificationObligationKind | str,
        *,
        source_text: str | None = None,
    ) -> ObligationLineageBundle:
        """Connect one supported obligation through the full lineage chain."""

        resolved = self._coerce_kind(kind)
        if resolved.value in DEFERRED_OBLIGATION_KINDS:
            raise UnsupportedObligationError(
                f"obligation {resolved.value!r} is deferred to LFP2-044 "
                "(session/process overlays)"
            )
        route = self.route_for(resolved)
        text = source_text or self._default_source_text(route)
        document = SourceDocument.from_text(
            f"doc:sv:{resolved.value}",
            text,
            encoding="utf-8",
        )
        ir_routes = default_ir_routes()
        ir_route = ir_routes[route.ir_kind]
        expression = self._build_expression(route, ir_route, document)
        source_range = SourceRange(start=0, end=document.byte_length)
        domain_slice = DomainLogicSliceV2.from_typed_expression(
            expression,
            slice_id=f"slice:sv:{resolved.value}",
            domain=DOMAIN_ID,
            document_id=document.document_id,
            source_digest=document.content_digest,
            property=property_id(route.property_name),
            view=view_id(route.view_name),
            notation=notation_id(route.notation_name),
            source_range=source_range,
            features=route.features or ir_route.features,
            assumption_ids=route.assumption_ids,
            metadata={
                "obligation_kind": resolved.value,
                "slice_interface": self.INTERFACE,
            },
        )
        domain_slice.require_admitted()
        domain_slice.validate_against(document=document, expression=expression)

        translation = self._resolve_translation(route)
        bounds = self.bounds if self.bounds is not None else RequestBounds.default()
        obligation = LogicObligationV2.from_slice(
            domain_slice,
            obligation_id=f"obl:sv:{resolved.value}",
            statement=route.statement,
            encoding=encoding_id(route.encoding_name),
            evidence_kind=evidence_id(route.evidence_name),
            bounds=bounds,
            authority_ceiling=route.authority_ceiling,
            metadata={
                "obligation_kind": resolved.value,
                "translation_edge_id": route.translation_edge_id,
            },
        )
        request = BackendRequestV2.from_obligation(
            obligation,
            request_id=f"req:sv:{resolved.value}",
            requested_provider=provider_id(route.provider_name),
            metadata={
                "obligation_kind": resolved.value,
                "hermetic": True,
            },
        )
        source_map = SourceMap(
            map_id=f"map:sv:{resolved.value}",
            document_id=document.document_id,
            entries=(
                SourceMapEntry(
                    entry_id=f"map:entry:sv:{resolved.value}",
                    range=source_range,
                    role="obligation",
                ),
            ),
        )
        compiled = admit_compiled_target(
            request,
            artifact_id=f"compiled:sv:{resolved.value}",
            compiler_id=route.compiler_id,
            target_text=route.target_text,
            source_map=source_map,
            assumption_ids=route.assumption_ids,
            loss_ids=self._loss_ids_for(route),
            toolchain_id=f"toolchain:hermetic:{route.provider_name}",
            metadata={"hermetic_fixture": True, "obligation_kind": resolved.value},
        )
        evidence_digest = content_sha256(
            canonical_json_bytes(
                {
                    "kind": resolved.value,
                    "output": route.result_output,
                    "request_digest": request.content_digest,
                }
            )
        )
        parsed = admit_parsed_result(
            compiled,
            artifact_id=f"parsed:sv:{resolved.value}",
            provider=provider_id(route.provider_name),
            result_kind=route.result_kind,
            output_text=route.result_output,
            decoded_evidence_digest=evidence_digest,
            evidence_kind=evidence_id(route.evidence_name),
            metadata={"hermetic_fixture": True},
        )
        execution = ProviderExecutionReceiptV2.from_parsed_target(
            parsed,
            receipt_id=f"exec:sv:{resolved.value}",
            launch_id=f"launch:hermetic:{route.provider_name}:{resolved.value}",
            tool_id=f"tool:hermetic:{route.provider_name}",
            bounds=bounds,
            record_kind=ExecutionRecordKind.HERMETIC_FIXTURE,
            execution_claimed=True,
            outcome=ExecutionOutcome.SUCCEEDED,
            exit_code=0,
            duration_ms=1,
            toolchain_id=f"toolchain:hermetic:{route.provider_name}",
            metadata={"hermetic_fixture": True},
        )
        match_digest = content_sha256(
            canonical_json_bytes(
                {
                    "execution_digest": execution.content_digest,
                    "output_digest": parsed.output_digest,
                    "result_digest": parsed.result_digest,
                }
            )
        )
        replay_receipt = EvidenceReplayReceipt.from_execution(
            execution,
            receipt_id=f"replay:sv:{resolved.value}",
            disposition=ReplayDisposition.REPLAYED,
            replay_claimed=True,
            match_digest=match_digest,
            decoded_evidence_digest=parsed.decoded_evidence_digest,
            reason="hermetic fixture replay matched execution identities",
            metadata={"hermetic_fixture": True},
        )

        typed_origin = TypedOriginLineage(
            document_id=document.document_id,
            source_digest=document.content_digest,
            expression_id=expression.expression_id,
            expression_digest=expression.content_digest,
            domain_slice_id=domain_slice.slice_id,
            domain_slice_digest=domain_slice.content_digest,
            ir_kind=route.ir_kind.value,
            source_range=source_range,
        )
        semantics = SemanticsLineage(
            family=_identity_value(domain_slice.family),
            profile=_identity_value(domain_slice.profile),
            property=_identity_value(domain_slice.property),
            view=_identity_value(domain_slice.view),
            notation=_identity_value(domain_slice.notation),
            features=tuple(domain_slice.features),
            assumption_ids=tuple(domain_slice.assumption_ids),
            statement=route.statement,
        )
        request_lineage = RequestLineage(
            obligation_id=obligation.obligation_id,
            obligation_digest=obligation.content_digest,
            request_id=request.request_id,
            request_digest=request.content_digest,
            encoding=_identity_value(request.encoding),
            evidence_kind=_identity_value(request.evidence_kind),
            provider=route.provider_name,
            authority_ceiling=route.authority_ceiling.value,
            bounds={
                "timeout_ms": bounds.timeout_ms,
                "max_steps": bounds.max_steps,
                "max_memory_bytes": bounds.max_memory_bytes,
                "max_output_bytes": bounds.max_output_bytes,
            },
        )
        result_lineage = ResultLineage(
            compiled_artifact_id=compiled.artifact_id,
            compiled_artifact_digest=compiled.content_digest,
            parsed_artifact_id=parsed.artifact_id,
            parsed_artifact_digest=parsed.content_digest,
            result_kind=route.result_kind,
            result_authority=route.result_authority.value,
            output_digest=parsed.output_digest,
            result_digest=parsed.result_digest,
            decoded_evidence_digest=parsed.decoded_evidence_digest,
        )
        replay_lineage = ReplayLineage(
            execution_receipt_id=execution.receipt_id,
            execution_receipt_digest=execution.content_digest,
            replay_receipt_id=replay_receipt.receipt_id,
            replay_receipt_digest=replay_receipt.content_digest,
            record_kind=ExecutionRecordKind.HERMETIC_FIXTURE.value,
            disposition=ReplayDisposition.REPLAYED.value,
            replay_claimed=True,
            match_digest=match_digest,
            launch_id=execution.launch_id,
            tool_id=execution.tool_id,
        )
        translation_digest = (
            translation.content_id
            if _is_sha256_hex(translation.content_id)
            else content_sha256(
                translation.content_id.encode("utf-8", errors="surrogatepass")
            )
        )
        authority = AuthorityLineage(
            stages=(
                AuthorityStage(
                    "typed_origin",
                    domain_slice.slice_id,
                    domain_slice.content_digest,
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "semantics",
                    f"semantics:{resolved.value}",
                    content_sha256(canonical_json_bytes(semantics.to_dict())),
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "translation",
                    translation.edge_id,
                    translation_digest,
                    translation.authority_ceiling,
                ),
                AuthorityStage(
                    "request",
                    request.request_id,
                    request.content_digest,
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "result",
                    parsed.artifact_id,
                    parsed.content_digest,
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "replay",
                    replay_receipt.receipt_id,
                    replay_receipt.content_digest,
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "authority_lineage",
                    f"authority:{resolved.value}",
                    content_sha256(
                        canonical_json_bytes(
                            {
                                "kind": resolved.value,
                                "terminal": route.authority_ceiling.value,
                            }
                        )
                    ),
                    route.authority_ceiling.value,
                ),
            ),
            terminal_authority=route.authority_ceiling.value,
            never_upgrades=True,
        )

        bundle = ObligationLineageBundle(
            obligation_kind=resolved,
            typed_origin=typed_origin,
            semantics=semantics,
            translation=translation,
            request=request_lineage,
            result=result_lineage,
            replay=replay_lineage,
            authority_lineage=authority,
            domain_slice=domain_slice,
            obligation=obligation,
            backend_request=request,
            compiled=compiled,
            parsed=parsed,
            execution=execution,
            replay_receipt=replay_receipt,
            expression=expression,
            document=document,
            notes=route.notes,
        )
        return bundle.require_complete_lineage()

    def connect_all(
        self,
        kinds: Sequence[SoftwareVerificationObligationKind | str] | None = None,
    ) -> tuple[ObligationLineageBundle, ...]:
        """Connect every supported obligation (or an explicit subset)."""

        if kinds is None:
            selected = SUPPORTED_OBLIGATION_KINDS
        else:
            selected = tuple(self._coerce_kind(item) for item in kinds)
        return tuple(self.connect_obligation(kind) for kind in selected)

    def validate_all(
        self,
        bundles: Sequence[ObligationLineageBundle] | None = None,
    ) -> Mapping[str, str]:
        """Validate complete lineage for each supported obligation.

        Returns a mapping of obligation kind → content digest.
        """

        items = bundles if bundles is not None else self.connect_all()
        seen: set[str] = set()
        digests: dict[str, str] = {}
        for bundle in items:
            complete = bundle.require_complete_lineage()
            kind = complete.obligation_kind.value
            if kind in seen:
                raise ObligationLineageError(
                    f"duplicate obligation kind in validation set: {kind}"
                )
            seen.add(kind)
            digests[kind] = complete.content_digest
        missing = [
            kind.value
            for kind in SUPPORTED_OBLIGATION_KINDS
            if kind.value not in digests
        ]
        if bundles is None and missing:
            raise ObligationLineageError(
                f"validation set missing supported obligations: {', '.join(missing)}"
            )
        return MappingProxyType(digests)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deferred_obligation_kinds": list(self.deferred_obligation_kinds()),
            "domain_id": self.domain_id,
            "interface": self.INTERFACE,
            "schema_version": self.SCHEMA_VERSION,
            "supported_obligation_kinds": list(self.supported_obligation_kinds()),
            "version": self.VERSION,
            "weakens_to_free_form": False,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _coerce_kind(
        self, kind: SoftwareVerificationObligationKind | str
    ) -> SoftwareVerificationObligationKind:
        if isinstance(kind, SoftwareVerificationObligationKind):
            return kind
        token = str(kind).strip()
        if token in DEFERRED_OBLIGATION_KINDS:
            raise UnsupportedObligationError(
                f"obligation {token!r} is deferred to LFP2-044 "
                "(session/process overlays)"
            )
        try:
            return SoftwareVerificationObligationKind(token)
        except ValueError as error:
            raise UnsupportedObligationError(
                f"unsupported obligation kind {token!r}; supported="
                f"{list(self.supported_obligation_kinds())}"
            ) from error

    def _default_source_text(self, route: ObligationRouteDescriptor) -> str:
        return (
            f"# software_verification obligation: {route.kind.value}\n"
            f"# family route: {route.ir_kind.value}\n"
            f"# statement: {route.statement}\n"
            f"obligation {route.kind.value} {{\n"
            f"  property = {route.property_name};\n"
            f"  edge = {route.translation_edge_id};\n"
            f"}}\n"
        )

    def _build_expression(
        self,
        route: ObligationRouteDescriptor,
        ir_route: Any,
        document: SourceDocument,
    ) -> TypedExpression:
        """Build a typed-expression origin bound to the IR route namespaces."""

        signature = LogicSignature(
            signature_id=f"sig:sv:slice:{route.kind.value}",
            family=ir_route.family_id,
            profile=ir_route.profile_id,
            sorts=(),
            symbols=(),
            features=route.features or ir_route.features,
            metadata={
                "bridge": SoftwareVerificationSyntaxBridge.INTERFACE,
                "domain": DOMAIN_ID,
                "kind": route.ir_kind.value,
                "slice": self.INTERFACE,
            },
        )
        payload = {
            "bridge_interface": SoftwareVerificationSyntaxBridge.INTERFACE,
            "domain": DOMAIN_ID,
            "domain_schema": ir_route.domain_schema,
            "kind": route.ir_kind.value,
            "obligation_kind": route.kind.value,
            "schema_version": ir_route.payload_schema,
            "slice_interface": self.INTERFACE,
            "source_digest": document.content_digest,
            "source_document_id": document.document_id,
            "statement": route.statement,
            "view_role": ir_route.view_role,
        }
        root = mk_extension(
            f"node:sv:slice:{route.kind.value}",
            family=ir_route.family_id,
            profile=ir_route.profile_id,
            features=route.features or ir_route.features,
            payload_schema=ir_route.payload_schema,
            payload=payload,
            children=(),
        )
        return TypedExpression(
            expression_id=f"expr:sv:slice:{route.kind.value}",
            root=root,
            signature=signature,
            family=ir_route.family_id,
            profile=ir_route.profile_id,
            range=SourceRange(start=0, end=document.byte_length),
            elaborate_on_init=False,
            metadata={
                "domain": DOMAIN_ID,
                "obligation_kind": route.kind.value,
                "slice": self.INTERFACE,
            },
        )

    def _resolve_translation(
        self, route: ObligationRouteDescriptor
    ) -> TranslationLineage:
        edge_id = route.translation_edge_id
        family_key = route.translation_family
        edge = self._lookup_translation_edge(edge_id, family_key)
        contract = getattr(edge, "contract", None)
        if contract is None:
            raise ObligationLineageError(
                f"translation edge {edge_id!r} lacks a TranslationContract"
            )
        source_family = getattr(contract.source, "family_id", "") or ""
        target_family = getattr(contract.target, "family_id", "") or ""
        preservation = contract.preservation
        preservation_value = (
            preservation.value if hasattr(preservation, "value") else str(preservation)
        )
        authority = contract.authority_ceiling
        authority_value = (
            authority.value if hasattr(authority, "value") else str(authority)
        )
        content_id = (
            getattr(edge, "content_id", None)
            or getattr(edge, "edge_content_id", None)
            or getattr(contract, "contract_content_id", None)
            or getattr(contract, "content_id", None)
            or edge_id
        )
        if callable(content_id):
            content_id = content_id()
        compiler = route.compiler_id
        identities = getattr(contract, "identities", None)
        if identities is not None:
            compiler = (
                getattr(identities, "compiler_identity", None)
                or getattr(identities, "compiler_id", None)
                or compiler
            )
        return TranslationLineage(
            edge_id=edge_id,
            family_key=family_key,
            source_family_id=str(source_family),
            target_family_id=str(target_family),
            preservation=preservation_value,
            authority_ceiling=authority_value,
            compiler_id=str(compiler),
            content_id=str(content_id),
            description=str(getattr(contract, "description", "") or route.notes),
        )

    def _lookup_translation_edge(self, edge_id: str, family_key: str) -> Any:
        # Prefer family-specific builders so edge ids resolve without relying
        # on private graph layout details.
        if family_key == "program":
            for edge in build_program_translation_edges():
                if edge.edge_id == edge_id:
                    return edge
        if family_key == "state_temporal":
            catalog = build_state_temporal_edges()
            for edge in catalog.edges:
                if edge.edge_id == edge_id:
                    return edge
        if family_key == "kernel_target":
            for edge in build_kernel_target_translation_edges():
                if edge.edge_id == edge_id:
                    return edge
        # Optional fallback: scan a pre-built composed graph when supplied.
        graph = self.translation_graph
        if graph is None:
            try:
                graph = build_logic_translation_graph()
            except Exception:
                graph = None
        if graph is not None:
            contracts = getattr(graph, "contracts", ()) or ()
            if callable(contracts):
                contracts = contracts()
            for contract in contracts:
                contract_id = getattr(contract, "contract_id", None)
                if contract_id == edge_id:
                    return type(
                        "EdgeProxy",
                        (),
                        {
                            "edge_id": edge_id,
                            "contract": contract,
                            "content_id": getattr(
                                contract, "contract_content_id", edge_id
                            ),
                        },
                    )()
        raise ObligationLineageError(
            f"translation edge {edge_id!r} not found in family {family_key!r}"
        )

    def _loss_ids_for(self, route: ObligationRouteDescriptor) -> tuple[str, ...]:
        if route.kind is SoftwareVerificationObligationKind.SEPARATION:
            return (
                "loss.heap_as_array",
                "loss.sep_conj_to_and",
            )
        if route.kind is SoftwareVerificationObligationKind.KERNEL_TARGET:
            return (
                "loss.candidate_until_kernel_acceptance",
                "loss.trust_escape_rejected",
            )
        if route.kind is SoftwareVerificationObligationKind.REFINEMENT:
            return ("loss.bounded_refinement",)
        if route.kind is SoftwareVerificationObligationKind.CONCURRENCY:
            return ("loss.bounded_interleaving",)
        if route.kind is SoftwareVerificationObligationKind.TEMPORAL:
            return ("loss.finite_trace",)
        return ()


def _identity_value(identity: LogicIdentity | Mapping[str, Any] | str | Any) -> str:
    if isinstance(identity, LogicIdentity):
        return identity.value
    if isinstance(identity, Mapping):
        return str(identity.get("value") or identity.get("id") or "")
    if hasattr(identity, "value") and not isinstance(identity, str):
        return str(getattr(identity, "value"))
    return str(identity)


def _is_sha256_hex(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def connect_software_verification_obligation(
    kind: SoftwareVerificationObligationKind | str,
    *,
    source_text: str | None = None,
) -> ObligationLineageBundle:
    """Module-level helper for :meth:`SoftwareVerificationLogicSlice.connect_obligation`."""

    return SoftwareVerificationLogicSlice().connect_obligation(
        kind, source_text=source_text
    )


def connect_all_software_verification_obligations() -> tuple[
    ObligationLineageBundle, ...
]:
    """Connect every supported base obligation end to end."""

    return SoftwareVerificationLogicSlice().connect_all()


def validate_software_verification_slice() -> Mapping[str, str]:
    """Validate complete lineage for every supported obligation."""

    return SoftwareVerificationLogicSlice().validate_all()


__all__ = [
    "DOMAIN_ID",
    "DEFERRED_OBLIGATION_KINDS",
    "LINEAGE_STAGES",
    "OBLIGATION_LINEAGE_SCHEMA",
    "SOFTWARE_VERIFICATION_LOGIC_SLICE_INTERFACE",
    "SOFTWARE_VERIFICATION_LOGIC_SLICE_SCHEMA",
    "SOFTWARE_VERIFICATION_LOGIC_SLICE_VERSION",
    "SUPPORTED_OBLIGATION_KINDS",
    "AuthorityLineage",
    "AuthorityStage",
    "ObligationLineageBundle",
    "ObligationLineageError",
    "ObligationRouteDescriptor",
    "ReplayLineage",
    "RequestLineage",
    "ResultLineage",
    "SemanticsLineage",
    "SoftwareVerificationLogicSlice",
    "SoftwareVerificationObligationKind",
    "SoftwareVerificationSliceError",
    "TranslationLineage",
    "TypedOriginLineage",
    "UnsupportedObligationError",
    "connect_all_software_verification_obligations",
    "connect_software_verification_obligation",
    "default_obligation_routes",
    "validate_software_verification_slice",
]
