#!/usr/bin/env python3
"""
Example script demonstrating the LLM Reasoning Tracer for GraphRAG.

This script shows how to:
1. Create reasoning traces for GraphRAG queries
2. Track document and entity access during reasoning
3. Record inferences, evidence, and conclusions
4. Analyze and visualize reasoning paths
5. Generate explanations of the reasoning process

NOTE: This is a mock implementation that will be replaced with
actual LLM integration in the future with the ipfs_accelerate_py package.
"""

import os
import sys
import json
import time
import random

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(parent_dir)

# Import the LLM reasoning tracer
from ipfs_datasets_py.llm_reasoning_tracer import (
    LLMReasoningTracer,
    ReasoningNodeType,
    ReasoningTrace
)


def llm_reasoning_example():
    """Demonstrate the LLM reasoning tracer functionality."""
    print("IPFS Datasets Python - LLM Reasoning Tracer Example")
    print("=================================================")
    
    # Create a temporary directory for the example
    import tempfile
    temp_dir = tempfile.mkdtemp()
    print(f"Using temporary directory: {temp_dir}")
    
    # Initialize the reasoning tracer
    tracer = LLMReasoningTracer(storage_dir=temp_dir)
    
    # Step 1: Create a trace for a research query
    print("\nStep 1: Creating a reasoning trace")
    print("--------------------------------")
    
    trace = tracer.create_trace(
        query="What is the relationship between climate change and biodiversity loss?",
        metadata={"domain": "environmental science", "priority": "high"}
    )
    
    print(f"Created trace with ID: {trace.trace_id}")
    print(f"Query: {trace.query}")
    
    # Step 2: Record document access
    print("\nStep 2: Recording document access")
    print("------------------------------")
    
    # Simulate document retrieval and add to trace
    documents = [
        {
            "id": "doc1",
            "content": "Climate change affects ecosystems through increasing temperatures, changing precipitation patterns, and extreme weather events. These changes can lead to habitat loss and fragmentation.",
            "relevance": 0.92
        },
        {
            "id": "doc2",
            "content": "Biodiversity loss accelerates as species fail to adapt to rapidly changing environmental conditions. Many species face extinction risks due to climate-related changes to their habitats.",
            "relevance": 0.88
        },
        {
            "id": "doc3",
            "content": "The relationship between climate change and biodiversity is bidirectional. Healthy ecosystems with high biodiversity can help mitigate climate change by sequestering carbon.",
            "relevance": 0.95
        }
    ]
    
    doc_nodes = []
    for doc in documents:
        doc_node_id = tracer.trace_document_access(
            trace=trace,
            document_content=doc["content"],
            document_id=doc["id"],
            relevance_score=doc["relevance"]
        )
        doc_nodes.append(doc_node_id)
        print(f"Added document {doc['id']} to trace (node ID: {doc_node_id})")
    
    # Step 3: Record entity access
    print("\nStep 3: Recording entity access")
    print("----------------------------")
    
    # Simulate entity extraction and add to trace
    entities = [
        {"name": "Climate Change", "id": "entity1", "type": "Phenomenon", "relevance": 0.98},
        {"name": "Biodiversity Loss", "id": "entity2", "type": "Phenomenon", "relevance": 0.97},
        {"name": "Habitat Fragmentation", "id": "entity3", "type": "Process", "relevance": 0.85},
        {"name": "Carbon Sequestration", "id": "entity4", "type": "Process", "relevance": 0.82}
    ]
    
    entity_nodes = []
    for entity in entities:
        entity_node_id = tracer.trace_entity_access(
            trace=trace,
            entity_name=entity["name"],
            entity_id=entity["id"],
            entity_type=entity["type"],
            relevance_score=entity["relevance"]
        )
        entity_nodes.append(entity_node_id)
        print(f"Added entity {entity['name']} to trace (node ID: {entity_node_id})")
    
    # Step 4: Record relationships between entities
    print("\nStep 4: Recording relationships")
    print("----------------------------")
    
    # Add relationships between entities
    relationships = [
        {"source": 0, "target": 1, "type": "causes", "confidence": 0.9},
        {"source": 0, "target": 2, "type": "causes", "confidence": 0.87},
        {"source": 3, "target": 0, "type": "mitigates", "confidence": 0.85}
    ]
    
    for rel in relationships:
        source_id = entity_nodes[rel["source"]]
        target_id = entity_nodes[rel["target"]]
        tracer.trace_relationship(
            trace=trace,
            source_node_id=source_id,
            target_node_id=target_id,
            relationship_type=rel["type"],
            confidence=rel["confidence"]
        )
        print(f"Added relationship: {entities[rel['source']]['name']} {rel['type']} {entities[rel['target']]['name']}")
    
    # Step 5: Record evidence
    print("\nStep 5: Recording evidence")
    print("-----------------------")
    
    # Extract evidence from documents
    evidence_statements = [
        {
            "text": "Climate change causes habitat loss and fragmentation",
            "source": 0,
            "confidence": 0.92
        },
        {
            "text": "Species face extinction risks due to climate-related habitat changes",
            "source": 1,
            "confidence": 0.9
        },
        {
            "text": "Biodiversity helps mitigate climate change through carbon sequestration",
            "source": 2,
            "confidence": 0.94
        }
    ]
    
    evidence_nodes = []
    for evidence in evidence_statements:
        evidence_node_id = tracer.trace_evidence(
            trace=trace,
            evidence_text=evidence["text"],
            source_node_id=doc_nodes[evidence["source"]],
            confidence=evidence["confidence"]
        )
        evidence_nodes.append(evidence_node_id)
        print(f"Added evidence: {evidence['text']}")
    
    # Step 6: Record inferences
    print("\nStep 6: Recording inferences")
    print("-------------------------")
    
    # Make inferences based on evidence
    inferences = [
        {
            "text": "Climate change directly contributes to biodiversity loss through ecosystem disruption",
            "sources": [0, 1],
            "confidence": 0.91
        },
        {
            "text": "There is a feedback loop where biodiversity loss can accelerate climate change",
            "sources": [2],
            "confidence": 0.85
        }
    ]
    
    inference_nodes = []
    for inference in inferences:
        source_nodes = [evidence_nodes[i] for i in inference["sources"]]
        inference_node_id = tracer.trace_inference(
            trace=trace,
            inference_text=inference["text"],
            source_node_ids=source_nodes,
            confidence=inference["confidence"]
        )
        inference_nodes.append(inference_node_id)
        print(f"Added inference: {inference['text']}")
    
    # Step 7: Record conclusion
    print("\nStep 7: Recording conclusion")
    print("-------------------------")
    
    # Draw a conclusion based on inferences
    conclusion_node_id = tracer.trace_conclusion(
        trace=trace,
        conclusion_text="Climate change and biodiversity loss are interconnected in a bidirectional relationship, creating both positive and negative feedback loops. Climate change accelerates biodiversity loss through habitat changes, while biodiversity loss can exacerbate climate change by reducing carbon sequestration capacity.",
        supporting_node_ids=inference_nodes,
        confidence=0.9
    )
    
    print(f"Added conclusion (node ID: {conclusion_node_id})")
    
    # Step 8: Analyze the reasoning trace
    print("\nStep 8: Analyzing the reasoning trace")
    print("---------------------------------")
    
    analysis = tracer.analyze_trace(trace)
    
    print(f"Node count: {analysis['node_count']}")
    print(f"Edge count: {analysis['edge_count']}")
    print(f"Node types: {json.dumps(analysis['node_types'], indent=2)}")
    print(f"Average confidence: {analysis['avg_confidence']:.2f}")
    print(f"Reasoning complexity: {analysis['reasoning_complexity']:.2f}")
    
    # Step 9: Generate an explanation
    print("\nStep 9: Generating an explanation")
    print("------------------------------")
    
    explanation = tracer.generate_explanation(trace, detail_level="high")
    print("\nExplanation:")
    print(explanation)
    
    # Step 10: Visualize the reasoning trace
    print("\nStep 10: Visualizing the reasoning trace")
    print("------------------------------------")
    
    # Export a visualization in D3.js format
    visualization_path = os.path.join(temp_dir, "reasoning_visualization.json")
    tracer.export_visualization(
        trace=trace,
        output_format="d3",
        output_file=visualization_path
    )
    
    print(f"Visualization exported to: {visualization_path}")
    
    # Save the trace
    trace_path = tracer.save_trace(trace)
    print(f"Trace saved to: {trace_path}")
    
    print("\nNOTE: This is a mock implementation of the LLM Reasoning Tracer.")
    print("In a full implementation, the reasoning would be performed by an actual LLM")
    print("using the ipfs_accelerate_py package.")


if __name__ == "__main__":
    llm_reasoning_example()