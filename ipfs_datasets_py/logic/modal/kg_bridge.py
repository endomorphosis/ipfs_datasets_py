"""Bridge modal F-logic IR into Neo4j-compatible graph data.

The modal codec emits simple F-logic triples as the deterministic symbolic
surface of the legal IR.  This module projects those triples into the migration
``GraphData`` format used by the decentralized Neo4j-compatible graph layer.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ipfs_datasets_py.knowledge_graphs.migration.formats import (
    GraphData,
    NodeData,
    RelationshipData,
    SchemaData,
)
from ipfs_datasets_py.logic.flogic import FLogicFrame, FLogicOntology
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import ModalIRDocument


FLOGIC_RESOURCE_LABEL = "FLogicResource"
FLOGIC_VALUE_LABEL = "FLogicValue"
FLOGIC_CLASS_LABEL = "FLogicClass"
FLOGIC_FRAME_LABEL = "FLogicFrame"
MODAL_FORMULA_LABEL = "ModalFormula"
LEGAL_MODAL_DOCUMENT_LABEL = "LegalModalDocument"

_FRAME_PREDICATES = {
    "candidate_ontology_frame",
    "interpreted_in_frame",
    "selected_ontology_frame",
}
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
    "citation_title",
    "evidence",
    "hint_id",
    "sample_id",
}
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
_CITATION_TOKENS = (
    "citation",
    "section",
    "source_id",
    "title",
    "usc",
)
_IDENTIFIER_RE = re.compile(r"[^A-Za-z0-9_]+")


def flogic_triples_to_graph_data(
    triples: Sequence[Mapping[str, Any]],
    *,
    graph_id: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> GraphData:
    """Convert F-logic triples into Neo4j-compatible migration graph data."""
    input_triple_count = len(triples)
    normalized = _normalize_triples(triples)
    projected = _canonical_projection_triples(normalized)
    node_map: Dict[str, NodeData] = {}
    relationships: List[RelationshipData] = []
    relationship_types: set[str] = set()
    projection_view_counts: Dict[str, int] = {}

    for index, triple in enumerate(projected):
        subject = triple["subject"]
        predicate = triple["predicate"]
        obj = triple["object"]
        projection_view = _projection_view_for_predicate(predicate)
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
        obj = str(triple.get("object", "")).strip()
        if not subject or not predicate or not obj:
            continue
        normalized.append({"subject": subject, "predicate": predicate, "object": obj})
    return normalized


def _canonical_projection_triples(
    triples: Sequence[Mapping[str, str]],
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
    return sorted(normalized, key=lambda item: (item["subject"], item["predicate"], item["object"]))


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
    metadata: Dict[str, Any] = {
        "flogic_input_triple_count": input_triple_count,
        "flogic_invalid_triple_count": max(0, input_triple_count - normalized_triple_count),
        "flogic_duplicate_triple_count": max(0, len(triples) - unique_triple_count),
        "flogic_normalized_triple_count": normalized_triple_count,
        "flogic_unique_triple_count": unique_triple_count,
        "frame_logic_projection_input_aligned": relationship_count == input_triple_count,
        "frame_logic_projection_input_relationship_gap": input_triple_count
        - relationship_count,
        "frame_logic_projection_aligned": relationship_count == len(triples),
        "frame_logic_projection_normalized_aligned": relationship_count
        == normalized_triple_count,
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
    }
    selected_frame = _selected_frame_from_triples(triples)
    if selected_frame:
        metadata["frame_logic_selected_frame"] = selected_frame
    return metadata


def _selected_frame_from_triples(triples: Sequence[Mapping[str, str]]) -> str:
    for triple in triples:
        if str(triple.get("predicate") or "") != "selected_ontology_frame":
            continue
        frame = str(triple.get("object") or "").strip()
        if frame:
            return frame
    return ""


def _projection_view_for_predicate(predicate: str) -> str:
    normalized = str(predicate or "").strip().lower()
    if not normalized:
        return "fact"
    if normalized == "type":
        return "type_assertion"
    if normalized in _FRAME_PREDICATES:
        return "frame_link"
    if normalized in _DOCUMENT_SCOPE_PREDICATES:
        return "document_scope"
    if normalized in _PROVENANCE_PREDICATES:
        return "provenance"
    if normalized in _MODAL_SEMANTIC_PREDICATES:
        return "modal_semantics"
    if "ontology_term" in normalized:
        return "ontology_term"
    if any(token in normalized for token in _CITATION_TOKENS):
        return "citation_structure"
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
