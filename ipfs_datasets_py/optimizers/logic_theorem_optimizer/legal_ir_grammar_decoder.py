"""Typed constrained decoding for LegalIR candidates.

The learned LegalIR heads are allowed to rank candidate productions, but they
must not receive metric reward for output that a deterministic compiler could
never consume.  This module validates decoded LegalIR payloads against compact
typed grammars before semantic metrics are scored.  It is intentionally
dependency-free and JSON-shape based so it can guard adapter outputs,
autoencoder targets, and rollout artifacts uniformly.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Optional

from .legal_ir_family_evaluator import canonical_legal_ir_evaluation_family


LEGAL_IR_GRAMMAR_DECODER_SCHEMA_VERSION: Final = "legal-ir-typed-grammar-decoder-v1"
LEGAL_IR_GRAMMAR_FAMILIES: Final[tuple[str, ...]] = (
    "deontic",
    "frame_logic",
    "tdfol",
    "knowledge_graphs",
    "cec",
    "external_provers",
    "decompiler",
    "temporal",
    "provenance",
)

_FAMILY_ALIASES: Final[Mapping[str, str]] = {
    "deontic": "deontic",
    "deontic_ir": "deontic",
    "deontic.ir": "deontic",
    "frame": "frame_logic",
    "frame_logic": "frame_logic",
    "flogic": "frame_logic",
    "modal.frame_logic": "frame_logic",
    "tdfol": "tdfol",
    "tdfol.prover": "tdfol",
    "kg": "knowledge_graphs",
    "knowledge_graph": "knowledge_graphs",
    "knowledge_graphs": "knowledge_graphs",
    "knowledge_graphs.neo4j_compat": "knowledge_graphs",
    "cec": "cec",
    "cec.native": "cec",
    "external_prover": "external_provers",
    "external_provers": "external_provers",
    "prover": "external_provers",
    "decompiler": "decompiler",
    "decompiler_plan": "decompiler",
    "temporal": "temporal",
    "temporal_logic": "temporal",
    "provenance": "provenance",
}

_PLACEHOLDER_RE: Final = re.compile(
    r"(\{\{[^}]*\}\}|<[^>]*(?:source|placeholder|todo|copy)[^>]*>|"
    r"\b(?:todo|tbd|placeholder|source_text|raw_source|copy_source|lorem ipsum)\b|"
    r"__[^_]*(?:source|placeholder|todo)[^_]*__)",
    re.IGNORECASE,
)
_SOURCE_TEXT_FIELD_RE: Final = re.compile(
    r"^(?:raw_source|source_text|copied_text|verbatim_text|source_copy)$",
    re.IGNORECASE,
)
_IDENT_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")


@dataclass(frozen=True, slots=True)
class LegalIRProductionSpec:
    """One typed production admitted by a LegalIR family grammar."""

    name: str
    family: str
    output_type: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "family": self.family,
            "name": self.name,
            "optional_fields": list(self.optional_fields),
            "output_type": self.output_type,
            "required_fields": list(self.required_fields),
        }


@dataclass(frozen=True, slots=True)
class LegalIRGrammarRejection:
    """Structured reason for rejecting a candidate or production."""

    reason: str
    path: str = "$"
    family: str = "unscoped"
    production: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "detail": self.detail,
            "family": self.family,
            "path": self.path,
            "production": self.production,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LegalIRGrammarValidation:
    """Validation result for one candidate IR object."""

    accepted: bool
    family: str
    candidate_ir: Any
    rejection_reasons: tuple[LegalIRGrammarRejection, ...] = ()
    selected_productions: tuple[str, ...] = ()
    masked_productions: tuple[str, ...] = ()
    schema_version: str = LEGAL_IR_GRAMMAR_DECODER_SCHEMA_VERSION

    @property
    def rejection_reason_names(self) -> tuple[str, ...]:
        return tuple(reason.reason for reason in self.rejection_reasons)

    @property
    def syntactic_validity_success_rate(self) -> float:
        return 1.0 if self.accepted else 0.0

    @property
    def source_copy_placeholder_penalty(self) -> float:
        return 1.0 if any(
            reason.reason in {"source_copy_placeholder", "raw_source_copy_field"}
            for reason in self.rejection_reasons
        ) else 0.0

    def metrics(self) -> dict[str, float]:
        rejection_count = float(len(self.rejection_reasons))
        invalid = 0.0 if self.accepted else 1.0
        values: dict[str, float] = {
            "legal_ir_grammar_accepted": 1.0 if self.accepted else 0.0,
            "legal_ir_grammar_invalid_production_penalty": invalid,
            "legal_ir_grammar_rejection_count": rejection_count,
            "legal_ir_grammar_rejection_ratio": invalid,
            "legal_ir_grammar_source_copy_placeholder_penalty": (
                self.source_copy_placeholder_penalty
            ),
            "legal_ir_grammar_syntactic_validity_success_rate": (
                self.syntactic_validity_success_rate
            ),
        }
        for reason in self.rejection_reasons:
            values[f"legal_ir_grammar_rejection_reason_{_metric_slug(reason.reason)}"] = 1.0
        return values

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "candidate_digest": _stable_digest(self.candidate_ir),
            "family": self.family,
            "masked_productions": list(self.masked_productions),
            "metrics": self.metrics(),
            "rejection_reasons": [
                reason.to_dict() for reason in self.rejection_reasons
            ],
            "schema_version": self.schema_version,
            "selected_productions": list(self.selected_productions),
        }


@dataclass(frozen=True, slots=True)
class ConstrainedLegalIRDecode:
    """Result of masking and selecting from scored LegalIR productions."""

    accepted: bool
    family: str
    decoded_ir: Any
    selected_production: str = ""
    selected_score: float = 0.0
    valid_scores: Mapping[str, float] = field(default_factory=dict)
    masked_scores: Mapping[str, float] = field(default_factory=dict)
    validation: LegalIRGrammarValidation = field(
        default_factory=lambda: LegalIRGrammarValidation(
            accepted=False,
            family="unscoped",
            candidate_ir=None,
            rejection_reasons=(
                LegalIRGrammarRejection(reason="no_candidate", family="unscoped"),
            ),
        )
    )
    schema_version: str = LEGAL_IR_GRAMMAR_DECODER_SCHEMA_VERSION

    @property
    def rejection_reasons(self) -> tuple[LegalIRGrammarRejection, ...]:
        return self.validation.rejection_reasons

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "decoded_ir": self.decoded_ir if self.accepted else None,
            "family": self.family,
            "masked_scores": {
                str(name): round(float(score), 12)
                for name, score in sorted(self.masked_scores.items())
            },
            "rejection_reasons": [
                reason.to_dict() for reason in self.rejection_reasons
            ],
            "schema_version": self.schema_version,
            "selected_production": self.selected_production,
            "selected_score": round(float(self.selected_score), 12),
            "valid_scores": {
                str(name): round(float(score), 12)
                for name, score in sorted(self.valid_scores.items())
            },
            "validation": self.validation.to_dict(),
        }


class LegalIRGrammarDecoder:
    """Validate and decode LegalIR candidates with family-specific grammars."""

    def __init__(
        self,
        *,
        production_specs: Optional[Sequence[LegalIRProductionSpec]] = None,
    ) -> None:
        specs = tuple(production_specs or default_legal_ir_production_specs())
        self.production_specs: dict[str, LegalIRProductionSpec] = {
            spec.name: spec for spec in specs
        }
        self.productions_by_family: dict[str, tuple[str, ...]] = {}
        for spec in specs:
            family = canonical_legal_ir_grammar_family(spec.family)
            self.productions_by_family.setdefault(family, ())
            self.productions_by_family[family] = (
                *self.productions_by_family[family],
                spec.name,
            )

    def validate(
        self,
        candidate_ir: Any,
        *,
        family: str = "",
        source_text: str = "",
        production: str = "",
    ) -> LegalIRGrammarValidation:
        family_name = infer_legal_ir_grammar_family(candidate_ir, family=family)
        candidate = _mapping_or_sequence(candidate_ir)
        rejections: list[LegalIRGrammarRejection] = []

        if candidate is None:
            rejections.append(
                LegalIRGrammarRejection(
                    reason="candidate_not_structured",
                    family=family_name,
                    production=production,
                    detail=type(candidate_ir).__name__,
                )
            )
            return _validation(candidate_ir, family_name, rejections, production)

        rejections.extend(
            _source_copy_rejections(
                candidate,
                source_text=source_text,
                family=family_name,
                production=production,
            )
        )
        family_validator = _FAMILY_VALIDATORS.get(family_name)
        if family_validator is None:
            rejections.append(
                LegalIRGrammarRejection(
                    reason="unsupported_family",
                    family=family_name,
                    production=production,
                )
            )
        else:
            rejections.extend(family_validator(candidate, family_name, production))
        return _validation(candidate_ir, family_name, rejections, production)

    def mask_invalid_productions(
        self,
        scored_productions: Mapping[str, Any] | Sequence[Any],
        *,
        family: str = "",
        source_text: str = "",
        context: Optional[Mapping[str, Any]] = None,
    ) -> ConstrainedLegalIRDecode:
        """Remove invalid productions before downstream metrics see them."""

        rows = _production_rows(scored_productions, context=context)
        valid_scores: dict[str, float] = {}
        masked_scores: dict[str, float] = {}
        validations: dict[str, LegalIRGrammarValidation] = {}
        for row in rows:
            name = row["name"]
            score = row["score"]
            output = row.get("output")
            row_family = row.get("family") or family
            validation = self.validate(
                output,
                family=str(row_family or ""),
                source_text=source_text,
                production=name,
            )
            validations[name] = validation
            if validation.accepted:
                valid_scores[name] = score
            else:
                masked_scores[name] = score

        if valid_scores:
            selected = max(valid_scores, key=lambda item: (valid_scores[item], item))
            validation = validations[selected]
            return ConstrainedLegalIRDecode(
                accepted=True,
                family=validation.family,
                decoded_ir=validation.candidate_ir,
                selected_production=selected,
                selected_score=valid_scores[selected],
                valid_scores=valid_scores,
                masked_scores=masked_scores,
                validation=validation,
            )

        reasons: list[LegalIRGrammarRejection] = []
        selected_family = canonical_legal_ir_grammar_family(family or "decompiler")
        for validation in validations.values():
            selected_family = validation.family
            reasons.extend(validation.rejection_reasons)
        if not reasons:
            reasons.append(
                LegalIRGrammarRejection(
                    reason="no_productions",
                    family=selected_family,
                )
            )
        validation = LegalIRGrammarValidation(
            accepted=False,
            family=selected_family,
            candidate_ir=None,
            rejection_reasons=tuple(_dedupe_rejections(reasons)),
            masked_productions=tuple(sorted(masked_scores)),
        )
        return ConstrainedLegalIRDecode(
            accepted=False,
            family=selected_family,
            decoded_ir=None,
            valid_scores={},
            masked_scores=masked_scores,
            validation=validation,
        )

    def decode(
        self,
        scored_productions: Mapping[str, Any] | Sequence[Any],
        *,
        family: str = "",
        source_text: str = "",
        context: Optional[Mapping[str, Any]] = None,
    ) -> ConstrainedLegalIRDecode:
        return self.mask_invalid_productions(
            scored_productions,
            family=family,
            source_text=source_text,
            context=context,
        )


def canonical_legal_ir_grammar_family(family: str) -> str:
    """Normalize grammar families, including view-name aliases."""

    normalized = str(family or "").strip().lower().replace("-", "_").replace("/", ".")
    normalized = normalized.removeprefix("legal_ir_view.").removeprefix(
        "legal-ir-view."
    )
    canonical = _FAMILY_ALIASES.get(normalized)
    if canonical:
        return canonical
    try:
        return canonical_legal_ir_evaluation_family(normalized)
    except ValueError:
        return "unscoped" if not normalized else normalized


def infer_legal_ir_grammar_family(candidate_ir: Any, *, family: str = "") -> str:
    explicit = canonical_legal_ir_grammar_family(family)
    if explicit and explicit != "unscoped":
        return explicit
    source = _object_to_mapping(candidate_ir)
    for key in ("family", "legal_ir_family", "view_family", "logic_family"):
        if key in source:
            resolved = canonical_legal_ir_grammar_family(str(source.get(key) or ""))
            if resolved != "unscoped":
                return resolved
    for key in ("legal_ir_view", "target_view", "view", "contract_id"):
        if key in source:
            resolved = canonical_legal_ir_grammar_family(str(source.get(key) or ""))
            if resolved != "unscoped":
                return resolved
    if any(key in source for key in ("obligations", "deontic_rules")):
        return "deontic"
    if any(key in source for key in ("triples", "frames", "frame_logic")):
        return "frame_logic"
    if any(key in source for key in ("formulas", "quantifiers", "predicates")):
        return "tdfol"
    if any(key in source for key in ("nodes", "edges", "graph")):
        return "knowledge_graphs"
    if any(key in source for key in ("counterexamples", "contexts", "events")):
        return "cec"
    if any(key in source for key in ("intervals", "temporal_windows", "relations")):
        return "temporal"
    if any(key in source for key in ("source_refs", "citations", "evidence")):
        return "provenance"
    if any(key in source for key in ("steps", "plan", "round_trip")):
        return "decompiler"
    return "unscoped"


def validate_legal_ir_candidate(
    candidate_ir: Any,
    *,
    family: str = "",
    source_text: str = "",
) -> LegalIRGrammarValidation:
    """Convenience API for validating one LegalIR payload."""

    return LegalIRGrammarDecoder().validate(
        candidate_ir,
        family=family,
        source_text=source_text,
    )


def constrained_legal_ir_decode(
    scored_productions: Mapping[str, Any] | Sequence[Any],
    *,
    family: str = "",
    source_text: str = "",
    context: Optional[Mapping[str, Any]] = None,
) -> ConstrainedLegalIRDecode:
    """Convenience API for masked production selection."""

    return LegalIRGrammarDecoder().decode(
        scored_productions,
        family=family,
        source_text=source_text,
        context=context,
    )


def default_legal_ir_production_specs() -> tuple[LegalIRProductionSpec, ...]:
    return (
        LegalIRProductionSpec(
            name="emit_deontic_rule",
            family="deontic",
            output_type="DeonticRule",
            required_fields=("modality", "subject", "action"),
            optional_fields=("condition", "exception", "object", "provenance"),
            description="obligation, permission, or prohibition over an actor/action",
        ),
        LegalIRProductionSpec(
            name="emit_frame_logic_triples",
            family="frame_logic",
            output_type="FrameLogicTriples",
            required_fields=("subject", "relation", "object"),
            optional_fields=("frame", "qualifiers", "provenance"),
        ),
        LegalIRProductionSpec(
            name="emit_tdfol_formula",
            family="tdfol",
            output_type="TDFOLFormula",
            required_fields=("predicate", "arguments"),
            optional_fields=("quantifier", "variables", "connective"),
        ),
        LegalIRProductionSpec(
            name="emit_knowledge_graph",
            family="knowledge_graphs",
            output_type="KnowledgeGraph",
            required_fields=("nodes", "edges"),
            optional_fields=("labels", "properties"),
        ),
        LegalIRProductionSpec(
            name="emit_cec_counterexample",
            family="cec",
            output_type="CounterexampleContext",
            required_fields=("events", "counterexamples"),
            optional_fields=("constraints", "contexts"),
        ),
        LegalIRProductionSpec(
            name="emit_external_prover_plan",
            family="external_provers",
            output_type="ExternalProverPlan",
            required_fields=("backend", "obligations"),
            optional_fields=("theory", "timeout", "route"),
        ),
        LegalIRProductionSpec(
            name="emit_temporal_window",
            family="temporal",
            output_type="TemporalWindow",
            required_fields=("intervals", "relations"),
            optional_fields=("bounds", "calendar", "timezone"),
        ),
        LegalIRProductionSpec(
            name="emit_provenance_receipt",
            family="provenance",
            output_type="ProvenanceReceipt",
            required_fields=("source_refs", "evidence"),
            optional_fields=("citations", "span_hashes", "receipts"),
        ),
        LegalIRProductionSpec(
            name="emit_decompiler_plan",
            family="decompiler",
            output_type="DecompilerPlan",
            required_fields=("steps", "target_view"),
            optional_fields=("round_trip", "source_copy_policy", "surface_template"),
        ),
    )


def grammar_metrics_from_validation(
    validation: LegalIRGrammarValidation,
) -> dict[str, float]:
    return validation.metrics()


def grammar_rejection_reason_names(
    validation: LegalIRGrammarValidation | ConstrainedLegalIRDecode,
) -> tuple[str, ...]:
    if isinstance(validation, ConstrainedLegalIRDecode):
        validation = validation.validation
    return validation.rejection_reason_names


def _validation(
    candidate_ir: Any,
    family: str,
    rejections: Sequence[LegalIRGrammarRejection],
    production: str,
) -> LegalIRGrammarValidation:
    deduped = tuple(_dedupe_rejections(rejections))
    return LegalIRGrammarValidation(
        accepted=not deduped,
        family=family,
        candidate_ir=candidate_ir,
        rejection_reasons=deduped,
        selected_productions=(production,) if production and not deduped else (),
        masked_productions=(production,) if production and deduped else (),
    )


def _dedupe_rejections(
    rejections: Sequence[LegalIRGrammarRejection],
) -> tuple[LegalIRGrammarRejection, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[LegalIRGrammarRejection] = []
    for rejection in rejections:
        key = (
            rejection.reason,
            rejection.path,
            rejection.family,
            rejection.production,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rejection)
    return tuple(deduped)


def _family_rejection(
    reason: str,
    *,
    family: str,
    path: str = "$",
    production: str = "",
    detail: str = "",
) -> LegalIRGrammarRejection:
    return LegalIRGrammarRejection(
        reason=reason,
        path=path,
        family=family,
        production=production,
        detail=detail,
    )


def _validate_deontic(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    rules = _items_from(source, "obligations", "deontic_rules", "rules", "clauses")
    if not rules:
        return (_family_rejection("missing_deontic_rule", family=family, production=production),)
    rejections: list[LegalIRGrammarRejection] = []
    allowed_modalities = {"obligation", "permission", "prohibition", "duty", "right"}
    for index, rule in enumerate(rules):
        entry = _object_to_mapping(rule)
        modality = str(entry.get("modality") or entry.get("operator") or "").lower()
        if modality not in allowed_modalities:
            rejections.append(
                _family_rejection(
                    "invalid_deontic_modality",
                    family=family,
                    path=f"$.rules[{index}].modality",
                    production=production,
                    detail=modality,
                )
            )
        for key in ("subject", "action"):
            if not _nonempty_text(entry.get(key)):
                rejections.append(
                    _family_rejection(
                        f"missing_deontic_{key}",
                        family=family,
                        path=f"$.rules[{index}].{key}",
                        production=production,
                    )
                )
    return tuple(rejections)


def _validate_frame_logic(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    triples = _items_from(source, "triples", "frame_logic", "relations")
    if not triples and isinstance(source.get("frames"), Sequence):
        triples = [
            relation
            for frame in _sequence(source.get("frames"))
            for relation in _items_from(_object_to_mapping(frame), "triples", "relations")
        ]
    if not triples:
        return (_family_rejection("missing_frame_logic_triple", family=family, production=production),)
    return tuple(
        rejection
        for index, triple in enumerate(triples)
        for rejection in _required_mapping_fields(
            triple,
            ("subject", "relation", "object"),
            family=family,
            path=f"$.triples[{index}]",
            production=production,
            reason_prefix="missing_frame_logic",
        )
    )


def _validate_tdfol(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    formulas = _items_from(source, "formulas", "rules", "clauses")
    if not formulas and ("predicate" in source or "formula" in source):
        formulas = [source]
    if not formulas:
        return (_family_rejection("missing_tdfol_formula", family=family, production=production),)
    rejections: list[LegalIRGrammarRejection] = []
    for index, formula in enumerate(formulas):
        entry = _object_to_mapping(formula)
        predicate = str(entry.get("predicate") or entry.get("name") or "").strip()
        if not _IDENT_RE.match(predicate):
            rejections.append(
                _family_rejection(
                    "invalid_tdfol_predicate",
                    family=family,
                    path=f"$.formulas[{index}].predicate",
                    production=production,
                    detail=predicate,
                )
            )
        arguments = entry.get("arguments", entry.get("args"))
        if not _sequence(arguments):
            rejections.append(
                _family_rejection(
                    "missing_tdfol_arguments",
                    family=family,
                    path=f"$.formulas[{index}].arguments",
                    production=production,
                )
            )
        quantifier = str(entry.get("quantifier") or "").strip().lower()
        if quantifier and quantifier not in {"forall", "exists", "none"}:
            rejections.append(
                _family_rejection(
                    "invalid_tdfol_quantifier",
                    family=family,
                    path=f"$.formulas[{index}].quantifier",
                    production=production,
                    detail=quantifier,
                )
            )
    return tuple(rejections)


def _validate_kg(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    graph = _object_to_mapping(source.get("graph")) if "graph" in source else source
    nodes = _sequence(graph.get("nodes"))
    edges = _sequence(graph.get("edges"))
    rejections: list[LegalIRGrammarRejection] = []
    if not nodes:
        rejections.append(_family_rejection("missing_kg_nodes", family=family, production=production))
    if not edges:
        rejections.append(_family_rejection("missing_kg_edges", family=family, production=production))
    node_ids = {
        str(_object_to_mapping(node).get("id") or "").strip()
        for node in nodes
        if str(_object_to_mapping(node).get("id") or "").strip()
    }
    for index, node in enumerate(nodes):
        rejections.extend(
            _required_mapping_fields(
                node,
                ("id", "label"),
                family=family,
                path=f"$.nodes[{index}]",
                production=production,
                reason_prefix="missing_kg_node",
            )
        )
    for index, edge in enumerate(edges):
        entry = _object_to_mapping(edge)
        rejections.extend(
            _required_mapping_fields(
                entry,
                ("source", "target", "label"),
                family=family,
                path=f"$.edges[{index}]",
                production=production,
                reason_prefix="missing_kg_edge",
            )
        )
        for endpoint in ("source", "target"):
            value = str(entry.get(endpoint) or "").strip()
            if value and node_ids and value not in node_ids:
                rejections.append(
                    _family_rejection(
                        "kg_edge_endpoint_unbound",
                        family=family,
                        path=f"$.edges[{index}].{endpoint}",
                        production=production,
                        detail=value,
                    )
                )
    return tuple(rejections)


def _validate_cec(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    events = _items_from(source, "events", "event_trace")
    counterexamples = _items_from(source, "counterexamples", "counterexample")
    rejections: list[LegalIRGrammarRejection] = []
    if not events:
        rejections.append(_family_rejection("missing_cec_events", family=family, production=production))
    if not counterexamples:
        rejections.append(_family_rejection("missing_cec_counterexample", family=family, production=production))
    for index, event in enumerate(events):
        rejections.extend(
            _required_mapping_fields(
                event,
                ("id", "type"),
                family=family,
                path=f"$.events[{index}]",
                production=production,
                reason_prefix="missing_cec_event",
            )
        )
    return tuple(rejections)


def _validate_external_provers(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    backend = str(source.get("backend") or source.get("prover") or "").strip()
    obligations = _items_from(source, "obligations", "proof_obligations", "goals")
    rejections: list[LegalIRGrammarRejection] = []
    if not backend:
        rejections.append(_family_rejection("missing_external_prover_backend", family=family, production=production))
    if not obligations:
        rejections.append(_family_rejection("missing_external_prover_obligation", family=family, production=production))
    return tuple(rejections)


def _validate_temporal(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    intervals = _items_from(source, "intervals", "temporal_windows", "windows")
    relations = _items_from(source, "relations", "temporal_relations")
    rejections: list[LegalIRGrammarRejection] = []
    if not intervals:
        rejections.append(_family_rejection("missing_temporal_interval", family=family, production=production))
    if not relations:
        rejections.append(_family_rejection("missing_temporal_relation", family=family, production=production))
    for index, interval in enumerate(intervals):
        entry = _object_to_mapping(interval)
        if not any(_nonempty_text(entry.get(key)) for key in ("start", "end", "duration", "date", "deadline")):
            rejections.append(
                _family_rejection(
                    "missing_temporal_bound",
                    family=family,
                    path=f"$.intervals[{index}]",
                    production=production,
                )
            )
    return tuple(rejections)


def _validate_provenance(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    refs = _items_from(source, "source_refs", "citations", "references")
    evidence = _items_from(source, "evidence", "receipts", "proof_evidence")
    rejections: list[LegalIRGrammarRejection] = []
    if not refs:
        rejections.append(_family_rejection("missing_provenance_source_ref", family=family, production=production))
    if not evidence:
        rejections.append(_family_rejection("missing_provenance_evidence", family=family, production=production))
    for index, ref in enumerate(refs):
        entry = _object_to_mapping(ref)
        if not any(_nonempty_text(entry.get(key)) for key in ("citation", "document_id", "span_hash", "source_hash")):
            rejections.append(
                _family_rejection(
                    "missing_provenance_reference_identifier",
                    family=family,
                    path=f"$.source_refs[{index}]",
                    production=production,
                )
            )
    return tuple(rejections)


def _validate_decompiler(
    candidate: Any,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(candidate)
    plan = _object_to_mapping(source.get("plan")) if isinstance(source.get("plan"), Mapping) else source
    steps = _items_from(plan, "steps", "operations")
    target_view = str(plan.get("target_view") or plan.get("legal_ir_view") or "").strip()
    rejections: list[LegalIRGrammarRejection] = []
    if not steps:
        rejections.append(_family_rejection("missing_decompiler_steps", family=family, production=production))
    if not target_view:
        rejections.append(_family_rejection("missing_decompiler_target_view", family=family, production=production))
    policy = str(plan.get("source_copy_policy") or "").strip().lower()
    if policy and policy not in {"hash_only", "span_hash_only", "citation_only", "no_source_text"}:
        rejections.append(
            _family_rejection(
                "unsafe_decompiler_source_copy_policy",
                family=family,
                path="$.source_copy_policy",
                production=production,
                detail=policy,
            )
        )
    for index, step in enumerate(steps):
        entry = _object_to_mapping(step)
        if not _nonempty_text(entry.get("op", entry.get("operation"))):
            rejections.append(
                _family_rejection(
                    "missing_decompiler_step_operation",
                    family=family,
                    path=f"$.steps[{index}].op",
                    production=production,
                )
            )
    return tuple(rejections)


_FAMILY_VALIDATORS = {
    "deontic": _validate_deontic,
    "frame_logic": _validate_frame_logic,
    "tdfol": _validate_tdfol,
    "knowledge_graphs": _validate_kg,
    "cec": _validate_cec,
    "external_provers": _validate_external_provers,
    "temporal": _validate_temporal,
    "provenance": _validate_provenance,
    "decompiler": _validate_decompiler,
}


def _required_mapping_fields(
    value: Any,
    fields: Sequence[str],
    *,
    family: str,
    path: str,
    production: str,
    reason_prefix: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source = _object_to_mapping(value)
    return tuple(
        _family_rejection(
            f"{reason_prefix}_{field}",
            family=family,
            path=f"{path}.{field}",
            production=production,
        )
        for field in fields
        if not _nonempty_text(source.get(field))
    )


def _source_copy_rejections(
    candidate: Any,
    *,
    source_text: str,
    family: str,
    production: str,
) -> tuple[LegalIRGrammarRejection, ...]:
    source_norm = _normalize_text(source_text)
    rejections: list[LegalIRGrammarRejection] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _SOURCE_TEXT_FIELD_RE.search(key_text):
                    rejections.append(
                        _family_rejection(
                            "raw_source_copy_field",
                            family=family,
                            path=child_path,
                            production=production,
                            detail=key_text,
                        )
                    )
                visit(child, child_path)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
            return
        if not isinstance(value, str):
            return
        text = value.strip()
        if not text:
            return
        if _PLACEHOLDER_RE.search(text):
            rejections.append(
                _family_rejection(
                    "source_copy_placeholder",
                    family=family,
                    path=path or "$",
                    production=production,
                    detail=text[:80],
                )
            )
            return
        if source_norm and len(_normalize_text(text)) >= 48:
            text_norm = _normalize_text(text)
            if text_norm == source_norm or text_norm in source_norm:
                rejections.append(
                    _family_rejection(
                        "source_copy_placeholder",
                        family=family,
                        path=path or "$",
                        production=production,
                        detail="candidate copies source text",
                    )
                )

    visit(candidate, "$")
    return tuple(rejections)


def _production_rows(
    scored_productions: Mapping[str, Any] | Sequence[Any],
    *,
    context: Optional[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    payloads = {}
    if isinstance(context, Mapping):
        raw_payloads = context.get("productions") or context.get("outputs") or {}
        if isinstance(raw_payloads, Mapping):
            payloads = dict(raw_payloads)
    rows: list[dict[str, Any]] = []
    if isinstance(scored_productions, Mapping):
        for name, value in scored_productions.items():
            row = _row_from_value(str(name), value, payloads.get(name))
            rows.append(row)
    else:
        for index, value in enumerate(_sequence(scored_productions)):
            rows.append(_row_from_value(f"production_{index}", value, None))
    return tuple(rows)


def _row_from_value(name: str, value: Any, context_output: Any) -> dict[str, Any]:
    source = _object_to_mapping(value)
    if source:
        row_name = str(source.get("name") or source.get("production") or name)
        score = _finite_float(source.get("score", source.get("logit", 0.0)))
        output = (
            source.get("output")
            if "output" in source
            else source.get("candidate_ir")
            if "candidate_ir" in source
            else source.get("decoded_ir")
            if "decoded_ir" in source
            else context_output
        )
        return {
            "family": source.get("family") or source.get("legal_ir_family") or "",
            "name": row_name,
            "output": output,
            "score": score,
        }
    return {
        "family": "",
        "name": name,
        "output": context_output,
        "score": _finite_float(value),
    }


def _mapping_or_sequence(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    source = _object_to_mapping(value)
    return source or None


def _object_to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None or isinstance(value, (str, bytes, bytearray, int, float, bool)):
        return {}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            mapped = to_dict()
        except TypeError:
            mapped = None
        if isinstance(mapped, Mapping):
            return dict(mapped)
    slots = getattr(value, "__slots__", ())
    if isinstance(slots, str):
        slots = (slots,)
    names = set(getattr(value, "__dict__", {}) or {})
    names.update(str(name) for name in slots if str(name) != "__weakref__")
    return {
        name: getattr(value, name)
        for name in sorted(names)
        if hasattr(value, name) and not name.startswith("_")
    }


def _items_from(source: Mapping[str, Any], *keys: str) -> tuple[Any, ...]:
    for key in keys:
        if key not in source:
            continue
        value = source.get(key)
        if isinstance(value, Mapping):
            return (value,)
        items = _sequence(value)
        if items:
            return items
    return ()


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    if value is None:
        return ()
    return ()


def _nonempty_text(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip()) and not _PLACEHOLDER_RE.search(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return math.isfinite(float(value))
    return value is not None


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _metric_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_") or "unknown"


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _stable_digest(value: Any) -> str:
    return hashlib.sha256(repr(value).encode("utf-8", "replace")).hexdigest()


__all__ = [
    "ConstrainedLegalIRDecode",
    "LEGAL_IR_GRAMMAR_DECODER_SCHEMA_VERSION",
    "LEGAL_IR_GRAMMAR_FAMILIES",
    "LegalIRGrammarDecoder",
    "LegalIRGrammarRejection",
    "LegalIRGrammarValidation",
    "LegalIRProductionSpec",
    "canonical_legal_ir_grammar_family",
    "constrained_legal_ir_decode",
    "default_legal_ir_production_specs",
    "grammar_metrics_from_validation",
    "grammar_rejection_reason_names",
    "infer_legal_ir_grammar_family",
    "validate_legal_ir_candidate",
]
