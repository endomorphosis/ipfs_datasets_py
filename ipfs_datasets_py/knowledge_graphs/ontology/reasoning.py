"""
Ontology Reasoning Engine — Item 12 of DEFERRED_FEATURES.md.

Provides OWL/RDFS-style inference rules applied to
:class:`~ipfs_datasets_py.knowledge_graphs.extraction.graph.KnowledgeGraph`
objects.

Supported inference rules
--------------------------
* **subClassOf** (``rdfs:subClassOf``) — transitive class hierarchy.  If
  ``Employee subClassOf Person`` then every ``Employee`` node is also typed
  ``Person``.
* **subPropertyOf** (``rdfs:subPropertyOf``) — if ``worksAt subPropertyOf
  isAffiliatedWith`` then every ``worksAt`` relationship generates an
  ``isAffiliatedWith`` relationship.
* **transitive** (``owl:TransitiveProperty``) — if ``(A, p, B)`` and
  ``(B, p, C)`` then ``(A, p, C)`` is inferred.
* **symmetric** (``owl:SymmetricProperty``) — if ``(A, p, B)`` then
  ``(B, p, A)`` is inferred.
* **inverseOf** (``owl:inverseOf``) — if ``(A, p, B)`` and *p inverseOf q*,
  then ``(B, q, A)`` is inferred.
* **domain** (``rdfs:domain``) — nodes that are the *source* of a property
  with a declared domain class get that class added to their type set.
* **range** (``rdfs:range``) — nodes that are the *target* of a property
  with a declared range class get that class added to their type set.

Consistency checking
---------------------
:meth:`OntologyReasoner.check_consistency` detects:

* Disjoint class violations — a node is typed with two classes declared as
  ``disjointWith``.
* Negative property assertions — an explicit ``NOT_p`` relationship exists
  alongside a positive ``p`` relationship for the same pair.

Usage
------
::

    from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
        OntologySchema, OntologyReasoner,
    )
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

    schema = OntologySchema()
    schema.add_subclass("Employee", "Person")
    schema.add_subclass("Manager", "Employee")
    schema.add_transitive("isAncestorOf")
    schema.add_symmetric("isSiblingOf")
    schema.add_inverse("isParentOf", "isChildOf")
    schema.add_domain("worksAt", "Person")
    schema.add_range("worksAt", "Organization")

    reasoner = OntologyReasoner(schema)
    kg = reasoner.materialize(my_kg)  # returns augmented copy
    violations = reasoner.check_consistency(kg)
"""

from __future__ import annotations

import copy
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ConsistencyViolation:
    """Describes a single ontology consistency violation.

    Attributes:
        violation_type: Human-readable category (e.g. ``"disjoint_class"``).
        message:        Description of the violation.
        entity_ids:     IDs of the entities involved.
        relationship_ids: IDs of the relationships involved (if any).
    """

    violation_type: str
    message: str
    entity_ids: List[str] = field(default_factory=list)
    relationship_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "violation_type": self.violation_type,
            "message": self.message,
            "entity_ids": self.entity_ids,
            "relationship_ids": self.relationship_ids,
        }


# ---------------------------------------------------------------------------
# OntologySchema
# ---------------------------------------------------------------------------


class OntologySchema:
    """Stores ontology declarations used by :class:`OntologyReasoner`.

    All declarations are **additive** — calling ``add_subclass`` multiple times
    builds up the hierarchy incrementally.

    Attributes:
        subclass_map:   ``{child_class: {parent_classes}}``.
        subproperty_map: ``{child_prop: {parent_props}}``.
        transitive:     Set of property names that are transitive.
        symmetric:      Set of property names that are symmetric.
        inverse_map:    ``{prop: inverse_prop}`` (bidirectional).
        domain_map:     ``{prop: domain_class}`` — source entity class.
        range_map:      ``{prop: range_class}`` — target entity class.
        disjoint_map:   ``{class_a: {class_b, …}}`` — disjoint class pairs.
    """

    def __init__(self) -> None:
        self.subclass_map: Dict[str, Set[str]] = {}
        self.subproperty_map: Dict[str, Set[str]] = {}
        self.transitive: Set[str] = set()
        self.symmetric: Set[str] = set()
        self.inverse_map: Dict[str, str] = {}
        self.domain_map: Dict[str, str] = {}
        self.range_map: Dict[str, str] = {}
        self.disjoint_map: Dict[str, Set[str]] = {}
        # OWL 2 property chain axioms: list of (chain_props, result_property)
        self.property_chains: List[Tuple[List[str], str]] = []

    # ------------------------------------------------------------------
    # Builder API
    # ------------------------------------------------------------------

    def add_subclass(self, child: str, parent: str) -> "OntologySchema":
        """Declare *child* as a sub-class of *parent*.

        Args:
            child:  Sub-class name.
            parent: Super-class name.

        Returns:
            ``self`` for chaining.
        """
        self.subclass_map.setdefault(child, set()).add(parent)
        return self

    def add_subproperty(self, child: str, parent: str) -> "OntologySchema":
        """Declare *child* as a sub-property of *parent*.

        Args:
            child:  Sub-property name.
            parent: Super-property name.

        Returns:
            ``self`` for chaining.
        """
        self.subproperty_map.setdefault(child, set()).add(parent)
        return self

    def add_transitive(self, property_name: str) -> "OntologySchema":
        """Declare *property_name* as a transitive property.

        Args:
            property_name: Relationship type name.

        Returns:
            ``self`` for chaining.
        """
        self.transitive.add(property_name)
        return self

    def add_symmetric(self, property_name: str) -> "OntologySchema":
        """Declare *property_name* as a symmetric property.

        Args:
            property_name: Relationship type name.

        Returns:
            ``self`` for chaining.
        """
        self.symmetric.add(property_name)
        return self

    def add_inverse(self, prop: str, inverse_prop: str) -> "OntologySchema":
        """Declare *prop* and *inverse_prop* as mutual inverses.

        Args:
            prop:         Forward property name.
            inverse_prop: Inverse property name.

        Returns:
            ``self`` for chaining.
        """
        self.inverse_map[prop] = inverse_prop
        self.inverse_map[inverse_prop] = prop
        return self

    def add_domain(self, property_name: str, domain_class: str) -> "OntologySchema":
        """Declare the domain class for *property_name*.

        Nodes appearing as the *source* of this relationship will be typed
        with *domain_class* during materialisation.

        Args:
            property_name: Relationship type name.
            domain_class:  Entity type / class name.

        Returns:
            ``self`` for chaining.
        """
        self.domain_map[property_name] = domain_class
        return self

    def add_range(self, property_name: str, range_class: str) -> "OntologySchema":
        """Declare the range class for *property_name*.

        Nodes appearing as the *target* of this relationship will be typed
        with *range_class* during materialisation.

        Args:
            property_name: Relationship type name.
            range_class:   Entity type / class name.

        Returns:
            ``self`` for chaining.
        """
        self.range_map[property_name] = range_class
        return self

    def add_disjoint(self, class_a: str, class_b: str) -> "OntologySchema":
        """Declare *class_a* and *class_b* as disjoint.

        An entity may not simultaneously belong to both classes.

        Args:
            class_a: First class.
            class_b: Second class (order does not matter).

        Returns:
            ``self`` for chaining.
        """
        self.disjoint_map.setdefault(class_a, set()).add(class_b)
        self.disjoint_map.setdefault(class_b, set()).add(class_a)
        return self

    def add_property_chain(
        self, chain: List[str], result_property: str
    ) -> "OntologySchema":
        """Declare an OWL 2 property chain axiom.

        A property chain axiom states that a path of the form
        ``(A, chain[0], B0), (B0, chain[1], B1), …, (B_{n-1}, chain[-1], C)``
        implies the inferred relationship ``(A, result_property, C)``.

        The chain must contain at least two properties.

        Args:
            chain:           Ordered list of property names forming the chain
                             (minimum length 2).
            result_property: Name of the resulting (inferred) property.

        Returns:
            ``self`` for chaining.

        Raises:
            ValueError: If *chain* contains fewer than two elements.

        Example::

            schema.add_property_chain(["hasMother", "hasMother"], "hasMaternalGrandmother")
            schema.add_property_chain(["isPartOf", "isPartOf"], "isPartOf")  # transitive via chain
        """
        if len(chain) < 2:
            raise ValueError(
                "Property chain must contain at least two properties; "
                f"got {chain!r}."
            )
        self.property_chains.append((list(chain), result_property))
        return self

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_turtle(self) -> str:
        """Serialise the schema to Turtle / N-Triples notation.

        The result uses the ``rdfs:`` and ``owl:`` prefixes and a local
        ``urn:ontology:`` base URI (``:``) for all named terms.

        Returns:
            Turtle string that can be written to a ``.ttl`` file or round-
            tripped via :meth:`from_turtle`.
        """
        lines: List[str] = [
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
            "@prefix owl:  <http://www.w3.org/2002/07/owl#> .",
            "@prefix :     <urn:ontology:> .",
            "",
        ]
        for child, parents in sorted(self.subclass_map.items()):
            for parent in sorted(parents):
                lines.append(f":{child} rdfs:subClassOf :{parent} .")
        for child, parents in sorted(self.subproperty_map.items()):
            for parent in sorted(parents):
                lines.append(f":{child} rdfs:subPropertyOf :{parent} .")
        for prop in sorted(self.transitive):
            lines.append(f":{prop} a owl:TransitiveProperty .")
        for prop in sorted(self.symmetric):
            lines.append(f":{prop} a owl:SymmetricProperty .")
        seen_inv: Set[FrozenSet[str]] = set()
        for prop, inv_prop in sorted(self.inverse_map.items()):
            pair: FrozenSet[str] = frozenset({prop, inv_prop})
            if pair not in seen_inv:
                seen_inv.add(pair)
                lines.append(f":{prop} owl:inverseOf :{inv_prop} .")
        for prop, domain_cls in sorted(self.domain_map.items()):
            lines.append(f":{prop} rdfs:domain :{domain_cls} .")
        for prop, range_cls in sorted(self.range_map.items()):
            lines.append(f":{prop} rdfs:range :{range_cls} .")
        seen_disj: Set[FrozenSet[str]] = set()
        for cls_a, classes in sorted(self.disjoint_map.items()):
            for cls_b in sorted(classes):
                pair = frozenset({cls_a, cls_b})
                if pair not in seen_disj:
                    seen_disj.add(pair)
                    lines.append(f":{cls_a} owl:disjointWith :{cls_b} .")
        for chain_props, result_prop in self.property_chains:
            chain_str = " ".join(f":{p}" for p in chain_props)
            lines.append(f":{result_prop} owl:propertyChainAxiom ( {chain_str} ) .")
        return "\n".join(lines) + "\n"

    @classmethod
    def from_turtle(cls, text: str) -> "OntologySchema":
        """Parse a Turtle string produced by :meth:`to_turtle`.

        Only the subset of Turtle understood by this class is recognised
        (local prefix ``:``, predicate keywords, and property-chain lists).
        Full Turtle or OWL/RDF files with arbitrary syntax are not supported.

        Args:
            text: Turtle string (as produced by :meth:`to_turtle`).

        Returns:
            New :class:`OntologySchema` populated from the declarations.
        """
        schema = cls()
        # Match triples of the form ":Subject Predicate Object ."
        # The non-greedy `(.+?)` object group is intentional: to_turtle()
        # generates one logical triple per line and never embeds literal dots
        # in the object value, so the trailing `\.\s*$` anchor is safe.
        # Full Turtle files with multi-line statements are not supported.
        triple_re = re.compile(
            r"^:(\S+)\s+([\w:]+)\s+(.+?)\s*\.\s*$"
        )
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("@prefix"):
                continue
            m = triple_re.match(line)
            if not m:
                continue
            subject, predicate, obj = m.group(1), m.group(2), m.group(3).strip()
            # Strip leading ':' from simple object names
            obj_name = obj.lstrip(":").strip()

            if predicate == "rdfs:subClassOf":
                schema.add_subclass(subject, obj_name)
            elif predicate == "rdfs:subPropertyOf":
                schema.add_subproperty(subject, obj_name)
            elif predicate == "a" and obj_name == "owl:TransitiveProperty":
                schema.add_transitive(subject)
            elif predicate == "a" and obj_name == "owl:SymmetricProperty":
                schema.add_symmetric(subject)
            elif predicate == "owl:inverseOf":
                schema.add_inverse(subject, obj_name)
            elif predicate == "rdfs:domain":
                schema.add_domain(subject, obj_name)
            elif predicate == "rdfs:range":
                schema.add_range(subject, obj_name)
            elif predicate == "owl:disjointWith":
                schema.add_disjoint(subject, obj_name)
            elif predicate == "owl:propertyChainAxiom":
                # Parse "( :p1 :p2 … )"
                chain = re.findall(r":(\w+)", obj)
                if len(chain) >= 2:
                    schema.add_property_chain(chain, subject)
        return schema

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_all_superclasses(self, cls: str) -> Set[str]:
        """Return the transitive closure of super-classes for *cls*."""
        result: Set[str] = set()
        queue = list(self.subclass_map.get(cls, set()))
        while queue:
            current = queue.pop()
            if current not in result:
                result.add(current)
                queue.extend(self.subclass_map.get(current, set()))
        return result

    def get_all_superproperties(self, prop: str) -> Set[str]:
        """Return the transitive closure of super-properties for *prop*."""
        result: Set[str] = set()
        queue = list(self.subproperty_map.get(prop, set()))
        while queue:
            current = queue.pop()
            if current not in result:
                result.add(current)
                queue.extend(self.subproperty_map.get(current, set()))
        return result


# ---------------------------------------------------------------------------
# OntologyReasoner
# ---------------------------------------------------------------------------


class OntologyReasoner:
    """Applies ontology inference rules to :class:`KnowledgeGraph` objects.

    Args:
        schema: :class:`OntologySchema` with the ontology declarations.
        max_iterations: Safety cap on the fixpoint loop (default 20).

    Example::

        schema = OntologySchema()
        schema.add_subclass("Manager", "Employee").add_subclass("Employee", "Person")
        reasoner = OntologyReasoner(schema)
        kg_with_inferences = reasoner.materialize(kg)
    """

    def __init__(
        self,
        schema: Optional[OntologySchema] = None,
        max_iterations: int = 20,
    ) -> None:
        self.schema = schema or OntologySchema()
        self.max_iterations = max_iterations

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def materialize(self, kg: Any, in_place: bool = False) -> Any:
        """Apply all inference rules and return the augmented knowledge graph.

        Runs a fixpoint loop until no new facts can be derived or until
        *max_iterations* is reached.

        Args:
            kg:       Source :class:`KnowledgeGraph`.
            in_place: If ``True``, mutate *kg* directly.  Default is ``False``
                      (work on a deep copy).

        Returns:
            The augmented :class:`KnowledgeGraph` (same object if *in_place*,
            otherwise a fresh copy).
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship

        result_kg: Any = kg if in_place else copy.deepcopy(kg)

        for iteration in range(self.max_iterations):
            new_facts = 0
            new_facts += self._apply_subclass(result_kg, Entity)
            new_facts += self._apply_subproperty(result_kg, Relationship)
            new_facts += self._apply_transitive(result_kg, Relationship)
            new_facts += self._apply_symmetric(result_kg, Relationship)
            new_facts += self._apply_inverse(result_kg, Relationship)
            new_facts += self._apply_domain(result_kg, Entity)
            new_facts += self._apply_range(result_kg, Entity)
            new_facts += self._apply_property_chains(result_kg, Relationship)

            if new_facts == 0:
                logger.debug(
                    "Ontology fixpoint reached after %d iteration(s).", iteration + 1
                )
                break
        else:
            logger.warning(
                "Ontology fixpoint did not converge within %d iterations.",
                self.max_iterations,
            )

        return result_kg

    def check_consistency(self, kg: Any) -> List[ConsistencyViolation]:
        """Check *kg* for ontology consistency violations.

        Detects:

        * **disjoint_class** — an entity has two types declared as
          ``owl:disjointWith``.
        * **negative_assertion** — a relationship ``NOT_p`` exists alongside
          a positive ``p`` for the same entity pair.

        Args:
            kg: :class:`KnowledgeGraph` to check.

        Returns:
            List of :class:`ConsistencyViolation` objects (empty = consistent).
        """
        violations: List[ConsistencyViolation] = []
        violations.extend(self._check_disjoint_classes(kg))
        violations.extend(self._check_negative_assertions(kg))
        return violations

    def get_inferred_types(self, entity_type: str) -> Set[str]:
        """Return all types that should be inferred for an entity with *entity_type*.

        Args:
            entity_type: The entity's declared type.

        Returns:
            Set of inferred super-class types (excluding *entity_type* itself).
        """
        return self.schema.get_all_superclasses(entity_type)

    # ------------------------------------------------------------------
    # Internal rule implementations
    # ------------------------------------------------------------------

    def _apply_subclass(self, kg: Any, Entity: Any) -> int:
        """Add inferred super-class types as new entity aliases.

        For each entity with type ``T``, if ``T subClassOf S``, we store the
        inferred type in ``entity.properties["inferred_types"]`` (to avoid
        conflating the primary type).  We also re-index the entity under the
        super-class type in ``kg.entity_types``.

        Returns:
            Number of new type inferences added.
        """
        new_count = 0
        for entity in list(kg.entities.values()):
            declared_type = entity.entity_type
            superclasses = self.schema.get_all_superclasses(declared_type)
            existing_inferred: Set[str] = set(
                (entity.properties or {}).get("inferred_types", [])
            )
            for sc in superclasses:
                if sc not in existing_inferred:
                    existing_inferred.add(sc)
                    kg.entity_types.setdefault(sc, set()).add(entity.entity_id)
                    new_count += 1

            if new_count:
                props = dict(entity.properties) if entity.properties else {}
                props["inferred_types"] = sorted(existing_inferred)
                entity.properties = props

        return new_count

    def _apply_subproperty(self, kg: Any, Relationship: Any) -> int:
        """Generate super-property relationships.

        For each relationship of type *p*, if ``p subPropertyOf q``, add a new
        relationship of type *q* between the same entities.

        Returns:
            Number of new relationships added.
        """
        new_count = 0
        for rel in list(kg.relationships.values()):
            superprops = self.schema.get_all_superproperties(rel.relationship_type)
            for sp in superprops:
                if not self._rel_exists(kg, rel.source_id, rel.target_id, sp):
                    new_rel = self._clone_rel(rel, sp, Relationship)
                    kg.add_relationship(new_rel)
                    new_count += 1
        return new_count

    def _apply_transitive(self, kg: Any, Relationship: Any) -> int:
        """Close transitive properties.

        If ``(A, p, B)`` and ``(B, p, C)`` and *p* is transitive, add ``(A, p, C)``.

        Returns:
            Number of new relationships added.
        """
        new_count = 0
        for prop in self.schema.transitive:
            rels = [
                r for r in kg.relationships.values()
                if r.relationship_type == prop
            ]
            # Build adjacency: source_id → set of target_ids
            adj: Dict[str, Set[str]] = {}
            for r in rels:
                adj.setdefault(r.source_id, set()).add(r.target_id)

            # Transitive closure via BFS per source
            for start in list(adj.keys()):
                visited: Set[str] = set()
                queue = list(adj.get(start, set()))
                while queue:
                    mid = queue.pop()
                    if mid in visited:
                        continue
                    visited.add(mid)
                    for end in adj.get(mid, set()):
                        if end != start and not self._rel_exists(kg, start, end, prop):
                            src_ent = kg.entities.get(start)
                            tgt_ent = kg.entities.get(end)
                            if src_ent and tgt_ent:
                                new_rel = Relationship(
                                    relationship_type=prop,
                                    source_entity=src_ent,
                                    target_entity=tgt_ent,
                                    confidence=0.75,
                                    properties={"inferred": True, "rule": "transitive"},
                                )
                                kg.add_relationship(new_rel)
                                new_count += 1
                                adj.setdefault(start, set()).add(end)
                        if end not in visited:
                            queue.append(end)

        return new_count

    def _apply_symmetric(self, kg: Any, Relationship: Any) -> int:
        """Generate reverse relationships for symmetric properties.

        If ``(A, p, B)`` and *p* is symmetric, add ``(B, p, A)``.

        Returns:
            Number of new relationships added.
        """
        new_count = 0
        for rel in list(kg.relationships.values()):
            if rel.relationship_type in self.schema.symmetric:
                if not self._rel_exists(kg, rel.target_id, rel.source_id, rel.relationship_type):
                    src_ent = kg.entities.get(rel.target_id)
                    tgt_ent = kg.entities.get(rel.source_id)
                    if src_ent and tgt_ent:
                        new_rel = Relationship(
                            relationship_type=rel.relationship_type,
                            source_entity=src_ent,
                            target_entity=tgt_ent,
                            confidence=rel.confidence,
                            properties={"inferred": True, "rule": "symmetric"},
                        )
                        kg.add_relationship(new_rel)
                        new_count += 1
        return new_count

    def _apply_inverse(self, kg: Any, Relationship: Any) -> int:
        """Generate inverse relationships.

        If ``(A, p, B)`` and *p inverseOf q*, add ``(B, q, A)``.

        Returns:
            Number of new relationships added.
        """
        new_count = 0
        for rel in list(kg.relationships.values()):
            inv_prop = self.schema.inverse_map.get(rel.relationship_type)
            if inv_prop:
                if not self._rel_exists(kg, rel.target_id, rel.source_id, inv_prop):
                    src_ent = kg.entities.get(rel.target_id)
                    tgt_ent = kg.entities.get(rel.source_id)
                    if src_ent and tgt_ent:
                        new_rel = Relationship(
                            relationship_type=inv_prop,
                            source_entity=src_ent,
                            target_entity=tgt_ent,
                            confidence=rel.confidence,
                            properties={"inferred": True, "rule": "inverse"},
                        )
                        kg.add_relationship(new_rel)
                        new_count += 1
        return new_count

    def _apply_domain(self, kg: Any, Entity: Any) -> int:
        """Infer entity types from property domains.

        If *p* has declared domain *D* and node *A* is the source of a *p*
        relationship, add *D* to *A*'s inferred types.

        Returns:
            Number of new type inferences.
        """
        new_count = 0
        for rel in kg.relationships.values():
            domain_cls = self.schema.domain_map.get(rel.relationship_type)
            if not domain_cls:
                continue
            entity = kg.entities.get(rel.source_id)
            if entity and entity.entity_type != domain_cls:
                inferred: Set[str] = set((entity.properties or {}).get("inferred_types", []))
                if domain_cls not in inferred:
                    inferred.add(domain_cls)
                    kg.entity_types.setdefault(domain_cls, set()).add(entity.entity_id)
                    props = dict(entity.properties) if entity.properties else {}
                    props["inferred_types"] = sorted(inferred)
                    entity.properties = props
                    new_count += 1
        return new_count

    def _apply_range(self, kg: Any, Entity: Any) -> int:
        """Infer entity types from property ranges.

        If *p* has declared range *R* and node *B* is the target of a *p*
        relationship, add *R* to *B*'s inferred types.

        Returns:
            Number of new type inferences.
        """
        new_count = 0
        for rel in kg.relationships.values():
            range_cls = self.schema.range_map.get(rel.relationship_type)
            if not range_cls:
                continue
            entity = kg.entities.get(rel.target_id)
            if entity and entity.entity_type != range_cls:
                inferred: Set[str] = set((entity.properties or {}).get("inferred_types", []))
                if range_cls not in inferred:
                    inferred.add(range_cls)
                    kg.entity_types.setdefault(range_cls, set()).add(entity.entity_id)
                    props = dict(entity.properties) if entity.properties else {}
                    props["inferred_types"] = sorted(inferred)
                    entity.properties = props
                    new_count += 1
        return new_count

    # ------------------------------------------------------------------
    # Consistency checks
    # ------------------------------------------------------------------

    def _apply_property_chains(self, kg: Any, Relationship: Any) -> int:
        """Apply OWL 2 property chain axioms.

        For each chain ``[p1, p2, …, pn] → result``, if there exists a path::

            (A, p1, B1), (B1, p2, B2), …, (B_{n-1}, pn, C)

        then ``(A, result, C)`` is inferred and added to *kg*.

        Args:
            kg:           :class:`KnowledgeGraph` to augment.
            Relationship: The :class:`Relationship` class (injected for
                          testability).

        Returns:
            Number of new relationships added.
        """
        new_count = 0
        for chain_props, result_prop in self.schema.property_chains:
            if len(chain_props) < 2:
                continue
            # Build adjacency list for each step in the chain
            adjs: List[Dict[str, Set[str]]] = []
            for prop in chain_props:
                adj: Dict[str, Set[str]] = {}
                for rel in kg.relationships.values():
                    if rel.relationship_type == prop:
                        adj.setdefault(rel.source_id, set()).add(rel.target_id)
                adjs.append(adj)

            # Follow each chain starting from nodes that appear in adjs[0].
            # adjs is built from kg.relationships above and is not mutated
            # during this loop, so iterating keys() directly is safe.
            for start_id in adjs[0].keys():
                frontier: Set[str] = {start_id}
                valid = True
                for adj in adjs:
                    next_frontier: Set[str] = set()
                    for node in frontier:
                        next_frontier.update(adj.get(node, set()))
                    frontier = next_frontier
                    if not frontier:
                        valid = False
                        break

                if not valid:
                    continue

                for end_id in frontier:
                    # Exclude self-loops: a property chain should not infer a
                    # reflexive relationship on the same start node unless the
                    # ontology explicitly declares reflexivity.
                    if end_id == start_id:
                        continue
                    if self._rel_exists(kg, start_id, end_id, result_prop):
                        continue
                    src_ent = kg.entities.get(start_id)
                    tgt_ent = kg.entities.get(end_id)
                    if not src_ent or not tgt_ent:
                        continue
                    new_rel = Relationship(
                        relationship_type=result_prop,
                        source_entity=src_ent,
                        target_entity=tgt_ent,
                        confidence=0.8,
                        properties={
                            "inferred": True,
                            "rule": "property_chain",
                            "chain": chain_props,
                        },
                    )
                    kg.add_relationship(new_rel)
                    new_count += 1

        return new_count

    def _check_disjoint_classes(self, kg: Any) -> List[ConsistencyViolation]:
        violations: List[ConsistencyViolation] = []
        for entity in kg.entities.values():
            entity_classes: Set[str] = {entity.entity_type}
            entity_classes.update((entity.properties or {}).get("inferred_types", []))

            for cls_a in entity_classes:
                for cls_b in self.schema.disjoint_map.get(cls_a, set()):
                    if cls_b in entity_classes:
                        violations.append(ConsistencyViolation(
                            violation_type="disjoint_class",
                            message=(
                                f"Entity '{entity.name}' ({entity.entity_id}) is typed with "
                                f"disjoint classes '{cls_a}' and '{cls_b}'."
                            ),
                            entity_ids=[entity.entity_id],
                        ))
                        break  # One violation per entity pair is enough
        return violations

    def _check_negative_assertions(self, kg: Any) -> List[ConsistencyViolation]:
        """Check for ``NOT_p`` alongside positive *p* for same entity pair."""
        violations: List[ConsistencyViolation] = []
        # Build positive assertion index: (src, tgt, prop) → rel_id
        positives: Dict[Tuple[str, str, str], str] = {}
        negatives: Dict[Tuple[str, str, str], str] = {}

        for rel in kg.relationships.values():
            rtype = rel.relationship_type
            key = (rel.source_id, rel.target_id, rtype.lstrip("NOT_").lstrip("not_"))
            if rtype.startswith("NOT_") or rtype.startswith("not_"):
                negatives[key] = rel.relationship_id
            else:
                positives[(rel.source_id, rel.target_id, rtype)] = rel.relationship_id

        for key, neg_id in negatives.items():
            pos_id = positives.get(key)
            if pos_id:
                violations.append(ConsistencyViolation(
                    violation_type="negative_assertion",
                    message=(
                        f"Conflicting positive and negative assertions for "
                        f"property '{key[2]}' between entities "
                        f"'{key[0]}' and '{key[1]}'."
                    ),
                    entity_ids=list({key[0], key[1]}),
                    relationship_ids=[pos_id, neg_id],
                ))
        return violations

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _rel_exists(kg: Any, src_id: str, tgt_id: str, rel_type: str) -> bool:
        """Return ``True`` if a relationship of *rel_type* already exists."""
        for rel in kg.relationships.values():
            if (
                rel.source_id == src_id
                and rel.target_id == tgt_id
                and rel.relationship_type == rel_type
            ):
                return True
        return False

    @staticmethod
    def _clone_rel(rel: Any, new_type: str, Relationship: Any) -> Any:
        """Clone *rel* with a different relationship type."""
        src_ent = rel.source_entity
        tgt_ent = rel.target_entity
        return Relationship(
            relationship_type=new_type,
            source_entity=src_ent,
            target_entity=tgt_ent,
            confidence=rel.confidence * 0.9,  # slight confidence penalty for inference
            properties={"inferred": True, "rule": "subproperty", "from": rel.relationship_type},
        )


__all__ = [
    "OntologySchema",
    "OntologyReasoner",
    "ConsistencyViolation",
]
