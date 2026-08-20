"""Domain-neutral reconstruction and adversarial decompilation contracts.

The measured source-withheld paraphraser remains
``ipfs_datasets_py.logic.legal_ir.canonical_decompiler``.  This module
classifies that surface, emits structural reviews, and keeps unsupported
inverses explicit.  It never increases semantic or proof authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from ipfs_datasets_py.logic.bridge.translation import (
    CLOSED_PRESERVATION_CLASSES,
    CLOSED_RECONSTRUCTION_MODES,
    EqualityCriterion,
    FidelityClaim,
    ReconstructionMode,
    TRANSLATION_PRESERVATION_INTERFACE,
    TranslationPreservationClass,
    TranslationReceipt,
    issue_translation_receipt,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_ROUNDTRIP_IR_INTERFACE,
    SELECTED_REALIZER_INTERFACE,
    SOURCE_WITHHELD_DECOMPILER_CONFIG,
    SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
    SOURCE_WITHHELD_RENDERING_SPEC_CID,
    CanonicalContractError,
    CanonicalRoundTripIR,
    CanonicalRule,
    DecompilerRequest,
    DecompilerResult,
    OperationStatus,
)
from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import (
    SourceWithheldCanonicalDecompiler,
    decompile_rule,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json


CANONICAL_DECOMPILER_IDENTITY_INTERFACE: Final = "CanonicalDecompilerIdentity@1"
CANONICAL_STRUCTURAL_REVIEW_INTERFACE: Final = "CanonicalStructuralReview@1"
CANONICAL_STRUCTURAL_REVIEW_SCHEMA: Final = "ipfs-datasets.canonical-structural-review.v1"
CANONICAL_CONTROLLED_RECONSTRUCTION_INTERFACE: Final = "CanonicalControlledReconstruction@1"
DOMAIN_NEUTRAL_DECOMPILER_INTERFACE: Final = "DomainNeutralCanonicalDecompiler@1"


def decompiler_identity_payload() -> dict[str, object]:
    """Return the frozen PGIR-022 decompiler identity without runtime state."""

    return {
        "config_cid": SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
        "deterministic": True,
        "interface": CANONICAL_DECOMPILER_IDENTITY_INTERFACE,
        "learned_stages": [],
        "preservation_classes": list(CLOSED_PRESERVATION_CLASSES),
        "preservation_interface": TRANSLATION_PRESERVATION_INTERFACE,
        "realizer": SELECTED_REALIZER_INTERFACE,
        "reconstruction_modes": list(CLOSED_RECONSTRUCTION_MODES),
        "rendering_spec_cid": SOURCE_WITHHELD_RENDERING_SPEC_CID,
        "source_withheld": True,
    }


CANONICAL_DECOMPILER_IDENTITY_CID: Final = cid_for_dag_json(decompiler_identity_payload())


def _readable_atom(atom: str) -> str:
    return " ".join(atom.replace("_", " ").split())


def _rule_facets(rule: CanonicalRule) -> dict[str, object]:
    return {
        "action": rule.action,
        "actor": rule.actor,
        "conditions": list(rule.conditions),
        "exceptions": list(rule.exceptions),
        "modality": rule.modality,
        "object": rule.object,
        "rule_cid": rule.rule_cid,
        "temporal": list(rule.temporal),
    }


def structural_review_payload(canonical_ir: CanonicalRoundTripIR) -> dict[str, object]:
    """Return a source-free facet inventory.  This is not prose realization."""

    if not isinstance(canonical_ir, CanonicalRoundTripIR):
        raise CanonicalContractError("structural review requires CanonicalRoundTripIR")
    return {
        "fidelity_claim": FidelityClaim.NONE.value,
        "interface": CANONICAL_STRUCTURAL_REVIEW_INTERFACE,
        "ir_cid": canonical_ir.ir_cid,
        "preservation_class": TranslationPreservationClass.LOSSLESS.value,
        "reconstruction_mode": ReconstructionMode.STRUCTURAL_REVIEW.value,
        "rule_count": len(canonical_ir.rules),
        "rules": [_rule_facets(rule) for rule in canonical_ir.rules],
        "schema_version": CANONICAL_STRUCTURAL_REVIEW_SCHEMA,
        "source_withheld": True,
    }


@dataclass(frozen=True, slots=True)
class StructuralReview:
    """Lossless facet inventory of canonical IR for structural review."""

    canonical_ir: CanonicalRoundTripIR

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_ir, CanonicalRoundTripIR):
            raise CanonicalContractError("structural review requires CanonicalRoundTripIR")

    @property
    def payload(self) -> dict[str, object]:
        return structural_review_payload(self.canonical_ir)

    @property
    def review_cid(self) -> str:
        return cid_for_dag_json(self.payload)

    def to_dict(self) -> dict[str, object]:
        return {**self.payload, "review_cid": self.review_cid}

    def receipt(self) -> TranslationReceipt:
        return issue_translation_receipt(
            direction_id="PGIR-022-STRUCTURAL-REVIEW",
            reconstruction_mode=ReconstructionMode.STRUCTURAL_REVIEW,
            preservation_class=TranslationPreservationClass.LOSSLESS,
            fidelity_claim=FidelityClaim.NONE,
            source_cid=self.canonical_ir.ir_cid,
            target_cid=self.review_cid,
            equality_criteria=(
                EqualityCriterion.CANONICAL_RULE_SET,
                EqualityCriterion.EXACT_IR_CID,
            ),
            details={"review_kind": "facet_inventory"},
        )


def decompile_structural_review(canonical_ir: CanonicalRoundTripIR) -> StructuralReview:
    """Emit a structural review.  The review is not a style paraphrase."""

    return StructuralReview(canonical_ir)


def paraphrase_translation_receipt(
    request: DecompilerRequest,
    result: DecompilerResult,
) -> TranslationReceipt:
    """Classify the measured source-withheld paraphraser without claiming fidelity."""

    if result.status is not OperationStatus.SUCCESS or result.text_cid is None:
        raise CanonicalContractError("paraphrase receipt requires a successful decompiler result")
    return issue_translation_receipt(
        direction_id="A4-CNL-001",
        reconstruction_mode=ReconstructionMode.STYLE_PARAPHRASE,
        preservation_class=TranslationPreservationClass.HEURISTIC,
        fidelity_claim=FidelityClaim.NONE,
        source_cid=request.canonical_ir.ir_cid,
        target_cid=result.text_cid,
        equality_criteria=(
            EqualityCriterion.SEMANTIC_RECOMPILE,
            EqualityCriterion.EXACT_IR_CID,
        ),
        declared_loss=(
            "controlled_paraphrase_is_not_source_reconstruction",
            "fidelity_requires_recompilation_and_semantic_comparison",
        ),
        details={
            "decompiler_identity_cid": CANONICAL_DECOMPILER_IDENTITY_CID,
            "realizer": SELECTED_REALIZER_INTERFACE,
            "source_withheld": True,
        },
    )


def _surface_polarity(text: str) -> str | None:
    lowered = f" {text.lower()} "
    prohibition = f" {SOURCE_WITHHELD_DECOMPILER_CONFIG['prohibition_surface']} "
    obligation = f" {SOURCE_WITHHELD_DECOMPILER_CONFIG['obligation_surface']} "
    permission = f" {SOURCE_WITHHELD_DECOMPILER_CONFIG['permission_surface']} "
    if prohibition in lowered:
        return "F"
    if permission in lowered:
        return "P"
    if obligation in lowered:
        return "O"
    return None


def detect_surface_semantic_differences(
    canonical_ir: CanonicalRoundTripIR,
    text: str,
) -> tuple[dict[str, object], ...]:
    """Compare frozen-surface polarity and facet mentions against the IR.

    This detector is an adversarial check, not a compiler and not a fidelity
    claim.  A missing mention is declared loss, never treated as zero.
    """

    if not isinstance(canonical_ir, CanonicalRoundTripIR):
        raise CanonicalContractError("semantic difference requires CanonicalRoundTripIR")
    if not isinstance(text, str):
        raise CanonicalContractError("semantic difference text must be a string")
    lowered = text.lower()
    differences: list[dict[str, object]] = []
    sentences = [item.strip() for item in text.split(".") if item.strip()]
    if len(sentences) != len(canonical_ir.rules):
        differences.append(
            {
                "kind": "rule_count_mismatch",
                "left_count": len(canonical_ir.rules),
                "right_count": len(sentences),
            }
        )
    for index, rule in enumerate(canonical_ir.rules):
        sentence = sentences[index] if index < len(sentences) else text
        polarity = _surface_polarity(sentence)
        if polarity is not None and polarity != rule.modality:
            differences.append(
                {
                    "action": rule.action,
                    "actor": rule.actor,
                    "kind": "changed_polarity",
                    "left": rule.modality,
                    "right": polarity,
                    "rule_cid": rule.rule_cid,
                }
            )
        for facet, values in (
            ("actor", (rule.actor,)),
            ("action", (rule.action,)),
            ("object", (rule.object,) if rule.object else ()),
            ("condition", rule.conditions),
            ("exception", rule.exceptions),
            ("temporal", rule.temporal),
        ):
            for value in values:
                surface = _readable_atom(value).lower()
                if surface and surface not in lowered:
                    differences.append(
                        {
                            "facet": facet,
                            "kind": "dropped_facet",
                            "rule_cid": rule.rule_cid,
                            "value": value,
                        }
                    )
    return tuple(differences)


@dataclass(frozen=True, slots=True)
class AdversarialDecompilationFixture:
    """Compact adversarial recipe.  Not a golden envelope dump."""

    fixture_id: str
    kind: str
    ir: CanonicalRoundTripIR
    adversarial_text: str
    expected_difference_kinds: tuple[str, ...]
    forbidden_preservation_class: TranslationPreservationClass
    forbidden_fidelity_claim: FidelityClaim

    def to_dict(self) -> dict[str, object]:
        return {
            "adversarial_text": self.adversarial_text,
            "expected_difference_kinds": list(self.expected_difference_kinds),
            "fixture_id": self.fixture_id,
            "forbidden_fidelity_claim": self.forbidden_fidelity_claim.value,
            "forbidden_preservation_class": self.forbidden_preservation_class.value,
            "ir": self.ir.to_dict(),
            "kind": self.kind,
        }


def adversarial_decompilation_fixtures() -> tuple[AdversarialDecompilationFixture, ...]:
    """Return compact polarity, drop, leak, and undeclared-authority recipes."""

    obligation = CanonicalRoundTripIR(
        (
            CanonicalRule(
                modality="O",
                actor="company_a",
                action="file",
                object="annual_report",
                conditions=("public_interest",),
                exceptions=("emergency",),
                temporal=("within_10_days",),
            ),
        )
    )
    prohibition = CanonicalRoundTripIR(
        (
            CanonicalRule(
                modality="F",
                actor="agency",
                action="publish",
                object="records",
            ),
        )
    )
    return (
        AdversarialDecompilationFixture(
            fixture_id="polarity_flip_obligation_to_prohibition",
            kind="changed_polarity",
            ir=obligation,
            adversarial_text=(
                "Company a must not file annual report within 10 days "
                "if public interest unless emergency."
            ),
            expected_difference_kinds=("changed_polarity",),
            forbidden_preservation_class=TranslationPreservationClass.LOSSLESS,
            forbidden_fidelity_claim=FidelityClaim.SEMANTIC,
        ),
        AdversarialDecompilationFixture(
            fixture_id="dropped_condition_and_exception",
            kind="dropped_facet",
            ir=obligation,
            adversarial_text="Company a must file annual report within 10 days.",
            expected_difference_kinds=("dropped_facet",),
            forbidden_preservation_class=TranslationPreservationClass.LOSSLESS,
            forbidden_fidelity_claim=FidelityClaim.SEMANTIC,
        ),
        AdversarialDecompilationFixture(
            fixture_id="permission_as_obligation",
            kind="changed_polarity",
            ir=CanonicalRoundTripIR(
                (
                    CanonicalRule(
                        modality="P",
                        actor="court",
                        action="review",
                        object="notice",
                    ),
                )
            ),
            adversarial_text="Court must review notice.",
            expected_difference_kinds=("changed_polarity",),
            forbidden_preservation_class=TranslationPreservationClass.EQUISATISFIABLE,
            forbidden_fidelity_claim=FidelityClaim.PROOF,
        ),
        AdversarialDecompilationFixture(
            fixture_id="prohibition_weakened_to_permission",
            kind="changed_polarity",
            ir=prohibition,
            adversarial_text="Agency may publish records.",
            expected_difference_kinds=("changed_polarity",),
            forbidden_preservation_class=TranslationPreservationClass.LOSSLESS,
            forbidden_fidelity_claim=FidelityClaim.PROOF,
        ),
        AdversarialDecompilationFixture(
            fixture_id="plausible_prose_as_fidelity",
            kind="undeclared_fidelity",
            ir=obligation,
            adversarial_text=(
                "In the public interest, Company A shall file the annual "
                "report within ten days except in an emergency."
            ),
            expected_difference_kinds=("dropped_facet",),
            forbidden_preservation_class=TranslationPreservationClass.LOSSLESS,
            forbidden_fidelity_claim=FidelityClaim.SEMANTIC,
        ),
    )


@dataclass(frozen=True, slots=True)
class AdversarialDecompilationVerdict:
    """Fail-closed evaluation of one adversarial decompilation fixture."""

    fixture_id: str
    admitted: bool
    difference_kinds: tuple[str, ...]
    rejected_claims: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "admitted": self.admitted,
            "difference_kinds": list(self.difference_kinds),
            "fixture_id": self.fixture_id,
            "rejected_claims": list(self.rejected_claims),
        }


def evaluate_adversarial_decompilation(
    fixture: AdversarialDecompilationFixture,
) -> AdversarialDecompilationVerdict:
    """Reject undeclared lossless/proof claims when the surface differs."""

    differences = detect_surface_semantic_differences(fixture.ir, fixture.adversarial_text)
    kinds = tuple(sorted({str(item["kind"]) for item in differences}))
    missing = tuple(kind for kind in fixture.expected_difference_kinds if kind not in kinds)
    rejected: list[str] = []
    if differences:
        rejected.append(f"preservation:{fixture.forbidden_preservation_class.value}")
        rejected.append(f"fidelity:{fixture.forbidden_fidelity_claim.value}")
    honest = paraphrase_translation_receipt(
        DecompilerRequest(canonical_ir=fixture.ir, request_id=fixture.fixture_id),
        SourceWithheldCanonicalDecompiler().decompile(
            DecompilerRequest(canonical_ir=fixture.ir, request_id=fixture.fixture_id)
        ),
    )
    if honest.fidelity_claim is not FidelityClaim.NONE:
        rejected.append("honest_paraphrase_claimed_fidelity")
    admitted = not missing and bool(differences)
    return AdversarialDecompilationVerdict(
        fixture_id=fixture.fixture_id,
        admitted=admitted,
        difference_kinds=kinds,
        rejected_claims=tuple(rejected),
    )


@dataclass(frozen=True, slots=True)
class DomainNeutralReconstruction:
    """Domain-neutral inverse that never invents a family or increases authority."""

    kind: str
    reconstruction_mode: ReconstructionMode
    preservation_class: TranslationPreservationClass
    fidelity_claim: FidelityClaim
    payload: Mapping[str, object]
    declared_loss: tuple[str, ...]
    source_cid: str
    target_cid: str
    receipt: TranslationReceipt | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "declared_loss": list(self.declared_loss),
            "fidelity_claim": self.fidelity_claim.value,
            "kind": self.kind,
            "payload": dict(self.payload),
            "preservation_class": self.preservation_class.value,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "reconstruction_mode": self.reconstruction_mode.value,
            "source_cid": self.source_cid,
            "target_cid": self.target_cid,
        }


class DomainNeutralCanonicalDecompiler:
    """Inverse dispatcher over existing contracts without a new logic family.

    Canonical IR can be realized as source-withheld paraphrase or reviewed as
    a facet inventory.  Formalization artifacts, LegalIRDocument envelopes, and
    unknown families remain unsupported as prose inverses.
    """

    __slots__ = ()

    @property
    def identity(self) -> str:
        return DOMAIN_NEUTRAL_DECOMPILER_INTERFACE

    @property
    def deterministic(self) -> bool:
        return True

    @property
    def uses_model(self) -> bool:
        return False

    def invert_canonical_ir(
        self,
        canonical_ir: CanonicalRoundTripIR,
        *,
        mode: ReconstructionMode | str = ReconstructionMode.STYLE_PARAPHRASE,
        request_id: str = "domain-neutral",
    ) -> DomainNeutralReconstruction:
        resolved = (
            mode if isinstance(mode, ReconstructionMode) else ReconstructionMode(mode)
        )
        if resolved is ReconstructionMode.STRUCTURAL_REVIEW:
            review = decompile_structural_review(canonical_ir)
            return DomainNeutralReconstruction(
                kind=CANONICAL_ROUNDTRIP_IR_INTERFACE,
                reconstruction_mode=ReconstructionMode.STRUCTURAL_REVIEW,
                preservation_class=TranslationPreservationClass.LOSSLESS,
                fidelity_claim=FidelityClaim.NONE,
                payload=review.to_dict(),
                declared_loss=(),
                source_cid=canonical_ir.ir_cid,
                target_cid=review.review_cid,
                receipt=review.receipt(),
            )
        if resolved is ReconstructionMode.STYLE_PARAPHRASE:
            request = DecompilerRequest(canonical_ir=canonical_ir, request_id=request_id)
            result = SourceWithheldCanonicalDecompiler().decompile(request)
            if result.status is not OperationStatus.SUCCESS or result.text_cid is None:
                raise CanonicalContractError("style paraphrase failed; no fidelity is claimed")
            receipt = paraphrase_translation_receipt(request, result)
            return DomainNeutralReconstruction(
                kind=CANONICAL_ROUNDTRIP_IR_INTERFACE,
                reconstruction_mode=ReconstructionMode.STYLE_PARAPHRASE,
                preservation_class=TranslationPreservationClass.HEURISTIC,
                fidelity_claim=FidelityClaim.NONE,
                payload={"text": result.text, "text_cid": result.text_cid},
                declared_loss=receipt.declared_loss,
                source_cid=canonical_ir.ir_cid,
                target_cid=result.text_cid,
                receipt=receipt,
            )
        if resolved is ReconstructionMode.CONTROLLED_SEMANTIC:
            request = DecompilerRequest(
                canonical_ir=canonical_ir,
                request_id=f"{request_id}:controlled",
            )
            result = SourceWithheldCanonicalDecompiler().decompile(request)
            if result.status is not OperationStatus.SUCCESS or result.text_cid is None:
                raise CanonicalContractError("controlled reconstruction failed")
            receipt = issue_translation_receipt(
                direction_id="A4-CNL-001",
                reconstruction_mode=ReconstructionMode.CONTROLLED_SEMANTIC,
                preservation_class=TranslationPreservationClass.HEURISTIC,
                fidelity_claim=FidelityClaim.CANDIDATE,
                source_cid=canonical_ir.ir_cid,
                target_cid=result.text_cid,
                declared_loss=(
                    "controlled_surface_is_not_semantic_authority",
                    "recompilation_gate_required",
                ),
                details={"awaiting": "semantic_recompilation_gate"},
            )
            return DomainNeutralReconstruction(
                kind=CANONICAL_CONTROLLED_RECONSTRUCTION_INTERFACE,
                reconstruction_mode=ReconstructionMode.CONTROLLED_SEMANTIC,
                preservation_class=TranslationPreservationClass.HEURISTIC,
                fidelity_claim=FidelityClaim.CANDIDATE,
                payload={"text": result.text, "text_cid": result.text_cid},
                declared_loss=receipt.declared_loss,
                source_cid=canonical_ir.ir_cid,
                target_cid=result.text_cid,
                receipt=receipt,
            )
        raise CanonicalContractError(f"unsupported reconstruction mode {resolved!r}")

    def invert_unsupported(
        self,
        *,
        kind: str,
        source_cid: str,
        reason: str,
        direction_id: str = "A4-TYPED-002",
    ) -> DomainNeutralReconstruction:
        """Retain an inverse as unsupported instead of inventing a family AST."""

        payload = {
            "interface": DOMAIN_NEUTRAL_DECOMPILER_INTERFACE,
            "kind": kind,
            "reason": reason,
            "reconstruction_mode": ReconstructionMode.STRUCTURAL_REVIEW.value,
            "unsupported": True,
        }
        target_cid = cid_for_dag_json(payload)
        receipt = issue_translation_receipt(
            direction_id=direction_id,
            reconstruction_mode=ReconstructionMode.STRUCTURAL_REVIEW,
            preservation_class=TranslationPreservationClass.UNSUPPORTED,
            fidelity_claim=FidelityClaim.NONE,
            source_cid=source_cid,
            target_cid=target_cid,
            equality_criteria=(EqualityCriterion.UNSUPPORTED,),
            details={"reason": reason},
        )
        return DomainNeutralReconstruction(
            kind=kind,
            reconstruction_mode=ReconstructionMode.STRUCTURAL_REVIEW,
            preservation_class=TranslationPreservationClass.UNSUPPORTED,
            fidelity_claim=FidelityClaim.NONE,
            payload=payload,
            declared_loss=(reason,),
            source_cid=source_cid,
            target_cid=target_cid,
            receipt=receipt,
        )


def decompile_with_preservation(
    request: DecompilerRequest,
    *,
    mode: ReconstructionMode | str = ReconstructionMode.STYLE_PARAPHRASE,
) -> tuple[DecompilerResult, TranslationReceipt | None, StructuralReview | None]:
    """Realize or review canonical IR and attach a closed translation class."""

    resolved = mode if isinstance(mode, ReconstructionMode) else ReconstructionMode(mode)
    decompiler = SourceWithheldCanonicalDecompiler()
    if resolved is ReconstructionMode.STRUCTURAL_REVIEW:
        if not isinstance(request, DecompilerRequest):
            raise CanonicalContractError("request must be DecompilerRequest")
        review = decompile_structural_review(request.canonical_ir)
        return decompiler.decompile(request), review.receipt(), review
    result = decompiler.decompile(request)
    if result.status is not OperationStatus.SUCCESS:
        return result, None, None
    if resolved is ReconstructionMode.CONTROLLED_SEMANTIC:
        receipt = issue_translation_receipt(
            direction_id="A4-CNL-001",
            reconstruction_mode=ReconstructionMode.CONTROLLED_SEMANTIC,
            preservation_class=TranslationPreservationClass.HEURISTIC,
            fidelity_claim=FidelityClaim.CANDIDATE,
            source_cid=request.canonical_ir.ir_cid,
            target_cid=result.text_cid or result.request_cid,
            declared_loss=(
                "controlled_surface_is_not_semantic_authority",
                "recompilation_gate_required",
            ),
        )
        return result, receipt, None
    return result, paraphrase_translation_receipt(request, result), None


__all__ = [
    "AdversarialDecompilationFixture",
    "AdversarialDecompilationVerdict",
    "CANONICAL_CONTROLLED_RECONSTRUCTION_INTERFACE",
    "CANONICAL_DECOMPILER_IDENTITY_CID",
    "CANONICAL_DECOMPILER_IDENTITY_INTERFACE",
    "CANONICAL_STRUCTURAL_REVIEW_INTERFACE",
    "CANONICAL_STRUCTURAL_REVIEW_SCHEMA",
    "DOMAIN_NEUTRAL_DECOMPILER_INTERFACE",
    "DomainNeutralCanonicalDecompiler",
    "DomainNeutralReconstruction",
    "StructuralReview",
    "adversarial_decompilation_fixtures",
    "decompile_rule",
    "decompile_structural_review",
    "decompile_with_preservation",
    "decompiler_identity_payload",
    "detect_surface_semantic_differences",
    "evaluate_adversarial_decompilation",
    "paraphrase_translation_receipt",
    "structural_review_payload",
]
