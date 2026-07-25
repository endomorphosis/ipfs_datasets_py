"""Source-free structural features for validated Intent IR documents."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Final, Sequence

from ...formalization.features import FormalizationFeatures
from ..canonicalize import intent_ir_sha256
from ..schema import (
    ControlEdgeKind,
    IntentIRDocument,
    IntentKind,
    IntentModality,
    NodeGrounding,
    StatementKind,
    validate_intent_ir,
)


INTENT_FEATURE_EXTRACTOR_ID: Final = "intent-ir-structural-features"
INTENT_FEATURE_EXTRACTOR_VERSION: Final = "1"


def _count_features(document: IntentIRDocument) -> dict[str, float]:
    """Build a closed-vocabulary vector without inspecting source text."""

    statement_kinds = Counter(item.kind for item in document.statements)
    modalities = Counter(item.modality for item in document.statements)
    statement_grounding = Counter(item.grounding for item in document.statements)
    action_grounding = Counter(item.grounding for item in document.actions)
    edge_grounding = Counter(item.grounding for item in document.control_edges)
    edge_kinds = Counter(item.kind for item in document.control_edges)

    features: dict[str, float] = {
        f"intent.kind.{kind.value}": float(document.intent_kind is kind)
        for kind in IntentKind
    }
    features.update(
        {
            f"statement.kind.{kind.value}.count": float(statement_kinds[kind])
            for kind in StatementKind
        }
    )
    features.update(
        {
            f"statement.modality.{modality.value}.count": float(
                modalities[modality]
            )
            for modality in IntentModality
        }
    )
    features.update(
        {
            f"control.kind.{kind.value}.count": float(edge_kinds[kind])
            for kind in ControlEdgeKind
        }
    )
    for label, counts in (
        ("statement", statement_grounding),
        ("action", action_grounding),
        ("control", edge_grounding),
    ):
        for grounding in NodeGrounding:
            features[f"{label}.grounding.{grounding.value}.count"] = float(
                counts[grounding]
            )

    features.update(
        {
            "action.count": float(len(document.actions)),
            "action.effect.ref.count": float(
                sum(len(item.effect_ids) for item in document.actions)
            ),
            "action.input.ref.count": float(
                sum(len(item.input_refs) for item in document.actions)
            ),
            "action.object.ref.count": float(
                sum(len(item.object_refs) for item in document.actions)
            ),
            "action.output.ref.count": float(
                sum(len(item.output_refs) for item in document.actions)
            ),
            "action.precondition.ref.count": float(
                sum(len(item.precondition_ids) for item in document.actions)
            ),
            "action.tool.ref.count": float(
                sum(len(item.tool_refs) for item in document.actions)
            ),
            "action.verification.ref.count": float(
                sum(len(item.verification_ids) for item in document.actions)
            ),
            "control.count": float(len(document.control_edges)),
            "control.guarded.count": float(
                sum(bool(item.guard_statement_id) for item in document.control_edges)
            ),
            "entry.action.count": float(len(document.entry_action_ids)),
            "evidence.reference.count": float(len(document.sources)),
            "statement.argument.count": float(
                sum(len(item.arguments) for item in document.statements)
            ),
            "statement.count": float(len(document.statements)),
            "statement.predicate.count": float(
                sum(bool(item.predicate) for item in document.statements)
            ),
            "terminal.action.count": float(len(document.terminal_action_ids)),
        }
    )
    return features


@dataclass(frozen=True, slots=True)
class IntentFeatureExtractor:
    """Deterministic closed-vocabulary Intent feature extractor."""

    extractor_id: str = INTENT_FEATURE_EXTRACTOR_ID
    extractor_version: str = INTENT_FEATURE_EXTRACTOR_VERSION

    def extract(
        self,
        document: IntentIRDocument,
        *,
        context_snapshot_ids: Sequence[str] = (),
    ) -> FormalizationFeatures:
        validated = validate_intent_ir(document)
        return FormalizationFeatures.from_values(
            sample_id=validated.document_id,
            domain="intent",
            declaration_digest=intent_ir_sha256(validated),
            features=_count_features(validated),
            extractor_id=self.extractor_id,
            extractor_version=self.extractor_version,
            context_snapshot_ids=context_snapshot_ids,
        )


def extract_intent_features(
    document: IntentIRDocument,
    *,
    context_snapshot_ids: Sequence[str] = (),
) -> FormalizationFeatures:
    """Extract stable structural features from validated Intent IR.

    Titles, normalized statement bodies, symbol spellings, source URIs,
    revisions, hashes, licenses, review states, confidence values, tags,
    GraphRAG neighbors, compiler outputs, and proof/results are never read.
    """

    return IntentFeatureExtractor().extract(
        document, context_snapshot_ids=context_snapshot_ids
    )


# Descriptive compatibility spelling for callers constructing advisor inputs.
build_intent_formalization_features = extract_intent_features


__all__ = [
    "INTENT_FEATURE_EXTRACTOR_ID",
    "INTENT_FEATURE_EXTRACTOR_VERSION",
    "IntentFeatureExtractor",
    "build_intent_formalization_features",
    "extract_intent_features",
]
