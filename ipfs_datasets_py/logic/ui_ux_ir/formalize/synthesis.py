"""Constrained Intent/IDL formal-to-UI synthesis (UIR-027).

``UISynthesizer@1`` emits *bounded UI/UX IR candidates* from stable program
and interface references plus reviewed formal constraints.

Design invariants (fail-closed):

- A deterministic template baseline works without any model or network.
- Optional learned/retrieved providers are injectable and lazy; their outputs
  remain candidates and never auto-admit.
- Every candidate is validated through schema, source, policy, formal
  coverage, accessibility, and capability gates.
- Missing or ambiguous semantics produce clarification requirements or fail
  closed rather than inventing grants, proofs, or execution authority.
- Generation alone never confers proof, policy, delegation, or execution
  authority (``AuthorityKind.SYNTHESIS_CANDIDATE`` only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping, Protocol, Sequence

from ..model.bindings import (
    ConfirmationClass,
    RiskClass,
    UIActionBinding,
    UIProgramRef,
    validate_action_binding,
)
from ..model.modality import (
    CANONICAL_CAPABILITIES,
    CANONICAL_INPUT_CAPABILITIES,
    CANONICAL_OUTPUT_CAPABILITIES,
)
from ..schema import (
    AuthorityKind,
    CompositionEdgeKind,
    LayoutRegionKind,
    ProgramBindingTargetKind,
    ReviewStatus,
    TerminalOutcomeKind,
    UIAccessibilityBinding,
    UIComponent,
    UICompositionEdge,
    UIDeviceCapabilityRequirement,
    UIFormalConstraintRef,
    UIIRDocument,
    UIIRValidationError,
    UILayoutRegion,
    UILocalizationBinding,
    UIMCPIDLBinding,
    UIModalityAlternative,
    UIModalityRequirement,
    UIProducer,
    UIProgramBinding,
    UIReviewBinding,
    UISourceRef,
    UITerminalOutcome,
    UITrustBinding,
    UIUXTask,
    validate_ui_ir,
)
from .contracts import CoverageDisposition, FormalView, ResultAuthority

UI_SYNTHESIZER_INTERFACE: Final = "UISynthesizer@1"
UI_SYNTHESIZER_ID: Final = "ui-ux-ir/synthesizer@1"
UI_SYNTHESIS_RESULT_SCHEMA: Final = "ui-synthesis-result/v1"
UI_SYNTHESIS_CANDIDATE_SCHEMA: Final = "ui-synthesis-candidate/v1"
UI_SYNTHESIS_ADMISSION_RECEIPT_SCHEMA: Final = "ui-synthesis-admission-receipt/v1"
TEMPLATE_PROVIDER_ID: Final = "deterministic.template@1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

# Authority surfaces generation must never invent or elevate.
_FORBIDDEN_AUTHORITY_KEYS: Final = frozenset(
    {
        "authority_grant",
        "capability_token",
        "delegation",
        "delegation_grant",
        "execution_grant",
        "grant",
        "grants",
        "permission_elevation",
        "role_grant",
        "ucan",
        "ucan_token",
    }
)

# Authority kinds that synthesis may *never* claim.
_FORBIDDEN_CLAIMED_AUTHORITIES: Final = frozenset(
    {
        AuthorityKind.PROOF,
        AuthorityKind.POLICY,
        AuthorityKind.INVOCATION,
        AuthorityKind.SATISFIABILITY,
        AuthorityKind.MONITOR,
        AuthorityKind.CONFORMANCE,
    }
)

DEFAULT_INPUT_CAPABILITIES: Final = (
    "pointer_mouse",
    "keyboard",
)
DEFAULT_OUTPUT_CAPABILITIES: Final = (
    "display",
)
DEFAULT_INPUT_ALTERNATIVE: Final = ("speech",)
DEFAULT_OUTPUT_ALTERNATIVE: Final = ("speech_output",)


class SynthesisProviderKind(str, Enum):
    """How a candidate was produced."""

    DETERMINISTIC_TEMPLATE = "deterministic_template"
    LEARNED = "learned"
    RETRIEVED = "retrieved"
    EXTERNAL = "external"


class AdmissionGate(str, Enum):
    """Deterministic admission gates for synthesis candidates."""

    SCHEMA = "schema"
    SOURCE = "source"
    POLICY = "policy"
    FORMAL_COVERAGE = "formal_coverage"
    ACCESSIBILITY = "accessibility"
    CAPABILITY = "capability"


class AdmissionDisposition(str, Enum):
    """Outcome of one admission gate."""

    PASS = "pass"
    FAIL = "fail"
    CLARIFY = "clarify"


class ClarificationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ReviewedFormalConstraint:
    """Reviewed formal constraint supplied to synthesis (not a proof result)."""

    constraint_id: str
    view: FormalView | str
    formula_ref: str
    coverage: CoverageDisposition = CoverageDisposition.FULL
    source_ref_ids: tuple[str, ...] = ()
    required: bool = True
    notes: str = ""

    def view_token(self) -> str:
        if isinstance(self.view, FormalView):
            return self.view.value
        return str(self.view)


@dataclass(frozen=True, slots=True)
class SynthesisProgramSeed:
    """Stable program/interface reference seed for template synthesis."""

    action_id: str
    program_ref: UIProgramRef
    risk_class: RiskClass = RiskClass.LOW
    confirmation_class: ConfirmationClass = ConfirmationClass.NONE
    binding_id: str = ""
    label: str = ""
    source_ref_ids: tuple[str, ...] = ()
    formal_constraint_ids: tuple[str, ...] = ()
    role: str = "button"

    def resolved_binding_id(self) -> str:
        return self.binding_id or f"bind:synth:{self.action_id}"


@dataclass(frozen=True, slots=True)
class SynthesisInputs:
    """Bounded inputs for formal-to-UI synthesis.

    Accepts stable program seeds and/or already-validated action bindings from
    Intent/IDL adapters. Does not execute Intent procedures or MCP methods.
    """

    document_id: str = "ui:synth:candidate"
    title: str = "Synthesized UI candidate"
    sources: tuple[UISourceRef, ...] = ()
    program_seeds: tuple[SynthesisProgramSeed, ...] = ()
    action_bindings: tuple[UIActionBinding, ...] = ()
    # Optional pre-built fragments (must still pass admission).
    localization: tuple[UILocalizationBinding, ...] = ()
    required_input_capabilities: tuple[str, ...] = DEFAULT_INPUT_CAPABILITIES
    required_output_capabilities: tuple[str, ...] = DEFAULT_OUTPUT_CAPABILITIES
    alternative_input_capabilities: tuple[str, ...] = DEFAULT_INPUT_ALTERNATIVE
    alternative_output_capabilities: tuple[str, ...] = DEFAULT_OUTPUT_ALTERNATIVE
    tags: tuple[str, ...] = ("synthesis", "candidate")
    # Opaque provenance notes (never authority).
    provenance_notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SynthesisPolicy:
    """Reviewed policy that admits or rejects synthesis candidates."""

    policy_id: str = "ui-synthesis/default"
    max_components: int = 64
    max_actions: int = 32
    max_candidates: int = 8
    require_accessibility: bool = True
    require_formal_coverage: bool = True
    require_capability_coverage: bool = True
    require_source_grounding: bool = True
    require_modality_alternatives: bool = True
    allow_learned_providers: bool = True
    min_confidence: float = 0.0
    max_confidence: float = 1.0
    # Hard-locked: generation never elevates these.
    allow_proof_authority: bool = False
    allow_policy_authority: bool = False
    allow_delegation_authority: bool = False
    allow_execution_authority: bool = False

    def __post_init__(self) -> None:
        # Force non-elevation even if a caller attempts to enable it.
        object.__setattr__(self, "allow_proof_authority", False)
        object.__setattr__(self, "allow_policy_authority", False)
        object.__setattr__(self, "allow_delegation_authority", False)
        object.__setattr__(self, "allow_execution_authority", False)
        if self.max_components < 1:
            raise UIIRValidationError("SynthesisPolicy.max_components must be >= 1")
        if self.max_actions < 1:
            raise UIIRValidationError("SynthesisPolicy.max_actions must be >= 1")
        if self.max_candidates < 1:
            raise UIIRValidationError("SynthesisPolicy.max_candidates must be >= 1")
        if not (0.0 <= self.min_confidence <= self.max_confidence <= 1.0):
            raise UIIRValidationError(
                "SynthesisPolicy confidence bounds must satisfy "
                "0 <= min_confidence <= max_confidence <= 1"
            )


@dataclass(frozen=True, slots=True)
class SynthesisClarification:
    """Clarification required before a unique admitted candidate exists."""

    code: str
    message: str
    related_symbols: tuple[str, ...] = ()
    severity: ClarificationSeverity = ClarificationSeverity.WARNING
    gate: AdmissionGate | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "gate": self.gate.value if self.gate is not None else "",
            "message": self.message,
            "related_symbols": list(self.related_symbols),
            "severity": self.severity.value,
        }


@dataclass(frozen=True, slots=True)
class GateResult:
    """Outcome of one admission gate for one candidate."""

    gate: AdmissionGate
    disposition: AdmissionDisposition
    details: str
    counterexamples: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.disposition is AdmissionDisposition.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "counterexamples": list(self.counterexamples),
            "details": self.details,
            "disposition": self.disposition.value,
            "gate": self.gate.value,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class FormalCoverageItem:
    """Coverage disposition for one synthesized semantic."""

    semantic_id: str
    kind: str  # component | action | constraint | modality
    disposition: CoverageDisposition
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "kind": self.kind,
            "notes": self.notes,
            "semantic_id": self.semantic_id,
        }


@dataclass(frozen=True, slots=True)
class SynthesisAdmissionReceipt:
    """Immutable receipt that generation did not confer elevated authority."""

    receipt_id: str
    candidate_id: str
    admitted: bool
    gates: tuple[GateResult, ...]
    authority_kind: AuthorityKind = AuthorityKind.SYNTHESIS_CANDIDATE
    result_authority: ResultAuthority = ResultAuthority.NONE
    claims_proof: bool = False
    claims_policy_authority: bool = False
    claims_delegation: bool = False
    claims_execution: bool = False
    rejected_authority_claims: tuple[str, ...] = ()
    formal_coverage: tuple[FormalCoverageItem, ...] = ()
    clarifications: tuple[SynthesisClarification, ...] = ()
    notes: str = ""
    schema_version: str = UI_SYNTHESIS_ADMISSION_RECEIPT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "authority_kind": self.authority_kind.value,
            "candidate_id": self.candidate_id,
            "claims_delegation": self.claims_delegation,
            "claims_execution": self.claims_execution,
            "claims_policy_authority": self.claims_policy_authority,
            "claims_proof": self.claims_proof,
            "clarifications": [item.to_dict() for item in self.clarifications],
            "formal_coverage": [item.to_dict() for item in self.formal_coverage],
            "gates": [gate.to_dict() for gate in self.gates],
            "notes": self.notes,
            "receipt_id": self.receipt_id,
            "rejected_authority_claims": list(self.rejected_authority_claims),
            "result_authority": self.result_authority.value,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class UISynthesisCandidate:
    """One generated UI/UX IR candidate with provenance and confidence.

    Authority is always ``synthesis_candidate``. Admission is a separate
    deterministic decision recorded on the receipt.
    """

    candidate_id: str
    document: UIIRDocument
    provider_id: str
    provider_kind: SynthesisProviderKind
    confidence: float
    provenance: tuple[str, ...] = ()
    ambiguity: tuple[str, ...] = ()
    formal_coverage: tuple[FormalCoverageItem, ...] = ()
    admission: SynthesisAdmissionReceipt | None = None
    authority_kind: AuthorityKind = AuthorityKind.SYNTHESIS_CANDIDATE
    result_authority: ResultAuthority = ResultAuthority.NONE
    schema_version: str = UI_SYNTHESIS_CANDIDATE_SCHEMA

    def __post_init__(self) -> None:
        # Hard-lock candidate-only authority.
        object.__setattr__(
            self, "authority_kind", AuthorityKind.SYNTHESIS_CANDIDATE
        )
        object.__setattr__(self, "result_authority", ResultAuthority.NONE)
        if not (0.0 <= self.confidence <= 1.0):
            raise UIIRValidationError(
                "UISynthesisCandidate.confidence must be in [0, 1]"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission": self.admission.to_dict() if self.admission else None,
            "ambiguity": list(self.ambiguity),
            "authority_kind": self.authority_kind.value,
            "candidate_id": self.candidate_id,
            "confidence": self.confidence,
            "document_id": self.document.document_id,
            "formal_coverage": [item.to_dict() for item in self.formal_coverage],
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind.value,
            "provenance": list(self.provenance),
            "result_authority": self.result_authority.value,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class UISynthesisResult:
    """Aggregate synthesis result: candidates, admissions, clarifications."""

    result_id: str
    policy_id: str
    candidates: tuple[UISynthesisCandidate, ...]
    admitted_candidate_ids: tuple[str, ...]
    rejected_candidate_ids: tuple[str, ...]
    clarifications: tuple[SynthesisClarification, ...]
    template_provider_id: str = TEMPLATE_PROVIDER_ID
    synthesizer_id: str = UI_SYNTHESIZER_ID
    interface: str = UI_SYNTHESIZER_INTERFACE
    schema_version: str = UI_SYNTHESIS_RESULT_SCHEMA
    # Hard exclusions: generation never produces these authorities.
    denied_authorities: tuple[str, ...] = (
        "proof",
        "policy",
        "delegation",
        "execution",
    )
    result_authority: ResultAuthority = ResultAuthority.NONE
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_authority", ResultAuthority.NONE)

    @property
    def admitted_candidates(self) -> tuple[UISynthesisCandidate, ...]:
        admitted = set(self.admitted_candidate_ids)
        return tuple(c for c in self.candidates if c.candidate_id in admitted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_candidate_ids": list(self.admitted_candidate_ids),
            "candidates": [item.to_dict() for item in self.candidates],
            "clarifications": [item.to_dict() for item in self.clarifications],
            "denied_authorities": list(self.denied_authorities),
            "interface": self.interface,
            "notes": self.notes,
            "policy_id": self.policy_id,
            "rejected_candidate_ids": list(self.rejected_candidate_ids),
            "result_authority": self.result_authority.value,
            "result_id": self.result_id,
            "schema_version": self.schema_version,
            "synthesizer_id": self.synthesizer_id,
            "template_provider_id": self.template_provider_id,
        }


@dataclass(frozen=True, slots=True)
class ExternalCandidateDraft:
    """Optional external/learned draft; still requires full admission."""

    draft_id: str
    document: UIIRDocument
    provider_id: str
    provider_kind: SynthesisProviderKind = SynthesisProviderKind.EXTERNAL
    confidence: float = 0.5
    provenance: tuple[str, ...] = ()
    ambiguity: tuple[str, ...] = ()


class LearnedCandidateProvider(Protocol):
    """Optional lazy provider of learned/retrieved drafts.

    Implementations must not be imported or invoked unless injected by the
    caller. Provider output is candidate-only.
    """

    def propose(
        self,
        inputs: SynthesisInputs,
        constraints: Sequence[ReviewedFormalConstraint],
        policy: SynthesisPolicy,
    ) -> Sequence[ExternalCandidateDraft]:
        """Return zero or more untrusted drafts (never admitted by default)."""


def _stable_id(*parts: str) -> str:
    cleaned = [
        re.sub(r"[^A-Za-z0-9._:/-]+", "_", part.strip().replace(" ", "_"))
        for part in parts
        if part and str(part).strip()
    ]
    if not cleaned:
        raise UIIRValidationError("Cannot build empty stable identifier")
    candidate = ":".join(cleaned)
    if not _IDENTIFIER_RE.fullmatch(candidate):
        candidate = f"id:{candidate}"
        candidate = re.sub(r"[^A-Za-z0-9._:/-]+", "_", candidate)
    if not _IDENTIFIER_RE.fullmatch(candidate):
        raise UIIRValidationError(f"Cannot stabilize identifier from parts {parts!r}")
    return candidate


def _default_source() -> UISourceRef:
    return UISourceRef(
        ref_id="source:synthesis:template",
        source_uri="ui-ux-ir://synthesis/deterministic-template",
        source_id="synthesis-template",
        source_revision="v1",
        content_sha256="c" * 64,
        review_status=ReviewStatus.MACHINE_EXTRACTED,
    )


def _normalize_seeds(
    inputs: SynthesisInputs,
) -> tuple[tuple[SynthesisProgramSeed, ...], tuple[SynthesisClarification, ...]]:
    """Merge program seeds and action bindings into ordered seeds."""

    clarifications: list[SynthesisClarification] = []
    seeds: list[SynthesisProgramSeed] = list(inputs.program_seeds)

    for binding in inputs.action_bindings:
        try:
            validate_action_binding(binding)
        except UIIRValidationError as exc:
            clarifications.append(
                SynthesisClarification(
                    code="seed.invalid_binding",
                    message=str(exc),
                    related_symbols=(binding.binding_id, binding.action_id),
                    severity=ClarificationSeverity.ERROR,
                )
            )
            continue
        seeds.append(
            SynthesisProgramSeed(
                action_id=binding.action_id,
                program_ref=binding.program_ref,
                risk_class=binding.risk_class,
                confirmation_class=binding.confirmation_class,
                binding_id=binding.binding_id,
                source_ref_ids=binding.source_ref_ids,
                formal_constraint_ids=binding.formal_constraint_ids,
                label=binding.action_id,
            )
        )

    if not seeds:
        clarifications.append(
            SynthesisClarification(
                code="seed.missing_actions",
                message=(
                    "No program seeds or action bindings provided; "
                    "template cannot invent executable actions"
                ),
                severity=ClarificationSeverity.ERROR,
            )
        )
    return tuple(seeds), tuple(clarifications)


def _sources_for_inputs(inputs: SynthesisInputs) -> tuple[UISourceRef, ...]:
    if inputs.sources:
        return inputs.sources
    return (_default_source(),)


def _source_ids(sources: Sequence[UISourceRef]) -> frozenset[str]:
    return frozenset(source.ref_id for source in sources)


def _primary_source_ids(
    seed: SynthesisProgramSeed,
    known: frozenset[str],
    fallback: Sequence[str],
) -> tuple[str, ...]:
    if seed.source_ref_ids:
        resolved = tuple(ref for ref in seed.source_ref_ids if ref in known)
        if resolved:
            return resolved
    return tuple(fallback)


def build_template_document(
    inputs: SynthesisInputs,
    constraints: Sequence[ReviewedFormalConstraint] = (),
    *,
    candidate_suffix: str = "template",
) -> tuple[UIIRDocument, tuple[FormalCoverageItem, ...], tuple[SynthesisClarification, ...]]:
    """Deterministic template baseline: Intent/IDL seeds → candidate UIIRDocument.

    No model is required. Missing actions or sources yield clarifications; the
    builder never invents authority grants or proof results.
    """

    clarifications: list[SynthesisClarification] = []
    seeds, seed_clarifications = _normalize_seeds(inputs)
    clarifications.extend(seed_clarifications)

    sources = _sources_for_inputs(inputs)
    known_sources = _source_ids(sources)
    fallback_source_ids = tuple(sorted(known_sources))[:1] or (
        _default_source().ref_id,
    )
    if not inputs.sources:
        clarifications.append(
            SynthesisClarification(
                code="source.defaulted",
                message=(
                    "No sources supplied; using synthesis template source with "
                    "machine_extracted review status"
                ),
                related_symbols=(fallback_source_ids[0],),
                severity=ClarificationSeverity.INFO,
                gate=AdmissionGate.SOURCE,
            )
        )

    document_id = _stable_id(inputs.document_id, candidate_suffix)
    root_id = _stable_id("component", document_id, "root")
    coverage: list[FormalCoverageItem] = []

    formal_refs: list[UIFormalConstraintRef] = []
    constraint_by_id: dict[str, ReviewedFormalConstraint] = {}
    for constraint in constraints:
        if not constraint.constraint_id.strip():
            clarifications.append(
                SynthesisClarification(
                    code="constraint.empty_id",
                    message="Reviewed formal constraint missing constraint_id",
                    severity=ClarificationSeverity.ERROR,
                    gate=AdmissionGate.FORMAL_COVERAGE,
                )
            )
            continue
        if constraint.constraint_id in constraint_by_id:
            clarifications.append(
                SynthesisClarification(
                    code="constraint.duplicate",
                    message=f"Duplicate formal constraint {constraint.constraint_id!r}",
                    related_symbols=(constraint.constraint_id,),
                    severity=ClarificationSeverity.ERROR,
                    gate=AdmissionGate.FORMAL_COVERAGE,
                )
            )
            continue
        constraint_by_id[constraint.constraint_id] = constraint
        src_ids = tuple(
            ref for ref in constraint.source_ref_ids if ref in known_sources
        ) or fallback_source_ids
        formal_refs.append(
            UIFormalConstraintRef(
                constraint_id=constraint.constraint_id,
                view=constraint.view_token(),
                formula_ref=constraint.formula_ref,
                source_ref_ids=src_ids,
            )
        )
        coverage.append(
            FormalCoverageItem(
                semantic_id=constraint.constraint_id,
                kind="constraint",
                disposition=constraint.coverage,
                notes=constraint.notes or "reviewed formal constraint input",
            )
        )

    required_constraint_ids = {
        c.constraint_id
        for c in constraint_by_id.values()
        if c.required and c.coverage is not CoverageDisposition.OUT_OF_SCOPE
    }

    components: list[UIComponent] = []
    edges: list[UICompositionEdge] = []
    program_bindings: list[UIProgramBinding] = []
    mcp_bindings: list[UIMCPIDLBinding] = []
    accessibility: list[UIAccessibilityBinding] = []
    localization: list[UILocalizationBinding] = list(inputs.localization)
    action_component_ids: list[str] = []
    all_program_ids: list[str] = []

    for index, seed in enumerate(seeds):
        try:
            seed.program_ref.validate()
        except UIIRValidationError as exc:
            clarifications.append(
                SynthesisClarification(
                    code="seed.invalid_program_ref",
                    message=str(exc),
                    related_symbols=(seed.action_id,),
                    severity=ClarificationSeverity.ERROR,
                    gate=AdmissionGate.SCHEMA,
                )
            )
            continue

        src_ids = _primary_source_ids(seed, known_sources, fallback_source_ids)
        if seed.source_ref_ids and not any(
            ref in known_sources for ref in seed.source_ref_ids
        ):
            clarifications.append(
                SynthesisClarification(
                    code="source.unresolved",
                    message=(
                        f"Action {seed.action_id!r} source_ref_ids do not resolve "
                        "to known sources"
                    ),
                    related_symbols=(seed.action_id, *seed.source_ref_ids),
                    severity=ClarificationSeverity.ERROR,
                    gate=AdmissionGate.SOURCE,
                )
            )

        binding_id = seed.resolved_binding_id()
        if not _IDENTIFIER_RE.fullmatch(binding_id):
            binding_id = _stable_id("bind", document_id, seed.action_id)

        # High-risk actions require confirmation; never invent grants.
        confirmation = seed.confirmation_class
        if seed.risk_class in {RiskClass.HIGH, RiskClass.DESTRUCTIVE}:
            if confirmation is ConfirmationClass.NONE:
                confirmation = ConfirmationClass.CONFIRM
                clarifications.append(
                    SynthesisClarification(
                        code="policy.confirmation_inferred",
                        message=(
                            f"Action {seed.action_id!r} risk {seed.risk_class.value} "
                            "requires confirmation; template set confirmation=confirm"
                        ),
                        related_symbols=(seed.action_id,),
                        severity=ClarificationSeverity.INFO,
                        gate=AdmissionGate.POLICY,
                    )
                )

        program_bindings.append(
            UIProgramBinding(
                binding_id=binding_id,
                target_kind=seed.program_ref.target_kind,
                target_ref=seed.program_ref.target_ref(),
                risk_class=seed.risk_class.value,
                confirmation_class=confirmation.value,
                source_ref_ids=src_ids,
            )
        )
        all_program_ids.append(binding_id)

        if seed.program_ref.target_kind is ProgramBindingTargetKind.MCP_IDL:
            mcp_bindings.append(
                UIMCPIDLBinding(
                    binding_id=_stable_id("mcp", binding_id),
                    interface_cid=seed.program_ref.mcp_idl_interface_cid,
                    method_name=seed.program_ref.mcp_idl_method_name,
                    argument_schema_ref=seed.program_ref.mcp_idl_argument_schema_ref,
                    result_schema_ref=seed.program_ref.mcp_idl_result_schema_ref,
                    source_ref_ids=src_ids,
                )
            )

        component_id = _stable_id("component", document_id, seed.action_id)
        action_component_ids.append(component_id)
        label = seed.label or seed.action_id
        loc_id = _stable_id("loc", document_id, seed.action_id)
        msg_id = _stable_id("msg", document_id, seed.action_id)
        if not any(item.localization_id == loc_id for item in localization):
            localization.append(
                UILocalizationBinding(
                    localization_id=loc_id,
                    message_id=msg_id,
                    default_text=label.replace("_", " ").replace(":", " "),
                    source_ref_ids=src_ids,
                )
            )

        components.append(
            UIComponent(
                component_id=component_id,
                role=seed.role or "button",
                purpose=f"Invoke action {seed.action_id}",
                accessible_name_ref=loc_id,
                parent_id=root_id,
                program_binding_ids=(binding_id,),
                presentation_classification="interactive",
                source_ref_ids=src_ids,
            )
        )
        edges.append(
            UICompositionEdge(
                edge_id=_stable_id("edge", root_id, component_id),
                kind=CompositionEdgeKind.CHILD,
                source_component_id=root_id,
                target_component_id=component_id,
                source_ref_ids=src_ids,
            )
        )
        accessibility.append(
            UIAccessibilityBinding(
                accessibility_id=_stable_id("a11y", component_id),
                component_id=component_id,
                role=seed.role or "button",
                name_ref=loc_id,
                source_ref_ids=src_ids,
            )
        )

        # Formal coverage for the action: link reviewed constraints when present.
        linked = tuple(
            cid
            for cid in seed.formal_constraint_ids
            if cid in constraint_by_id
        )
        if linked:
            disposition = CoverageDisposition.FULL
            notes = f"linked formal constraints: {', '.join(linked)}"
            required_constraint_ids.difference_update(linked)
        elif constraint_by_id:
            disposition = CoverageDisposition.PARTIAL
            notes = "action present; no explicit formal constraint link"
            clarifications.append(
                SynthesisClarification(
                    code="formal.partial_action",
                    message=(
                        f"Action {seed.action_id!r} has no linked formal constraint; "
                        "coverage is partial"
                    ),
                    related_symbols=(seed.action_id,),
                    severity=ClarificationSeverity.WARNING,
                    gate=AdmissionGate.FORMAL_COVERAGE,
                )
            )
        else:
            disposition = CoverageDisposition.EXPLICIT_UNSUPPORTED
            notes = "no reviewed formal constraints supplied for synthesis"
        coverage.append(
            FormalCoverageItem(
                semantic_id=seed.action_id,
                kind="action",
                disposition=disposition,
                notes=notes,
            )
        )

    if not action_component_ids:
        # Fail-closed empty shell: still emit a root so schema can diagnose.
        clarifications.append(
            SynthesisClarification(
                code="template.no_actions",
                message="Template produced no action components",
                severity=ClarificationSeverity.ERROR,
            )
        )

    root_sources = fallback_source_ids
    components.insert(
        0,
        UIComponent(
            component_id=root_id,
            role="form",
            purpose=inputs.title or "Synthesized interaction surface",
            accessible_name_ref=_stable_id("loc", document_id, "root"),
            child_ids=tuple(action_component_ids),
            program_binding_ids=tuple(all_program_ids),
            presentation_classification="structure",
            source_ref_ids=root_sources,
        ),
    )
    root_loc_id = _stable_id("loc", document_id, "root")
    if not any(item.localization_id == root_loc_id for item in localization):
        localization.append(
            UILocalizationBinding(
                localization_id=root_loc_id,
                message_id=_stable_id("msg", document_id, "root"),
                default_text=inputs.title,
                source_ref_ids=root_sources,
            )
        )
    accessibility.insert(
        0,
        UIAccessibilityBinding(
            accessibility_id=_stable_id("a11y", root_id),
            component_id=root_id,
            role="form",
            name_ref=root_loc_id,
            source_ref_ids=root_sources,
        ),
    )
    coverage.append(
        FormalCoverageItem(
            semantic_id=root_id,
            kind="component",
            disposition=(
                CoverageDisposition.FULL
                if action_component_ids
                else CoverageDisposition.PARTIAL
            ),
            notes="template root container",
        )
    )

    # Unlinked required constraints remain as explicit partial/unsupported.
    for constraint_id in sorted(required_constraint_ids):
        clarifications.append(
            SynthesisClarification(
                code="formal.unlinked_required",
                message=(
                    f"Required formal constraint {constraint_id!r} is not linked "
                    "to any synthesized action"
                ),
                related_symbols=(constraint_id,),
                severity=ClarificationSeverity.WARNING,
                gate=AdmissionGate.FORMAL_COVERAGE,
            )
        )

    region = UILayoutRegion(
        region_id=_stable_id("region", document_id, "main"),
        kind=LayoutRegionKind.STACK,
        component_ids=(root_id, *action_component_ids),
        source_ref_ids=root_sources,
    )

    input_caps = tuple(
        cap for cap in inputs.required_input_capabilities if cap.strip()
    ) or DEFAULT_INPUT_CAPABILITIES
    output_caps = tuple(
        cap for cap in inputs.required_output_capabilities if cap.strip()
    ) or DEFAULT_OUTPUT_CAPABILITIES
    alt_in = tuple(
        cap for cap in inputs.alternative_input_capabilities if cap.strip()
    ) or DEFAULT_INPUT_ALTERNATIVE
    alt_out = tuple(
        cap for cap in inputs.alternative_output_capabilities if cap.strip()
    ) or DEFAULT_OUTPUT_ALTERNATIVE

    input_req = UIModalityRequirement(
        requirement_id=_stable_id("mod", document_id, "input", "primary"),
        direction="input",
        capability_ids=input_caps,
        essential=True,
        source_ref_ids=root_sources,
    )
    input_alt_req = UIModalityRequirement(
        requirement_id=_stable_id("mod", document_id, "input", "alt"),
        direction="input",
        capability_ids=alt_in,
        essential=False,
        source_ref_ids=root_sources,
    )
    output_req = UIModalityRequirement(
        requirement_id=_stable_id("mod", document_id, "output", "primary"),
        direction="output",
        capability_ids=output_caps,
        essential=True,
        source_ref_ids=root_sources,
    )
    output_alt_req = UIModalityRequirement(
        requirement_id=_stable_id("mod", document_id, "output", "alt"),
        direction="output",
        capability_ids=alt_out,
        essential=False,
        source_ref_ids=root_sources,
    )
    modality_alts = (
        UIModalityAlternative(
            alternative_id=_stable_id("modalt", document_id, "input"),
            primary_requirement_id=input_req.requirement_id,
            alternative_requirement_id=input_alt_req.requirement_id,
            source_ref_ids=root_sources,
        ),
        UIModalityAlternative(
            alternative_id=_stable_id("modalt", document_id, "output"),
            primary_requirement_id=output_req.requirement_id,
            alternative_requirement_id=output_alt_req.requirement_id,
            source_ref_ids=root_sources,
        ),
    )
    device_req = UIDeviceCapabilityRequirement(
        requirement_id=_stable_id("devcap", document_id, "baseline"),
        capability_ids=tuple(sorted(set(input_caps) | set(output_caps))),
        source_ref_ids=root_sources,
    )
    coverage.append(
        FormalCoverageItem(
            semantic_id=device_req.requirement_id,
            kind="modality",
            disposition=CoverageDisposition.FULL,
            notes="template capability requirements",
        )
    )

    ux_tasks = (
        UIUXTask(
            task_id=_stable_id("task", document_id, "primary"),
            name=inputs.title,
            step_component_ids=tuple(action_component_ids) or (root_id,),
            source_ref_ids=root_sources,
        ),
    )

    terminals = (
        UITerminalOutcome(
            outcome_id=_stable_id("outcome", document_id, "success"),
            kind=TerminalOutcomeKind.SUCCESS,
            description="Primary task completed",
            source_ref_ids=root_sources,
        ),
        UITerminalOutcome(
            outcome_id=_stable_id("outcome", document_id, "failure"),
            kind=TerminalOutcomeKind.FAILURE,
            description="Primary task failed",
            source_ref_ids=root_sources,
        ),
    )

    # Candidate-only trust binding — never proof/policy/delegation/execution.
    trust = (
        UITrustBinding(
            trust_id=_stable_id("trust", document_id, "synthesis"),
            authority_kind=AuthorityKind.SYNTHESIS_CANDIDATE,
            subject_ref=document_id,
            source_ref_ids=root_sources,
        ),
    )

    document = UIIRDocument(
        document_id=document_id,
        title=inputs.title,
        sources=sources,
        components=tuple(components),
        entry_components=(root_id,),
        terminal_outcomes=terminals,
        tags=tuple(inputs.tags) + ("synthesis_candidate",),
        producer=UIProducer(
            producer_id="producer:ui-ux-ir-synthesizer",
            name="UI/UX IR deterministic template synthesizer",
            version="1",
        ),
        review=UIReviewBinding(
            review_status=ReviewStatus.MACHINE_EXTRACTED,
            reviewer="ui-ux-ir/synthesizer",
            notes="Candidate only; admission gates decide usability",
        ),
        trust_bindings=trust,
        composition_edges=tuple(edges),
        layout_regions=(region,),
        ux_tasks=ux_tasks,
        accessibility=tuple(accessibility),
        localization=tuple(localization),
        input_modality_requirements=(input_req, input_alt_req),
        output_modality_requirements=(output_req, output_alt_req),
        modality_alternatives=modality_alts,
        device_capability_requirements=(device_req,),
        program_bindings=tuple(program_bindings),
        mcp_idl_bindings=tuple(mcp_bindings),
        formal_constraint_refs=tuple(formal_refs),
        # Never mint proof obligations from generation alone.
        proof_obligation_refs=(),
    )

    return document, tuple(coverage), tuple(clarifications)


def _scan_forbidden_authority(payload: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_s = str(key)
            full = f"{path}/{key_s}" if path else key_s
            if key_s.lower() in _FORBIDDEN_AUTHORITY_KEYS:
                found.append(full)
            found.extend(_scan_forbidden_authority(value, full))
    elif isinstance(payload, Sequence) and not isinstance(
        payload, (str, bytes, bytearray)
    ):
        for index, item in enumerate(payload):
            found.extend(_scan_forbidden_authority(item, f"{path}[{index}]"))
    return found


def _gate_schema(document: UIIRDocument) -> GateResult:
    try:
        validate_ui_ir(document)
    except UIIRValidationError as exc:
        return GateResult(
            gate=AdmissionGate.SCHEMA,
            disposition=AdmissionDisposition.FAIL,
            details="schema validation failed",
            counterexamples=(str(exc),),
        )
    return GateResult(
        gate=AdmissionGate.SCHEMA,
        disposition=AdmissionDisposition.PASS,
        details="UIIRDocument validates against closed envelope contract",
    )


def _gate_source(
    document: UIIRDocument,
    policy: SynthesisPolicy,
) -> GateResult:
    if not policy.require_source_grounding:
        return GateResult(
            gate=AdmissionGate.SOURCE,
            disposition=AdmissionDisposition.PASS,
            details="source grounding not required by policy",
        )
    counterexamples: list[str] = []
    if not document.sources:
        counterexamples.append("sources.empty")
    known = {source.ref_id for source in document.sources}
    for component in document.components:
        for ref in component.source_ref_ids:
            if ref not in known:
                counterexamples.append(
                    f"component.source_unresolved:{component.component_id}:{ref}"
                )
        if not component.source_ref_ids:
            counterexamples.append(
                f"component.source_missing:{component.component_id}"
            )
    for binding in document.program_bindings:
        for ref in binding.source_ref_ids:
            if ref not in known:
                counterexamples.append(
                    f"program.source_unresolved:{binding.binding_id}:{ref}"
                )
    if counterexamples:
        return GateResult(
            gate=AdmissionGate.SOURCE,
            disposition=AdmissionDisposition.FAIL,
            details="source grounding incomplete",
            counterexamples=tuple(counterexamples),
        )
    return GateResult(
        gate=AdmissionGate.SOURCE,
        disposition=AdmissionDisposition.PASS,
        details=f"sources={len(document.sources)} grounded",
    )


def _gate_policy(
    document: UIIRDocument,
    policy: SynthesisPolicy,
    *,
    confidence: float,
) -> GateResult:
    counterexamples: list[str] = []
    if len(document.components) > policy.max_components:
        counterexamples.append(
            f"components.exceeded:{len(document.components)}>{policy.max_components}"
        )
    if not document.program_bindings:
        counterexamples.append("actions.empty")
    if len(document.program_bindings) > policy.max_actions:
        counterexamples.append(
            f"actions.exceeded:{len(document.program_bindings)}>{policy.max_actions}"
        )
    if confidence < policy.min_confidence or confidence > policy.max_confidence:
        counterexamples.append(
            f"confidence.out_of_bounds:{confidence}"
        )

    # High-risk bindings must retain confirmation.
    for binding in document.program_bindings:
        if binding.risk_class in {"high", "destructive"}:
            if binding.confirmation_class in {"", "none"}:
                counterexamples.append(
                    f"policy.confirmation_missing:{binding.binding_id}"
                )

    # Reject authority-bearing payload keys and forbidden trust claims.
    forbidden_paths = _scan_forbidden_authority(document.to_dict())
    counterexamples.extend(f"authority.key:{path}" for path in forbidden_paths)

    for trust in document.trust_bindings:
        if trust.authority_kind in _FORBIDDEN_CLAIMED_AUTHORITIES:
            counterexamples.append(
                f"trust.forbidden_authority:{trust.trust_id}:{trust.authority_kind.value}"
            )
        if trust.authority_kind is not AuthorityKind.SYNTHESIS_CANDIDATE:
            # Only synthesis_candidate is acceptable from generation.
            if trust.authority_kind not in {
                AuthorityKind.DECLARATION,
                AuthorityKind.INTERFACE,
                AuthorityKind.LEGACY_ALIAS,
            }:
                counterexamples.append(
                    f"trust.elevated:{trust.trust_id}:{trust.authority_kind.value}"
                )

    # Proof obligation refs with a prover claim are not allowed from generation.
    for obligation in document.proof_obligation_refs:
        if obligation.prover:
            counterexamples.append(
                f"proof.prover_claimed:{obligation.obligation_id}:{obligation.prover}"
            )

    if counterexamples:
        return GateResult(
            gate=AdmissionGate.POLICY,
            disposition=AdmissionDisposition.FAIL,
            details="policy gate rejected candidate",
            counterexamples=tuple(counterexamples),
        )
    return GateResult(
        gate=AdmissionGate.POLICY,
        disposition=AdmissionDisposition.PASS,
        details="policy bounds and non-elevation rules satisfied",
    )


def _gate_formal_coverage(
    document: UIIRDocument,
    coverage: Sequence[FormalCoverageItem],
    constraints: Sequence[ReviewedFormalConstraint],
    policy: SynthesisPolicy,
) -> GateResult:
    if not policy.require_formal_coverage:
        return GateResult(
            gate=AdmissionGate.FORMAL_COVERAGE,
            disposition=AdmissionDisposition.PASS,
            details="formal coverage not required by policy",
        )

    counterexamples: list[str] = []
    clarify = False
    coverage_by_id = {item.semantic_id: item for item in coverage}

    required = [
        c
        for c in constraints
        if c.required and c.coverage is not CoverageDisposition.OUT_OF_SCOPE
    ]
    if required:
        present_ids = {ref.constraint_id for ref in document.formal_constraint_refs}
        for constraint in required:
            if constraint.constraint_id not in present_ids:
                counterexamples.append(
                    f"formal.missing_ref:{constraint.constraint_id}"
                )
            item = coverage_by_id.get(constraint.constraint_id)
            if item is None:
                counterexamples.append(
                    f"formal.missing_coverage:{constraint.constraint_id}"
                )
            elif item.disposition in {
                CoverageDisposition.EXPLICIT_UNSUPPORTED,
                CoverageDisposition.LOSSY,
            }:
                counterexamples.append(
                    f"formal.unsupported:{constraint.constraint_id}:"
                    f"{item.disposition.value}"
                )

    # Every program binding must have a declared coverage disposition.
    action_coverage = [item for item in coverage if item.kind == "action"]
    if document.program_bindings and not action_coverage and not coverage:
        counterexamples.append("formal.coverage_empty")

    ordered_pairs: list[tuple[UIProgramBinding, FormalCoverageItem | None]] = []
    if action_coverage and len(action_coverage) == len(document.program_bindings):
        ordered_pairs = list(zip(document.program_bindings, action_coverage))
    else:
        for binding in document.program_bindings:
            matched = next(
                (
                    item
                    for item in action_coverage
                    if item.semantic_id == binding.binding_id
                    or item.semantic_id in binding.binding_id
                    or item.semantic_id in binding.target_ref
                ),
                action_coverage[0] if len(action_coverage) == 1 else None,
            )
            ordered_pairs.append((binding, matched))

    linked_full = 0
    for binding, matched in ordered_pairs:
        if matched is None:
            counterexamples.append(f"formal.action_uncovered:{binding.binding_id}")
            continue
        if matched.disposition is CoverageDisposition.FULL:
            linked_full += 1
        elif matched.disposition is CoverageDisposition.LOSSY and required:
            counterexamples.append(
                f"formal.action_lossy:{binding.binding_id}"
            )
        # PARTIAL / EXPLICIT_UNSUPPORTED on individual actions are honest
        # dispositions. They clarify only when required constraints exist and
        # *no* action carries full coverage (nothing is grounded).
        # EXPLICIT_UNSUPPORTED without required constraints passes (template
        # baseline without formal inputs).

    if required and document.program_bindings and linked_full == 0:
        clarify = True

    if counterexamples:
        return GateResult(
            gate=AdmissionGate.FORMAL_COVERAGE,
            disposition=AdmissionDisposition.FAIL,
            details="formal coverage incomplete",
            counterexamples=tuple(counterexamples),
        )
    if clarify:
        return GateResult(
            gate=AdmissionGate.FORMAL_COVERAGE,
            disposition=AdmissionDisposition.CLARIFY,
            details="formal coverage partial; clarification required",
            counterexamples=(),
        )
    return GateResult(
        gate=AdmissionGate.FORMAL_COVERAGE,
        disposition=AdmissionDisposition.PASS,
        details=f"coverage_items={len(coverage)}",
    )


def _gate_accessibility(
    document: UIIRDocument,
    policy: SynthesisPolicy,
) -> GateResult:
    if not policy.require_accessibility:
        return GateResult(
            gate=AdmissionGate.ACCESSIBILITY,
            disposition=AdmissionDisposition.PASS,
            details="accessibility not required by policy",
        )
    counterexamples: list[str] = []
    a11y_by_component = {
        item.component_id: item for item in document.accessibility
    }
    for component in document.components:
        interactive = component.presentation_classification in {
            "interactive",
            "structure",
        } or component.role in {"button", "link", "textbox", "form", "dialog"}
        if not interactive:
            continue
        binding = a11y_by_component.get(component.component_id)
        if binding is None:
            counterexamples.append(f"a11y.missing:{component.component_id}")
            continue
        if not binding.role:
            counterexamples.append(f"a11y.role_missing:{component.component_id}")
        if not binding.name_ref and not component.accessible_name_ref:
            counterexamples.append(f"a11y.name_missing:{component.component_id}")
    if counterexamples:
        return GateResult(
            gate=AdmissionGate.ACCESSIBILITY,
            disposition=AdmissionDisposition.FAIL,
            details="accessibility bindings incomplete",
            counterexamples=tuple(counterexamples),
        )
    return GateResult(
        gate=AdmissionGate.ACCESSIBILITY,
        disposition=AdmissionDisposition.PASS,
        details=f"accessibility_bindings={len(document.accessibility)}",
    )


def _gate_capability(
    document: UIIRDocument,
    policy: SynthesisPolicy,
) -> GateResult:
    if not policy.require_capability_coverage:
        return GateResult(
            gate=AdmissionGate.CAPABILITY,
            disposition=AdmissionDisposition.PASS,
            details="capability coverage not required by policy",
        )
    counterexamples: list[str] = []
    unknown: list[str] = []

    def _check_caps(caps: Sequence[str], label: str) -> None:
        for cap in caps:
            if cap not in CANONICAL_CAPABILITIES:
                unknown.append(f"{label}:{cap}")

    for req in document.input_modality_requirements:
        _check_caps(req.capability_ids, f"input:{req.requirement_id}")
        for cap in req.capability_ids:
            if cap not in CANONICAL_INPUT_CAPABILITIES:
                counterexamples.append(
                    f"capability.not_input:{req.requirement_id}:{cap}"
                )
    for req in document.output_modality_requirements:
        _check_caps(req.capability_ids, f"output:{req.requirement_id}")
        for cap in req.capability_ids:
            if cap not in CANONICAL_OUTPUT_CAPABILITIES:
                counterexamples.append(
                    f"capability.not_output:{req.requirement_id}:{cap}"
                )
    for req in document.device_capability_requirements:
        _check_caps(req.capability_ids, f"device:{req.requirement_id}")

    counterexamples.extend(f"capability.unknown:{item}" for item in unknown)

    if policy.require_modality_alternatives:
        essential_ids = {
            req.requirement_id
            for req in (
                *document.input_modality_requirements,
                *document.output_modality_requirements,
            )
            if req.essential
        }
        covered = {alt.primary_requirement_id for alt in document.modality_alternatives}
        for req_id in sorted(essential_ids - covered):
            counterexamples.append(f"capability.alternative_missing:{req_id}")

    if counterexamples:
        return GateResult(
            gate=AdmissionGate.CAPABILITY,
            disposition=AdmissionDisposition.FAIL,
            details="capability gate failed",
            counterexamples=tuple(counterexamples),
        )
    return GateResult(
        gate=AdmissionGate.CAPABILITY,
        disposition=AdmissionDisposition.PASS,
        details="canonical capabilities and alternatives satisfied",
    )


def admit_candidate(
    document: UIIRDocument,
    *,
    candidate_id: str,
    confidence: float,
    policy: SynthesisPolicy,
    constraints: Sequence[ReviewedFormalConstraint] = (),
    formal_coverage: Sequence[FormalCoverageItem] = (),
    extra_clarifications: Sequence[SynthesisClarification] = (),
) -> SynthesisAdmissionReceipt:
    """Run deterministic admission gates; never elevate authority."""

    gates = (
        _gate_schema(document),
        _gate_source(document, policy),
        _gate_policy(document, policy, confidence=confidence),
        _gate_formal_coverage(document, formal_coverage, constraints, policy),
        _gate_accessibility(document, policy),
        _gate_capability(document, policy),
    )

    clarifications = list(extra_clarifications)
    rejected_authority: list[str] = []

    # Record explicit non-claims.
    for gate in gates:
        if gate.gate is AdmissionGate.POLICY:
            for item in gate.counterexamples:
                if item.startswith("authority.") or item.startswith("trust.") or item.startswith("proof."):
                    rejected_authority.append(item)
        if gate.disposition is AdmissionDisposition.CLARIFY:
            clarifications.append(
                SynthesisClarification(
                    code=f"gate.clarify.{gate.gate.value}",
                    message=gate.details,
                    related_symbols=gate.counterexamples,
                    severity=ClarificationSeverity.WARNING,
                    gate=gate.gate,
                )
            )
        elif gate.disposition is AdmissionDisposition.FAIL:
            clarifications.append(
                SynthesisClarification(
                    code=f"gate.fail.{gate.gate.value}",
                    message=gate.details,
                    related_symbols=gate.counterexamples,
                    severity=ClarificationSeverity.ERROR,
                    gate=gate.gate,
                )
            )

    hard_fail = any(g.disposition is AdmissionDisposition.FAIL for g in gates)
    needs_clarify = any(
        g.disposition is AdmissionDisposition.CLARIFY for g in gates
    )
    # Clarify-only (no hard fail) is not admitted; missing semantics clarify.
    admitted = (not hard_fail) and (not needs_clarify)

    return SynthesisAdmissionReceipt(
        receipt_id=_stable_id("receipt", "admission", candidate_id),
        candidate_id=candidate_id,
        admitted=admitted,
        gates=gates,
        authority_kind=AuthorityKind.SYNTHESIS_CANDIDATE,
        result_authority=ResultAuthority.NONE,
        claims_proof=False,
        claims_policy_authority=False,
        claims_delegation=False,
        claims_execution=False,
        rejected_authority_claims=tuple(sorted(set(rejected_authority))),
        formal_coverage=tuple(formal_coverage),
        clarifications=tuple(clarifications),
        notes=(
            "admitted via deterministic gates"
            if admitted
            else (
                "clarification required before admission"
                if needs_clarify and not hard_fail
                else "admission failed"
            )
        ),
    )


def synthesize_template_candidate(
    inputs: SynthesisInputs,
    constraints: Sequence[ReviewedFormalConstraint] = (),
    policy: SynthesisPolicy | None = None,
) -> UISynthesisCandidate:
    """Build and admit the deterministic template candidate (no model)."""

    policy = policy or SynthesisPolicy()
    document, coverage, clarifications = build_template_document(
        inputs, constraints, candidate_suffix="template"
    )
    candidate_id = _stable_id("candidate", document.document_id)
    confidence = 1.0  # deterministic baseline
    admission = admit_candidate(
        document,
        candidate_id=candidate_id,
        confidence=confidence,
        policy=policy,
        constraints=constraints,
        formal_coverage=coverage,
        extra_clarifications=clarifications,
    )
    provenance = (
        f"provider:{TEMPLATE_PROVIDER_ID}",
        f"synthesizer:{UI_SYNTHESIZER_ID}",
        *inputs.provenance_notes,
    )
    return UISynthesisCandidate(
        candidate_id=candidate_id,
        document=document,
        provider_id=TEMPLATE_PROVIDER_ID,
        provider_kind=SynthesisProviderKind.DETERMINISTIC_TEMPLATE,
        confidence=confidence,
        provenance=provenance,
        ambiguity=tuple(
            c.code
            for c in clarifications
            if c.severity is not ClarificationSeverity.INFO
        ),
        formal_coverage=coverage,
        admission=admission,
    )


def _admit_external_draft(
    draft: ExternalCandidateDraft,
    *,
    policy: SynthesisPolicy,
    constraints: Sequence[ReviewedFormalConstraint],
) -> UISynthesisCandidate:
    """Admit an external/learned draft without elevating its authority."""

    if draft.provider_kind in {
        SynthesisProviderKind.LEARNED,
        SynthesisProviderKind.RETRIEVED,
    } and not policy.allow_learned_providers:
        # Still package the draft as a rejected candidate.
        coverage: tuple[FormalCoverageItem, ...] = ()
        admission = SynthesisAdmissionReceipt(
            receipt_id=_stable_id("receipt", "admission", draft.draft_id),
            candidate_id=draft.draft_id,
            admitted=False,
            gates=(
                GateResult(
                    gate=AdmissionGate.POLICY,
                    disposition=AdmissionDisposition.FAIL,
                    details="learned/retrieved providers disabled by policy",
                    counterexamples=("provider.disabled",),
                ),
            ),
            rejected_authority_claims=("provider.disabled",),
            notes="provider disabled",
        )
        return UISynthesisCandidate(
            candidate_id=draft.draft_id,
            document=draft.document,
            provider_id=draft.provider_id,
            provider_kind=draft.provider_kind,
            confidence=draft.confidence,
            provenance=draft.provenance,
            ambiguity=draft.ambiguity,
            formal_coverage=coverage,
            admission=admission,
        )

    # External drafts do not get free formal coverage credit.
    coverage = (
        FormalCoverageItem(
            semantic_id=draft.document.document_id,
            kind="component",
            disposition=CoverageDisposition.PARTIAL,
            notes="external draft; coverage inferred only via admission gates",
        ),
    )
    admission = admit_candidate(
        draft.document,
        candidate_id=draft.draft_id,
        confidence=draft.confidence,
        policy=policy,
        constraints=constraints,
        formal_coverage=coverage,
        extra_clarifications=tuple(
            SynthesisClarification(
                code="external.candidate",
                message=(
                    f"External provider {draft.provider_id!r} output remains "
                    "candidate-only until gates pass"
                ),
                related_symbols=(draft.draft_id,),
                severity=ClarificationSeverity.INFO,
            )
            for _ in (0,)
        ),
    )
    return UISynthesisCandidate(
        candidate_id=draft.draft_id,
        document=draft.document,
        provider_id=draft.provider_id,
        provider_kind=draft.provider_kind,
        confidence=draft.confidence,
        provenance=draft.provenance + (f"provider:{draft.provider_id}",),
        ambiguity=draft.ambiguity,
        formal_coverage=coverage,
        admission=admission,
    )


def synthesize_ui_ir(
    inputs: SynthesisInputs,
    constraints: Sequence[ReviewedFormalConstraint] = (),
    policy: SynthesisPolicy | None = None,
    *,
    learned_provider: LearnedCandidateProvider | None = None,
    external_drafts: Sequence[ExternalCandidateDraft] = (),
) -> UISynthesisResult:
    """Synthesize bounded UI/UX IR candidates and run admission gates.

    Always runs the deterministic template baseline. Optional learned providers
    are invoked only when explicitly injected; their outputs remain candidates.
    """

    policy = policy or SynthesisPolicy()
    if not inputs.document_id.strip():
        raise UIIRValidationError("SynthesisInputs.document_id must not be empty")

    candidates: list[UISynthesisCandidate] = []

    # 1. Deterministic template baseline (no model).
    template = synthesize_template_candidate(inputs, constraints, policy)
    candidates.append(template)

    # 2. Explicit external drafts (already in hand; still gated).
    for draft in external_drafts:
        candidates.append(
            _admit_external_draft(draft, policy=policy, constraints=constraints)
        )

    # 3. Optional learned provider — lazy, injectable only.
    if learned_provider is not None:
        if not policy.allow_learned_providers:
            # Do not call the provider when disabled.
            pass
        else:
            try:
                drafts = learned_provider.propose(inputs, constraints, policy)
            except Exception as exc:  # provider failures are non-fatal
                # Surface as clarification on the result, not an authority claim.
                drafts = ()
                candidates[0] = UISynthesisCandidate(
                    candidate_id=candidates[0].candidate_id,
                    document=candidates[0].document,
                    provider_id=candidates[0].provider_id,
                    provider_kind=candidates[0].provider_kind,
                    confidence=candidates[0].confidence,
                    provenance=candidates[0].provenance
                    + (f"learned_provider_error:{type(exc).__name__}",),
                    ambiguity=candidates[0].ambiguity + ("learned_provider_error",),
                    formal_coverage=candidates[0].formal_coverage,
                    admission=candidates[0].admission,
                )
            for draft in drafts:
                candidates.append(
                    _admit_external_draft(
                        draft, policy=policy, constraints=constraints
                    )
                )

    # Bound candidate count deterministically (template always retained first).
    if len(candidates) > policy.max_candidates:
        candidates = candidates[: policy.max_candidates]

    admitted_ids = [
        c.candidate_id
        for c in candidates
        if c.admission is not None and c.admission.admitted
    ]
    rejected_ids = [
        c.candidate_id
        for c in candidates
        if c.admission is None or not c.admission.admitted
    ]

    all_clarifications: list[SynthesisClarification] = []
    for candidate in candidates:
        if candidate.admission is not None:
            all_clarifications.extend(candidate.admission.clarifications)

    # Global invariant: no candidate may claim elevated authority.
    for candidate in candidates:
        if candidate.authority_kind is not AuthorityKind.SYNTHESIS_CANDIDATE:
            raise UIIRValidationError(
                f"Candidate {candidate.candidate_id!r} elevated authority_kind "
                f"to {candidate.authority_kind.value!r}"
            )
        if candidate.result_authority is not ResultAuthority.NONE:
            raise UIIRValidationError(
                f"Candidate {candidate.candidate_id!r} elevated result_authority "
                f"to {candidate.result_authority.value!r}"
            )
        if candidate.admission is not None and (
            candidate.admission.claims_proof
            or candidate.admission.claims_policy_authority
            or candidate.admission.claims_delegation
            or candidate.admission.claims_execution
        ):
            raise UIIRValidationError(
                f"Candidate {candidate.candidate_id!r} admission receipt claims "
                "proof/policy/delegation/execution authority"
            )

    result_id = _stable_id("synth", inputs.document_id)
    return UISynthesisResult(
        result_id=result_id,
        policy_id=policy.policy_id,
        candidates=tuple(candidates),
        admitted_candidate_ids=tuple(admitted_ids),
        rejected_candidate_ids=tuple(rejected_ids),
        clarifications=tuple(all_clarifications),
        notes=(
            f"template={TEMPLATE_PROVIDER_ID}; "
            f"admitted={len(admitted_ids)}; rejected={len(rejected_ids)}"
        ),
    )


class UISynthesizer:
    """Object facade for ``UISynthesizer@1``."""

    interface: str = UI_SYNTHESIZER_INTERFACE
    synthesizer_id: str = UI_SYNTHESIZER_ID

    def __init__(
        self,
        policy: SynthesisPolicy | None = None,
        learned_provider: LearnedCandidateProvider | None = None,
    ) -> None:
        self.policy = policy or SynthesisPolicy()
        self.learned_provider = learned_provider

    def synthesize(
        self,
        inputs: SynthesisInputs,
        constraints: Sequence[ReviewedFormalConstraint] = (),
        policy: SynthesisPolicy | None = None,
        *,
        external_drafts: Sequence[ExternalCandidateDraft] = (),
    ) -> UISynthesisResult:
        return synthesize_ui_ir(
            inputs,
            constraints,
            policy or self.policy,
            learned_provider=self.learned_provider,
            external_drafts=external_drafts,
        )


# Convenience alias matching the public API target name.
synthesize = synthesize_ui_ir


__all__ = [
    "AdmissionDisposition",
    "AdmissionGate",
    "ClarificationSeverity",
    "ExternalCandidateDraft",
    "FormalCoverageItem",
    "GateResult",
    "LearnedCandidateProvider",
    "ReviewedFormalConstraint",
    "SynthesisAdmissionReceipt",
    "SynthesisClarification",
    "SynthesisInputs",
    "SynthesisPolicy",
    "SynthesisProgramSeed",
    "SynthesisProviderKind",
    "TEMPLATE_PROVIDER_ID",
    "UI_SYNTHESIZER_ID",
    "UI_SYNTHESIZER_INTERFACE",
    "UI_SYNTHESIS_RESULT_SCHEMA",
    "UISynthesisCandidate",
    "UISynthesisResult",
    "UISynthesizer",
    "admit_candidate",
    "build_template_document",
    "synthesize",
    "synthesize_template_candidate",
    "synthesize_ui_ir",
]
