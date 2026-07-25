"""Semantic decompilation and mutation review for Intent formalizations.

Decompilation is deliberately a review operation, not an inverse compiler.
It extracts the Intent semantics represented by formal views and compares them
with a validated Intent declaration.  Exact text regeneration is neither
required nor claimed; goals, modality, action effects, control flow, guards,
and source grounding are compared structurally.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ...formalization.compiler import FormalizationArtifact
from ...ir_core.claims import FrozenMap, freeze_json, thaw_json
from ..schema import (
    ControlEdgeKind,
    IntentIRDocument,
    IntentModality,
    IntentStatement,
    StatementKind,
    validate_intent_ir,
)
from .compiler import (
    INTENT_ACTION_VIEW_ID,
    INTENT_FACT_VIEW_ID,
    INTENT_MODAL_VIEW_ID,
    INTENT_WORKFLOW_VIEW_ID,
)


INTENT_DECOMPILER_VERSION: Final = "intent-decompiler/v1"

_EDGE_OPERATORS: Final[dict[ControlEdgeKind, str]] = {
    ControlEdgeKind.NEXT: "next",
    ControlEdgeKind.ON_SUCCESS: "on_success",
    ControlEdgeKind.ON_FAILURE: "on_failure",
    ControlEdgeKind.CONDITIONAL: "conditional",
    ControlEdgeKind.RETRY: "retry",
    ControlEdgeKind.PARALLEL: "parallel",
    ControlEdgeKind.JOIN: "join",
}


class IntentDecompilerError(ValueError):
    """Raised when an artifact cannot be reviewed as Intent semantics."""


class IntentSemanticMutationKind(str, Enum):
    """Semantic dimensions protected by the round-trip review."""

    GOAL = "goal"
    MODALITY = "modality"
    ACTION_ORDER = "action_order"
    GUARD = "guard"
    EFFECT = "effect"
    SOURCE_GROUNDING = "source_grounding"
    UNSUPPORTED = "unsupported"


def _statement_body(statement: IntentStatement) -> dict[str, Any]:
    return {
        "arguments": list(statement.arguments),
        "confidence": float(statement.confidence),
        "grounding": statement.grounding.value,
        "modality": statement.modality.value,
        "predicate": statement.predicate,
        "review_status": statement.review_status.value,
        "statement_kind": statement.kind.value,
        "text": statement.normalized_text,
    }


def _modal_operator(statement: IntentStatement) -> str:
    if (
        statement.kind is StatementKind.GOAL
        and statement.modality is IntentModality.ASSERTED
    ):
        return IntentModality.INTENDED.value
    return statement.modality.value


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, FrozenMap):
        return value.to_dict()
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _node_id(formula: Any, expected_kind: str | None = None) -> str:
    ids = tuple(formula.metadata.get("intent_node_ids", ()))
    kinds = tuple(formula.metadata.get("intent_node_kinds", ()))
    if expected_kind and expected_kind in kinds:
        index = kinds.index(expected_kind)
        if index < len(ids):
            return str(ids[index])
    return str(ids[0]) if ids else formula.formula_id


@dataclass(frozen=True, slots=True)
class IntentSemanticMutation:
    """One structurally detected semantic difference."""

    kind: IntentSemanticMutationKind
    semantic_id: str
    expected: Any
    actual: Any
    formula_id: str = ""
    source_ref_ids: tuple[str, ...] = ()
    message: str = ""

    def __post_init__(self) -> None:
        try:
            kind = (
                self.kind
                if isinstance(self.kind, IntentSemanticMutationKind)
                else IntentSemanticMutationKind(self.kind)
            )
        except (TypeError, ValueError) as exc:
            raise IntentDecompilerError(
                f"unknown semantic mutation kind: {self.kind!r}"
            ) from exc
        object.__setattr__(self, "kind", kind)
        if not isinstance(self.semantic_id, str) or not self.semantic_id:
            raise IntentDecompilerError("mutation semantic_id must not be empty")
        object.__setattr__(self, "expected", freeze_json(self.expected))
        object.__setattr__(self, "actual", freeze_json(self.actual))
        refs = tuple(self.source_ref_ids)
        if len(refs) != len(set(refs)) or not all(
            isinstance(item, str) and item for item in refs
        ):
            raise IntentDecompilerError(
                "mutation source_ref_ids must be unique non-empty strings"
            )
        object.__setattr__(self, "source_ref_ids", tuple(sorted(refs)))
        if not self.message:
            object.__setattr__(
                self,
                "message",
                f"{kind.value} semantics differ for {self.semantic_id}",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actual": thaw_json(self.actual),
            "expected": thaw_json(self.expected),
            "formula_id": self.formula_id,
            "kind": self.kind.value,
            "message": self.message,
            "semantic_id": self.semantic_id,
            "source_ref_ids": list(self.source_ref_ids),
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "IntentSemanticMutation":
        payload = _mapping(value)
        allowed = {
            "actual",
            "expected",
            "formula_id",
            "kind",
            "message",
            "semantic_id",
            "source_ref_ids",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise IntentDecompilerError(
                "unknown semantic mutation field(s): " + ", ".join(unknown)
            )
        return cls(
            kind=payload.get("kind", ""),
            semantic_id=payload.get("semantic_id", ""),
            expected=payload.get("expected"),
            actual=payload.get("actual"),
            formula_id=payload.get("formula_id", ""),
            source_ref_ids=tuple(payload.get("source_ref_ids", ())),
            message=payload.get("message", ""),
        )


@dataclass(frozen=True, slots=True)
class DecompiledIntentReview:
    """Review-oriented semantic projection of formal Intent views."""

    declaration_id: str
    declaration_digest: str
    goals: FrozenMap = field(default_factory=FrozenMap)
    modalities: FrozenMap = field(default_factory=FrozenMap)
    action_order: FrozenMap = field(default_factory=FrozenMap)
    guards: FrozenMap = field(default_factory=FrozenMap)
    effects: FrozenMap = field(default_factory=FrozenMap)
    source_grounding: FrozenMap = field(default_factory=FrozenMap)
    formula_ids: FrozenMap = field(default_factory=FrozenMap)
    unsupported_formula_ids: tuple[str, ...] = ()
    schema_version: str = INTENT_DECOMPILER_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.declaration_id, str) or not self.declaration_id:
            raise IntentDecompilerError("declaration_id must not be empty")
        if (
            not isinstance(self.declaration_digest, str)
            or not self.declaration_digest.startswith("sha256:")
        ):
            raise IntentDecompilerError(
                "declaration_digest must be a sha256 digest"
            )
        for name in (
            "goals",
            "modalities",
            "action_order",
            "guards",
            "effects",
            "source_grounding",
            "formula_ids",
        ):
            value = getattr(self, name)
            object.__setattr__(
                self,
                name,
                value if isinstance(value, FrozenMap) else FrozenMap(value),
            )
        unsupported = tuple(sorted(self.unsupported_formula_ids))
        if len(unsupported) != len(set(unsupported)):
            raise IntentDecompilerError(
                "unsupported_formula_ids must be unique"
            )
        object.__setattr__(self, "unsupported_formula_ids", unsupported)
        if self.schema_version != INTENT_DECOMPILER_VERSION:
            raise IntentDecompilerError(
                f"unsupported decompiler schema: {self.schema_version}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_order": self.action_order.to_dict(),
            "declaration_digest": self.declaration_digest,
            "declaration_id": self.declaration_id,
            "effects": self.effects.to_dict(),
            "formula_ids": self.formula_ids.to_dict(),
            "goals": self.goals.to_dict(),
            "guards": self.guards.to_dict(),
            "modalities": self.modalities.to_dict(),
            "schema_version": self.schema_version,
            "source_grounding": self.source_grounding.to_dict(),
            "unsupported_formula_ids": list(self.unsupported_formula_ids),
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "DecompiledIntentReview":
        payload = _mapping(value)
        allowed = {
            "action_order",
            "declaration_digest",
            "declaration_id",
            "effects",
            "formula_ids",
            "goals",
            "guards",
            "modalities",
            "schema_version",
            "source_grounding",
            "unsupported_formula_ids",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise IntentDecompilerError(
                "unknown decompiled review field(s): " + ", ".join(unknown)
            )
        return cls(
            declaration_id=payload.get("declaration_id", ""),
            declaration_digest=payload.get("declaration_digest", ""),
            goals=FrozenMap(_mapping(payload.get("goals", {}))),
            modalities=FrozenMap(_mapping(payload.get("modalities", {}))),
            action_order=FrozenMap(
                _mapping(payload.get("action_order", {}))
            ),
            guards=FrozenMap(_mapping(payload.get("guards", {}))),
            effects=FrozenMap(_mapping(payload.get("effects", {}))),
            source_grounding=FrozenMap(
                _mapping(payload.get("source_grounding", {}))
            ),
            formula_ids=FrozenMap(
                _mapping(payload.get("formula_ids", {}))
            ),
            unsupported_formula_ids=tuple(
                payload.get("unsupported_formula_ids", ())
            ),
            schema_version=payload.get(
                "schema_version", INTENT_DECOMPILER_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class IntentRoundTripReport:
    """Semantic comparison result for an Intent document and formal artifact."""

    review: DecompiledIntentReview
    mutations: tuple[IntentSemanticMutation, ...] = ()
    schema_version: str = INTENT_DECOMPILER_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.review, DecompiledIntentReview):
            raise IntentDecompilerError(
                "review must be a DecompiledIntentReview"
            )
        mutations = tuple(sorted(
            self.mutations,
            key=lambda item: (
                item.kind.value,
                item.semantic_id,
                item.formula_id,
            ),
        ))
        object.__setattr__(self, "mutations", mutations)
        if self.schema_version != INTENT_DECOMPILER_VERSION:
            raise IntentDecompilerError(
                f"unsupported round-trip schema: {self.schema_version}"
            )

    @property
    def passed(self) -> bool:
        return not self.mutations

    @property
    def mutation_kinds(self) -> tuple[IntentSemanticMutationKind, ...]:
        return tuple(dict.fromkeys(item.kind for item in self.mutations))

    def mutations_of(
        self, kind: IntentSemanticMutationKind
    ) -> tuple[IntentSemanticMutation, ...]:
        normalized = IntentSemanticMutationKind(kind)
        return tuple(item for item in self.mutations if item.kind is normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutations": [item.to_dict() for item in self.mutations],
            "passed": self.passed,
            "review": self.review.to_dict(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "IntentRoundTripReport":
        payload = _mapping(value)
        allowed = {"mutations", "passed", "review", "schema_version"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise IntentDecompilerError(
                "unknown round-trip report field(s): " + ", ".join(unknown)
            )
        mutations = payload.get("mutations", ())
        if (
            isinstance(mutations, (str, bytes, bytearray))
            or not isinstance(mutations, Sequence)
        ):
            raise IntentDecompilerError("mutations must be a sequence")
        report = cls(
            review=DecompiledIntentReview.from_dict(
                _mapping(payload.get("review", {}))
            ),
            mutations=tuple(
                IntentSemanticMutation.from_dict(_mapping(item))
                for item in mutations
            ),
            schema_version=payload.get(
                "schema_version", INTENT_DECOMPILER_VERSION
            ),
        )
        if "passed" in payload and payload["passed"] is not report.passed:
            raise IntentDecompilerError(
                "serialized passed flag disagrees with report mutations"
            )
        return report


class IntentDecompiler:
    """Decompile formal views for review and detect semantic mutations."""

    version: Final = INTENT_DECOMPILER_VERSION

    def decompile(
        self, artifact: FormalizationArtifact
    ) -> DecompiledIntentReview:
        """Extract the semantic fields carried by an Intent formalization."""

        self._validate_artifact(artifact)
        goals: dict[str, Any] = {}
        modalities: dict[str, Any] = {}
        action_order: dict[str, Any] = {}
        guards: dict[str, Any] = {}
        effects: dict[str, Any] = {}
        source_grounding: dict[str, Any] = {}
        formula_ids: dict[str, Any] = {}
        unsupported: list[str] = []

        for formula in artifact.formulas:
            expression = _mapping(formula.expression)
            semantic_id = _node_id(formula)
            grounding_key = f"{formula.view_id}|{semantic_id}"
            source_grounding[grounding_key] = list(formula.source_ref_ids)
            formula_ids[grounding_key] = formula.formula_id
            if formula.opaque:
                unsupported.append(formula.formula_id)

            if formula.view_id == INTENT_MODAL_VIEW_ID:
                body = _mapping(expression.get("body"))
                semantic_id = _node_id(formula, "statement")
                if body.get("statement_kind") == StatementKind.GOAL.value:
                    goals[semantic_id] = body
                modalities[semantic_id] = expression.get("operator")
            elif formula.view_id == INTENT_ACTION_VIEW_ID:
                semantic_id = _node_id(formula, "action")
                effects[semantic_id] = {
                    "action_effect_ids": list(
                        _mapping(expression.get("action")).get(
                            "effect_ids", ()
                        )
                    ),
                    "effects": [
                        _mapping(item)
                        for item in expression.get("effects", ())
                    ],
                    "postcondition": [
                        _mapping(item)
                        for item in expression.get("postcondition", ())
                    ],
                }
            elif (
                formula.view_id == INTENT_WORKFLOW_VIEW_ID
                and expression.get("kind") == "workflow_temporal_transition"
            ):
                semantic_id = _node_id(formula, "control-edge")
                edge = _mapping(expression.get("edge"))
                action_order[semantic_id] = {
                    "kind": edge.get("kind"),
                    "operator": expression.get("operator"),
                    "source_action_id": edge.get("source_action_id"),
                    "target_action_id": edge.get("target_action_id"),
                }
                if edge.get("guard_statement_id") or expression.get("guard") is not None:
                    guards[semantic_id] = {
                        "guard": _mapping(expression.get("guard")),
                        "guard_statement_id": edge.get("guard_statement_id"),
                    }

        return DecompiledIntentReview(
            declaration_id=artifact.declaration_id,
            declaration_digest=artifact.declaration_digest,
            goals=FrozenMap(goals),
            modalities=FrozenMap(modalities),
            action_order=FrozenMap(action_order),
            guards=FrozenMap(guards),
            effects=FrozenMap(effects),
            source_grounding=FrozenMap(source_grounding),
            formula_ids=FrozenMap(formula_ids),
            unsupported_formula_ids=tuple(unsupported),
        )

    decompile_for_review = decompile

    def compare(
        self,
        document: IntentIRDocument | FormalizationArtifact,
        artifact: FormalizationArtifact | IntentIRDocument,
    ) -> IntentRoundTripReport:
        """Compare protected semantic dimensions with the source declaration."""

        if isinstance(document, FormalizationArtifact) and isinstance(
            artifact, IntentIRDocument
        ):
            document, artifact = artifact, document
        if not isinstance(document, IntentIRDocument) or not isinstance(
            artifact, FormalizationArtifact
        ):
            raise IntentDecompilerError(
                "compare requires one IntentIRDocument and one "
                "FormalizationArtifact"
            )
        document = validate_intent_ir(document)
        self._validate_artifact(artifact)
        review = self.decompile(artifact)
        mutations: list[IntentSemanticMutation] = []
        if artifact.declaration_id != document.document_id:
            raise IntentDecompilerError(
                "artifact declaration_id does not match the Intent document"
            )

        statements = {
            item.statement_id: item for item in document.statements
        }
        actions = {item.action_id: item for item in document.actions}
        all_sources = tuple(sorted(item.ref_id for item in document.sources))

        expected_goals = {
            item.statement_id: _statement_body(item)
            for item in document.statements
            if item.kind is StatementKind.GOAL
        }
        expected_modalities = {
            item.statement_id: _modal_operator(item)
            for item in document.statements
            if (
                item.kind is StatementKind.GOAL
                or item.modality is not IntentModality.ASSERTED
            )
        }
        expected_effects = {
            action.action_id: {
                "action_effect_ids": sorted(set(action.effect_ids)),
                "effects": [
                    statements[item].to_dict()
                    for item in action.effect_ids
                ],
                "postcondition": [
                    statements[item].to_dict()
                    for item in action.effect_ids
                ],
            }
            for action in document.actions
        }
        expected_order = {
            edge.edge_id: {
                "kind": edge.kind.value,
                "operator": _EDGE_OPERATORS[edge.kind],
                "source_action_id": edge.source_action_id,
                "target_action_id": edge.target_action_id,
            }
            for edge in document.control_edges
        }
        expected_guards = {
            edge.edge_id: {
                "guard": statements[edge.guard_statement_id].to_dict(),
                "guard_statement_id": edge.guard_statement_id,
            }
            for edge in document.control_edges
            if edge.guard_statement_id
        }

        self._compare_map(
            IntentSemanticMutationKind.GOAL,
            expected_goals,
            review.goals.to_dict(),
            review,
            INTENT_MODAL_VIEW_ID,
            mutations,
        )
        self._compare_map(
            IntentSemanticMutationKind.MODALITY,
            expected_modalities,
            review.modalities.to_dict(),
            review,
            INTENT_MODAL_VIEW_ID,
            mutations,
        )
        self._compare_map(
            IntentSemanticMutationKind.EFFECT,
            expected_effects,
            review.effects.to_dict(),
            review,
            INTENT_ACTION_VIEW_ID,
            mutations,
        )
        self._compare_map(
            IntentSemanticMutationKind.ACTION_ORDER,
            expected_order,
            review.action_order.to_dict(),
            review,
            INTENT_WORKFLOW_VIEW_ID,
            mutations,
        )
        self._compare_map(
            IntentSemanticMutationKind.GUARD,
            expected_guards,
            review.guards.to_dict(),
            review,
            INTENT_WORKFLOW_VIEW_ID,
            mutations,
        )

        # The typed fact view is an independent representation.  Comparing it
        # prevents a mutation from hiding behind an intact specialized view.
        for formula in artifact.formulas:
            expression = _mapping(formula.expression)
            if formula.view_id == INTENT_FACT_VIEW_ID:
                if expression.get("kind") == "typed_fact":
                    statement_id = _node_id(formula, "statement")
                    statement = statements.get(statement_id)
                    if statement is None:
                        continue
                    actual_body = {
                        key: value
                        for key, value in expression.items()
                        if key != "kind"
                    }
                    if (
                        statement.kind is StatementKind.GOAL
                        and actual_body != _statement_body(statement)
                    ):
                        mutations.append(
                            IntentSemanticMutation(
                                kind=IntentSemanticMutationKind.GOAL,
                                semantic_id=statement_id,
                                expected=_statement_body(statement),
                                actual=actual_body,
                                formula_id=formula.formula_id,
                                source_ref_ids=formula.source_ref_ids,
                                message=(
                                    f"typed fact goal semantics differ for "
                                    f"{statement_id}"
                                ),
                            )
                        )
                    if expression.get("modality") != statement.modality.value:
                        mutations.append(
                            IntentSemanticMutation(
                                kind=IntentSemanticMutationKind.MODALITY,
                                semantic_id=statement_id,
                                expected=statement.modality.value,
                                actual=expression.get("modality"),
                                formula_id=formula.formula_id,
                                source_ref_ids=formula.source_ref_ids,
                                message=(
                                    f"typed fact modality differs for "
                                    f"{statement_id}"
                                ),
                            )
                        )
                elif expression.get("kind") == "typed_action_fact":
                    action_id = _node_id(formula, "action")
                    action = actions.get(action_id)
                    actual_action = _mapping(expression.get("action"))
                    if action is not None and list(
                        actual_action.get("effect_ids", ())
                    ) != sorted(set(action.effect_ids)):
                        mutations.append(
                            IntentSemanticMutation(
                                kind=IntentSemanticMutationKind.EFFECT,
                                semantic_id=action_id,
                                expected=sorted(set(action.effect_ids)),
                                actual=list(
                                    actual_action.get("effect_ids", ())
                                ),
                                formula_id=formula.formula_id,
                                source_ref_ids=formula.source_ref_ids,
                                message=(
                                    f"typed action effect references differ for "
                                    f"{action_id}"
                                ),
                            )
                        )
            elif formula.view_id == INTENT_MODAL_VIEW_ID:
                statement_id = _node_id(formula, "statement")
                statement = statements.get(statement_id)
                body = _mapping(expression.get("body"))
                if (
                    statement is not None
                    and body.get("modality") != statement.modality.value
                ):
                    mutations.append(
                        IntentSemanticMutation(
                            kind=IntentSemanticMutationKind.MODALITY,
                            semantic_id=statement_id,
                            expected=statement.modality.value,
                            actual=body.get("modality"),
                            formula_id=formula.formula_id,
                            source_ref_ids=formula.source_ref_ids,
                            message=(
                                f"modal body modality differs for {statement_id}"
                            ),
                        )
                    )

        bindings = {
            item.subject_id: item for item in artifact.source_map.bindings
        }
        for formula in artifact.formulas:
            expression = _mapping(formula.expression)
            expected_refs = self._expected_sources(
                formula.view_id,
                expression,
                formula,
                statements=statements,
                actions=actions,
                all_sources=all_sources,
                document=document,
            )
            actual_refs = tuple(sorted(formula.source_ref_ids))
            if expected_refs is not None and actual_refs != expected_refs:
                mutations.append(
                    IntentSemanticMutation(
                        kind=IntentSemanticMutationKind.SOURCE_GROUNDING,
                        semantic_id=_node_id(formula),
                        expected=list(expected_refs),
                        actual=list(actual_refs),
                        formula_id=formula.formula_id,
                        source_ref_ids=actual_refs,
                    )
                )
            binding = bindings.get(formula.formula_id)
            if binding is not None and tuple(
                sorted(binding.source_ref_ids)
            ) != actual_refs:
                mutations.append(
                    IntentSemanticMutation(
                        kind=IntentSemanticMutationKind.SOURCE_GROUNDING,
                        semantic_id=_node_id(formula),
                        expected=list(actual_refs),
                        actual=list(sorted(binding.source_ref_ids)),
                        formula_id=formula.formula_id,
                        source_ref_ids=actual_refs,
                        message=(
                            f"formula/source-map grounding differs for "
                            f"{formula.formula_id}"
                        ),
                    )
                )

        for formula_id in review.unsupported_formula_ids:
            formula = next(
                item for item in artifact.formulas
                if item.formula_id == formula_id
            )
            mutations.append(
                IntentSemanticMutation(
                    kind=IntentSemanticMutationKind.UNSUPPORTED,
                    semantic_id=_node_id(formula),
                    expected={"opaque": False},
                    actual={"opaque": True},
                    formula_id=formula.formula_id,
                    source_ref_ids=formula.source_ref_ids,
                    message=(
                        f"formal semantics for {_node_id(formula)} are opaque "
                        "and require review"
                    ),
                )
            )
        return IntentRoundTripReport(review=review, mutations=tuple(mutations))

    validate_round_trip = compare
    detect_mutations = compare

    @staticmethod
    def _validate_artifact(artifact: FormalizationArtifact) -> None:
        if not isinstance(artifact, FormalizationArtifact):
            raise IntentDecompilerError(
                "artifact must be a FormalizationArtifact"
            )
        if artifact.domain != "intent":
            raise IntentDecompilerError(
                "IntentDecompiler requires an intent artifact"
            )

    @staticmethod
    def _compare_map(
        kind: IntentSemanticMutationKind,
        expected: dict[str, Any],
        actual: dict[str, Any],
        review: DecompiledIntentReview,
        view_id: str,
        mutations: list[IntentSemanticMutation],
    ) -> None:
        keys = sorted(set(expected).union(actual))
        formulas = review.formula_ids.to_dict()
        grounding = review.source_grounding.to_dict()
        for semantic_id in keys:
            expected_value = expected.get(semantic_id)
            actual_value = actual.get(semantic_id)
            if expected_value == actual_value:
                continue
            lookup = f"{view_id}|{semantic_id}"
            mutations.append(
                IntentSemanticMutation(
                    kind=kind,
                    semantic_id=semantic_id,
                    expected=expected_value,
                    actual=actual_value,
                    formula_id=str(formulas.get(lookup, "")),
                    source_ref_ids=tuple(grounding.get(lookup, ())),
                )
            )

    @staticmethod
    def _expected_sources(
        view_id: str,
        expression: dict[str, Any],
        formula: Any,
        *,
        statements: dict[str, IntentStatement],
        actions: dict[str, Any],
        all_sources: tuple[str, ...],
        document: IntentIRDocument,
    ) -> tuple[str, ...] | None:
        def refs(value: Any) -> set[str]:
            raw = tuple(value.source_ref_ids)
            return set(raw or all_sources)

        semantic_id = _node_id(formula)
        if view_id == INTENT_MODAL_VIEW_ID:
            statement = statements.get(_node_id(formula, "statement"))
            return tuple(sorted(refs(statement))) if statement else None
        if view_id == INTENT_ACTION_VIEW_ID:
            action = actions.get(_node_id(formula, "action"))
            if action is None:
                return None
            combined = refs(action)
            for statement_id in (
                *action.precondition_ids,
                *action.effect_ids,
                *action.verification_ids,
            ):
                combined.update(refs(statements[statement_id]))
            return tuple(sorted(combined))
        if view_id == INTENT_WORKFLOW_VIEW_ID:
            if expression.get("kind") == "workflow_boundary":
                return all_sources
            edges = {
                item.edge_id: item for item in document.control_edges
            }
            edge = edges.get(_node_id(formula, "control-edge"))
            if edge is None:
                return None
            combined = refs(edge)
            combined.update(refs(actions[edge.source_action_id]))
            combined.update(refs(actions[edge.target_action_id]))
            if edge.guard_statement_id:
                combined.update(refs(statements[edge.guard_statement_id]))
            return tuple(sorted(combined))
        body = _mapping(expression.get("body"))
        if body:
            statement = statements.get(semantic_id)
            return tuple(sorted(refs(statement))) if statement else None
        if expression.get("kind") == "typed_fact":
            statement = statements.get(_node_id(formula, "statement"))
            return tuple(sorted(refs(statement))) if statement else None
        if expression.get("kind") == "typed_action_fact":
            action = actions.get(_node_id(formula, "action"))
            return tuple(sorted(refs(action))) if action else None
        return None


decompile_intent_artifact = IntentDecompiler().decompile
compare_intent_round_trip = IntentDecompiler().compare


__all__ = [
    "INTENT_DECOMPILER_VERSION",
    "DecompiledIntentReview",
    "IntentDecompiler",
    "IntentDecompilerError",
    "IntentRoundTripReport",
    "IntentSemanticMutation",
    "IntentSemanticMutationKind",
    "compare_intent_round_trip",
    "decompile_intent_artifact",
]
