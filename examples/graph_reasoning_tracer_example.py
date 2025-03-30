#!/usr/bin/env python3
"""
Example script demonstrating the enhanced WikipediaKnowledgeGraphTracer capabilities.

This example demonstrates the use of the reasoning tracer for temperature-controlled
knowledge graph extraction, cross-document analysis, and visualizations.
"""

import os
import sys
import json
import time
from typing import Dict, List, Any

# Add parent directory to path to import the modules
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# Import required modules
from ipfs_datasets_py.llm_reasoning_tracer import (
    WikipediaKnowledgeGraphTracer,
    ReasoningTrace,
    ReasoningStep,
    StepType,
    ConfidenceLevel
)
from ipfs_datasets_py.knowledge_graph_extraction import (
    KnowledgeGraph,
    Entity,
    Relationship,
    KnowledgeGraphExtractor
)

def extraction_temperature_analysis():
    """Example of analyzing how temperature affects knowledge graph extraction."""
    print("\n=== Knowledge Graph Extraction Temperature Analysis ===")
    
    # Initialize tracer
    tracer = WikipediaKnowledgeGraphTracer()
    
    # Set up example knowledge graphs with different temperature settings
    # In a real scenario, these would be created by extracting from Wikipedia
    
    # Define a helper function to create a mock knowledge graph
    def create_mock_knowledge_graph(entity_count, relationship_count, entity_types, relationship_types, name="mock_kg"):
        kg = KnowledgeGraph(name=name)
        
        # Add entities
        for i in range(entity_count):
            # Distribute entities among types
            entity_type = list(entity_types.keys())[i % len(entity_types)]
            entity = kg.add_entity(
                entity_type=entity_type,
                name=f"Entity {i+1}",
                properties={"property1": f"value1_{i}", "property2": f"value2_{i}"}
            )
            
        # Add relationships
        entity_list = list(kg.entities.values())
        for i in range(min(relationship_count, len(entity_list) - 1)):
            # Distribute relationships among types
            rel_type = list(relationship_types.keys())[i % len(relationship_types)]
            source = entity_list[i]
            target = entity_list[(i + 1) % len(entity_list)]
            kg.add_relationship(
                relationship_type=rel_type,
                source=source,
                target=target
            )
            
        return kg
    
    # Create mock traces for different temperature settings
    
    # Low temperature (0.3, 0.2) - Few entities, simple relationships
    low_temp_entity_types = {"person": 2, "organization": 1}
    low_temp_rel_types = {"works_for": 2}
    low_temp_kg = create_mock_knowledge_graph(5, 3, low_temp_entity_types, low_temp_rel_types)
    
    # Medium temperature (0.6, 0.5) - Moderate entities and relationships
    medium_temp_entity_types = {"person": 4, "organization": 3, "location": 2, "event": 1}
    medium_temp_rel_types = {"works_for": 3, "located_in": 2, "founded": 1, "attended": 2}
    medium_temp_kg = create_mock_knowledge_graph(15, 12, medium_temp_entity_types, medium_temp_rel_types)
    
    # High temperature (0.9, 0.8) - Many entities, complex relationships
    high_temp_entity_types = {"person": 10, "organization": 8, "location": 6, "event": 4, "product": 3, "concept": 2}
    high_temp_rel_types = {"works_for": 8, "located_in": 6, "founded": 4, "attended": 5, "created": 3, "uses": 2, "has_part": 3, "related_to": 4}
    high_temp_kg = create_mock_knowledge_graph(35, 40, high_temp_entity_types, high_temp_rel_types)
    
    # Create traces for each temperature setting
    low_temp_trace = tracer.trace_extraction_and_validation("Mock Wikipedia Page", 0.3, 0.2)[0]
    medium_temp_trace = tracer.trace_extraction_and_validation("Mock Wikipedia Page", 0.6, 0.5)[0]
    high_temp_trace = tracer.trace_extraction_and_validation("Mock Wikipedia Page", 0.9, 0.8)[0]
    
    # Add mock steps to traces
    
    # Low temperature trace
    low_temp_trace.create_step(
        step_type=StepType.FINAL,
        description="Completed knowledge graph extraction and validation",
        outputs={
            "entity_count": len(low_temp_kg.entities),
            "relationship_count": len(low_temp_kg.relationships),
            "entity_types": low_temp_entity_types,
            "relationship_types": low_temp_rel_types,
            "knowledge_graph": low_temp_kg
        },
        metadata={"execution_time": 1.2}
    )
    
    # Medium temperature trace
    medium_temp_trace.create_step(
        step_type=StepType.FINAL,
        description="Completed knowledge graph extraction and validation",
        outputs={
            "entity_count": len(medium_temp_kg.entities),
            "relationship_count": len(medium_temp_kg.relationships),
            "entity_types": medium_temp_entity_types,
            "relationship_types": medium_temp_rel_types,
            "knowledge_graph": medium_temp_kg
        },
        metadata={"execution_time": 2.5}
    )
    
    # High temperature trace
    high_temp_trace.create_step(
        step_type=StepType.FINAL,
        description="Completed knowledge graph extraction and validation",
        outputs={
            "entity_count": len(high_temp_kg.entities),
            "relationship_count": len(high_temp_kg.relationships),
            "entity_types": high_temp_entity_types,
            "relationship_types": high_temp_rel_types,
            "knowledge_graph": high_temp_kg
        },
        metadata={"execution_time": 4.8}
    )
    
    # Store traces in tracing manager
    tracer.tracing_manager.store_trace(low_temp_trace)
    tracer.tracing_manager.store_trace(medium_temp_trace)
    tracer.tracing_manager.store_trace(high_temp_trace)
    
    # Compare temperature settings
    comparison = tracer.compare_temperature_settings(
        trace_ids=[low_temp_trace.trace_id, medium_temp_trace.trace_id, high_temp_trace.trace_id],
        comparison_aspects=["entity_count", "relationship_count", "structure_complexity"]
    )
    
    # Print temperature comparison insights
    print("\nTemperature Comparison Insights:")
    for insight in comparison.get("insights", []):
        print(f"- {insight}")
    
    # Generate temperature recommendations for different profiles
    for profile in ["concise", "balanced", "detailed"]:
        recommendation = tracer.generate_temperature_recommendation(
            trace_id=medium_temp_trace.trace_id,
            target=profile
        )
        
        if "error" not in recommendation:
            print(f"\nRecommendations for {profile} extraction:")
            print(f"- Current settings: extraction={recommendation['current_settings']['extraction_temperature']:.1f}, structure={recommendation['current_settings']['structure_temperature']:.1f}")
            print(f"- Recommended settings: extraction={recommendation['recommended_settings']['extraction_temperature']:.1f}, structure={recommendation['recommended_settings']['structure_temperature']:.1f}")
            
            for reason in recommendation.get("reasoning", []):
                print(f"  - {reason}")

def cross_document_analysis_example():
    """Example of cross-document analysis with the WikipediaKnowledgeGraphTracer."""
    print("\n=== Cross-Document Analysis Example ===")
    
    # Initialize tracer
    tracer = WikipediaKnowledgeGraphTracer()
    
    # Create mock knowledge graphs for different Wikipedia pages
    
    # Knowledge graph for "Artificial Intelligence"
    ai_kg = KnowledgeGraph(name="Artificial Intelligence")
    
    # Add entities
    ai_entity = ai_kg.add_entity(entity_type="concept", name="Artificial Intelligence", properties={"definition": "Intelligence demonstrated by machines"})
    ml_entity = ai_kg.add_entity(entity_type="concept", name="Machine Learning", properties={"definition": "Study of algorithms that improve through experience"})
    dl_entity = ai_kg.add_entity(entity_type="concept", name="Deep Learning", properties={"definition": "Neural network approach to machine learning"})
    alan_turing = ai_kg.add_entity(entity_type="person", name="Alan Turing", properties={"birth_year": "1912", "death_year": "1954"})
    turing_test = ai_kg.add_entity(entity_type="concept", name="Turing Test", properties={"year_proposed": "1950"})
    
    # Add relationships
    ai_kg.add_relationship(relationship_type="includes", source=ai_entity, target=ml_entity)
    ai_kg.add_relationship(relationship_type="includes", source=ml_entity, target=dl_entity)
    ai_kg.add_relationship(relationship_type="proposed_by", source=turing_test, target=alan_turing)
    ai_kg.add_relationship(relationship_type="related_to", source=ai_entity, target=turing_test)
    
    # Knowledge graph for "Machine Learning"
    ml_kg = KnowledgeGraph(name="Machine Learning")
    
    # Add entities
    ml_main = ml_kg.add_entity(entity_type="concept", name="Machine Learning", properties={"definition": "Field of AI focusing on data-driven algorithms"})
    supervised = ml_kg.add_entity(entity_type="concept", name="Supervised Learning", properties={"approach": "Learning from labeled data"})
    unsupervised = ml_kg.add_entity(entity_type="concept", name="Unsupervised Learning", properties={"approach": "Learning from unlabeled data"})
    reinforcement = ml_kg.add_entity(entity_type="concept", name="Reinforcement Learning", properties={"approach": "Learning through interaction with environment"})
    deep_learning = ml_kg.add_entity(entity_type="concept", name="Deep Learning", properties={"definition": "Machine learning using neural networks with multiple layers"})
    arthur_samuel = ml_kg.add_entity(entity_type="person", name="Arthur Samuel", properties={"birth_year": "1901", "death_year": "1990"})
    
    # Add relationships
    ml_kg.add_relationship(relationship_type="has_subfield", source=ml_main, target=supervised)
    ml_kg.add_relationship(relationship_type="has_subfield", source=ml_main, target=unsupervised)
    ml_kg.add_relationship(relationship_type="has_subfield", source=ml_main, target=reinforcement)
    ml_kg.add_relationship(relationship_type="includes", source=ml_main, target=deep_learning)
    ml_kg.add_relationship(relationship_type="pioneered_by", source=ml_main, target=arthur_samuel)
    
    # Knowledge graph for "Deep Learning"
    dl_kg = KnowledgeGraph(name="Deep Learning")
    
    # Add entities
    dl_main = dl_kg.add_entity(entity_type="concept", name="Deep Learning", properties={"definition": "Subset of machine learning using neural networks"})
    cnn = dl_kg.add_entity(entity_type="concept", name="Convolutional Neural Network", properties={"application": "Image processing"})
    rnn = dl_kg.add_entity(entity_type="concept", name="Recurrent Neural Network", properties={"application": "Sequential data"})
    ml_concept = dl_kg.add_entity(entity_type="concept", name="Machine Learning", properties={"relation": "Parent field"})
    geoff_hinton = dl_kg.add_entity(entity_type="person", name="Geoffrey Hinton", properties={"affiliation": "University of Toronto"})
    yann_lecun = dl_kg.add_entity(entity_type="person", name="Yann LeCun", properties={"affiliation": "Meta AI Research"})
    
    # Add relationships
    dl_kg.add_relationship(relationship_type="subfield_of", source=dl_main, target=ml_concept)
    dl_kg.add_relationship(relationship_type="includes", source=dl_main, target=cnn)
    dl_kg.add_relationship(relationship_type="includes", source=dl_main, target=rnn)
    dl_kg.add_relationship(relationship_type="pioneered_by", source=dl_main, target=geoff_hinton)
    dl_kg.add_relationship(relationship_type="pioneered_by", source=cnn, target=yann_lecun)
    
    # Create traces for each knowledge graph
    ai_trace = tracer.trace_extraction_and_validation("Artificial Intelligence", 0.7, 0.6)[0]
    ml_trace = tracer.trace_extraction_and_validation("Machine Learning", 0.7, 0.6)[0]
    dl_trace = tracer.trace_extraction_and_validation("Deep Learning", 0.7, 0.6)[0]
    
    # Add mock steps to traces
    ai_trace.create_step(
        step_type=StepType.FINAL,
        description="Completed knowledge graph extraction and validation",
        outputs={
            "entity_count": len(ai_kg.entities),
            "relationship_count": len(ai_kg.relationships),
            "knowledge_graph": ai_kg,
            "page_title": "Artificial Intelligence"
        }
    )
    
    ml_trace.create_step(
        step_type=StepType.FINAL,
        description="Completed knowledge graph extraction and validation",
        outputs={
            "entity_count": len(ml_kg.entities),
            "relationship_count": len(ml_kg.relationships),
            "knowledge_graph": ml_kg,
            "page_title": "Machine Learning"
        }
    )
    
    dl_trace.create_step(
        step_type=StepType.FINAL,
        description="Completed knowledge graph extraction and validation",
        outputs={
            "entity_count": len(dl_kg.entities),
            "relationship_count": len(dl_kg.relationships),
            "knowledge_graph": dl_kg,
            "page_title": "Deep Learning"
        }
    )
    
    # Store traces in tracing manager
    tracer.tracing_manager.store_trace(ai_trace)
    tracer.tracing_manager.store_trace(ml_trace)
    tracer.tracing_manager.store_trace(dl_trace)
    
    # Perform cross-document analysis
    analysis_result = tracer.cross_document_analysis(
        trace_ids=[ai_trace.trace_id, ml_trace.trace_id, dl_trace.trace_id],
        entity_threshold=0.7,
        relationship_threshold=0.6
    )
    
    # Print analysis results
    print(f"\nAnalyzed {analysis_result.get('document_count', 0)} documents:")
    for title in analysis_result.get("document_titles", []):
        print(f"- {title}")
    
    print(f"\nFound {len(analysis_result.get('connecting_entities', []))} connecting entities across documents:")
    for i, connection in enumerate(analysis_result.get("connecting_entities", [])[:3]):  # Show first 3
        entity1 = connection["entity1"]
        entity2 = connection["entity2"]
        print(f"{i+1}. '{entity1['name']}' in '{entity1['source_document']}' connects to '{entity2['name']}' in '{entity2['source_document']}' (similarity: {connection['similarity']:.2f})")
    
    print(f"\nFound {len(analysis_result.get('shared_relationships', []))} shared relationships:")
    for i, shared in enumerate(analysis_result.get("shared_relationships", [])[:3]):  # Show first 3
        rel1 = shared["relationship1"]
        rel2 = shared["relationship2"]
        print(f"{i+1}. '{rel1['source_name']} {rel1['relationship_type']} {rel1['target_name']}' in '{rel1['source_document']}'")
        print(f"   matches '{rel2['source_name']} {rel2['relationship_type']} {rel2['target_name']}' in '{rel2['source_document']}'")
    
    # Print knowledge gaps
    gaps = analysis_result.get("knowledge_gaps", {})
    property_gaps = gaps.get("property_gaps", [])
    
    print(f"\nFound {len(property_gaps)} property gaps where information is missing in some documents:")
    for i, gap in enumerate(property_gaps[:3]):  # Show first 3
        print(f"{i+1}. Entity '{gap['entity_name']}' in '{gap['document']}' is missing properties: {', '.join(gap['missing_properties'])}")
    
    # Print inferences
    inferences = analysis_result.get("potential_inferences", [])
    
    print(f"\nGenerated {len(inferences)} potential inferences:")
    for i, inference in enumerate(inferences[:3]):  # Show first 3
        print(f"{i+1}. {inference['explanation']} (confidence: {inference['confidence']:.2f})")
    
    # Print visualization
    print("\nCross-document connection visualization:")
    print(analysis_result.get("visualization", "No visualization available"))

def detailed_graph_visualization():
    """Example of enhanced knowledge graph visualization."""
    print("\n=== Enhanced Knowledge Graph Visualization ===")
    
    # Initialize tracer
    tracer = WikipediaKnowledgeGraphTracer()
    
    # Create a sample knowledge graph
    kg = KnowledgeGraph(name="History of Computing")
    
    # Add entities
    computer = kg.add_entity(entity_type="concept", name="Computer", properties={"definition": "Electronic device for processing data"})
    programming = kg.add_entity(entity_type="concept", name="Programming", properties={"definition": "Process of creating software"})
    eniac = kg.add_entity(entity_type="technology", name="ENIAC", properties={"year": "1945"})
    arpanet = kg.add_entity(entity_type="technology", name="ARPANET", properties={"year": "1969"})
    internet = kg.add_entity(entity_type="technology", name="Internet", properties={"definition": "Global network of computers"})
    alan_turing = kg.add_entity(entity_type="person", name="Alan Turing", properties={"birth": "1912", "death": "1954"})
    grace_hopper = kg.add_entity(entity_type="person", name="Grace Hopper", properties={"birth": "1906", "death": "1992"})
    cobol = kg.add_entity(entity_type="technology", name="COBOL", properties={"year": "1959"})
    year_1945 = kg.add_entity(entity_type="date", name="1945", properties={"century": "20th"})
    year_1959 = kg.add_entity(entity_type="date", name="1959", properties={"century": "20th"})
    year_1969 = kg.add_entity(entity_type="date", name="1969", properties={"century": "20th"})
    
    # Add relationships
    kg.add_relationship(relationship_type="created_in", source=eniac, target=year_1945)
    kg.add_relationship(relationship_type="created_in", source=cobol, target=year_1959)
    kg.add_relationship(relationship_type="created_in", source=arpanet, target=year_1969)
    kg.add_relationship(relationship_type="developed", source=grace_hopper, target=cobol)
    kg.add_relationship(relationship_type="pioneered", source=alan_turing, target=computer)
    kg.add_relationship(relationship_type="precursor_of", source=arpanet, target=internet)
    kg.add_relationship(relationship_type="related_to", source=computer, target=programming)
    kg.add_relationship(relationship_type="example_of", source=eniac, target=computer)
    
    # Generate visualizations
    basic_graph = tracer._generate_mermaid_graph(
        entity_types={"concept": 2, "technology": 3, "person": 2, "date": 3},
        relationship_types={"created_in": 3, "developed": 1, "pioneered": 1, "precursor_of": 1, "related_to": 1, "example_of": 1}
    )
    
    detailed_graph = tracer._generate_detailed_mermaid_graph({"entities": kg.entities, "relationships": kg.relationships})
    
    timeline = tracer._generate_entity_timeline({"entities": kg.entities, "relationships": kg.relationships})
    
    # Print visualizations
    print("\nBasic Knowledge Graph Visualization:")
    print(basic_graph)
    
    print("\nDetailed Knowledge Graph Visualization:")
    print(detailed_graph)
    
    print("\nTimeline Visualization:")
    print(timeline)

def main():
    """Main function to run examples."""
    print("=== LLM Reasoning Tracer Examples ===")
    
    # Run examples
    extraction_temperature_analysis()
    cross_document_analysis_example()
    detailed_graph_visualization()
    
    print("\nExamples completed.")

if __name__ == "__main__":
    main()