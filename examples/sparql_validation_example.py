#!/usr/bin/env python3
"""
Example script demonstrating SPARQL validation for knowledge graphs.

This example shows how to use the SPARQLValidator to validate knowledge graphs
against Wikidata's SPARQL endpoint.
"""

import os
import sys
import json
from typing import Dict, List, Any, Optional

# Add parent directory to path to import the modules
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# Import required modules
from ipfs_datasets_py.llm.llm_semantic_validation import SPARQLValidator, ValidationResult
from ipfs_datasets_py.knowledge_graph_extraction import Entity, Relationship, KnowledgeGraph
from ipfs_datasets_py.llm.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer

def create_sample_knowledge_graph() -> KnowledgeGraph:
    """Create a sample knowledge graph about IPFS and related entities."""
    # Create a new knowledge graph
    kg = KnowledgeGraph(name="ipfs_ecosystem")

    # Create entities
    ipfs = kg.add_entity(
        entity_type="technology",
        name="IPFS",
        properties={
            "description": "InterPlanetary File System - a protocol for distributed content addressing",
            "developer": "Protocol Labs",
            "inception": "2015"
        }
    )

    protocol_labs = kg.add_entity(
        entity_type="organization",
        name="Protocol Labs",
        properties={
            "description": "Research, development, and deployment lab for network protocols",
            "industry": "software industry",
            "founded": "2014",
            "headquarters": "San Francisco"
        }
    )

    juan_benet = kg.add_entity(
        entity_type="person",
        name="Juan Benet",
        properties={
            "description": "Creator of IPFS and founder of Protocol Labs",
            "occupation": "computer scientist",
            "education": "Stanford University"
        }
    )

    filecoin = kg.add_entity(
        entity_type="technology",
        name="Filecoin",
        properties={
            "description": "Decentralized storage network built on IPFS",
            "developer": "Protocol Labs",
            "inception": "2017"
        }
    )

    # Create relationships
    kg.add_relationship(
        relationship_type="developed_by",
        source=ipfs,
        target=protocol_labs,
        properties={"year": "2015"}
    )

    kg.add_relationship(
        relationship_type="founded_by",
        source=protocol_labs,
        target=juan_benet,
        properties={"year": "2014"}
    )

    kg.add_relationship(
        relationship_type="works_for",
        source=juan_benet,
        target=protocol_labs,
        properties={"role": "Founder and CEO"}
    )

    kg.add_relationship(
        relationship_type="created",
        source=juan_benet,
        target=ipfs,
        properties={"year": "2014"}
    )

    kg.add_relationship(
        relationship_type="based_on",
        source=filecoin,
        target=ipfs,
        properties={"relationship": "uses IPFS for content addressing"}
    )

    kg.add_relationship(
        relationship_type="developed_by",
        source=filecoin,
        target=protocol_labs,
        properties={"year": "2017"}
    )

    return kg

def validate_entity_example(validator: SPARQLValidator) -> None:
    """Example of validating a single entity."""
    print("\n=== Entity Validation Example ===")

    # Validate IPFS entity
    result = validator.validate_entity(
        entity_name="IPFS",
        entity_type="technology",
        entity_properties={
            "developer": "Protocol Labs",
            "inception": "2015"
        }
    )

    # Print the result
    print(f"Entity validation {'successful' if result.is_valid else 'failed'}")
    print(f"Entity: IPFS")
    print(f"Wikidata match: {result.data['wikidata_entity']['label']} ({result.data['wikidata_entity']['id']})")

    if result.is_valid:
        print("\nValidated properties:")
        for prop, validation in result.data["validated_properties"].items():
            print(f"  - {prop}: matches Wikidata '{validation['wikidata_match']}' with confidence {validation['confidence']:.2f}")
    else:
        print("\nProperty mismatches:")
        for mismatch in result.data["property_mismatches"]:
            print(f"  - {mismatch['property']}: expected '{mismatch['expected']}', but no match found")
            if mismatch.get("closest_match"):
                print(f"    Closest match: '{mismatch['closest_match']['property']}' with value '{mismatch['closest_match']['value']}'")

def validate_relationship_example(validator: SPARQLValidator) -> None:
    """Example of validating a relationship between entities."""
    print("\n=== Relationship Validation Example ===")

    # Validate Protocol Labs founded by Juan Benet
    result = validator.validate_relationship(
        source_entity="Protocol Labs",
        relationship_type="founded_by",
        target_entity="Juan Benet"
    )

    # Print the result
    print(f"Relationship validation {'successful' if result.is_valid else 'failed'}")
    print(f"Relationship: Protocol Labs founded_by Juan Benet")

    if result.is_valid:
        print(f"Matches Wikidata relationship: {result.data['wikidata_relationship']['property']} ({result.data['wikidata_relationship']['property_id']})")
        print(f"Confidence: {result.data['confidence']:.2f}")
    else:
        print(f"Error: {result.errors[0]}")
        if "closest_match" in result.data and result.data["closest_match"]:
            print(f"Closest match: {result.data['closest_match']['property']}")

def validate_knowledge_graph_example(validator: SPARQLValidator, kg: KnowledgeGraph) -> None:
    """Example of validating an entire knowledge graph."""
    print("\n=== Knowledge Graph Validation Example ===")

    # Validate the entire knowledge graph
    result = validator.validate_knowledge_graph(
        kg=kg,
        validation_depth=2,
        min_confidence=0.7
    )

    # Print the result summary
    print(f"Knowledge graph validation {'successful' if result.is_valid else 'failed'}")
    print(f"Entity coverage: {result.data['entity_coverage']:.2f}")

    if 'relationship_coverage' in result.data:
        print(f"Relationship coverage: {result.data['relationship_coverage']:.2f}")

    print(f"Overall coverage: {result.data['overall_coverage']:.2f}")

    # Print the detailed explanation
    explanation = validator.generate_validation_explanation(
        result,
        explanation_type="detailed"
    )

    print("\nDetailed Explanation:")
    print(explanation)

def validate_with_entity_focus_example(validator: SPARQLValidator, kg: KnowledgeGraph) -> None:
    """Example of validating a knowledge graph with focus on a specific entity."""
    print("\n=== Knowledge Graph Validation with Entity Focus Example ===")

    # Validate the knowledge graph focused on the IPFS entity
    result = validator.validate_knowledge_graph(
        kg=kg,
        main_entity_name="IPFS",
        validation_depth=2,
        min_confidence=0.7
    )

    # Print the result
    print(f"Knowledge graph validation for IPFS {'successful' if result.is_valid else 'failed'}")
    print(f"Property coverage: {result.data['property_coverage']:.2f}")
    print(f"Relationship coverage: {result.data['relationship_coverage']:.2f}")
    print(f"Overall coverage: {result.data['overall_coverage']:.2f}")

    # Generate fix suggestions if validation failed
    if not result.is_valid:
        fix_suggestions = validator.generate_validation_explanation(
            result,
            explanation_type="fix"
        )

        print("\nFix Suggestions:")
        print(fix_suggestions)

def find_paths_example(validator: SPARQLValidator) -> None:
    """Example of finding paths between entities."""
    print("\n=== Entity Path Finding Example ===")

    # Find paths between Juan Benet and IPFS
    result = validator.find_entity_paths(
        source_entity="Juan Benet",
        target_entity="IPFS",
        max_path_length=2
    )

    # Print the result
    print(f"Path finding {'successful' if result.is_valid else 'failed'}")
    print(f"Looking for paths between: Juan Benet and IPFS")

    if result.is_valid:
        direct_paths = result.data.get("direct_paths", [])
        two_hop_paths = result.data.get("two_hop_paths", [])

        if direct_paths:
            print("\nDirect paths found:")
            for i, path in enumerate(direct_paths):
                print(f"  {i+1}. Juan Benet --[{path['property']}]--> IPFS")

        if two_hop_paths:
            print("\nTwo-hop paths found:")
            for i, path in enumerate(two_hop_paths):
                print(f"  {i+1}. Juan Benet --[{path['first_property']}]--> {path['intermediate']} --[{path['second_property']}]--> IPFS")
    else:
        print(f"Error: {result.errors[0]}")

def find_similar_entities_example(validator: SPARQLValidator) -> None:
    """Example of finding similar entities."""
    print("\n=== Similar Entities Example ===")

    # Find entities similar to IPFS
    result = validator.find_similar_entities(
        entity_name="IPFS",
        entity_type="technology",
        min_similarity=0.3
    )

    # Print the result
    print(f"Similar entity search {'successful' if result.is_valid else 'failed'}")
    print(f"Looking for entities similar to: IPFS")

    if result.is_valid:
        similar_entities = result.data.get("similar_entities", [])

        if similar_entities:
            print("\nSimilar entities found:")
            for i, entity in enumerate(similar_entities):
                print(f"  {i+1}. {entity['entity']} (similarity: {entity['similarity']:.2f})")
    else:
        print(f"Error: {result.errors[0]}")

def validate_common_properties_example(validator: SPARQLValidator) -> None:
    """Example of validating common properties for an entity type."""
    print("\n=== Common Properties Validation Example ===")

    # Validate common properties for a technology entity
    result = validator.validate_common_properties(
        entity_name="IPFS",
        entity_type="technology",
        entity_properties={
            "developer": "Protocol Labs",
            "inception": "2015",
            "description": "InterPlanetary File System",
            "license": "MIT License",
            "programming_language": "Go",
            "website": "https://ipfs.io"
        }
    )

    # Print the result
    print(f"Common properties validation {'successful' if result.is_valid else 'failed'}")
    print(f"Entity: IPFS (technology)")
    print(f"Coverage: {result.data.get('coverage', 0.0):.2f}")

    if 'common_properties' in result.data:
        common_props = result.data["common_properties"]
        found_props = result.data.get("found_properties", [])
        missing_props = result.data.get("missing_properties", [])

        print(f"\nCommon properties for type 'technology': {len(common_props)}")
        print(f"Properties found: {len(found_props)}")
        print(f"Properties missing: {len(missing_props)}")

        if found_props:
            print("\nFound properties:")
            for prop in found_props:
                print(f"  - {prop['property']} (used in {prop['percentage']:.0f}% of similar entities)")

        if missing_props:
            print("\nMissing properties:")
            for prop in missing_props:
                print(f"  - {prop['property']} (used in {prop['percentage']:.0f}% of similar entities)")
    else:
        print(f"Error: {result.errors[0]}")

def custom_sparql_query_example(validator: SPARQLValidator) -> None:
    """Example of executing a custom SPARQL query."""
    print("\n=== Custom SPARQL Query Example ===")

    # Execute a custom SPARQL query to find programming languages used by IPFS-related projects
    query = """
    SELECT ?project ?projectLabel ?language ?languageLabel
    WHERE {
      ?project wdt:P31 wd:Q7397 .  # Instance of software
      ?project ?label ?languageLabel .
      FILTER(CONTAINS(LCASE(?projectLabel), "ipfs")) .

      ?project wdt:P277 ?language .  # Programming language
      ?language wdt:P31 wd:Q9143 .   # Instance of programming language

      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    }
    LIMIT 10
    """

    result = validator.execute_custom_sparql_query(query)

    # Print the result
    if "error" not in result:
        bindings = result.get("results", {}).get("bindings", [])

        if bindings:
            print("\nIPFS-related projects and their programming languages:")
            for binding in bindings:
                project = binding.get("projectLabel", {}).get("value", "Unknown project")
                language = binding.get("languageLabel", {}).get("value", "Unknown language")
                print(f"  - {project}: {language}")
        else:
            print("No results found")
    else:
        print(f"Error: {result['error']}")

def integration_example(validator: SPARQLValidator) -> None:
    """
    Example of an integrated validation workflow combining multiple validation types.

    This demonstrates how to combine different validation techniques into a
    comprehensive validation workflow for knowledge graphs.
    """
    print("\n=== Integrated Validation Workflow Example ===")

    # Create a simple knowledge graph about IPFS and related entities
    ipfs = {
        "name": "IPFS",
        "type": "technology",
        "properties": {
            "developer": "Protocol Labs",
            "inception": "2015",
            "description": "InterPlanetary File System",
            "license": "MIT License"
        }
    }

    filecoin = {
        "name": "Filecoin",
        "type": "technology",
        "properties": {
            "developer": "Protocol Labs",
            "inception": "2017",
            "description": "Decentralized storage network"
        }
    }

    protocol_labs = {
        "name": "Protocol Labs",
        "type": "organization",
        "properties": {
            "founder": "Juan Benet",
            "founded": "2014",
            "industry": "software"
        }
    }

    relationships = [
        {"source": "IPFS", "relationship": "developed_by", "target": "Protocol Labs"},
        {"source": "Filecoin", "relationship": "developed_by", "target": "Protocol Labs"},
        {"source": "Filecoin", "relationship": "based_on", "target": "IPFS"}
    ]

    print("Starting validation workflow for a knowledge graph with these entities:")
    print(f"  - {ipfs['name']} ({ipfs['type']})")
    print(f"  - {filecoin['name']} ({filecoin['type']})")
    print(f"  - {protocol_labs['name']} ({protocol_labs['type']})")

    # Step 1: Entity validation
    print("\nStep 1: Entity validation")
    entity_validation_results = {}

    for entity in [ipfs, filecoin, protocol_labs]:
        result = validator.validate_entity(
            entity_name=entity["name"],
            entity_type=entity["type"],
            entity_properties=entity["properties"]
        )
        entity_validation_results[entity["name"]] = result
        print(f"  - {entity['name']}: {'✓' if result.is_valid else '✗'}")

    # Step 2: Relationship validation
    print("\nStep 2: Relationship validation")
    relationship_validation_results = {}

    for rel in relationships:
        result = validator.validate_relationship(
            source_entity=rel["source"],
            relationship_type=rel["relationship"],
            target_entity=rel["target"],
            bidirectional=False
        )
        rel_key = f"{rel['source']}_{rel['relationship']}_{rel['target']}"
        relationship_validation_results[rel_key] = result
        print(f"  - {rel['source']} {rel['relationship']} {rel['target']}: {'✓' if result.is_valid else '✗'}")

    # Step 3: Path finding
    print("\nStep 3: Path finding between indirectly related entities")
    path_result = validator.find_entity_paths(
        source_entity="Juan Benet",
        target_entity="Filecoin"
    )

    if path_result.is_valid:
        direct_paths = path_result.data.get("direct_paths", [])
        two_hop_paths = path_result.data.get("two_hop_paths", [])

        if direct_paths:
            print("  Direct paths found")
        elif two_hop_paths:
            print("  Two-hop paths found through:")
            for path in two_hop_paths[:2]:  # Show at most 2 paths
                print(f"    - {path['intermediate']}")
    else:
        print("  No paths found")

    # Step 4: Common properties validation
    print("\nStep 4: Common properties validation")
    for entity in [ipfs, filecoin, protocol_labs]:
        result = validator.validate_common_properties(
            entity_name=entity["name"],
            entity_type=entity["type"],
            entity_properties=entity["properties"]
        )

        if result.is_valid:
            coverage = result.data.get("coverage", 0.0)
            print(f"  - {entity['name']}: {coverage:.0%} of common properties present")
        else:
            print(f"  - {entity['name']}: Validation failed")

    # Step 5: Generate comprehensive validation report
    print("\nStep 5: Generating comprehensive validation report")

    # Calculate overall validation scores
    entity_score = sum(1 for r in entity_validation_results.values() if r.is_valid) / len(entity_validation_results)
    relationship_score = sum(1 for r in relationship_validation_results.values() if r.is_valid) / len(relationship_validation_results)

    overall_score = (entity_score * 0.6) + (relationship_score * 0.4)  # Weight entities more than relationships

    print(f"  Entity validation score: {entity_score:.0%}")
    print(f"  Relationship validation score: {relationship_score:.0%}")
    print(f"  Overall validation score: {overall_score:.0%}")

    if overall_score >= 0.8:
        print("\nConclusion: Knowledge graph is highly reliable (>80% validation)")
    elif overall_score >= 0.6:
        print("\nConclusion: Knowledge graph is moderately reliable (60-80% validation)")
    else:
        print("\nConclusion: Knowledge graph needs significant improvement (<60% validation)")

def main():
    """Main function demonstrating SPARQL validation capabilities."""
    print("=== SPARQL Validation Examples ===")

    # Initialize the validator
    validator = SPARQLValidator(
        endpoint_url="https://query.wikidata.org/sparql",
        cache_results=True
    )

    # Initialize a tracer (optional)
    tracer = WikipediaKnowledgeGraphTracer()
    validator_with_tracing = SPARQLValidator(
        endpoint_url="https://query.wikidata.org/sparql",
        tracer=tracer,
        cache_results=True
    )

    # Create a sample knowledge graph
    kg = create_sample_knowledge_graph()

    # Run basic examples
    validate_entity_example(validator)
    validate_relationship_example(validator)
    validate_knowledge_graph_example(validator, kg)
    validate_with_entity_focus_example(validator_with_tracing, kg)

    # Run advanced examples
    find_paths_example(validator)
    find_similar_entities_example(validator)
    validate_common_properties_example(validator)
    custom_sparql_query_example(validator)

    # Run integrated workflow example
    integration_example(validator)

    print("\nExamples completed.")

if __name__ == "__main__":
    main()
