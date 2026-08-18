"""Semantic recompilation gate for paraphrase and reconstruction fidelity.

Pipeline success of ``CanonicalSemanticRoundTrip`` is not semantic admission.
This module compares L1 and L2, records the closed equality criteria, and
issues a translation receipt.  Style paraphrase cannot claim fidelity without
this gate.  The gate never issues proof authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from ipfs_datasets_py.logic.bridge.decompiler import (
    CANONICAL_DECOMPILER_IDENTITY_CID,
    detect_surface_semantic_differences,
    paraphrase_translation_receipt,
)
from ipfs_datasets_py.logic.bridge.translation import (
    CLOSED_EQUALITY_CRITERIA,
    EqualityCriterion,
    FidelityClaim,
    ReconstructionMode,
    TRANSLATION_PRESERVATION_INTERFACE,
    TranslationPreservationClass,
    TranslationReceipt,
    issue_translation_receipt,
    recorded_roundtrip_directions,
    translation_direction_catalog,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CanonicalContractError,
    CanonicalRoundTripIR,
    CompilerRequest,
    DecompilerRequest,
    DecompilerResult,
    OperationStatus,
)
from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import (
    CanonicalSemanticRoundTrip,
    CanonicalSemanticRoundTripResult,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json


SEMANTIC_RECOMPILATION_GATE_INTERFACE: Final = "CanonicalSemanticRecompilationGate@1"
SEMANTIC_RECOMPILATION_GATE_SCHEMA: Final = (
    "ipfs-datasets.canonical-semantic-recompilation-gate.v1"
)
SEMANTIC_DIFFERENCE_INTERFACE: Final = "CanonicalSemanticDifference@1"


def compare_canonical_semantics(
    left: CanonicalRoundTripIR,
    right: CanonicalRoundTripIR,
) -> tuple[dict[str, object], ...]:
    """Compare two canonical IRs by CID, rule set, and facet polarity."""

    if not isinstance(left, CanonicalRoundTripIR) or not isinstance(right, CanonicalRoundTripIR):
        raise CanonicalContractError("semantic comparison requires CanonicalRoundTripIR")
    differences: list[dict[str, object]] = []
    if left.ir_cid != right.ir_cid:
        differences.append(
            {
                "criterion": EqualityCriterion.EXACT_IR_CID.value,
                "equal": False,
                "kind": "ir_cid_mismatch",
                "left_cid": left.ir_cid,
                "right_cid": right.ir_cid,
            }
        )
    left_cids = {rule.rule_cid for rule in left.rules}
    right_cids = {rule.rule_cid for rule in right.rules}
    if left_cids != right_cids:
        differences.append(
            {
                "added": sorted(right_cids - left_cids),
                "criterion": EqualityCriterion.CANONICAL_RULE_SET.value,
                "dropped": sorted(left_cids - right_cids),
                "equal": False,
                "kind": "rule_set_mismatch",
            }
        )
    left_by_key = {(rule.actor, rule.action, rule.object): rule for rule in left.rules}
    right_keys = {(item.actor, item.action, item.object) for item in right.rules}
    for rule in right.rules:
        key = (rule.actor, rule.action, rule.object)
        counterpart = left_by_key.get(key)
        if counterpart is None:
            differences.append(
                {
                    "action": rule.action,
                    "actor": rule.actor,
                    "kind": "added_rule",
                    "object": rule.object,
                    "rule_cid": rule.rule_cid,
                }
            )
            continue
        if counterpart.modality != rule.modality:
            differences.append(
                {
                    "action": rule.action,
                    "actor": rule.actor,
                    "kind": "changed_polarity",
                    "left": counterpart.modality,
                    "right": rule.modality,
                    "rule_cid": rule.rule_cid,
                }
            )
        for facet in ("conditions", "exceptions", "temporal"):
            left_values = set(getattr(counterpart, facet))
            right_values = set(getattr(rule, facet))
            if left_values == right_values:
                continue
            differences.append(
                {
                    "added": sorted(right_values - left_values),
                    "dropped": sorted(left_values - right_values),
                    "facet": facet,
                    "kind": "changed_qualifiers",
                    "rule_cid": rule.rule_cid,
                }
            )
    for rule in left.rules:
        key = (rule.actor, rule.action, rule.object)
        if key not in right_keys:
            differences.append(
                {
                    "action": rule.action,
                    "actor": rule.actor,
                    "kind": "dropped_rule",
                    "object": rule.object,
                    "rule_cid": rule.rule_cid,
                }
            )
    return tuple(differences)


def classify_ir_preservation(
    left: CanonicalRoundTripIR,
    right: CanonicalRoundTripIR,
) -> tuple[TranslationPreservationClass, tuple[str, ...]]:
    """Classify L1 versus L2 without treating missing equality as lossless."""

    if left.ir_cid == right.ir_cid:
        return TranslationPreservationClass.LOSSLESS, ()
    left_cids = {rule.rule_cid for rule in left.rules}
    right_cids = {rule.rule_cid for rule in right.rules}
    if right_cids and right_cids < left_cids:
        return TranslationPreservationClass.UNDER_APPROXIMATION, tuple(
            sorted(left_cids - right_cids)
        )
    if left_cids and left_cids < right_cids:
        return TranslationPreservationClass.OVER_APPROXIMATION, tuple(
            sorted(right_cids - left_cids)
        )
    differences = compare_canonical_semantics(left, right)
    loss = tuple(sorted({str(item["kind"]) for item in differences})) or (
        "undeclared_semantic_drift",
    )
    return TranslationPreservationClass.HEURISTIC, loss


def _gate_payload(
    *,
    admitted: bool,
    reconstruction_mode: ReconstructionMode,
    preservation_class: TranslationPreservationClass,
    fidelity_claim: FidelityClaim,
    differences: Sequence[Mapping[str, object]],
    l1_ir_cid: str,
    l2_ir_cid: str | None,
    t1_text_cid: str | None,
    declared_loss: Sequence[str],
) -> dict[str, object]:
    return {
        "admitted": admitted,
        "declared_loss": list(declared_loss),
        "decompiler_identity_cid": CANONICAL_DECOMPILER_IDENTITY_CID,
        "differences": [dict(item) for item in differences],
        "fidelity_claim": fidelity_claim.value,
        "interface": SEMANTIC_RECOMPILATION_GATE_INTERFACE,
        "l1_ir_cid": l1_ir_cid,
        "l2_ir_cid": l2_ir_cid,
        "preservation_class": preservation_class.value,
        "preservation_interface": TRANSLATION_PRESERVATION_INTERFACE,
        "reconstruction_mode": reconstruction_mode.value,
        "schema_version": SEMANTIC_RECOMPILATION_GATE_SCHEMA,
        "t1_text_cid": t1_text_cid,
    }


@dataclass(frozen=True, slots=True)
class SemanticRecompilationGateResult:
    """Admission decision for paraphrase or reconstruction fidelity."""

    status: OperationStatus
    admitted: bool
    reconstruction_mode: ReconstructionMode
    preservation_class: TranslationPreservationClass
    fidelity_claim: FidelityClaim
    equality_criteria: tuple[EqualityCriterion, ...]
    differences: tuple[dict[str, object], ...]
    declared_loss: tuple[str, ...]
    l1_ir_cid: str
    l2_ir_cid: str | None
    t1_text_cid: str | None
    comparison_cid: str
    receipt: TranslationReceipt | None
    roundtrip: CanonicalSemanticRoundTripResult

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reconstruction_mode",
            self.reconstruction_mode
            if isinstance(self.reconstruction_mode, ReconstructionMode)
            else ReconstructionMode(self.reconstruction_mode),
        )
        object.__setattr__(
            self,
            "preservation_class",
            self.preservation_class
            if isinstance(self.preservation_class, TranslationPreservationClass)
            else TranslationPreservationClass(self.preservation_class),
        )
        object.__setattr__(
            self,
            "fidelity_claim",
            self.fidelity_claim
            if isinstance(self.fidelity_claim, FidelityClaim)
            else FidelityClaim(self.fidelity_claim),
        )
        if (
            self.admitted
            and self.fidelity_claim is FidelityClaim.SEMANTIC
            and self.reconstruction_mode is ReconstructionMode.STYLE_PARAPHRASE
            and self.preservation_class is not TranslationPreservationClass.LOSSLESS
        ):
            raise CanonicalContractError(
                "style paraphrase cannot be admitted as semantic unless the IR cycle is lossless"
            )
        if self.fidelity_claim is FidelityClaim.PROOF:
            raise CanonicalContractError(
                "the semantic recompilation gate never issues proof authority"
            )

    def to_dict(self) -> dict[str, object]:
        payload = _gate_payload(
            admitted=self.admitted,
            reconstruction_mode=self.reconstruction_mode,
            preservation_class=self.preservation_class,
            fidelity_claim=self.fidelity_claim,
            differences=self.differences,
            l1_ir_cid=self.l1_ir_cid,
            l2_ir_cid=self.l2_ir_cid,
            t1_text_cid=self.t1_text_cid,
            declared_loss=self.declared_loss,
        )
        return {
            **payload,
            "comparison_cid": self.comparison_cid,
            "equality_criteria": [item.value for item in self.equality_criteria],
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "recorded_directions": list(recorded_roundtrip_directions()),
            "roundtrip_result_cid": self.roundtrip.result_cid,
            "status": self.status.value,
        }


def evaluate_semantic_recompilation_gate(
    roundtrip: CanonicalSemanticRoundTripResult,
    *,
    reconstruction_mode: ReconstructionMode | str = ReconstructionMode.STYLE_PARAPHRASE,
) -> SemanticRecompilationGateResult:
    """Admit fidelity only after successful recompilation and semantic comparison."""

    resolved = (
        reconstruction_mode
        if isinstance(reconstruction_mode, ReconstructionMode)
        else ReconstructionMode(reconstruction_mode)
    )
    l1 = None if roundtrip.l1_result is None else roundtrip.l1_result.canonical_ir
    l2 = None if roundtrip.l2_result is None else roundtrip.l2_result.canonical_ir
    t1 = roundtrip.t1_result
    if (
        roundtrip.status is not OperationStatus.SUCCESS
        or l1 is None
        or l2 is None
        or t1 is None
        or t1.text is None
        or t1.text_cid is None
    ):
        loss = (
            "incomplete_recompilation",
            "no_semantic_admission_without_l1_t1_l2",
        )
        differences: tuple[dict[str, object], ...] = (
            {
                "kind": "incomplete_cycle",
                "terminal_stage": roundtrip.terminal_stage,
            },
        )
        comparison_cid = cid_for_dag_json(
            _gate_payload(
                admitted=False,
                reconstruction_mode=resolved,
                preservation_class=TranslationPreservationClass.HEURISTIC,
                fidelity_claim=FidelityClaim.NONE,
                differences=differences,
                l1_ir_cid=l1.ir_cid if l1 is not None else roundtrip.request_cid,
                l2_ir_cid=None if l2 is None else l2.ir_cid,
                t1_text_cid=None if t1 is None else t1.text_cid,
                declared_loss=loss,
            )
        )
        return SemanticRecompilationGateResult(
            status=roundtrip.status,
            admitted=False,
            reconstruction_mode=resolved,
            preservation_class=TranslationPreservationClass.UNSUPPORTED
            if roundtrip.status is OperationStatus.FAILED
            else TranslationPreservationClass.HEURISTIC,
            fidelity_claim=FidelityClaim.NONE,
            equality_criteria=(EqualityCriterion.SEMANTIC_RECOMPILE,),
            differences=differences,
            declared_loss=loss,
            l1_ir_cid=l1.ir_cid if l1 is not None else roundtrip.request_cid,
            l2_ir_cid=None if l2 is None else l2.ir_cid,
            t1_text_cid=None if t1 is None else t1.text_cid,
            comparison_cid=comparison_cid,
            receipt=None,
            roundtrip=roundtrip,
        )

    ir_differences = compare_canonical_semantics(l1, l2)
    surface_differences = detect_surface_semantic_differences(l1, t1.text)
    preservation, declared_loss = classify_ir_preservation(l1, l2)
    admitted = (
        not ir_differences
        and preservation is TranslationPreservationClass.LOSSLESS
        and l1.ir_cid == l2.ir_cid
    )
    mode_for_receipt = (
        ReconstructionMode.CONTROLLED_SEMANTIC
        if admitted and resolved is ReconstructionMode.STYLE_PARAPHRASE
        else resolved
    )
    if mode_for_receipt is ReconstructionMode.STRUCTURAL_REVIEW:
        fidelity = FidelityClaim.NONE
    elif admitted:
        fidelity = FidelityClaim.SEMANTIC
    elif resolved is ReconstructionMode.CONTROLLED_SEMANTIC:
        fidelity = FidelityClaim.CANDIDATE
    else:
        fidelity = FidelityClaim.NONE
    comparison_cid = cid_for_dag_json(
        _gate_payload(
            admitted=admitted,
            reconstruction_mode=resolved,
            preservation_class=preservation,
            fidelity_claim=fidelity,
            differences=ir_differences,
            l1_ir_cid=l1.ir_cid,
            l2_ir_cid=l2.ir_cid,
            t1_text_cid=t1.text_cid,
            declared_loss=declared_loss,
        )
    )
    if mode_for_receipt is ReconstructionMode.STRUCTURAL_REVIEW:
        mode_for_receipt = ReconstructionMode.CONTROLLED_SEMANTIC
    receipt = issue_translation_receipt(
        direction_id="PGIR-022-IR-CYCLE",
        reconstruction_mode=mode_for_receipt,
        preservation_class=preservation,
        fidelity_claim=fidelity,
        source_cid=l1.ir_cid,
        target_cid=l2.ir_cid,
        equality_criteria=(
            EqualityCriterion.SEMANTIC_RECOMPILE,
            EqualityCriterion.EXACT_IR_CID,
            EqualityCriterion.CANONICAL_RULE_SET,
        ),
        declared_loss=declared_loss,
        recompilation_cid=roundtrip.result_cid,
        semantic_comparison_cid=comparison_cid,
        details={
            "ir_differences": [dict(item) for item in ir_differences],
            "surface_differences": [dict(item) for item in surface_differences],
            "t1_text_cid": t1.text_cid,
        },
    )
    return SemanticRecompilationGateResult(
        status=roundtrip.status,
        admitted=admitted,
        reconstruction_mode=resolved,
        preservation_class=preservation,
        fidelity_claim=receipt.fidelity_claim,
        equality_criteria=receipt.equality_criteria,
        differences=ir_differences,
        declared_loss=declared_loss,
        l1_ir_cid=l1.ir_cid,
        l2_ir_cid=l2.ir_cid,
        t1_text_cid=t1.text_cid,
        comparison_cid=comparison_cid,
        receipt=receipt,
        roundtrip=roundtrip,
    )


def run_with_preservation(
    request: CompilerRequest,
    *,
    reconstruction_mode: ReconstructionMode | str = ReconstructionMode.STYLE_PARAPHRASE,
    orchestrator: CanonicalSemanticRoundTrip | None = None,
) -> SemanticRecompilationGateResult:
    """Execute the measured cycle, then admit fidelity only through the gate."""

    cycle = CanonicalSemanticRoundTrip() if orchestrator is None else orchestrator
    return evaluate_semantic_recompilation_gate(
        cycle.run(request),
        reconstruction_mode=reconstruction_mode,
    )


def recorded_roundtrip_equality_criteria() -> dict[str, tuple[str, ...]]:
    """Return every required direction with its recorded equality criteria."""

    return {
        spec.direction_id: tuple(item.value for item in spec.equality_criteria)
        for spec in translation_direction_catalog()
    }


def paraphrase_without_recompilation_is_not_fidelity(
    request: DecompilerRequest,
    result: DecompilerResult,
) -> TranslationReceipt:
    """Bind the measured paraphraser as heuristic with no semantic claim."""

    return paraphrase_translation_receipt(request, result)


__all__ = [
    "CLOSED_EQUALITY_CRITERIA",
    "SEMANTIC_DIFFERENCE_INTERFACE",
    "SEMANTIC_RECOMPILATION_GATE_INTERFACE",
    "SEMANTIC_RECOMPILATION_GATE_SCHEMA",
    "SemanticRecompilationGateResult",
    "classify_ir_preservation",
    "compare_canonical_semantics",
    "evaluate_semantic_recompilation_gate",
    "paraphrase_without_recompilation_is_not_fidelity",
    "recorded_roundtrip_directions",
    "recorded_roundtrip_equality_criteria",
    "run_with_preservation",
]
