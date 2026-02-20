"""
Ontology package for knowledge graph inference and reasoning.

Provides OWL/RDFS-style reasoning over KnowledgeGraph objects:
- Class hierarchy inference (rdfs:subClassOf)
- Property hierarchy (rdfs:subPropertyOf)
- Transitive and symmetric property closure
- Inverse property inference
- Domain/range type checking and inference
- Basic consistency checking

Usage::

    from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema, OntologyReasoner

    schema = OntologySchema()
    schema.add_subclass("Employee", "Person")
    schema.add_transitive("isAncestorOf")

    reasoner = OntologyReasoner(schema)
    augmented_kg = reasoner.materialize(my_kg)
"""

from .reasoning import OntologySchema, OntologyReasoner, ConsistencyViolation

__all__ = [
    "OntologySchema",
    "OntologyReasoner",
    "ConsistencyViolation",
]
