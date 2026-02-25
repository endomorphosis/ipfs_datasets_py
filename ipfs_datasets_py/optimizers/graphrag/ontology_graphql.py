"""Lightweight GraphQL query interface for ontologies.

Provides a practical GraphQL API for querying extracted ontologies from
OntologyGenerator. Supports entity selection, relationship traversal, filtering,
and field projection without requiring a full GraphQL server.

Supported Query Features
------------------------
* **Entity selection by type** — Top-level field name matches entity type
* **Argument filters** — Equality filters on ``id``, ``text``, ``type``,
  ``confidence``, or any entity ``properties`` key
* **Field projection** — Request specific fields: ``id``, ``text``, ``type``,
  ``confidence``, ``properties``, ``context``, ``source_span``
* **Relationship traversal** — Nested field whose name matches a relationship
  type resolves to target entities via ``source_id`` → ``target_id`` edges
* **Aliases** — Standard GraphQL alias syntax (``myEntities: person { text }``)
* **Scalar values** — String, int, float, bool, null arguments

Response Format
---------------
Follows GraphQL-over-HTTP specification::

    {"data": {...}}
    {"data": {...}, "errors": [...]}  # on parse or resolution errors

Example Usage
-------------
::

    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    from ipfs_datasets_py.optimizers.graphrag.ontology_graphql import OntologyGraphQLExecutor

    generator = OntologyGenerator()
    result = generator.extract_entities("Apple Inc. acquired Tesla for $100B.", context)
    ontology = result.ontology

    executor = OntologyGraphQLExecutor(ontology)

    # Query all organizations with confidence > 0.8
    response = executor.execute('''
    {
        Organization(confidence: 0.8) {
            id
            text
            confidence
            properties
            acquires {
                text
                type
            }
        }
    }
    ''')
    # {"data": {"Organization": [{"id": "...", "text": "Apple Inc.", ...}]}}

Integration
-----------
This module reuses the GraphQL parser from the knowledge graphs module and
adapts the executor for ontology-specific data structures (TypedDict-based
Entity/Relationship instead of dataclass-based KnowledgeGraph entities).

See Also
--------
- :mod:`ipfs_datasets_py.knowledge_graphs.query.graphql` — Knowledge graph GraphQL (sibling implementation)
- :mod:`ipfs_datasets_py.optimizers.graphrag.ontology_types` — Entity/Relationship type definitions
- :mod:`ipfs_datasets_py.optimizers.graphrag.ontology_generator` — Ontology extraction
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

# Import parser and AST from knowledge graph GraphQL module (DRY)
from ipfs_datasets_py.knowledge_graphs.query.graphql import (
    GraphQLField,
    GraphQLDocument,
    GraphQLParser,
    GraphQLParseError,
)

from ipfs_datasets_py.optimizers.graphrag.ontology_types import (
    Entity,
    Relationship,
    Ontology,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ontology GraphQL Executor
# ---------------------------------------------------------------------------


class OntologyGraphQLExecutor:
    """Execute GraphQL-style queries against an ontology.

    Supports a practical GraphQL subset optimized for ontology exploration:
    entity filtering, relationship traversal, field projection, and aliases.

    Results are returned in the standard GraphQL-over-HTTP response envelope::

        {"data": {...}}
        {"data": {...}, "errors": [...]}  # on partial failures

    Args:
        ontology: An :class:`~ipfs_datasets_py.optimizers.graphrag.ontology_types.Ontology`
            TypedDict (contains ``entities`` and ``relationships`` lists).

    Example::

        executor = OntologyGraphQLExecutor(ontology)
        result = executor.execute(\"\"\"
        {
            Person(confidence: 0.8) {
                id
                text
                properties
                works_at {
                    text
                    type
                }
            }
        }
        \"\"\")

    Notes:
        - Entity types are matched case-insensitively
        - Argument filters use equality comparison
        - Relationship traversal follows ``source_id`` → ``target_id`` edges
        - Missing fields return ``None``
        - Parse errors and resolution exceptions surface in the ``errors`` array
    """

    def __init__(self, ontology: Ontology) -> None:
        """Initialize the GraphQL executor.

        Args:
            ontology: Ontology dict with ``entities`` and ``relationships`` keys.
                Expected to match the :class:`Ontology` TypedDict structure.
        """
        self._ontology = ontology
        self._parser = GraphQLParser()

        # Index entities and relationships for fast lookup
        self._entities: List[Entity] = ontology.get("entities", [])
        self._relationships: List[Relationship] = ontology.get("relationships", [])

        # Build entity lookup by ID for relationship resolution
        self._entity_by_id: Dict[str, Entity] = {
            e["id"]: e for e in self._entities
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, query_text: str) -> Dict[str, Any]:
        """Execute a GraphQL query against the ontology.

        Args:
            query_text: GraphQL query string following the subset grammar.

        Returns:
            GraphQL response dict::

                {"data": {field_key: [entity_dicts]}}

            If parse or resolution errors occur, includes an ``errors`` key::

                {"data": {...}, "errors": [{"message": "...", "path": [...]}]}

        Example::

            >>> result = executor.execute('{ Person { text confidence } }')
            >>> result["data"]["Person"]
            [{"text": "Alice", "confidence": 0.95}, ...]
        """
        # Parse the query
        try:
            doc = self._parser.parse(query_text)
        except GraphQLParseError as exc:
            return {"data": None, "errors": [{"message": str(exc)}]}

        # Resolve each top-level selection
        data: Dict[str, Any] = {}
        errors: List[Dict[str, str]] = []

        for sel in doc.selections:
            key = sel.alias or sel.name
            try:
                data[key] = self._resolve_selection(sel)
            except Exception as exc:  # noqa: BLE001 — surface as GraphQL error
                logger.debug(
                    "GraphQL resolution error for field %r (%s): %s",
                    sel.name,
                    type(exc).__name__,
                    exc,
                )
                errors.append({"message": str(exc), "path": [key]})
                data[key] = None

        result: Dict[str, Any] = {"data": data}
        if errors:
            result["errors"] = errors
        return result

    # ------------------------------------------------------------------
    # Internal resolution helpers
    # ------------------------------------------------------------------

    def _resolve_selection(self, sel: GraphQLField) -> List[Dict[str, Any]]:
        """Resolve a top-level entity-type selection.

        Args:
            sel: GraphQL field selection targeting an entity type.

        Returns:
            List of entity dicts matching the type and filters.
        """
        entity_type = sel.name

        # Collect entities matching the type (case-insensitive)
        matches = [
            e
            for e in self._entities
            if e["type"].lower() == entity_type.lower()
        ]

        # Apply argument equality filters
        for arg_name, arg_value in sel.arguments.items():
            if arg_name == "id":
                matches = [e for e in matches if e["id"] == str(arg_value)]
            elif arg_name == "text":
                matches = [e for e in matches if e["text"] == str(arg_value)]
            elif arg_name == "type":
                matches = [e for e in matches if e["type"] == str(arg_value)]
            elif arg_name == "confidence":
                # Numeric filter: entities with confidence >= filter value
                matches = [
                    e for e in matches if e["confidence"] >= float(arg_value)
                ]
            else:
                # Filter on properties
                matches = [
                    e
                    for e in matches
                    if e.get("properties", {}).get(arg_name) == arg_value
                ]

        # If no field selection, return default entity dicts
        if not sel.sub_fields:
            return [self._default_entity_dict(e) for e in matches]

        # Project specific fields
        return [self._project_entity(e, sel.sub_fields) for e in matches]

    def _project_entity(
        self,
        entity: Entity,
        fields: List[GraphQLField],
    ) -> Dict[str, Any]:
        """Project entity fields according to the GraphQL field list.

        Args:
            entity: Entity dict to project.
            fields: List of field selections.

        Returns:
            Dict with only requested fields.
        """
        result: Dict[str, Any] = {}
        for fld in fields:
            key = fld.alias or fld.name
            if fld.sub_fields:
                # Nested field — resolve as relationship traversal
                result[key] = self._resolve_relationship(entity, fld)
            else:
                # Scalar field
                result[key] = self._get_entity_field(entity, fld.name)
        return result

    def _get_entity_field(self, entity: Entity, field_name: str) -> Any:
        """Return a single scalar field value from an entity.

        Args:
            entity: Entity dict.
            field_name: Field name to retrieve.

        Returns:
            Field value or None if missing.
        """
        # Core entity fields
        if field_name == "id":
            return entity["id"]
        if field_name == "text":
            return entity["text"]
        if field_name == "type":
            return entity["type"]
        if field_name == "confidence":
            return entity["confidence"]
        if field_name == "context":
            return entity.get("context")
        if field_name == "source_span":
            return entity.get("source_span")
        if field_name == "properties":
            return entity.get("properties", {})

        # Fall through to properties dict (e.g., "age", "city")
        return entity.get("properties", {}).get(field_name)

    def _resolve_relationship(
        self,
        source: Entity,
        fld: GraphQLField,
    ) -> List[Dict[str, Any]]:
        """Resolve a nested relationship field to target entities.

        Args:
            source: Source entity.
            fld: GraphQL field representing a relationship type.

        Returns:
            List of target entity dicts connected via the relationship type.
        """
        rel_type = fld.name
        targets: List[Entity] = []

        # Find all relationships of this type starting from source entity
        for rel in self._relationships:
            if (
                rel["type"].lower() == rel_type.lower()
                and rel["source_id"] == source["id"]
            ):
                target = self._entity_by_id.get(rel["target_id"])
                if target is not None:
                    targets.append(target)

        # If no field selection, return default dicts
        if not fld.sub_fields:
            return [self._default_entity_dict(t) for t in targets]

        # Project specific fields from targets
        return [self._project_entity(t, fld.sub_fields) for t in targets]

    def _default_entity_dict(self, entity: Entity) -> Dict[str, Any]:
        """Return the default dict representation of an entity.

        Args:
            entity: Entity dict.

        Returns:
            Dict with ``id``, ``text``, ``type``, ``confidence``, and all properties.
        """
        result: Dict[str, Any] = {
            "id": entity["id"],
            "text": entity["text"],
            "type": entity["type"],
            "confidence": entity["confidence"],
        }
        # Merge in properties if present
        if "properties" in entity:
            result.update(entity["properties"])
        return result


__all__ = [
    "OntologyGraphQLExecutor",
    "GraphQLParseError",  # re-export from knowledge_graphs module
]
