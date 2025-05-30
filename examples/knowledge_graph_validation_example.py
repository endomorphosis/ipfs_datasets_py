#!/usr/bin/env python3
"""
Example script demonstrating integrated knowledge graph extraction and validation.

This example shows how to use the KnowledgeGraphExtractorWithValidation to extract
knowledge graphs from text, Wikipedia articles, and multiple documents, with
automatic validation against Wikidata's SPARQL endpoint and correction suggestions.
"""

import os
import sys
import json
from typing import Dict, List, Any

# Add parent directory to path to import the modules
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# Import required modules
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractorWithValidation

def extract_from_text_example():
    """Example of extracting and validating a knowledge graph from text."""
    print("\n=== Extract and Validate Knowledge Graph from Text Example ===")

    # Initialize extractor with validation
    extractor = KnowledgeGraphExtractorWithValidation(
        validate_during_extraction=True,
        auto_correct_suggestions=True,
        cache_validation_results=True
    )

    # Sample text about IPFS
    text = """
    IPFS (InterPlanetary File System) is a protocol and peer-to-peer network for storing and sharing data
    in a distributed file system. IPFS was created by Juan Benet and is now developed by Protocol Labs.
    The development of IPFS began in 2014 and was first released in February 2015. Protocol Labs was
    also founded by Juan Benet in 2014. IPFS uses content-addressing to uniquely identify each file
    in a global namespace connecting all computing devices. Filecoin is a cryptocurrency built on top
    of IPFS, developed by Protocol Labs. IPFS is written in Go and JavaScript.
    """

    # Extract and validate knowledge graph
    result = extractor.extract_knowledge_graph(
        text=text,
        extraction_temperature=0.7,
        structure_temperature=0.6,
        validation_depth=2  # Include relationship validation
    )

    # Print extraction results
    kg = result["knowledge_graph"]
    print(f"Extracted Knowledge Graph: {kg.name}")
    print(f"Entities: {len(kg.entities)}")
    print(f"Entity types:")
    for entity_type, entity_ids in kg.entity_types.items():
        print(f"  - {entity_type}: {len(entity_ids)}")
    print(f"Relationships: {len(kg.relationships)}")
    print(f"Relationship types:")
    for rel_type, rel_ids in kg.relationship_types.items():
        print(f"  - {rel_type}: {len(rel_ids)}")

    # Print validation results if available
    if "validation_metrics" in result:
        print("\nValidation Metrics:")
        for metric, value in result["validation_metrics"].items():
            print(f"  - {metric}: {value:.2f}")

    # Print correction suggestions if available
    if "corrections" in result:
        print("\nCorrection Suggestions:")
        if "entities" in result["corrections"]:
            print("  Entity corrections:")
            for entity_id, correction in result["corrections"]["entities"].items():
                entity = kg.get_entity_by_id(entity_id)
                if entity:
                    print(f"    - {entity.name}: Suggestions available")

        if "relationships" in result["corrections"]:
            print("  Relationship corrections:")
            for rel_id, correction in result["corrections"]["relationships"].items():
                rel = kg.get_relationship_by_id(rel_id)
                if rel:
                    source = rel.source_entity.name if rel.source_entity else "Unknown"
                    target = rel.target_entity.name if rel.target_entity else "Unknown"
                    print(f"    - {source} {rel.relationship_type} {target}: {correction['suggestions']}")

    # Apply corrections if available
    if "corrections" in result:
        print("\nApplying corrections...")
        corrected_kg = extractor.apply_validation_corrections(
            kg=kg,
            corrections=result["corrections"]
        )
        print(f"Original KG: {len(kg.entities)} entities, {len(kg.relationships)} relationships")
        print(f"Corrected KG: {len(corrected_kg.entities)} entities, {len(corrected_kg.relationships)} relationships")

def extract_from_wikipedia_example():
    """Example of extracting and validating a knowledge graph from a Wikipedia page."""
    print("\n=== Extract and Validate Knowledge Graph from Wikipedia Example ===")

    # Initialize extractor with validation
    extractor = KnowledgeGraphExtractorWithValidation(
        validate_during_extraction=True,
        auto_correct_suggestions=True,
        cache_validation_results=True
    )

    # Extract from Wikipedia
    result = extractor.extract_from_wikipedia(
        page_title="InterPlanetary File System",
        extraction_temperature=0.7,
        structure_temperature=0.6,
        validation_depth=2,
        focus_validation_on_main_entity=True
    )

    # Print extraction results
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    kg = result["knowledge_graph"]
    print(f"Extracted Knowledge Graph from Wikipedia: {kg.name}")
    print(f"Entities: {len(kg.entities)}")
    print(f"Entity types:")
    for entity_type, entity_ids in kg.entity_types.items():
        print(f"  - {entity_type}: {len(entity_ids)}")
    print(f"Relationships: {len(kg.relationships)}")
    print(f"Relationship types:")
    for rel_type, rel_ids in kg.relationship_types.items():
        print(f"  - {rel_type}: {len(rel_ids)}")

    # Print validation results if available
    if "validation_metrics" in result:
        print("\nValidation Metrics:")
        for metric, value in result["validation_metrics"].items():
            print(f"  - {metric}: {value:.2f}")

    # Print path analysis if available
    if "path_analysis" in result:
        print("\nEntity Path Analysis:")
        pa = result["path_analysis"]
        if "direct_paths" in pa.get("data", {}):
            direct_paths = pa["data"]["direct_paths"]
            print(f"  Direct paths found: {len(direct_paths)}")
            for i, path in enumerate(direct_paths[:3]):  # Show max 3 paths
                print(f"    {i+1}. {path['property']}")

        if "two_hop_paths" in pa.get("data", {}):
            two_hop_paths = pa["data"]["two_hop_paths"]
            print(f"  Two-hop paths found: {len(two_hop_paths)}")
            for i, path in enumerate(two_hop_paths[:3]):  # Show max 3 paths
                print(f"    {i+1}. via {path['intermediate']} ({path['first_property']} → {path['second_property']})")

def extract_from_documents_example():
    """Example of extracting and validating a knowledge graph from multiple documents."""
    print("\n=== Extract and Validate Knowledge Graph from Multiple Documents Example ===")

    # Initialize extractor with validation
    extractor = KnowledgeGraphExtractorWithValidation(
        validate_during_extraction=True,
        auto_correct_suggestions=True,
        cache_validation_results=True
    )

    # Sample documents about AI models
    documents = [
        {
            "title": "GPT-4 Overview",
            "text": """
            GPT-4 is a large multimodal model created by OpenAI, announced on March 14, 2023.
            It is the successor to GPT-3.5 and has shown human-level performance on various
            professional and academic benchmarks. GPT-4 was trained using both publicly available
            data and data licensed from third-party providers. The training was completed in
            August 2022. OpenAI CEO Sam Altman has called GPT-4 "OpenAI's most capable model."
            """
        },
        {
            "title": "Claude 3 Release",
            "text": """
            Claude 3 is a family of multimodal AI assistants created by Anthropic, released
            in March 2024. The Claude 3 family includes three models: Haiku, Sonnet, and Opus,
            with increasing capabilities. Claude was founded by Dario Amodei and other former
            OpenAI researchers. Anthropic raised over $750 million in funding in 2023 from
            investors including Google and Amazon. Claude 3 models are available through
            Anthropic's API and through Amazon's Bedrock service.
            """
        },
        {
            "title": "Gemini Model",
            "text": """
            Gemini is a family of large language models developed by Google DeepMind,
            first announced in December 2023. The Gemini family includes Ultra, Pro,
            and Nano versions with different capability levels. Google CEO Sundar Pichai
            described Gemini as "the most capable AI model" from Google. Gemini Ultra
            achieved state-of-the-art performance on 30 of 32 academic benchmarks used
            in large language model testing. Gemini is integrated into Google products
            including Bard, which was later renamed to Gemini.
            """
        }
    ]

    # Extract and validate knowledge graph
    result = extractor.extract_from_documents(
        documents=documents,
        text_key="text",
        extraction_temperature=0.7,
        structure_temperature=0.6,
        validation_depth=2  # Include relationship validation
    )

    # Print extraction results
    kg = result["knowledge_graph"]
    print(f"Extracted Knowledge Graph from multiple documents: {kg.name}")
    print(f"Entities: {len(kg.entities)}")
    print(f"Entity types:")
    for entity_type, entity_ids in kg.entity_types.items():
        if entity_ids:  # Only show non-empty types
            print(f"  - {entity_type}: {len(entity_ids)}")
    print(f"Relationships: {len(kg.relationships)}")
    print(f"Relationship types:")
    for rel_type, rel_ids in kg.relationship_types.items():
        if rel_ids:  # Only show non-empty types
            print(f"  - {rel_type}: {len(rel_ids)}")

    # Print validation results if available
    if "validation_metrics" in result:
        print("\nValidation Metrics:")
        for metric, value in result["validation_metrics"].items():
            print(f"  - {metric}: {value:.2f}")

    # Print path analysis if available
    if "path_analysis" in result:
        print("\nEntity Path Analysis:")
        paths = result["path_analysis"]
        print(f"  Paths found between top entities: {len(paths)}")
        for i, path in enumerate(paths[:3]):  # Show max 3 path groups
            print(f"    {i+1}. {path['source']} → {path['target']}")
            if "direct_paths" in path["paths"].get("data", {}):
                direct = path["paths"]["data"]["direct_paths"]
                print(f"       Direct paths: {len(direct)}")
                for j, dpath in enumerate(direct[:2]):
                    print(f"         {j+1}. {dpath['property']}")

def main():
    """Main function demonstrating different extraction and validation examples."""
    print("=== Knowledge Graph Extraction and Validation Examples ===")
    print("This script demonstrates the integration of knowledge graph extraction and validation.")

    # Run examples
    extract_from_text_example()
    extract_from_wikipedia_example()
    extract_from_documents_example()

    print("\nExamples completed.")

if __name__ == "__main__":
    main()
