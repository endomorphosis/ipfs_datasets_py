"""Bridge modal F-logic IR into Neo4j-compatible graph data.

The modal codec emits simple F-logic triples as the deterministic symbolic
surface of the legal IR.  This module projects those triples into the migration
``GraphData`` format used by the decentralized Neo4j-compatible graph layer.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ipfs_datasets_py.knowledge_graphs.migration.formats import (
    GraphData,
    NodeData,
    RelationshipData,
    SchemaData,
)
from ipfs_datasets_py.knowledge_graphs.neo4j_compat.legal_ir_projection import (
    augment_legal_ir_projection_triples,
)
from ipfs_datasets_py.logic.flogic import FLogicFrame, FLogicOntology
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import ModalIRDocument


FLOGIC_RESOURCE_LABEL = "FLogicResource"
FLOGIC_VALUE_LABEL = "FLogicValue"
FLOGIC_CLASS_LABEL = "FLogicClass"
FLOGIC_FRAME_LABEL = "FLogicFrame"
MODAL_FORMULA_LABEL = "ModalFormula"
LEGAL_MODAL_DOCUMENT_LABEL = "LegalModalDocument"
LEGAL_CITATION_STRUCTURE_LABEL = "LegalCitationStructure"
LEGAL_DOCUMENT_SCOPE_LABEL = "LegalDocumentScope"
LEGAL_EDITORIAL_STATUS_LABEL = "LegalEditorialStatus"
LEGAL_FRAME_ALIGNMENT_LABEL = "LegalFrameAlignment"
LEGAL_IR_VIEW_ALIGNMENT_LABEL = "LegalIRViewAlignment"
LEGAL_ONTOLOGY_TERM_LABEL = "LegalOntologyTerm"
LEGAL_SECTION_STRUCTURE_LABEL = "LegalSectionStructure"

_FRAME_PREDICATES = {
    "candidate_ontology_frame",
    "interpreted_in_frame",
    "selected_ontology_frame",
}
_FRAME_PREDICATE_PREFIXES = (
    "candidate_ontology_frame",
    "interpreted_in_frame",
    "selected_ontology_frame",
)
_VALUE_LABELS_BY_PREDICATE = {
    "modal_family": "ModalFamily",
    "modal_operator": "ModalOperator",
    "modal_system": "ModalSystem",
    "predicate": "LegalPredicate",
    "predicate_role": "LegalPredicateRole",
    "source": "LegalSource",
}
_DOCUMENT_SCOPE_PREDICATES = {
    "belongs_to_document",
    "contains_formula",
    "contains_norm",
    "source",
    "source_id",
}
_PROVENANCE_PREDICATES = {
    "citation",
    "citation_source",
    "evidence",
    "hint_id",
    "sample_id",
}
_PROVENANCE_PREDICATE_PREFIXES = (
    "source_context_span_",
    "support_span_",
)
_MODAL_SEMANTIC_PREDICATES = {
    "cue",
    "modal_cue",
    "modal_family",
    "modal_operator",
    "modal_system",
    "operator",
    "predicate",
    "predicate_role",
}
_MODAL_SEMANTIC_PREDICATE_PREFIXES = (
    "bridge_",
    "condition_",
    "condition_scope_",
    "cue_modal_",
    "cue_bridge_",
    "fallback_rule_",
    "fallback_surface_",
    "modal_",
    "predicate_",
    "refined_modal_",
    "refined_temporal_",
    "selected_frame_modal_family",
    "source_action_family_",
    "source_condition_family_",
    "source_logical_variable_",
    "source_object_family_",
    "source_subject_family_",
    "source_temporal_family_",
)
_DOCUMENT_SCOPE_PREDICATE_PREFIXES = (
    "source_text_",
    "source_id",
)
_LEGAL_IR_VIEW_ALIGNMENT_PREDICATES = {
    "learned_legal_ir_predicted_view",
    "learned_legal_ir_predicted_view_weight",
    "learned_legal_ir_target_view",
    "learned_legal_ir_target_view_weight",
    "learned_legal_ir_view_gap",
    "learned_legal_ir_view_rank",
}
_LEGAL_IR_VIEW_ALIGNMENT_PREDICATE_PREFIXES = (
    "compiler_guidance_legal_ir_",
    "learned_legal_ir_",
)
_CITATION_PREDICATE_PREFIXES = (
    "citation_",
)
_CITATION_TOKENS = (
    "citation",
    "section",
    "source_id",
    "title",
    "usc",
)
_EDITORIAL_STATUS_PREDICATES = {
    "status_scope",
    "status_keyword",
}
_EDITORIAL_STATUS_PREDICATE_PREFIXES = (
    "editorial_reference_status_",
    "status_codification_",
    "status_public_law_",
    "status_transfer_",
    "status_keyword_",
)
_EDITORIAL_STATUS_TOKENS = (
    "omitted",
    "repeal",
    "repealed",
    "status_bridge",
    "transferred",
)
_EDITORIAL_STATUS_VALUE_TOKENS = (
    "omitted",
    "repealed",
    "transferred",
)
_SECTION_STRUCTURE_PREDICATE_PREFIXES = (
    "citation_section_",
    "citation_source_id_section_",
    "citation_source_id_title_section_",
    "citation_title_section_",
    "fallback_section_heading_",
    "section_catchline",
    "section_definition_",
    "section_heading_",
    "section_marker",
    "section_paragraph_",
    "section_component_",
    "section_profile_",
    "section_range_",
    "section_style_",
    "section_subsection_",
    "source_id_section_",
    "source_id_title_section_",
    "usc_hierarchy_",
)
_SOURCE_ID_CITATION_STRUCTURE_PREDICATES = {
    "source_id_citation_canonical",
    "source_id_scheme",
    "source_id_title",
    "source_id_title_number",
    "source_id_title_section_key",
}
_SOURCE_ID_CITATION_STRUCTURE_PREDICATE_PREFIXES = (
    "source_id_citation_",
    "source_id_title_",
)
_SECTION_STRUCTURE_TOKENS = (
    "chapter",
    "heading_tail",
    "part",
    "section_component",
    "section_definition",
    "section_heading",
    "section_marker",
    "section_paragraph",
    "section_profile",
    "section_range",
    "section_style",
    "section_subsection",
    "subchapter",
    "subtitle",
    "title",
)
_NODE_LABELS_BY_PROJECTION_VIEW = {
    "citation_structure": LEGAL_CITATION_STRUCTURE_LABEL,
    "document_scope": LEGAL_DOCUMENT_SCOPE_LABEL,
    "editorial_status": LEGAL_EDITORIAL_STATUS_LABEL,
    "frame_link": LEGAL_FRAME_ALIGNMENT_LABEL,
    "legal_ir_view_alignment": LEGAL_IR_VIEW_ALIGNMENT_LABEL,
    "ontology_term": LEGAL_ONTOLOGY_TERM_LABEL,
    "section_structure": LEGAL_SECTION_STRUCTURE_LABEL,
}
_IDENTIFIER_RE = re.compile(r"[^A-Za-z0-9_]+")
_GRAPH_PROJECTION_GUIDANCE_ROUTE = "repair_multiview_legal_ir_graph_projection"
_NEO4J_COMPAT_TARGET_COMPONENT = "knowledge_graphs.neo4j_compat"
_DEONTIC_IR_TARGET_VIEW = "deontic.ir"
_TEMPORAL_IR_TARGET_VIEW = "temporal"
_DEONTIC_OPERATOR_SYMBOLS = {"F", "O", "P"}
_DEONTIC_OPERATOR_LABEL_TOKENS = (
    "duty",
    "obligation",
    "permission",
    "prohibition",
    "required",
)
_DEONTIC_SURFACE_CUE_RE = re.compile(
    r"\b("
    r"shall|shall\s+not|must|must\s+not|may|may\s+not|"
    r"required\s+to|requires?\s+that|duty\s+to|"
    r"obligated\s+to|prohibited\s+from|authorized\s+to"
    r")\b",
    re.IGNORECASE,
)
_DEONTIC_TEMPORAL_SCOPE_CUE_RE = re.compile(
    r"\b("
    r"deadline|due\s+date|effective\s+date|effective\s+on|"
    r"not\s+later\s+than|no\s+later\s+than|"
    r"within\s+(?:\d+|the\s+)?(?:applicable\s+)?"
    r"(?:day|days|month|months|year|years|period|fiscal\s+year)|"
    r"after\s+enactment|before\s+the\s+end\s+of|"
    r"annual|annually|periodic|periodically|"
    r"on\s+or\s+before|until|expires?|expiration"
    r")\b",
    re.IGNORECASE,
)


def flogic_triples_to_graph_data(
    triples: Sequence[Mapping[str, Any]],
    *,
    augment_sparse_legal_projection: bool = True,
    graph_id: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> GraphData:
    """Convert F-logic triples into Neo4j-compatible migration graph data."""
    input_triple_count = len(triples)
    normalized = _normalize_triples(triples)
    projected = _canonical_projection_triples(
        normalized,
        augment_sparse_legal_projection=augment_sparse_legal_projection,
    )
    node_map: Dict[str, NodeData] = {}
    relationships: List[RelationshipData] = []
    relationship_types: set[str] = set()
    projection_view_counts: Dict[str, int] = {}

    for index, triple in enumerate(projected):
        subject = triple["subject"]
        predicate = triple["predicate"]
        obj = triple["object"]
        projection_view = _projection_view_for_triple(predicate, obj)
        subject_node = _ensure_node(node_map, subject, labels=[FLOGIC_RESOURCE_LABEL])
        object_labels = [FLOGIC_VALUE_LABEL]
        if predicate == "type":
            object_labels = [FLOGIC_CLASS_LABEL]
            _add_label(subject_node, _neo4j_label(obj, fallback="FLogicType"))
            if obj == "legal_modal_document":
                _add_label(subject_node, LEGAL_MODAL_DOCUMENT_LABEL)
        elif predicate == "belongs_to_document":
            _add_label(subject_node, MODAL_FORMULA_LABEL)
        elif predicate in _FRAME_PREDICATES:
            object_labels = [FLOGIC_FRAME_LABEL, FLOGIC_RESOURCE_LABEL]
        elif predicate in _VALUE_LABELS_BY_PREDICATE:
            object_labels.append(_VALUE_LABELS_BY_PREDICATE[predicate])
        projection_label = _NODE_LABELS_BY_PROJECTION_VIEW.get(projection_view)
        if projection_label:
            _add_label(subject_node, projection_label)
            object_labels.append(projection_label)

        object_node = _ensure_node(node_map, obj, labels=object_labels)
        rel_type = _relationship_type(predicate)
        relationship_types.add(rel_type)
        relationships.append(
            RelationshipData(
                id=_relationship_id(index, subject, predicate, obj),
                type=rel_type,
                start_node=subject_node.id,
                end_node=object_node.id,
                properties={
                    "flogic_object": obj,
                    "flogic_predicate": predicate,
                    "flogic_subject": subject,
                    "flogic_triple_key": _triple_identity_key(subject, predicate, obj),
                    "frame_logic_projection_view": projection_view,
                    "source": "flogic_triple",
                    "triple_index": index,
                },
            )
        )
        projection_view_counts[projection_view] = projection_view_counts.get(projection_view, 0) + 1

    node_labels = sorted({label for node in node_map.values() for label in node.labels})
    unique_triple_count = _unique_triple_count(projected)
    duplicate_triple_count = max(0, len(projected) - unique_triple_count)
    graph_metadata = {
        "flogic_duplicate_triple_count": duplicate_triple_count,
        "flogic_normalized_triple_count": len(normalized),
        "flogic_triple_count": len(projected),
        "flogic_unique_triple_count": unique_triple_count,
        "graph_id": graph_id or _default_graph_id(normalized),
        "neo4j_compatible": True,
        "source": "modal_flogic_ir",
    }
    if metadata:
        graph_metadata.update(dict(metadata))
    graph_metadata.update(
        _projection_alignment_metadata(
            projected,
            input_triple_count=input_triple_count,
            normalized_triple_count=len(normalized),
            node_count=len(node_map),
            projection_view_counts=projection_view_counts,
            relationship_count=len(relationships),
        )
    )
    return GraphData(
        nodes=sorted(node_map.values(), key=lambda node: node.id),
        relationships=relationships,
        schema=SchemaData(
            node_labels=node_labels,
            relationship_types=sorted(relationship_types),
        ),
        metadata=graph_metadata,
    )


def modal_ir_to_neo4j_graph_data(
    modal_ir: ModalIRDocument,
    *,
    selected_frame: Optional[str] = None,
    triples: Optional[Sequence[Mapping[str, Any]]] = None,
) -> GraphData:
    """Project a modal IR document into Neo4j-compatible F-logic graph data."""
    frame_logic = getattr(modal_ir, "frame_logic", None)
    if triples is None:
        if frame_logic is not None and getattr(frame_logic, "triples", None):
            triples = frame_logic.to_triples()
    if triples is None:
        triples = modal_ir.metadata.get("flogic_triples")
    if triples is None:
        from .codec import modal_ir_to_flogic_triples

        triples = modal_ir_to_flogic_triples(modal_ir, selected_frame=selected_frame)
    triples = _with_modal_ir_document_projection_context(modal_ir, triples)
    triples = _with_guided_legal_ir_projection_triples(modal_ir, triples)
    return flogic_triples_to_graph_data(
        triples,
        graph_id=f"{modal_ir.document_id}:flogic",
        metadata={
            "frame_logic_ontology_name": str(
                getattr(frame_logic, "ontology_name", "") or ""
            ),
            "frame_logic_selected_frame": str(
                (
                    getattr(frame_logic, "selected_frame", None)
                    or selected_frame
                    or ""
                )
            ),
            "modal_ir_document_id": modal_ir.document_id,
            "modal_ir_hash": modal_ir.canonical_hash(),
            "modal_ir_version": modal_ir.version,
        },
    )


def flogic_triples_to_ontology(
    triples: Sequence[Mapping[str, Any]],
    *,
    name: str = "modal_flogic_ir",
) -> FLogicOntology:
    """Build a compact F-logic ontology from simple ``subject/predicate/object`` triples."""
    by_subject: Dict[str, Dict[str, List[str]]] = {}
    for triple in _normalize_triples(triples):
        by_subject.setdefault(triple["subject"], {}).setdefault(
            triple["predicate"],
            [],
        ).append(triple["object"])

    frames: List[FLogicFrame] = []
    for subject, methods in sorted(by_subject.items()):
        scalar_methods: Dict[str, Any] = {}
        set_methods: Dict[str, List[Any]] = {}
        isa: Optional[str] = None
        for predicate, values in sorted(methods.items()):
            unique_values = _unique(values)
            if predicate == "type" and unique_values:
                isa = unique_values[0]
                continue
            if len(unique_values) == 1:
                scalar_methods[predicate] = unique_values[0]
            else:
                set_methods[predicate] = list(unique_values)
        frames.append(
            FLogicFrame(
                object_id=subject,
                scalar_methods=scalar_methods,
                set_methods=set_methods,
                isa=isa,
            )
        )
    return FLogicOntology(name=name, frames=frames)


def flogic_ontology_to_dict(ontology: FLogicOntology) -> Dict[str, Any]:
    """Return a stable JSON-ready summary of an F-logic ontology."""
    return {
        "frame_count": len(ontology.frames),
        "frames": [frame.to_ergo_string() for frame in ontology.frames],
        "name": ontology.name,
        "program": ontology.to_ergo_program(),
    }


def import_graph_data_to_graph_engine(
    graph_data: GraphData,
    *,
    engine: Optional[Any] = None,
    preserve_ids: bool = True,
    skip_duplicates: bool = True,
) -> Tuple[Any, Dict[str, int]]:
    """Import ``GraphData`` into the in-process Neo4j-compatible graph engine."""
    if engine is None:
        from ipfs_datasets_py.knowledge_graphs.core import GraphEngine

        engine = GraphEngine()
    report = engine.import_graph_data(
        graph_data,
        preserve_ids=preserve_ids,
        skip_duplicates=skip_duplicates,
    )
    return engine, report


def import_modal_ir_to_graph_engine(
    modal_ir: ModalIRDocument,
    *,
    engine: Optional[Any] = None,
    selected_frame: Optional[str] = None,
    preserve_ids: bool = True,
    skip_duplicates: bool = True,
) -> Tuple[Any, Dict[str, int]]:
    """Convert modal IR frame logic to graph data and import it into ``GraphEngine``."""
    graph_data = modal_ir_to_neo4j_graph_data(modal_ir, selected_frame=selected_frame)
    return import_graph_data_to_graph_engine(
        graph_data,
        engine=engine,
        preserve_ids=preserve_ids,
        skip_duplicates=skip_duplicates,
    )


def _normalize_triples(triples: Sequence[Mapping[str, Any]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for triple in triples:
        subject = str(triple.get("subject", "")).strip()
        predicate = str(triple.get("predicate", "")).strip()
        obj = _canonical_triple_object_text(triple.get("object", ""))
        if not subject or not predicate or not obj:
            continue
        normalized.append({"subject": subject, "predicate": predicate, "object": obj})
    return normalized


def _canonical_triple_object_text(value: Any) -> str:
    if isinstance(value, (Mapping, list, tuple)):
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":")).strip()
        except (TypeError, ValueError):
            pass
    return str(value or "").strip()


def _canonical_projection_triples(
    triples: Sequence[Mapping[str, str]],
    *,
    augment_sparse_legal_projection: bool = True,
) -> List[Dict[str, str]]:
    """Return triples in deterministic lexical order."""
    normalized = [
        {
            "subject": str(triple.get("subject") or ""),
            "predicate": str(triple.get("predicate") or ""),
            "object": str(triple.get("object") or ""),
        }
        for triple in triples
    ]
    if augment_sparse_legal_projection:
        normalized = augment_legal_ir_projection_triples(normalized)
    return sorted(
        normalized,
        key=lambda item: (item["subject"], item["predicate"], item["object"]),
    )


def _ensure_node(
    node_map: Dict[str, NodeData],
    flogic_id: str,
    *,
    labels: Iterable[str],
) -> NodeData:
    node_id = _node_id(flogic_id)
    if node_id not in node_map:
        node_map[node_id] = NodeData(
            id=node_id,
            labels=[],
            properties={
                "flogic_id": flogic_id,
                "name": flogic_id,
                "source": "modal_flogic_ir",
            },
        )
    node = node_map[node_id]
    for label in labels:
        _add_label(node, label)
    return node


def _add_label(node: NodeData, label: str) -> None:
    if label and label not in node.labels:
        node.labels.append(label)


def _node_id(flogic_id: str) -> str:
    digest = hashlib.sha256(flogic_id.encode("utf-8")).hexdigest()[:20]
    return f"flogic-node-{digest}"


def _relationship_id(index: int, subject: str, predicate: str, obj: str) -> str:
    payload = "\x1f".join((_triple_identity_key(subject, predicate, obj), str(index)))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"flogic-rel-{digest}"


def _triple_identity_key(subject: str, predicate: str, obj: str) -> str:
    return "\x1f".join((subject, predicate, obj))


def _relationship_type(predicate: str) -> str:
    rel_type = _IDENTIFIER_RE.sub("_", predicate).strip("_").upper()
    if not rel_type:
        return "RELATED_TO"
    if rel_type[0].isdigit():
        return f"FLOGIC_{rel_type}"
    return rel_type


def _neo4j_label(value: str, *, fallback: str) -> str:
    parts = [part for part in _IDENTIFIER_RE.split(value) if part]
    label = "".join(part[:1].upper() + part[1:] for part in parts)
    if not label:
        return fallback
    if label[0].isdigit():
        return f"{fallback}{label}"
    return label


def _default_graph_id(triples: Sequence[Mapping[str, str]]) -> str:
    if triples:
        return f"{triples[0]['subject']}:flogic"
    return "modal_flogic_ir"


def _projection_alignment_metadata(
    triples: Sequence[Mapping[str, str]],
    *,
    input_triple_count: int,
    normalized_triple_count: int,
    node_count: int,
    projection_view_counts: Mapping[str, int],
    relationship_count: int,
) -> Dict[str, Any]:
    subjects = {str(triple["subject"]) for triple in triples}
    predicates = {str(triple["predicate"]) for triple in triples}
    objects = {str(triple["object"]) for triple in triples}
    unique_triple_count = _unique_triple_count(triples)
    canonical_view_distribution = _canonical_component_distribution(
        projection_view_counts,
        relationship_count=relationship_count,
        triples=triples,
    )
    graph_failure_penalty = 0.0 if node_count > 0 and relationship_count > 0 else 1.0
    graph_projection_signal_count = _graph_projection_signal_count(
        projection_view_counts
    )
    projected_triple_aligned = relationship_count == len(triples)
    augmented_triple_count = max(0, len(triples) - normalized_triple_count)
    metadata: Dict[str, Any] = {
        "canonical_legal_ir_projection_components": sorted(canonical_view_distribution),
        "canonical_legal_ir_projection_view_distribution": canonical_view_distribution,
        "canonical_legal_ir_projection_view_total": len(canonical_view_distribution),
        "frame_logic_to_neo4j_alignment_total": relationship_count
        if projected_triple_aligned
        else 0,
        "frame_logic_to_neo4j_component_pair": (
            "modal.frame_logic->knowledge_graphs.neo4j_compat"
        ),
        "frame_logic_to_neo4j_source_component": "modal.frame_logic",
        "frame_logic_to_neo4j_target_component": "knowledge_graphs.neo4j_compat",
        "flogic_input_triple_count": input_triple_count,
        "flogic_invalid_triple_count": max(0, input_triple_count - normalized_triple_count),
        "flogic_duplicate_triple_count": max(0, len(triples) - unique_triple_count),
        "flogic_normalized_triple_count": normalized_triple_count,
        "flogic_unique_triple_count": unique_triple_count,
        "frame_logic_projection_augmented_aligned": (
            projected_triple_aligned and relationship_count >= normalized_triple_count
        ),
        "frame_logic_projection_augmented_triple_count": augmented_triple_count,
        "frame_logic_projection_input_aligned": relationship_count == input_triple_count,
        "frame_logic_projection_input_relationship_gap": max(
            0,
            input_triple_count - relationship_count,
        ),
        "frame_logic_projection_aligned": projected_triple_aligned,
        "frame_logic_projection_normalized_aligned": (
            projected_triple_aligned and relationship_count >= normalized_triple_count
        ),
        "frame_logic_projection_normalized_relationship_gap": max(
            0,
            normalized_triple_count - relationship_count,
        ),
        "frame_logic_projection_has_duplicate_facts": len(triples) != unique_triple_count,
        "frame_logic_projection_node_count": node_count,
        "frame_logic_projection_relationship_count": relationship_count,
        "frame_logic_projection_view_count": len(projection_view_counts),
        "frame_logic_projection_view_distribution": {
            name: int(projection_view_counts[name])
            for name in sorted(projection_view_counts)
        },
        "frame_logic_projection_views": sorted(projection_view_counts),
        "frame_logic_unique_object_count": len(objects),
        "frame_logic_unique_predicate_count": len(predicates),
        "frame_logic_unique_subject_count": len(subjects),
        "legal_ir_multiview_graph_failure_penalty": graph_failure_penalty,
        "legal_ir_graph_projection_signal_count": graph_projection_signal_count,
        "legal_ir_graph_projection_signal_ratio": (
            graph_projection_signal_count / relationship_count
            if relationship_count > 0
            else 0.0
        ),
    }
    legal_view_metadata = _legal_view_coverage_metadata(
        triples,
        projection_view_counts=projection_view_counts,
    )
    metadata.update(legal_view_metadata)
    metadata["legal_ir_view_cross_entropy_loss"] = max(
        0.0,
        1.0
        - float(
            legal_view_metadata.get(
                "frame_logic_projection_legal_view_coverage_ratio",
                0.0,
            )
        ),
    )
    selected_frame = _selected_frame_from_triples(triples)
    if selected_frame:
        metadata["frame_logic_selected_frame"] = selected_frame
    return metadata


def _legal_view_coverage_metadata(
    triples: Sequence[Mapping[str, str]],
    *,
    projection_view_counts: Mapping[str, int],
) -> Dict[str, Any]:
    """Summarize deterministic legal-structure coverage for graph consumers."""

    required_views = _required_legal_projection_views(triples)
    present_views = {str(name) for name, count in projection_view_counts.items() if count}
    missing_views = [view for view in required_views if view not in present_views]
    return {
        "frame_logic_projection_legal_view_coverage_complete": not missing_views,
        "frame_logic_projection_legal_view_coverage_ratio": (
            1.0
            if not required_views
            else (len(required_views) - len(missing_views)) / len(required_views)
        ),
        "frame_logic_projection_legal_view_missing": missing_views,
        "frame_logic_projection_legal_view_required": required_views,
    }


def _required_legal_projection_views(
    triples: Sequence[Mapping[str, str]],
) -> List[str]:
    predicates = {
        str(triple.get("predicate") or "").strip().lower()
        for triple in triples
    }
    if not predicates:
        return []
    has_source_id = any(
        predicate == "source_id" or predicate.startswith("source_id_")
        for predicate in predicates
    )
    has_citation = any(
        predicate == "citation" or predicate.startswith("citation_")
        for predicate in predicates
    )
    has_section = any(
        predicate.startswith(_SECTION_STRUCTURE_PREDICATE_PREFIXES)
        or "section_heading" in predicate
        or "section_component" in predicate
        or "section_profile" in predicate
        for predicate in predicates
    )
    has_editorial_status = any(
        predicate in _EDITORIAL_STATUS_PREDICATES
        or predicate.startswith(_EDITORIAL_STATUS_PREDICATE_PREFIXES)
        or any(token in predicate for token in _EDITORIAL_STATUS_TOKENS)
        for predicate in predicates
    )
    has_view_alignment = any(
        predicate in _LEGAL_IR_VIEW_ALIGNMENT_PREDICATES
        or predicate.startswith(_LEGAL_IR_VIEW_ALIGNMENT_PREDICATE_PREFIXES)
        for predicate in predicates
    )
    has_frame_link = any(
        predicate in _FRAME_PREDICATES
        or predicate.startswith(_FRAME_PREDICATE_PREFIXES)
        for predicate in predicates
    )
    required: List[str] = []
    if has_source_id:
        required.append("document_scope")
    if has_source_id or has_citation:
        required.append("citation_structure")
    if has_section:
        required.append("section_structure")
    if has_editorial_status:
        required.append("editorial_status")
    if has_view_alignment:
        required.append("legal_ir_view_alignment")
    if has_frame_link:
        required.append("frame_link")
    return sorted(set(required))


def _with_modal_ir_document_projection_context(
    modal_ir: ModalIRDocument,
    triples: Sequence[Mapping[str, Any]],
) -> List[Mapping[str, Any]]:
    """Carry document-level LegalIR context into sparse frame-logic graphs."""

    projected = list(triples or [])
    context_triples = _modal_ir_document_projection_context_triples(modal_ir)
    if not context_triples:
        return projected
    seen = {
        (
            str(triple.get("subject") or ""),
            str(triple.get("predicate") or ""),
            str(triple.get("object") or ""),
        )
        for triple in projected
    }
    for triple in context_triples:
        key = (
            str(triple.get("subject") or ""),
            str(triple.get("predicate") or ""),
            str(triple.get("object") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        projected.append(triple)
    return projected


def _modal_ir_document_projection_context_triples(
    modal_ir: ModalIRDocument,
) -> List[Dict[str, str]]:
    metadata = getattr(modal_ir, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        metadata = {}
    subject = str(getattr(modal_ir, "document_id", "") or "").strip()
    if not subject:
        return []

    triples: List[Dict[str, str]] = []
    for predicate, value in (
        ("source_id", getattr(modal_ir, "document_id", "")),
        ("source", getattr(modal_ir, "source", "")),
        ("citation", metadata.get("citation")),
        ("sample_text", getattr(modal_ir, "normalized_text", "")),
    ):
        text = str(value or "").strip()
        if not text:
            continue
        triples.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": text,
            }
        )
    return triples


def _canonical_component_distribution(
    projection_view_counts: Mapping[str, int],
    *,
    relationship_count: int,
    triples: Sequence[Mapping[str, str]] = (),
) -> Dict[str, float]:
    if relationship_count <= 0:
        return {}
    structural_count = sum(
        int(projection_view_counts.get(view_name, 0) or 0)
        for view_name in (
            "citation_structure",
            "document_scope",
            "editorial_status",
            "frame_link",
            "legal_ir_view_alignment",
            "ontology_term",
            "section_structure",
            "type_assertion",
        )
    )
    modal_count = sum(
        int(projection_view_counts.get(view_name, 0) or 0)
        for view_name in ("fact", "modal_semantics", "provenance")
    )
    distribution = {
        "knowledge_graphs.neo4j_compat": max(1, structural_count),
        "modal.frame_logic": max(1, modal_count),
    }
    learned_distribution = _learned_legal_ir_view_distribution(triples)
    if learned_distribution:
        return learned_distribution
    total = float(sum(distribution.values()))
    return {
        component: count / total
        for component, count in sorted(distribution.items())
    }


def _learned_legal_ir_view_distribution(
    triples: Sequence[Mapping[str, str]],
) -> Dict[str, float]:
    """Prefer explicit compiler view weights over count-derived frame mass."""

    predicted = _learned_legal_ir_weight_triples(
        triples,
        weight_predicate="learned_legal_ir_predicted_view_weight",
    )
    target = _learned_legal_ir_weight_triples(
        triples,
        weight_predicate="learned_legal_ir_target_view_weight",
    )
    if predicted:
        repaired = _frame_logic_repaired_view_distribution(
            predicted=predicted,
            target=target,
        )
        return repaired or predicted

    if target:
        gaps = _learned_legal_ir_gap_triples(triples)
        if gaps.get("modal.frame_logic", 0.0) >= 0.0:
            return {}
        if len(target) > 1:
            target = {
                view: weight
                for view, weight in target.items()
                if view != "modal.frame_logic"
            }
        return _normalize_view_distribution(target)
    return {}


def _frame_logic_repaired_view_distribution(
    *,
    predicted: Mapping[str, float],
    target: Mapping[str, float],
) -> Dict[str, float]:
    """Preserve canonical view mass when learned frame logits are misbalanced.

    Frame-logic guidance historically needed an explicit repair when learned
    logits underweighted ``modal.frame_logic``.  The same ontology constraint is
    needed in the opposite direction: if a frame-heavy prediction underweights
    target-positive temporal or deontic evidence, carry the target view weights
    into the graph projection and rescale the remaining predicted mass.
    """

    positive_target_repairs: Dict[str, float] = {}
    for view, raw_target in target.items():
        target_weight = max(0.0, float(raw_target or 0.0))
        if target_weight <= 0.0:
            continue
        predicted_weight = max(0.0, float(predicted.get(view, 0.0) or 0.0))
        if target_weight > predicted_weight:
            positive_target_repairs[view] = min(1.0, target_weight)
    if not positive_target_repairs:
        return {}

    repair_total = sum(positive_target_repairs.values())
    if repair_total <= 0.0:
        return {}
    if repair_total >= 1.0:
        return _normalize_view_distribution(positive_target_repairs)

    remaining_predicted = {
        view: weight
        for view, weight in predicted.items()
        if view not in positive_target_repairs and weight > 0.0
    }
    repaired: Dict[str, float] = dict(positive_target_repairs)
    remainder = max(0.0, 1.0 - repair_total)
    remaining_total = sum(remaining_predicted.values())
    if remainder > 0.0 and remaining_total > 0.0:
        for view, weight in sorted(remaining_predicted.items()):
            repaired[view] = remainder * (weight / remaining_total)
    return {
        view: weight
        for view, weight in sorted(repaired.items())
        if weight > 0.0
    }


def _learned_legal_ir_weight_triples(
    triples: Sequence[Mapping[str, str]],
    *,
    weight_predicate: str,
) -> Dict[str, float]:
    weights: Dict[str, float] = {}
    for triple in triples:
        if str(triple.get("predicate") or "") != weight_predicate:
            continue
        view, weight = _weighted_view_object(str(triple.get("object") or ""))
        if not view or weight is None or weight <= 0.0:
            continue
        weights[view] = max(weights.get(view, 0.0), weight)
    return _normalize_view_distribution(weights)


def _learned_legal_ir_gap_triples(
    triples: Sequence[Mapping[str, str]],
) -> Dict[str, float]:
    gaps: Dict[str, float] = {}
    for triple in triples:
        if str(triple.get("predicate") or "") != "learned_legal_ir_view_gap":
            continue
        view, gap = _weighted_view_object(str(triple.get("object") or ""))
        if not view or gap is None:
            continue
        gaps[view] = gaps.get(view, 0.0) + gap
    return dict(sorted(gaps.items()))


def _weighted_view_object(value: str) -> Tuple[str, Optional[float]]:
    raw_view, separator, raw_weight = str(value or "").strip().rpartition(":")
    if not separator:
        return "", None
    view = _canonical_legal_ir_view_name(raw_view)
    weight = _finite_float(raw_weight)
    return view, weight


def _normalize_view_distribution(distribution: Mapping[str, float]) -> Dict[str, float]:
    total = sum(max(0.0, float(value)) for value in distribution.values())
    if total <= 0.0:
        return {}
    return {
        view: max(0.0, float(value)) / total
        for view, value in sorted(distribution.items())
        if max(0.0, float(value)) > 0.0
    }


def _graph_projection_signal_count(
    projection_view_counts: Mapping[str, int],
) -> int:
    """Count structural projection facts that directly exercise Neo4j shape."""

    return sum(
        int(projection_view_counts.get(view_name, 0) or 0)
        for view_name in (
            "citation_structure",
            "document_scope",
            "editorial_status",
            "frame_link",
            "legal_ir_view_alignment",
            "ontology_term",
            "section_structure",
            "type_assertion",
        )
    )


def _selected_frame_from_triples(triples: Sequence[Mapping[str, str]]) -> str:
    for triple in triples:
        if str(triple.get("predicate") or "") != "selected_ontology_frame":
            continue
        frame = str(triple.get("object") or "").strip()
        if frame:
            return frame
    return ""


def _projection_view_for_triple(predicate: str, obj: str = "") -> str:
    normalized = str(predicate or "").strip().lower()
    normalized_object = str(obj or "").strip().lower()
    if not normalized:
        return "fact"
    if normalized == "type":
        return "type_assertion"
    if normalized in _EDITORIAL_STATUS_PREDICATES or normalized.startswith(
        _EDITORIAL_STATUS_PREDICATE_PREFIXES
    ):
        return "editorial_status"
    if any(token in normalized for token in _EDITORIAL_STATUS_TOKENS):
        return "editorial_status"
    if (
        normalized.startswith("source_status_clause")
        and normalized_object in _EDITORIAL_STATUS_VALUE_TOKENS
    ):
        return "editorial_status"
    if normalized in _FRAME_PREDICATES or normalized.startswith(_FRAME_PREDICATE_PREFIXES):
        return "frame_link"
    if "ontology_term" in normalized:
        return "ontology_term"
    if normalized in _LEGAL_IR_VIEW_ALIGNMENT_PREDICATES or normalized.startswith(
        _LEGAL_IR_VIEW_ALIGNMENT_PREDICATE_PREFIXES
    ):
        return "legal_ir_view_alignment"
    if normalized.startswith(_SECTION_STRUCTURE_PREDICATE_PREFIXES):
        return "section_structure"
    if (
        normalized in _SOURCE_ID_CITATION_STRUCTURE_PREDICATES
        or normalized.startswith(_SOURCE_ID_CITATION_STRUCTURE_PREDICATE_PREFIXES)
    ):
        return "citation_structure"
    if normalized in _MODAL_SEMANTIC_PREDICATES or normalized.startswith(
        _MODAL_SEMANTIC_PREDICATE_PREFIXES
    ):
        return "modal_semantics"
    if normalized in _PROVENANCE_PREDICATES or normalized.startswith(
        _PROVENANCE_PREDICATE_PREFIXES
    ):
        return "provenance"
    if normalized in _DOCUMENT_SCOPE_PREDICATES or normalized.startswith(
        _DOCUMENT_SCOPE_PREDICATE_PREFIXES
    ):
        return "document_scope"
    if normalized.startswith(_CITATION_PREDICATE_PREFIXES):
        return "citation_structure"
    if any(token in normalized for token in _CITATION_TOKENS):
        return "citation_structure"
    if any(token in normalized for token in _SECTION_STRUCTURE_TOKENS):
        return "section_structure"
    return "fact"


def _unique(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _unique_triple_count(triples: Sequence[Mapping[str, str]]) -> int:
    return len(
        {
            (
                str(triple.get("subject") or ""),
                str(triple.get("predicate") or ""),
                str(triple.get("object") or ""),
            )
            for triple in triples
        }
    )


def _with_guided_legal_ir_projection_triples(
    modal_ir: ModalIRDocument,
    triples: Sequence[Mapping[str, Any]],
) -> List[Mapping[str, Any]]:
    """Add graph-lane LegalIR guidance triples when codec metadata carries it."""

    projected = list(triples or [])
    guidance_triples = _guided_legal_ir_projection_triples(modal_ir)
    if not guidance_triples:
        return projected

    seen = {
        (
            str(triple.get("subject") or ""),
            str(triple.get("predicate") or ""),
            str(triple.get("object") or ""),
        )
        for triple in projected
    }
    for triple in guidance_triples:
        key = (
            str(triple.get("subject") or ""),
            str(triple.get("predicate") or ""),
            str(triple.get("object") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        projected.append(triple)
    return projected


def _guided_legal_ir_projection_triples(
    modal_ir: ModalIRDocument,
) -> List[Dict[str, str]]:
    metadata = getattr(modal_ir, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        return []

    predicted = _canonical_numeric_distribution(
        metadata.get("compiler_guidance_legal_ir_predicted_view_distribution")
    )
    target = _canonical_numeric_distribution(
        metadata.get("compiler_guidance_legal_ir_target_view_distribution")
    )
    gaps = _canonical_numeric_signed_mapping(
        metadata.get("compiler_guidance_legal_ir_view_gap_distribution")
    )
    packet_gap_targets, packet_gap_values = _packet_legal_ir_view_gap_evidence(
        metadata
    )
    if packet_gap_targets:
        target = {**target, **packet_gap_targets}
    if packet_gap_values:
        gaps = {**gaps, **packet_gap_values}
    formula_target, formula_gaps = _modal_formula_legal_ir_view_targets(modal_ir)
    if formula_target:
        target = {**target, **formula_target}
    if formula_gaps:
        gaps = {**gaps, **formula_gaps}
    if _metadata_implies_neo4j_projection_guidance(metadata):
        if _NEO4J_COMPAT_TARGET_COMPONENT not in target:
            target = {
                **target,
                _NEO4J_COMPAT_TARGET_COMPONENT: 1.0,
            }
        if _NEO4J_COMPAT_TARGET_COMPONENT not in gaps:
            gaps = {
                **gaps,
                _NEO4J_COMPAT_TARGET_COMPONENT: round(
                    target[_NEO4J_COMPAT_TARGET_COMPONENT]
                    - predicted.get(_NEO4J_COMPAT_TARGET_COMPONENT, 0.0),
                    12,
                ),
            }
    if not predicted and not target and not gaps:
        return []

    ranked_views = sorted(
        set(predicted) | set(target) | set(gaps),
        key=lambda view: max(
            predicted.get(view, 0.0),
            target.get(view, 0.0),
            abs(gaps.get(view, 0.0)),
        ),
        reverse=True,
    )[:6]
    triples: List[Dict[str, str]] = []
    for rank, view in enumerate(ranked_views, start=1):
        safe_view = str(view or "").strip()
        if not safe_view:
            continue
        if view in predicted:
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "learned_legal_ir_predicted_view",
                    "object": safe_view,
                }
            )
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "learned_legal_ir_predicted_view_weight",
                    "object": f"{safe_view}:{predicted[view]:.6f}",
                }
            )
        if view in target:
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "learned_legal_ir_target_view",
                    "object": safe_view,
                }
            )
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "learned_legal_ir_target_view_weight",
                    "object": f"{safe_view}:{target[view]:.6f}",
                }
            )
        triples.extend(
            [
                {
                    "subject": modal_ir.document_id,
                    "predicate": "learned_legal_ir_view_rank",
                    "object": f"{rank}:{safe_view}",
                },
                {
                    "subject": modal_ir.document_id,
                    "predicate": "learned_legal_ir_view_gap",
                    "object": (
                        f"{safe_view}:"
                        f"{gaps.get(view, target.get(view, 0.0) - predicted.get(view, 0.0)):.6f}"
                    ),
                },
            ]
        )
    return triples


def _modal_formula_legal_ir_view_targets(
    modal_ir: ModalIRDocument,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Infer LegalIR view targets from deterministic modal-operator evidence."""

    formulas = list(getattr(modal_ir, "formulas", []) or [])
    if not formulas:
        return {}, {}

    document_text = str(getattr(modal_ir, "normalized_text", "") or "")
    deontic_count = 0
    temporal_count = 0
    for formula in formulas:
        if _formula_has_deontic_operator_pattern(
            formula,
            document_text=document_text,
        ):
            deontic_count += 1
        if _formula_has_deontic_temporal_scope(
            formula,
            document_text=document_text,
        ):
            temporal_count += 1

    targets: Dict[str, float] = {}
    if deontic_count > 0:
        targets[_DEONTIC_IR_TARGET_VIEW] = deontic_count / len(formulas)
    if temporal_count > 0:
        targets[_TEMPORAL_IR_TARGET_VIEW] = temporal_count / len(formulas)
    if not targets:
        return {}, {}

    return targets, dict(targets)


def _formula_has_deontic_operator_pattern(
    formula: Any,
    *,
    document_text: str,
) -> bool:
    operator = getattr(formula, "operator", None)
    family = str(getattr(operator, "family", "") or "").strip().lower()
    if family == "deontic":
        return True

    symbol = str(getattr(operator, "symbol", "") or "").strip().upper()
    if symbol in _DEONTIC_OPERATOR_SYMBOLS:
        return True

    label = str(getattr(operator, "label", "") or "").strip().lower()
    if any(token in label for token in _DEONTIC_OPERATOR_LABEL_TOKENS):
        return True

    text_parts = [document_text]
    predicate = getattr(formula, "predicate", None)
    text_parts.append(str(getattr(predicate, "role", "") or ""))
    text_parts.append(str(getattr(predicate, "name", "") or "").replace("_", " "))
    for field_name in ("conditions", "exceptions"):
        text_parts.extend(
            str(value or "")
            for value in (getattr(formula, field_name, []) or [])
        )
    metadata = getattr(formula, "metadata", {}) or {}
    if isinstance(metadata, Mapping):
        for key in ("modal_cue", "cue", "source_text", "surface_text"):
            text_parts.append(str(metadata.get(key) or ""))
    return bool(_DEONTIC_SURFACE_CUE_RE.search(" ".join(text_parts)))


def _formula_has_deontic_temporal_scope(
    formula: Any,
    *,
    document_text: str,
) -> bool:
    text_parts = [document_text]
    predicate = getattr(formula, "predicate", None)
    text_parts.append(str(getattr(predicate, "role", "") or ""))
    text_parts.append(str(getattr(predicate, "name", "") or "").replace("_", " "))
    for field_name in ("conditions", "exceptions"):
        text_parts.extend(
            str(value or "")
            for value in (getattr(formula, field_name, []) or [])
        )
    metadata = getattr(formula, "metadata", {}) or {}
    if isinstance(metadata, Mapping):
        for key in ("modal_cue", "cue", "source_text", "surface_text"):
            text_parts.append(str(metadata.get(key) or ""))
    return bool(_DEONTIC_TEMPORAL_SCOPE_CUE_RE.search(" ".join(text_parts)))


def _metadata_implies_neo4j_projection_guidance(metadata: Mapping[str, Any]) -> bool:
    target_distribution = _canonical_numeric_distribution(
        metadata.get("compiler_guidance_legal_ir_target_view_distribution")
    )
    if _NEO4J_COMPAT_TARGET_COMPONENT in target_distribution:
        return True
    packet_gap_targets, _packet_gap_values = _packet_legal_ir_view_gap_evidence(
        metadata
    )
    if _NEO4J_COMPAT_TARGET_COMPONENT in packet_gap_targets:
        return True
    features = _compiler_guidance_metadata_features(metadata)
    has_graph_route = any(
        _GRAPH_PROJECTION_GUIDANCE_ROUTE in feature for feature in features
    )
    has_neo4j_target = any(
        _NEO4J_COMPAT_TARGET_COMPONENT in feature for feature in features
    )
    feature_text = "\n".join(features)
    has_graph_failure_metric = (
        "legal_ir_multiview_graph_failure_penalty" in feature_text
    )
    has_knowledge_graph_scope = "knowledge_graphs" in feature_text
    return (
        has_graph_route
        or has_neo4j_target
        or (has_graph_failure_metric and has_knowledge_graph_scope)
    )


def _compiler_guidance_metadata_features(metadata: Mapping[str, Any]) -> List[str]:
    features: List[str] = []
    _extend_guidance_mapping_features(metadata, features)
    for key in (
        "compiler_guidance_synthesis_focus",
        "compiler_guidance_semantic_overlay_terms",
    ):
        features.extend(_feature_values(metadata.get(key)))
    ranked = metadata.get("compiler_guidance_ranked_features")
    features.extend(_feature_values(ranked))
    groups = metadata.get("compiler_guidance_feature_groups")
    if isinstance(groups, Mapping):
        for value in groups.values():
            features.extend(_feature_values(value))
    gap_targets, gap_values = _packet_legal_ir_view_gap_evidence(metadata)
    features.extend(gap_targets)
    features.extend(
        f"compiler_guidance_legal_ir_view_gap:{view}:{score:.6f}"
        for view, score in sorted(gap_values.items())
    )
    return _unique(features)


def _extend_guidance_mapping_features(
    value: Any,
    features: List[str],
) -> None:
    mapping = _guidance_mapping(value)
    if not mapping:
        return
    for key in (
        "compiler_guidance_route",
        "route",
        "compiler_guidance_action",
        "action",
        "original_action",
        "failed_action",
        "failed_todo_action",
    ):
        route = str(mapping.get(key) or "").strip()
        if route:
            features.append(route)
            features.append(f"compiler-guidance-route:{route}")
    for key in (
        "program_synthesis_scope",
        "scope",
        "target_file_lane",
        "target_lane",
        "target_metrics",
    ):
        value = mapping.get(key)
        for feature in _feature_values(value):
            features.append(feature)
            features.append(f"{key}:{feature}")
    for key in (
        "target_component",
        "target_view",
        "predicted_component",
        "predicted_view",
    ):
        target = str(mapping.get(key) or "").strip()
        if target:
            features.append(target)
            features.append(f"{key}:{target}")
    for routes_key in ("compiler_guidance_todo_routes", "todo_routes", "routes"):
        raw_routes = mapping.get(routes_key)
        if isinstance(raw_routes, Mapping):
            features.extend(str(route) for route in raw_routes if str(route).strip())
        else:
            features.extend(_feature_values(raw_routes))
    for distribution_key in (
        "legal_ir_target_view_distribution",
        "compiler_guidance_legal_ir_target_view_distribution",
        "target_view_distribution",
    ):
        distribution = mapping.get(distribution_key)
        if isinstance(distribution, Mapping):
            features.extend(str(name) for name in distribution if str(name).strip())
    gap_targets, gap_values = _packet_legal_ir_view_gap_evidence(mapping)
    features.extend(gap_targets)
    features.extend(
        f"compiler_guidance_legal_ir_view_gap:{view}:{score:.6f}"
        for view, score in sorted(gap_values.items())
    )
    for bundle_key in (
        "bundle",
        "semantic_bundle",
        "semantic_bundle_key",
        "compiler_guidance_bundle",
        "vector_bundle",
    ):
        bundle_value = mapping.get(bundle_key)
        features.extend(_feature_values(bundle_value))
        _extend_guidance_mapping_features(bundle_value, features)
    for nested_key in (
        "attribution",
        "compiler_guidance",
        "compiler_guidance_attribution",
        "guidance",
        "metadata",
    ):
        _extend_guidance_mapping_features(mapping.get(nested_key), features)
    for evidence in _guidance_records(
        mapping.get("evidence")
        if "evidence" in mapping
        else mapping.get("compiler_guidance_evidence")
    ):
        _extend_guidance_mapping_features(evidence, features)


def _guidance_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, (str, bytes)):
        return {}
    text = value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else value
    text = text.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _guidance_records(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, (str, bytes)):
        mapping = _guidance_mapping(value)
        return [mapping] if mapping else []
    try:
        return list(value)
    except TypeError:
        return []


def _feature_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        feature = str(value.get("feature") or value.get("name") or "").strip()
        if feature:
            return [feature]
        values: Iterable[Any] = value.values()
    elif isinstance(value, (str, bytes)):
        values = [value]
    else:
        try:
            values = list(value)
        except TypeError:
            values = [value]

    features: List[str] = []
    for item in values:
        if isinstance(item, Mapping):
            feature = str(item.get("feature") or item.get("name") or "").strip()
        else:
            feature = str(item or "").strip()
        if feature:
            features.append(feature)
    return features


def _numeric_distribution(value: Any) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    distribution: Dict[str, float] = {}
    for key, raw_value in value.items():
        name = str(key or "").strip()
        number = _finite_float(raw_value)
        if name and number is not None:
            distribution[name] = number
    total = sum(max(0.0, score) for score in distribution.values())
    if total <= 0.0:
        return {}
    return {
        key: max(0.0, score) / total
        for key, score in sorted(distribution.items())
        if max(0.0, score) > 0.0
    }


def _packet_legal_ir_view_gap_evidence(
    metadata: Mapping[str, Any],
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Normalize autoencoder view-gap buckets into graph target evidence.

    Packet metadata commonly uses compact keys such as
    ``knowledge_graphs_neo4j_compat:underrepresented`` instead of the bridge
    runtime's dotted ``knowledge_graphs.neo4j_compat`` distribution keys.
    Underrepresented buckets mean the graph lane should be projected into the
    Neo4j view, while overrepresented buckets remain negative gap evidence.
    """

    target: Dict[str, float] = {}
    gaps: Dict[str, float] = {}

    for raw_gaps in (
        metadata.get("compiler_guidance_legal_ir_view_gaps"),
        metadata.get("compiler_guidance_legal_ir_view_family_gaps"),
        metadata.get("legal_ir_view_family_gaps"),
        metadata.get("legal_ir_view_gaps"),
    ):
        if not isinstance(raw_gaps, Mapping):
            continue
        for raw_key, raw_value in raw_gaps.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            raw_view, _separator, raw_direction = key.partition(":")
            view = _canonical_legal_ir_view_name(raw_view)
            if not view:
                continue
            weight = _packet_gap_weight(raw_value)
            direction = raw_direction.strip().lower()
            if direction == "underrepresented":
                target[view] = max(target.get(view, 0.0), weight)
                gaps[view] = max(gaps.get(view, 0.0), weight)
            elif direction == "overrepresented":
                gaps[view] = min(gaps.get(view, 0.0), -weight)
            else:
                gaps[view] = gaps.get(view, 0.0) + weight
                if weight > 0.0:
                    target[view] = max(target.get(view, 0.0), weight)

    underrepresented = {
        _canonical_legal_ir_view_name(value)
        for value in _feature_values(metadata.get("legal_ir_underrepresented_components"))
    }
    underrepresented.discard("")
    raw_component_gaps = metadata.get("legal_ir_component_gaps")
    if isinstance(raw_component_gaps, Mapping):
        for raw_key, raw_value in raw_component_gaps.items():
            view = _canonical_legal_ir_view_name(str(raw_key or ""))
            if not view:
                continue
            number = _finite_float(raw_value)
            if number is None:
                continue
            gaps[view] = gaps.get(view, 0.0) + number
            if number > 0.0 or view in underrepresented:
                target[view] = max(target.get(view, 0.0), abs(number) or 1.0)

    for view in underrepresented:
        target[view] = max(target.get(view, 0.0), abs(gaps.get(view, 0.0)) or 1.0)
        gaps[view] = max(gaps.get(view, 0.0), target[view])

    for evidence in _guidance_records(metadata.get("evidence")):
        if not isinstance(evidence, Mapping):
            continue
        nested_target, nested_gaps = _packet_legal_ir_view_gap_evidence(evidence)
        for view, weight in nested_target.items():
            target[view] = max(target.get(view, 0.0), weight)
        for view, value in nested_gaps.items():
            gaps[view] = gaps.get(view, 0.0) + value

    for evidence in _guidance_records(metadata.get("compiler_guidance_evidence")):
        if not isinstance(evidence, Mapping):
            continue
        nested_target, nested_gaps = _packet_legal_ir_view_gap_evidence(evidence)
        for view, weight in nested_target.items():
            target[view] = max(target.get(view, 0.0), weight)
        for view, value in nested_gaps.items():
            gaps[view] = gaps.get(view, 0.0) + value
    return target, gaps


def _canonical_numeric_distribution(value: Any) -> Dict[str, float]:
    distribution: Dict[str, float] = {}
    for key, score in _numeric_distribution(value).items():
        view = _canonical_legal_ir_view_name(key)
        if not view:
            continue
        distribution[view] = distribution.get(view, 0.0) + score
    total = sum(distribution.values())
    if total <= 0.0:
        return {}
    return {
        key: score / total
        for key, score in sorted(distribution.items())
        if score > 0.0
    }


def _canonical_numeric_signed_mapping(value: Any) -> Dict[str, float]:
    mapping: Dict[str, float] = {}
    for key, score in _numeric_signed_mapping(value).items():
        view = _canonical_legal_ir_view_name(key)
        if not view:
            continue
        mapping[view] = mapping.get(view, 0.0) + score
    return dict(sorted(mapping.items()))


def _canonical_legal_ir_view_name(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    aliases = {
        "knowledge_graph": _NEO4J_COMPAT_TARGET_COMPONENT,
        "knowledge_graphs_neo4j_compat": _NEO4J_COMPAT_TARGET_COMPONENT,
        "knowledge_graphs.neo4j_compat": _NEO4J_COMPAT_TARGET_COMPONENT,
        "neo4j_compat": _NEO4J_COMPAT_TARGET_COMPONENT,
        "frame": "modal.frame_logic",
        "modal_frame_logic": "modal.frame_logic",
        "modal.frame_logic": "modal.frame_logic",
        "tdfol_prover": "TDFOL.prover",
        "tdfol.prover": "TDFOL.prover",
        "deontic_ir": "deontic.ir",
        "deontic.ir": "deontic.ir",
        "cec_native": "CEC.native",
        "cec.native": "CEC.native",
        "zkp_circuits": "zkp.circuits",
        "zkp.circuits": "zkp.circuits",
        "external_provers_router": "external_provers.router",
        "external_provers.router": "external_provers.router",
    }
    return aliases.get(normalized.lower(), normalized)


def _packet_gap_weight(value: Any) -> float:
    if isinstance(value, Mapping):
        for key in ("count", "score", "weight", "loss_value", "ce_delta"):
            number = _finite_float(value.get(key))
            if number is not None and number != 0.0:
                return abs(number)
        return 1.0
    number = _finite_float(value)
    if number is None or number == 0.0:
        return 1.0
    return abs(number)


def _numeric_signed_mapping(value: Any) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    mapping: Dict[str, float] = {}
    for key, raw_value in sorted(value.items()):
        name = str(key or "").strip()
        number = _finite_float(raw_value)
        if name and number is not None:
            mapping[name] = number
    return mapping


def _finite_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


__all__ = [
    "FLOGIC_CLASS_LABEL",
    "FLOGIC_FRAME_LABEL",
    "FLOGIC_RESOURCE_LABEL",
    "FLOGIC_VALUE_LABEL",
    "LEGAL_MODAL_DOCUMENT_LABEL",
    "MODAL_FORMULA_LABEL",
    "flogic_ontology_to_dict",
    "flogic_triples_to_graph_data",
    "flogic_triples_to_ontology",
    "import_graph_data_to_graph_engine",
    "import_modal_ir_to_graph_engine",
    "modal_ir_to_neo4j_graph_data",
]
