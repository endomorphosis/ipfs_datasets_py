"""GraphRAG ontology serialization helpers.

This module centralizes conversions between the internal GraphRAG dataclasses
(:class:`~ipfs_datasets_py.optimizers.graphrag.ontology_generator.Entity` and
:class:`~ipfs_datasets_py.optimizers.graphrag.ontology_generator.Relationship`)
and the public ontology-dict schema used across the package.

The canonical *public* dict schema intentionally stays minimal:

Entity dict keys:
    - ``id`` (str)
    - ``text`` (str)
    - ``type`` (str)
    - ``confidence`` (float)
    - ``properties`` (dict)

Relationship dict keys:
    - ``id`` (str)
    - ``source_id`` (str)
    - ``target_id`` (str)
    - ``type`` (str)
    - ``confidence`` (float)
    - ``properties`` (dict)

Internal-only fields like ``source_span``, ``last_seen``, or ``direction`` are
preserved on the dataclass side but are not emitted in the public dicts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple, cast

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity as EntityModel,
    EntityExtractionResult as ExtractionResultModel,
    Relationship as RelationshipModel,
)


def entity_model_to_dict(entity: EntityModel) -> Dict[str, Any]:
    """Convert an :class:`Entity` dataclass to the canonical public dict."""
    return {
        "id": entity.id,
        "text": entity.text,
        "type": entity.type,
        "confidence": float(getattr(entity, "confidence", 1.0)),
        "properties": dict(getattr(entity, "properties", {}) or {}),
    }


def relationship_model_to_dict(rel: RelationshipModel) -> Dict[str, Any]:
    """Convert a :class:`Relationship` dataclass to the canonical public dict."""
    return {
        "id": rel.id,
        "source_id": rel.source_id,
        "target_id": rel.target_id,
        "type": rel.type,
        "confidence": float(getattr(rel, "confidence", 1.0)),
        "properties": dict(getattr(rel, "properties", {}) or {}),
    }


def entity_dict_to_model(d: Mapping[str, Any]) -> EntityModel:
    """Convert a (possibly extended) entity dict to an :class:`Entity`.

    The function accepts canonical public dicts and also tolerates additional
    keys like ``source_span`` and ``last_seen``.
    """
    return EntityModel.from_dict(dict(d))


def relationship_dict_to_model(d: Mapping[str, Any]) -> RelationshipModel:
    """Convert a (possibly extended) relationship dict to a :class:`Relationship`.

    The function accepts canonical public dicts and also tolerates additional
    keys like ``direction``.
    """
    return RelationshipModel.from_dict(dict(d))


def build_ontology_dict(
    *,
    entities: Sequence[EntityModel],
    relationships: Sequence[RelationshipModel],
) -> Dict[str, Any]:
    """Build a canonical public ontology dict from dataclass collections."""
    return {
        "entities": [entity_model_to_dict(e) for e in entities],
        "relationships": [relationship_model_to_dict(r) for r in relationships],
    }


def ontology_from_extraction_result(extraction: ExtractionResultModel) -> Dict[str, Any]:
    """Convert an :class:`EntityExtractionResult` to a canonical ontology dict."""
    return build_ontology_dict(entities=extraction.entities, relationships=extraction.relationships)


def models_from_ontology_dict(ontology: Mapping[str, Any]) -> Tuple[List[EntityModel], List[RelationshipModel]]:
    """Convert a canonical ontology dict into lists of dataclass models."""
    entities_raw = cast(Sequence[Mapping[str, Any]], ontology.get("entities") or [])
    rels_raw = cast(Sequence[Mapping[str, Any]], ontology.get("relationships") or [])
    return (
        [entity_dict_to_model(e) for e in entities_raw],
        [relationship_dict_to_model(r) for r in rels_raw],
    )
