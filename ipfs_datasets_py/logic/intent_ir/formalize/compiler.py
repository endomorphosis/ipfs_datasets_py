"""Deterministic, source-grounded lowering from Intent IR to formal views.

The compiler in this module is deliberately syntactic.  It validates and
canonicalizes Intent IR, constructs typed formulas and solver-neutral proof
obligations, and records exact lineage in the shared provenance contracts.  It
does not invoke a model, theorem prover, solver, or source instruction.

Optional GraphRAG results are retained as context-only assumptions.  They are
never attached to proof obligations and cannot acquire proof authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

from ...formalization.compiler import (
    FormalizationArtifact,
    FormalizationCompiler,
    FormalizationCompilerConfig,
    UnsupportedSemanticsPolicy,
)
from ...formalization.samples import (
    FormalizationSample,
    FormalizationValidationError,
)
from ...formalization.views import (
    CrossViewLink,
    CrossViewRelation,
    FormalFormula,
    FormalSymbol,
    FormalizationView,
    SymbolTable,
    ViewRegistry,
)
from ...ir_core.claims import Assumption, ProofObligation
from ...ir_core.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticLocation,
    DiagnosticReport,
    DiagnosticSeverity,
)
from ...ir_core.provenance import (
    ConfigBinding,
    ProducerBinding,
    Provenance,
    ProvenanceBinding,
    SourceRef as CoreSourceRef,
    SourceReviewStatus,
)
from ..canonicalize import canonical_intent_ir_bytes, intent_ir_sha256
from ..decoder import decode_intent_ir
from ..graphrag.retrieval import RetrievedPremise, RetrievalResult
from ..schema import (
    ControlEdgeKind,
    IntentAction,
    IntentIRDocument,
    IntentModality,
    IntentStatement,
    NodeGrounding,
    StatementKind,
    validate_intent_ir,
)


INTENT_FORMALIZATION_COMPILER_VERSION: Final = (
    "intent-formalization-compiler/v1"
)
INTENT_FORMALIZATION_PRODUCER_ID: Final = "intent-formalization-compiler"
INTENT_FORMALIZATION_CONFIG_ID: Final = "intent-formalization-default"
INTENT_FORMALIZATION_DOMAIN: Final = "intent"

INTENT_FACT_VIEW_ID: Final = "intent-ir-view/facts/v1"
INTENT_MODAL_VIEW_ID: Final = "intent-ir-view/intention-deontic/v1"
INTENT_ACTION_VIEW_ID: Final = "intent-ir-view/action-hoare/v1"
INTENT_WORKFLOW_VIEW_ID: Final = "intent-ir-view/workflow-temporal/v1"
INTENT_INVARIANT_VIEW_ID: Final = "intent-ir-view/invariant/v1"
INTENT_FAILURE_VIEW_ID: Final = "intent-ir-view/failure/v1"
INTENT_VERIFICATION_VIEW_ID: Final = "intent-ir-view/verification/v1"

# Descriptive aliases make the registry convenient for callers without
# creating a second serialization contract.
INTENT_INTENTION_DEONTIC_VIEW_ID: Final = INTENT_MODAL_VIEW_ID
INTENT_ACTION_HOARE_VIEW_ID: Final = INTENT_ACTION_VIEW_ID
INTENT_WORKFLOW_TEMPORAL_VIEW_ID: Final = INTENT_WORKFLOW_VIEW_ID


class IntentFormalizationCompilerError(FormalizationValidationError):
    """Raised when an Intent sample cannot be faithfully compiled."""


INTENT_FORMALIZATION_VIEW_REGISTRY = ViewRegistry(
    (
        FormalizationView(
            view_id=INTENT_FACT_VIEW_ID,
            logic_family="typed_first_order",
            description="Typed Intent entities, predicates, and action facts.",
            capabilities=("source_grounding", "typed_symbols"),
            metadata={"intent_constructs": ["statement", "action"]},
        ),
        FormalizationView(
            view_id=INTENT_MODAL_VIEW_ID,
            logic_family="intention_deontic",
            description=(
                "Goals, intentions, requirements, permissions, and prohibitions."
            ),
            capabilities=("deontic_modality", "intention", "source_grounding"),
            metadata={"intent_constructs": ["goal", "modality"]},
        ),
        FormalizationView(
            view_id=INTENT_ACTION_VIEW_ID,
            logic_family="dynamic_hoare",
            description="Actions with preconditions, effects, and observations.",
            capabilities=("action_contracts", "hoare_triples", "source_grounding"),
            metadata={"intent_constructs": ["action"]},
        ),
        FormalizationView(
            view_id=INTENT_WORKFLOW_VIEW_ID,
            logic_family="workflow_temporal",
            description=(
                "Entry, terminal, sequencing, branching, retry, and concurrency."
            ),
            capabilities=("state_transitions", "temporal_control", "source_grounding"),
            metadata={"intent_constructs": ["control_edge", "workflow_boundary"]},
        ),
        FormalizationView(
            view_id=INTENT_INVARIANT_VIEW_ID,
            logic_family="safety",
            description="State invariants represented as always obligations.",
            capabilities=("invariants", "proof_obligations", "source_grounding"),
            metadata={"intent_constructs": ["invariant"]},
        ),
        FormalizationView(
            view_id=INTENT_FAILURE_VIEW_ID,
            logic_family="safety_liveness",
            description="Explicit failure conditions and failure transitions.",
            capabilities=(
                "failure_conditions",
                "proof_obligations",
                "source_grounding",
            ),
            metadata={"intent_constructs": ["failure"]},
        ),
        FormalizationView(
            view_id=INTENT_VERIFICATION_VIEW_ID,
            logic_family="verification_condition",
            description="Observable criteria and evidence obligations.",
            capabilities=("observations", "proof_obligations", "source_grounding"),
            metadata={"intent_constructs": ["verification"]},
        ),
    ),
    registry_id="intent-ir-formalization-views",
)
INTENT_VIEW_REGISTRY: Final = INTENT_FORMALIZATION_VIEW_REGISTRY


_EDGE_OPERATORS: Final[dict[ControlEdgeKind, str]] = {
    ControlEdgeKind.NEXT: "next",
    ControlEdgeKind.ON_SUCCESS: "on_success",
    ControlEdgeKind.ON_FAILURE: "on_failure",
    ControlEdgeKind.CONDITIONAL: "conditional",
    ControlEdgeKind.RETRY: "retry",
    ControlEdgeKind.PARALLEL: "parallel",
    ControlEdgeKind.JOIN: "join",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _derived_id(prefix: str, *parts: str) -> str:
    raw = "\0".join(parts)
    readable = ":".join(parts)
    candidate = f"{prefix}:{readable}"
    if len(candidate) <= 256 and all(
        character.isascii()
        and (character.isalnum() or character in "._:/-")
        for character in candidate
    ):
        return candidate
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _binding_id(subject_id: str, purpose: str) -> str:
    digest = hashlib.sha256(
        f"{purpose}\0{subject_id}".encode("utf-8")
    ).hexdigest()
    return f"binding:intent:{purpose}:{digest[:32]}"


def _node_id(kind: str, record_id: str) -> str:
    return _derived_id(f"intent-node:{kind}", record_id)


def _formula_id(view: str, kind: str, record_id: str) -> str:
    return _derived_id(f"formula:intent:{view}:{kind}", record_id)


def _review_status(value: Any) -> SourceReviewStatus:
    try:
        return SourceReviewStatus(value.value)
    except (AttributeError, ValueError):
        return SourceReviewStatus.UNREVIEWED


def _source_ref(source: Any) -> CoreSourceRef:
    metadata: dict[str, Any] = {
        "content_binding": "declared_source_bytes",
        "intent_review_status": source.review_status.value,
    }
    if source.span is not None:
        # Intent v1 records character coordinates but does not assert that
        # character offsets equal byte offsets.  Retain them without inventing
        # a shared byte span.
        metadata["intent_character_span"] = source.span.to_dict()
    return CoreSourceRef(
        ref_id=source.ref_id,
        source_uri=source.source_uri,
        source_id=source.source_id,
        source_revision=source.source_revision,
        content_sha256=source.content_sha256,
        container_uri=source.container_uri,
        container_sha256=source.container_sha256,
        content_cid=source.content_cid,
        license_expression=source.license_expression,
        review_status=_review_status(source.review_status),
        metadata=metadata,
    )


def _sources_for(
    source_ref_ids: Sequence[str],
    *,
    all_source_ids: tuple[str, ...],
) -> tuple[str, ...]:
    refs = tuple(sorted(set(source_ref_ids)))
    unknown = set(refs) - set(all_source_ids)
    if unknown:
        raise IntentFormalizationCompilerError(
            "Intent node references unknown sources: " + ", ".join(sorted(unknown))
        )
    # Inferred nodes may be source-free in Intent IR.  Their formulas remain
    # explicitly assumptions and are grounded to the declaration's source set.
    return refs or all_source_ids


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


def _premise_payload(value: Any) -> tuple[dict[str, Any], tuple[str, ...], str]:
    if isinstance(value, RetrievedPremise):
        payload = value.to_dict()
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        raise IntentFormalizationCompilerError(
            "graph premises must be RetrievedPremise values or mappings"
        )
    if payload.get("proof_authority", False) is not False:
        raise IntentFormalizationCompilerError(
            "retrieved premises cannot have proof authority"
        )
    if payload.get("authority", "context_only") != "context_only":
        raise IntentFormalizationCompilerError(
            "retrieved premise authority must be context_only"
        )
    node_id = str(payload.get("node_id") or "")
    if not node_id:
        raise IntentFormalizationCompilerError(
            "retrieved premise requires a node_id"
        )
    raw_sources = payload.get("source_ids", ())
    if isinstance(raw_sources, (str, bytes, bytearray)) or not isinstance(
        raw_sources, Sequence
    ):
        raise IntentFormalizationCompilerError(
            "retrieved premise source_ids must be a sequence"
        )
    source_ids = tuple(sorted({str(item) for item in raw_sources if str(item)}))
    payload["authority"] = "context_only"
    payload["proof_authority"] = False
    return payload, source_ids, node_id


def _graph_context(
    value: Any,
) -> tuple[
    dict[str, Any] | None,
    tuple[tuple[dict[str, Any], tuple[str, ...], str], ...],
]:
    if value is None:
        return None, ()
    raw_premises: Sequence[Any]
    if isinstance(value, RetrievalResult):
        context = value.to_dict()
        raw_premises = value.premises
    elif isinstance(value, Mapping):
        context = dict(value)
        candidate = context.get("premises", ())
        if isinstance(candidate, (str, bytes, bytearray)) or not isinstance(
            candidate, Sequence
        ):
            raise IntentFormalizationCompilerError(
                "graph context premises must be a sequence"
            )
        raw_premises = candidate
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        raw_premises = value
        context = {
            "authority": "context_only",
            "premises": [
                item.to_dict() if isinstance(item, RetrievedPremise) else dict(item)
                for item in value
            ],
        }
    else:
        raise IntentFormalizationCompilerError(
            "graph context must be a RetrievalResult, mapping, or premise sequence"
        )
    premises = tuple(_premise_payload(item) for item in raw_premises)
    context["premises"] = [item[0] for item in premises]
    if context.get("proof_authority", False) is not False:
        raise IntentFormalizationCompilerError(
            "graph context cannot have proof authority"
        )
    if context.get("authority", "context_only") != "context_only":
        raise IntentFormalizationCompilerError(
            "graph context authority must be context_only"
        )
    context["authority"] = "context_only"
    context["proof_authority"] = False
    return context, premises


class IntentFormalizationCompiler(FormalizationCompiler):
    """Compile validated Intent IR into deterministic shared formal views."""

    producer_id: Final = INTENT_FORMALIZATION_PRODUCER_ID
    producer_version: Final = INTENT_FORMALIZATION_COMPILER_VERSION
    view_registry: Final = INTENT_FORMALIZATION_VIEW_REGISTRY

    def adapt_sample(self, document: IntentIRDocument) -> FormalizationSample:
        """Create a source-grounded, canonical sample from one Intent document."""

        document = validate_intent_ir(document)
        canonical = canonical_intent_ir_bytes(document)
        digest = hashlib.sha256(canonical).hexdigest()
        sample_id = f"sample:intent:{digest[:32]}"
        all_source_ids = tuple(sorted(source.ref_id for source in document.sources))
        core_sources = tuple(_source_ref(source) for source in document.sources)
        bindings: list[ProvenanceBinding] = [
            ProvenanceBinding(
                binding_id=_binding_id(document.document_id, "document"),
                subject_id=document.document_id,
                source_ref_ids=all_source_ids,
                metadata={
                    "intent_construct": "document",
                    "intent_document_id": document.document_id,
                },
            ),
            ProvenanceBinding(
                binding_id=_binding_id(
                    _node_id("document", document.document_id), "input"
                ),
                subject_id=_node_id("document", document.document_id),
                source_ref_ids=all_source_ids,
                parent_subject_ids=(document.document_id,),
                derived=True,
                metadata={
                    "intent_construct": "document",
                    "intent_node_id": document.document_id,
                    "node_grounding": NodeGrounding.GROUNDED.value,
                },
            ),
        ]

        assumptions: list[Assumption] = []
        assumption_by_node: dict[str, str] = {}

        def bind_node(
            kind: str,
            record_id: str,
            source_refs: Sequence[str],
            grounding: NodeGrounding,
        ) -> tuple[str, tuple[str, ...]]:
            node_id = _node_id(kind, record_id)
            refs = _sources_for(source_refs, all_source_ids=all_source_ids)
            bindings.append(
                ProvenanceBinding(
                    binding_id=_binding_id(node_id, "input"),
                    subject_id=node_id,
                    source_ref_ids=refs,
                    parent_subject_ids=(document.document_id,),
                    derived=True,
                    metadata={
                        "intent_construct": kind,
                        "intent_node_id": record_id,
                        "node_grounding": grounding.value,
                    },
                )
            )
            return node_id, refs

        for statement in sorted(
            document.statements, key=lambda item: item.statement_id
        ):
            node_id, refs = bind_node(
                "statement",
                statement.statement_id,
                statement.source_ref_ids,
                statement.grounding,
            )
            if (
                statement.kind is StatementKind.ASSUMPTION
                or statement.grounding is NodeGrounding.INFERRED
                or float(statement.confidence) < 1.0
            ):
                assumption_id = _derived_id(
                    "assumption:intent:statement", statement.statement_id
                )
                assumptions.append(
                    Assumption(
                        assumption_id=assumption_id,
                        statement=statement.normalized_text,
                        source_refs=refs,
                        metadata={
                            "intent_node_id": statement.statement_id,
                            "intent_node_ref": node_id,
                            "kind": statement.kind.value,
                            "node_grounding": statement.grounding.value,
                            "stated_confidence": float(statement.confidence),
                            "uncertain": float(statement.confidence) < 1.0,
                        },
                    )
                )
                assumption_by_node[node_id] = assumption_id

        for action in sorted(document.actions, key=lambda item: item.action_id):
            node_id, refs = bind_node(
                "action",
                action.action_id,
                action.source_ref_ids,
                action.grounding,
            )
            if action.grounding is NodeGrounding.INFERRED:
                assumption_id = _derived_id(
                    "assumption:intent:action", action.action_id
                )
                assumptions.append(
                    Assumption(
                        assumption_id=assumption_id,
                        statement=f"{action.actor} {action.verb}",
                        source_refs=refs,
                        metadata={
                            "intent_node_id": action.action_id,
                            "intent_node_ref": node_id,
                            "kind": "action",
                            "node_grounding": action.grounding.value,
                        },
                    )
                )
                assumption_by_node[node_id] = assumption_id

        for edge in sorted(document.control_edges, key=lambda item: item.edge_id):
            node_id, refs = bind_node(
                "control-edge",
                edge.edge_id,
                edge.source_ref_ids,
                edge.grounding,
            )
            if edge.grounding is NodeGrounding.INFERRED:
                assumption_id = _derived_id(
                    "assumption:intent:control-edge", edge.edge_id
                )
                assumptions.append(
                    Assumption(
                        assumption_id=assumption_id,
                        statement=(
                            f"{edge.kind.value}({edge.source_action_id},"
                            f"{edge.target_action_id})"
                        ),
                        source_refs=refs,
                        metadata={
                            "intent_node_id": edge.edge_id,
                            "intent_node_ref": node_id,
                            "kind": "control_edge",
                            "node_grounding": edge.grounding.value,
                        },
                    )
                )
                assumption_by_node[node_id] = assumption_id

        provenance = Provenance(
            provenance_id=f"provenance:intent:{digest[:32]}",
            sources=core_sources,
            bindings=tuple(bindings),
            metadata={
                "compiler_adapter_schema": INTENT_FORMALIZATION_COMPILER_VERSION,
                "intent_ir_digest": f"sha256:{digest}",
            },
        )
        return FormalizationSample(
            sample_id=sample_id,
            domain=INTENT_FORMALIZATION_DOMAIN,
            declaration_id=document.document_id,
            declaration_digest=f"sha256:{digest}",
            payload={
                "adapter_schema_version": INTENT_FORMALIZATION_COMPILER_VERSION,
                "declaration": document.to_dict(),
                "declaration_digest": f"sha256:{digest}",
                "input_scope": "intent_ir_declaration_only",
            },
            provenance=provenance,
            source_ref_ids=all_source_ids,
            assumptions=tuple(assumptions),
            tags=("declaration", "intent"),
            metadata={
                "adapter_schema_version": INTENT_FORMALIZATION_COMPILER_VERSION,
                "intent_ir_digest": f"sha256:{digest}",
            },
        )

    to_formalization_sample = adapt_sample

    def default_config(
        self, sample_or_document: FormalizationSample | IntentIRDocument
    ) -> FormalizationCompilerConfig:
        sample = (
            sample_or_document
            if isinstance(sample_or_document, FormalizationSample)
            else self.adapt_sample(sample_or_document)
        )
        document = self._sample_document(sample)
        targets = {INTENT_FACT_VIEW_ID}
        if any(
            statement.kind is StatementKind.GOAL
            or statement.modality is not IntentModality.ASSERTED
            for statement in document.statements
        ):
            targets.add(INTENT_MODAL_VIEW_ID)
        if document.actions:
            targets.update((INTENT_ACTION_VIEW_ID, INTENT_WORKFLOW_VIEW_ID))
        if any(
            item.kind is StatementKind.INVARIANT for item in document.statements
        ):
            targets.add(INTENT_INVARIANT_VIEW_ID)
        if any(item.kind is StatementKind.FAILURE for item in document.statements):
            targets.add(INTENT_FAILURE_VIEW_ID)
        if any(
            item.kind is StatementKind.VERIFICATION
            for item in document.statements
        ):
            targets.add(INTENT_VERIFICATION_VIEW_ID)
        return FormalizationCompilerConfig(
            compiler_id=self.producer_id,
            compiler_version=self.producer_version,
            target_view_ids=tuple(targets),
            config_id=INTENT_FORMALIZATION_CONFIG_ID,
            producer_id=self.producer_id,
            unsupported_policy=UnsupportedSemanticsPolicy.PRESERVE_OPAQUE,
            options={
                "graph_context_authority": "context_only",
                "proof_backend_execution": False,
                "retrieved_premises_are_proofs": False,
            },
        )

    def compile(
        self,
        sample: FormalizationSample | IntentIRDocument,
        config: FormalizationCompilerConfig | None = None,
        *,
        graph_context: Any = None,
        graph_projection: Any = None,
    ) -> FormalizationArtifact:
        """Compile an Intent sample or document without invoking a backend.

        ``graph_projection`` is the legacy Intent protocol spelling for
        ``graph_context``.  Supplying both is rejected to avoid ambiguous
        artifact identities.
        """

        if graph_context is not None and graph_projection is not None:
            raise IntentFormalizationCompilerError(
                "supply graph_context or graph_projection, not both"
            )
        if isinstance(sample, IntentIRDocument):
            sample = self.adapt_sample(sample)
        if not isinstance(sample, FormalizationSample):
            raise IntentFormalizationCompilerError(
                "Intent compiler requires an IntentIRDocument or FormalizationSample"
            )
        config = config or self.default_config(sample)
        if not isinstance(config, FormalizationCompilerConfig):
            raise IntentFormalizationCompilerError(
                "config must be a FormalizationCompilerConfig"
            )
        document = self._sample_document(sample)
        unknown_views = set(config.target_view_ids) - set(self.view_registry.view_ids)
        if unknown_views:
            raise IntentFormalizationCompilerError(
                "Intent compiler targets unknown views: "
                + ", ".join(sorted(unknown_views))
            )
        context, retrieved = _graph_context(
            graph_context if graph_context is not None else graph_projection
        )
        return self._compile(sample, document, config, context, retrieved)

    def _compile(
        self,
        sample: FormalizationSample,
        document: IntentIRDocument,
        config: FormalizationCompilerConfig,
        context: dict[str, Any] | None,
        retrieved: tuple[tuple[dict[str, Any], tuple[str, ...], str], ...],
    ) -> FormalizationArtifact:
        all_sources = tuple(sorted(item.ref_id for item in sample.provenance.sources))
        statements = {item.statement_id: item for item in document.statements}
        actions = {item.action_id: item for item in document.actions}
        formulas: list[FormalFormula] = []
        obligations: list[ProofObligation] = []
        links: list[CrossViewLink] = []
        diagnostics: list[Diagnostic] = []
        bindings = list(sample.provenance.bindings)
        symbol_specs: dict[str, dict[str, Any]] = {}
        formula_by_key: dict[tuple[str, str, str], str] = {}
        binding_producer_id = config.producer_id or self.producer_id
        severity = (
            DiagnosticSeverity.ERROR
            if config.strict_unsupported
            else DiagnosticSeverity.WARNING
        )

        assumptions = list(sample.assumptions)
        assumption_by_node = {
            str(item.metadata.get("intent_node_ref")): item.assumption_id
            for item in sample.assumptions
            if item.metadata.get("intent_node_ref")
        }
        assumption_ids_seen = {item.assumption_id for item in assumptions}
        for premise, premise_sources, premise_node_id in retrieved:
            digest = hashlib.sha256(_canonical_bytes(premise)).hexdigest()
            assumption_id = f"assumption:intent:retrieved:{digest[:32]}"
            if assumption_id in assumption_ids_seen:
                continue
            assumption_ids_seen.add(assumption_id)
            known_refs = tuple(
                sorted(set(premise_sources).intersection(all_sources))
            )
            assumptions.append(
                Assumption(
                    assumption_id=assumption_id,
                    statement=_canonical_bytes(premise).decode("utf-8"),
                    source_refs=known_refs or sample.source_ref_ids,
                    metadata={
                        "authority": "context_only",
                        "graph_digest": premise.get("graph_digest", ""),
                        "premise": premise,
                        "premise_node_id": premise_node_id,
                        "proof_authority": False,
                        "source_resolution": (
                            "intent_source_refs"
                            if known_refs
                            else "query_source_fallback"
                        ),
                    },
                )
            )

        def refs_for_node(node: Any) -> tuple[str, ...]:
            return _sources_for(
                node.source_ref_ids, all_source_ids=all_sources
            )

        def combined_refs(*nodes: Any) -> tuple[str, ...]:
            refs: set[str] = set()
            for node in nodes:
                refs.update(refs_for_node(node))
            return tuple(sorted(refs)) or all_sources

        def add_symbol(
            *,
            node_kind: str,
            node_id: str,
            role: str,
            name: str,
            sort: str,
            refs: tuple[str, ...],
        ) -> str:
            symbol_id = _derived_id(
                f"symbol:intent:{node_kind}:{role}", node_id, name
            )
            spec = symbol_specs.setdefault(
                symbol_id,
                {
                    "kind": "predicate"
                    if role in {"predicate", "verb", "transition"}
                    else "constant",
                    "name": name.strip(),
                    "node_id": node_id,
                    "role": role,
                    "sort": sort,
                    "sources": set(),
                },
            )
            spec["sources"].update(refs)
            return symbol_id

        def unsupported_formula(
            formula: FormalFormula,
            *,
            reason: str,
            field_path: str,
        ) -> None:
            diagnostics.append(
                Diagnostic(
                    code=DiagnosticCode.UNSUPPORTED_FEATURE,
                    message=reason,
                    severity=severity,
                    location=DiagnosticLocation(
                        subject_ids=(
                            *formula.input_node_ids,
                            formula.formula_id,
                        ),
                        source_ref_ids=formula.source_ref_ids,
                        span_ids=formula.span_ids,
                        field_path=field_path,
                    ),
                    producer_id=binding_producer_id,
                    config_id=config.config_id,
                    metadata={
                        "opaque_formula_id": formula.formula_id,
                        "retained_as_opaque": True,
                        "view_id": formula.view_id,
                    },
                )
            )

        def emit(
            *,
            view_id: str,
            view_token: str,
            node_kind: str,
            record_id: str,
            expression: Mapping[str, Any],
            input_nodes: Sequence[tuple[str, str]],
            refs: tuple[str, ...],
            symbol_ids: Sequence[str] = (),
            assumption_ids: Sequence[str] = (),
            opaque_reason: str = "",
            field_path: str = "",
        ) -> str:
            formula_id = _formula_id(view_token, node_kind, record_id)
            normalized_inputs = tuple(dict.fromkeys(input_nodes))
            formula = FormalFormula(
                formula_id=formula_id,
                view_id=view_id,
                expression=expression,
                symbol_ids=tuple(symbol_ids),
                source_ref_ids=refs,
                assumption_ids=tuple(assumption_ids),
                input_node_ids=tuple(
                    _node_id(kind, identifier)
                    for kind, identifier in normalized_inputs
                ),
                opaque=bool(opaque_reason),
                metadata={
                    "intent_node_ids": [
                        identifier for _, identifier in normalized_inputs
                    ],
                    "intent_node_kinds": [
                        kind for kind, _ in normalized_inputs
                    ],
                    "retains_source_semantics": True,
                },
            )
            formulas.append(formula)
            formula_by_key[(view_token, node_kind, record_id)] = formula_id
            bindings.append(
                ProvenanceBinding(
                    binding_id=_binding_id(formula_id, "formula"),
                    subject_id=formula_id,
                    source_ref_ids=refs,
                    producer_id=binding_producer_id,
                    config_id=config.config_id,
                    parent_subject_ids=formula.input_node_ids,
                    derived=True,
                )
            )
            if opaque_reason:
                unsupported_formula(
                    formula,
                    reason=opaque_reason,
                    field_path=field_path,
                )
            return formula_id

        def node_assumptions(kind: str, record_id: str) -> tuple[str, ...]:
            value = assumption_by_node.get(_node_id(kind, record_id))
            return (value,) if value else ()

        # Typed facts retain every statement, including constructs that also
        # lower into a specialized view.
        if INTENT_FACT_VIEW_ID in config.target_view_ids:
            for statement in sorted(
                document.statements, key=lambda item: item.statement_id
            ):
                refs = refs_for_node(statement)
                predicate_name = (
                    statement.predicate
                    or f"statement:{statement.kind.value}"
                )
                symbol_ids = [
                    add_symbol(
                        node_kind="statement",
                        node_id=statement.statement_id,
                        role="predicate",
                        name=predicate_name,
                        sort="predicate",
                        refs=refs,
                    )
                ]
                for index, argument in enumerate(statement.arguments):
                    symbol_ids.append(
                        add_symbol(
                            node_kind="statement",
                            node_id=statement.statement_id,
                            role=f"argument-{index}",
                            name=argument,
                            sort="term",
                            refs=refs,
                        )
                    )
                emit(
                    view_id=INTENT_FACT_VIEW_ID,
                    view_token="facts",
                    node_kind="statement",
                    record_id=statement.statement_id,
                    expression={"kind": "typed_fact", **_statement_body(statement)},
                    input_nodes=(("statement", statement.statement_id),),
                    refs=refs,
                    symbol_ids=symbol_ids,
                    assumption_ids=node_assumptions(
                        "statement", statement.statement_id
                    ),
                    opaque_reason=(
                        "Intent statement has no typed predicate; normalized text "
                        "was retained as an opaque fact"
                        if not statement.predicate
                        else ""
                    ),
                    field_path=f"/statements/{statement.statement_id}/predicate",
                )
            for action in sorted(document.actions, key=lambda item: item.action_id):
                refs = refs_for_node(action)
                symbol_ids = self._action_symbols(
                    action, refs=refs, add_symbol=add_symbol
                )
                emit(
                    view_id=INTENT_FACT_VIEW_ID,
                    view_token="facts",
                    node_kind="action",
                    record_id=action.action_id,
                    expression={
                        "action": action.to_dict(),
                        "kind": "typed_action_fact",
                    },
                    input_nodes=(("action", action.action_id),),
                    refs=refs,
                    symbol_ids=symbol_ids,
                    assumption_ids=node_assumptions("action", action.action_id),
                )

        # Goal/intention and deontic lowering.
        if INTENT_MODAL_VIEW_ID in config.target_view_ids:
            for statement in sorted(
                document.statements, key=lambda item: item.statement_id
            ):
                if (
                    statement.kind is not StatementKind.GOAL
                    and statement.modality is IntentModality.ASSERTED
                ):
                    continue
                refs = refs_for_node(statement)
                symbol_id = add_symbol(
                    node_kind="statement",
                    node_id=statement.statement_id,
                    role="predicate",
                    name=statement.predicate
                    or f"statement:{statement.kind.value}",
                    sort="predicate",
                    refs=refs,
                )
                emit(
                    view_id=INTENT_MODAL_VIEW_ID,
                    view_token="modal",
                    node_kind="statement",
                    record_id=statement.statement_id,
                    expression={
                        "body": _statement_body(statement),
                        "kind": "intention_deontic_formula",
                        "operator": _modal_operator(statement),
                    },
                    input_nodes=(("statement", statement.statement_id),),
                    refs=refs,
                    symbol_ids=(symbol_id,),
                    assumption_ids=node_assumptions(
                        "statement", statement.statement_id
                    ),
                    opaque_reason=(
                        "Modal statement has no typed predicate; its normalized "
                        "body was retained opaquely"
                        if not statement.predicate
                        else ""
                    ),
                    field_path=f"/statements/{statement.statement_id}/predicate",
                )

        # Hoare-style action contracts explicitly include all referenced IR
        # statement nodes and the union of their sources.
        if INTENT_ACTION_VIEW_ID in config.target_view_ids:
            for action in sorted(document.actions, key=lambda item: item.action_id):
                related = [
                    statements[identifier]
                    for identifier in (
                        *action.precondition_ids,
                        *action.effect_ids,
                        *action.verification_ids,
                    )
                ]
                refs = combined_refs(action, *related)
                input_nodes = [
                    ("action", action.action_id),
                    *(("statement", item.statement_id) for item in related),
                ]
                relevant_assumptions = set(
                    node_assumptions("action", action.action_id)
                )
                for identifier in action.precondition_ids:
                    relevant_assumptions.update(
                        node_assumptions("statement", identifier)
                    )
                emit(
                    view_id=INTENT_ACTION_VIEW_ID,
                    view_token="action",
                    node_kind="action",
                    record_id=action.action_id,
                    expression={
                        "action": action.to_dict(),
                        "effects": [
                            statements[item].to_dict()
                            for item in action.effect_ids
                        ],
                        "kind": "hoare_action_contract",
                        "postcondition": [
                            statements[item].to_dict()
                            for item in action.effect_ids
                        ],
                        "precondition": [
                            statements[item].to_dict()
                            for item in action.precondition_ids
                        ],
                        "verification": [
                            statements[item].to_dict()
                            for item in action.verification_ids
                        ],
                    },
                    input_nodes=input_nodes,
                    refs=refs,
                    symbol_ids=self._action_symbols(
                        action, refs=refs, add_symbol=add_symbol
                    ),
                    assumption_ids=tuple(sorted(relevant_assumptions)),
                )

        # Temporal workflow formulas cover both graph boundaries and edges.
        if INTENT_WORKFLOW_VIEW_ID in config.target_view_ids and document.actions:
            emit(
                view_id=INTENT_WORKFLOW_VIEW_ID,
                view_token="workflow",
                node_kind="document",
                record_id=document.document_id,
                expression={
                    "entry_action_ids": list(document.entry_action_ids),
                    "kind": "workflow_boundary",
                    "terminal_action_ids": list(document.terminal_action_ids),
                },
                input_nodes=(
                    ("document", document.document_id),
                    *(("action", item) for item in document.entry_action_ids),
                    *(("action", item) for item in document.terminal_action_ids),
                ),
                refs=all_sources,
            )
            for edge in sorted(document.control_edges, key=lambda item: item.edge_id):
                edge_nodes: list[Any] = [
                    edge,
                    actions[edge.source_action_id],
                    actions[edge.target_action_id],
                ]
                input_nodes = [
                    ("control-edge", edge.edge_id),
                    ("action", edge.source_action_id),
                    ("action", edge.target_action_id),
                ]
                if edge.guard_statement_id:
                    edge_nodes.append(statements[edge.guard_statement_id])
                    input_nodes.append(("statement", edge.guard_statement_id))
                refs = combined_refs(*edge_nodes)
                transition_symbol = add_symbol(
                    node_kind="control-edge",
                    node_id=edge.edge_id,
                    role="transition",
                    name=edge.kind.value,
                    sort="transition",
                    refs=refs,
                )
                guard = (
                    statements[edge.guard_statement_id].to_dict()
                    if edge.guard_statement_id
                    else None
                )
                emit(
                    view_id=INTENT_WORKFLOW_VIEW_ID,
                    view_token="workflow",
                    node_kind="control-edge",
                    record_id=edge.edge_id,
                    expression={
                        "edge": edge.to_dict(),
                        "guard": guard,
                        "kind": "workflow_temporal_transition",
                        "operator": _EDGE_OPERATORS[edge.kind],
                    },
                    input_nodes=input_nodes,
                    refs=refs,
                    symbol_ids=(transition_symbol,),
                    assumption_ids=node_assumptions(
                        "control-edge", edge.edge_id
                    ),
                    opaque_reason=(
                        "Workflow guard has no typed predicate; the complete guard "
                        "was retained opaquely"
                        if guard is not None
                        and not statements[edge.guard_statement_id].predicate
                        else ""
                    ),
                    field_path=(
                        f"/statements/{edge.guard_statement_id}/predicate"
                        if edge.guard_statement_id
                        else f"/control_edges/{edge.edge_id}"
                    ),
                )

        specialized = (
            (
                StatementKind.INVARIANT,
                INTENT_INVARIANT_VIEW_ID,
                "invariant",
                "safety_invariant",
                "always",
            ),
            (
                StatementKind.FAILURE,
                INTENT_FAILURE_VIEW_ID,
                "failure",
                "failure_condition",
                "avoid",
            ),
            (
                StatementKind.VERIFICATION,
                INTENT_VERIFICATION_VIEW_ID,
                "verification",
                "verification_condition",
                "observe",
            ),
        )
        declared_assumption_ids = tuple(
            item.assumption_id
            for item in sample.assumptions
            if item.metadata.get("kind") == StatementKind.ASSUMPTION.value
        )
        for statement_kind, view_id, token, expression_kind, operator in specialized:
            if view_id not in config.target_view_ids:
                continue
            for statement in sorted(
                document.statements, key=lambda item: item.statement_id
            ):
                if statement.kind is not statement_kind:
                    continue
                refs = refs_for_node(statement)
                own_assumptions = node_assumptions(
                    "statement", statement.statement_id
                )
                formula_id = emit(
                    view_id=view_id,
                    view_token=token,
                    node_kind="statement",
                    record_id=statement.statement_id,
                    expression={
                        "body": _statement_body(statement),
                        "kind": expression_kind,
                        "operator": operator,
                    },
                    input_nodes=(("statement", statement.statement_id),),
                    refs=refs,
                    symbol_ids=(
                        add_symbol(
                            node_kind="statement",
                            node_id=statement.statement_id,
                            role="predicate",
                            name=statement.predicate
                            or f"statement:{statement.kind.value}",
                            sort="predicate",
                            refs=refs,
                        ),
                    ),
                    assumption_ids=own_assumptions,
                    opaque_reason=(
                        f"{statement_kind.value.capitalize()} has no typed predicate; "
                        "the normalized statement was retained opaquely"
                        if not statement.predicate
                        else ""
                    ),
                    field_path=f"/statements/{statement.statement_id}/predicate",
                )
                obligation_assumptions = tuple(
                    sorted(set(declared_assumption_ids).union(own_assumptions))
                )
                obligation_semantics = {
                    "formula_id": formula_id,
                    "operator": operator,
                    "statement": statement.to_dict(),
                }
                obligations.append(
                    ProofObligation(
                        obligation_id=_derived_id(
                            f"obligation:intent:{token}", statement.statement_id
                        ),
                        statement=_canonical_bytes(obligation_semantics).decode(
                            "utf-8"
                        ),
                        assumption_ids=obligation_assumptions,
                        logic_family=self.view_registry[view_id].logic_family,
                        source_refs=refs,
                        metadata={
                            "declaration_digest": sample.declaration_digest,
                            "formula_id": formula_id,
                            "intent_node_id": statement.statement_id,
                            "retrieved_premises_excluded": True,
                        },
                    )
                )

        # Link every specialized representation back to its source fact.
        formula_lookup = {item.formula_id: item for item in formulas}
        if INTENT_FACT_VIEW_ID in config.target_view_ids:
            for statement in document.statements:
                source_id = formula_by_key.get(
                    ("facts", "statement", statement.statement_id)
                )
                if source_id:
                    for token in (
                        "modal",
                        "invariant",
                        "failure",
                        "verification",
                    ):
                        target_id = formula_by_key.get(
                            (token, "statement", statement.statement_id)
                        )
                        if target_id:
                            links.append(
                                self._cross_link(
                                    source_id,
                                    target_id,
                                    formula_lookup,
                                    relation=CrossViewRelation.LOWERS_TO,
                                    properties=(
                                        "intent_node",
                                        "modality",
                                        "source_grounding",
                                    ),
                                )
                            )
            for action in document.actions:
                source_id = formula_by_key.get(
                    ("facts", "action", action.action_id)
                )
                target_id = formula_by_key.get(
                    ("action", "action", action.action_id)
                )
                if source_id and target_id:
                    links.append(
                        self._cross_link(
                            source_id,
                            target_id,
                            formula_lookup,
                            relation=CrossViewRelation.LOWERS_TO,
                            properties=(
                                "action",
                                "actor",
                                "source_grounding",
                            ),
                        )
                    )

        emitted_views = {item.view_id for item in formulas}
        for view_id in sorted(set(config.target_view_ids) - emitted_views):
            diagnostics.append(
                Diagnostic(
                    code=DiagnosticCode.UNSUPPORTED_FEATURE,
                    message=(
                        "Intent document has no construct for requested view "
                        f"{view_id}"
                    ),
                    severity=severity,
                    location=DiagnosticLocation(
                        subject_ids=(document.document_id,),
                        source_ref_ids=all_sources,
                        field_path="/compiler_config/target_view_ids",
                    ),
                    producer_id=binding_producer_id,
                    config_id=config.config_id,
                    metadata={
                        "retained_as_opaque": False,
                        "view_id": view_id,
                    },
                )
            )

        symbols = tuple(
            FormalSymbol(
                symbol_id=symbol_id,
                name=spec["name"],
                kind=spec["kind"],
                sort=spec["sort"],
                source_ref_ids=tuple(sorted(spec["sources"])),
                metadata={
                    "intent_node_id": spec["node_id"],
                    "role": spec["role"],
                },
            )
            for symbol_id, spec in sorted(symbol_specs.items())
        )
        for symbol in symbols:
            node_id = str(symbol.metadata["intent_node_id"])
            candidate_parents = [
                _node_id(kind, node_id)
                for kind in ("statement", "action", "control-edge")
                if _node_id(kind, node_id)
                in {item.subject_id for item in sample.provenance.bindings}
            ]
            bindings.append(
                ProvenanceBinding(
                    binding_id=_binding_id(symbol.symbol_id, "symbol"),
                    subject_id=symbol.symbol_id,
                    source_ref_ids=symbol.source_ref_ids,
                    producer_id=binding_producer_id,
                    config_id=config.config_id,
                    parent_subject_ids=tuple(candidate_parents)
                    or (document.document_id,),
                    derived=True,
                )
            )

        producer = ProducerBinding(
            producer_id=binding_producer_id,
            name="Intent IR deterministic formalization compiler",
            version=config.compiler_version,
            metadata={"compiler_id": config.compiler_id},
        )
        config_binding = ConfigBinding(
            config_id=config.config_id,
            content_sha256=config.identity.hexdigest,
            schema_id=config.schema_version,
        )
        source_map = Provenance(
            provenance_id=sample.provenance.provenance_id,
            sources=sample.provenance.sources,
            spans=sample.provenance.spans,
            producers=tuple(
                {
                    item.producer_id: item
                    for item in (*sample.provenance.producers, producer)
                }.values()
            ),
            configs=tuple(
                {
                    item.config_id: item
                    for item in (*sample.provenance.configs, config_binding)
                }.values()
            ),
            bindings=tuple(bindings),
            metadata=sample.provenance.metadata,
        )
        context_digest = (
            hashlib.sha256(_canonical_bytes(context)).hexdigest()[:16]
            if context is not None
            else "no-graph"
        )
        report = DiagnosticReport(
            report_id=(
                f"diagnostics:intent:{sample.digest[7:23]}:"
                f"{config.digest[7:23]}:{context_digest}"
            ),
            diagnostics=tuple(
                sorted(diagnostics, key=lambda item: item.diagnostic_id)
            ),
            provenance_id=source_map.provenance_id,
            producer_id=binding_producer_id,
            config_id=config.config_id,
            metadata={
                "graph_context_present": context is not None,
                "retrieved_premise_count": len(retrieved),
                "unsupported_formula_count": sum(
                    item.opaque for item in formulas
                ),
            },
        )
        metadata: dict[str, Any] = {
            "adapter_schema_version": INTENT_FORMALIZATION_COMPILER_VERSION,
            "graph_context_present": context is not None,
            "intent_ir_digest": sample.declaration_digest,
            "proof_backend_executed": False,
            "retrieved_premise_count": len(retrieved),
            "retrieved_premises_have_proof_authority": False,
        }
        if context is not None:
            metadata["graph_context"] = context
        return FormalizationArtifact.from_sample(
            sample,
            compiler_config=config,
            view_registry=self.view_registry,
            symbol_table=SymbolTable(
                table_id=_derived_id(
                    "symbols:intent", document.document_id
                ),
                symbols=symbols,
                metadata={"domain": INTENT_FORMALIZATION_DOMAIN},
            ),
            formulas=tuple(formulas),
            cross_view_links=tuple(links),
            assumptions=tuple(assumptions),
            proof_obligations=tuple(obligations),
            source_map=source_map,
            diagnostics=report,
            metadata=metadata,
        )

    @staticmethod
    def _action_symbols(
        action: IntentAction,
        *,
        refs: tuple[str, ...],
        add_symbol: Any,
    ) -> tuple[str, ...]:
        specs = [
            ("actor", action.actor, "principal"),
            ("verb", action.verb, "action"),
            *(("object", value, "resource") for value in action.object_refs),
            *(("tool", value, "tool") for value in action.tool_refs),
            *(("input", value, "input") for value in action.input_refs),
            *(("output", value, "output") for value in action.output_refs),
        ]
        return tuple(
            add_symbol(
                node_kind="action",
                node_id=action.action_id,
                role=f"{role}-{index}" if role != "verb" else role,
                name=name,
                sort=sort,
                refs=refs,
            )
            for index, (role, name, sort) in enumerate(specs)
        )

    @staticmethod
    def _cross_link(
        source_formula_id: str,
        target_formula_id: str,
        formulas: Mapping[str, FormalFormula],
        *,
        relation: CrossViewRelation,
        properties: tuple[str, ...],
    ) -> CrossViewLink:
        source = formulas[source_formula_id]
        target = formulas[target_formula_id]
        return CrossViewLink(
            link_id=_derived_id(
                "link:intent", source_formula_id, target_formula_id
            ),
            source_formula_id=source_formula_id,
            target_formula_id=target_formula_id,
            relation=relation,
            preserved_properties=properties,
            source_ref_ids=tuple(
                sorted(set(source.source_ref_ids).union(target.source_ref_ids))
            ),
        )

    def _sample_document(
        self, sample: FormalizationSample
    ) -> IntentIRDocument:
        if (
            not isinstance(sample, FormalizationSample)
            or sample.domain != INTENT_FORMALIZATION_DOMAIN
        ):
            raise IntentFormalizationCompilerError(
                "IntentFormalizationCompiler requires an Intent FormalizationSample"
            )
        payload = sample.payload.to_dict()
        if (
            payload.get("adapter_schema_version")
            != INTENT_FORMALIZATION_COMPILER_VERSION
        ):
            raise IntentFormalizationCompilerError(
                "sample was not produced by this Intent compiler schema"
            )
        declaration = payload.get("declaration")
        if not isinstance(declaration, Mapping):
            raise IntentFormalizationCompilerError(
                "Intent sample declaration must be a mapping"
            )
        try:
            document = decode_intent_ir(declaration)
        except ValueError as exc:
            raise IntentFormalizationCompilerError(
                f"invalid Intent sample declaration: {exc}"
            ) from exc
        digest = intent_ir_sha256(document)
        if digest != sample.declaration_digest:
            raise IntentFormalizationCompilerError(
                "Intent sample declaration digest does not match its payload"
            )
        if document.document_id != sample.declaration_id:
            raise IntentFormalizationCompilerError(
                "Intent sample declaration_id does not match its payload"
            )
        return document

    def compile_document(
        self,
        document: IntentIRDocument,
        config: FormalizationCompilerConfig | None = None,
        *,
        graph_context: Any = None,
    ) -> FormalizationArtifact:
        """Explicit direct-document convenience entry point."""

        return self.compile(document, config, graph_context=graph_context)

    adapt_artifact = compile_document

    def formalize(
        self,
        document: IntentIRDocument,
        *,
        graph_projection: Any = None,
    ) -> Mapping[str, Any]:
        """Implement the original Intent formalizer port with a wire mapping."""

        return self.compile(
            document, graph_projection=graph_projection
        ).to_dict()

    adapt = compile_document


# Alternate noun used by adapters in the other IR domains.
IntentIRFormalizationCompiler = IntentFormalizationCompiler

INTENT_IR_FORMALIZATION_COMPILER_VERSION: Final = (
    INTENT_FORMALIZATION_COMPILER_VERSION
)
INTENT_IR_FORMALIZATION_PRODUCER_ID: Final = INTENT_FORMALIZATION_PRODUCER_ID
INTENT_IR_FORMALIZATION_CONFIG_ID: Final = INTENT_FORMALIZATION_CONFIG_ID
INTENT_IR_FORMALIZATION_DOMAIN: Final = INTENT_FORMALIZATION_DOMAIN
INTENT_IR_FACT_VIEW_ID: Final = INTENT_FACT_VIEW_ID
INTENT_IR_MODAL_VIEW_ID: Final = INTENT_MODAL_VIEW_ID
INTENT_IR_ACTION_VIEW_ID: Final = INTENT_ACTION_VIEW_ID
INTENT_IR_WORKFLOW_VIEW_ID: Final = INTENT_WORKFLOW_VIEW_ID
INTENT_IR_INVARIANT_VIEW_ID: Final = INTENT_INVARIANT_VIEW_ID
INTENT_IR_FAILURE_VIEW_ID: Final = INTENT_FAILURE_VIEW_ID
INTENT_IR_VERIFICATION_VIEW_ID: Final = INTENT_VERIFICATION_VIEW_ID
INTENT_IR_FORMALIZATION_VIEW_REGISTRY: Final = (
    INTENT_FORMALIZATION_VIEW_REGISTRY
)


__all__ = [
    "INTENT_ACTION_HOARE_VIEW_ID",
    "INTENT_ACTION_VIEW_ID",
    "INTENT_FACT_VIEW_ID",
    "INTENT_FAILURE_VIEW_ID",
    "INTENT_FORMALIZATION_COMPILER_VERSION",
    "INTENT_FORMALIZATION_CONFIG_ID",
    "INTENT_FORMALIZATION_DOMAIN",
    "INTENT_FORMALIZATION_PRODUCER_ID",
    "INTENT_FORMALIZATION_VIEW_REGISTRY",
    "INTENT_INTENTION_DEONTIC_VIEW_ID",
    "INTENT_IR_ACTION_VIEW_ID",
    "INTENT_IR_FAILURE_VIEW_ID",
    "INTENT_IR_FACT_VIEW_ID",
    "INTENT_IR_FORMALIZATION_COMPILER_VERSION",
    "INTENT_IR_FORMALIZATION_CONFIG_ID",
    "INTENT_IR_FORMALIZATION_DOMAIN",
    "INTENT_IR_FORMALIZATION_PRODUCER_ID",
    "INTENT_IR_FORMALIZATION_VIEW_REGISTRY",
    "INTENT_IR_INVARIANT_VIEW_ID",
    "INTENT_IR_MODAL_VIEW_ID",
    "INTENT_IR_VERIFICATION_VIEW_ID",
    "INTENT_IR_WORKFLOW_VIEW_ID",
    "INTENT_INVARIANT_VIEW_ID",
    "INTENT_MODAL_VIEW_ID",
    "INTENT_VERIFICATION_VIEW_ID",
    "INTENT_VIEW_REGISTRY",
    "INTENT_WORKFLOW_TEMPORAL_VIEW_ID",
    "INTENT_WORKFLOW_VIEW_ID",
    "IntentFormalizationCompiler",
    "IntentFormalizationCompilerError",
    "IntentIRFormalizationCompiler",
]
