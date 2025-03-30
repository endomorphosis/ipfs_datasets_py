#!/usr/bin/env python
"""
Example demonstrating the integration between RAG Query Optimizer and GraphRAG LLM Processing
for enhanced cross-document reasoning.

This example shows how to:
1. Initialize the RAG Query Optimizer and GraphRAG LLM Processor
2. Perform optimized cross-document reasoning with different knowledge graph types
3. Access and interpret the optimized reasoning results
"""

import numpy as np
from typing import Dict, List, Any, Optional

from ipfs_datasets_py.rag_query_optimizer import (
    UnifiedGraphRAGQueryOptimizer,
    WikipediaKnowledgeGraphOptimizer,
    IPLDGraphRAGQueryOptimizer
)
from ipfs_datasets_py.llm_graphrag import (
    GraphRAGLLMProcessor,
    ReasoningEnhancer
)
from ipfs_datasets_py.llm_interface import LLMInterfaceFactory
from ipfs_datasets_py.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer


def create_mock_documents() -> List[Dict[str, Any]]:
    """Create mock documents for the example."""
    return [
        {
            "id": "doc1",
            "title": "Neural Networks Overview",
            "content": "Neural networks are a key component of deep learning, inspired by the human brain.",
            "type": "academic",
            "trace_id": "trace123"
        },
        {
            "id": "doc2",
            "title": "Transformer Architecture",
            "content": "Transformers revolutionized NLP by using self-attention mechanisms instead of recurrence.",
            "type": "academic",
            "trace_id": "trace456"
        },
        {
            "id": "doc3",
            "title": "Large Language Models",
            "content": "Large language models are trained on vast amounts of text data to generate human-like responses.",
            "type": "academic",
            "root_cid": "bafybeihsl7tqdebswdmafvytgkofgxnpq5rwzzqpsbd7gtaiujwsn4qeyy"
        }
    ]


def create_mock_connections() -> List[Dict[str, Any]]:
    """Create mock document connections for the example."""
    return [
        {
            "doc1": {"id": "doc1", "title": "Neural Networks Overview"},
            "doc2": {"id": "doc2", "title": "Transformer Architecture"},
            "entity": {"id": "entity1", "name": "Deep Learning", "type": "concept"},
            "connection_type": "related_to",
            "explanation": "Both neural networks and transformers are key components of deep learning."
        },
        {
            "doc2": {"id": "doc2", "title": "Transformer Architecture"},
            "doc3": {"id": "doc3", "title": "Large Language Models"},
            "entity": {"id": "entity2", "name": "Attention Mechanism", "type": "concept"},
            "connection_type": "instance_of",
            "explanation": "Large language models use transformer architectures which rely on attention mechanisms."
        }
    ]


def run_wikipedia_example():
    """Run an example of optimizer-enhanced cross-document reasoning with Wikipedia knowledge graphs."""
    print("\n=== Wikipedia Knowledge Graph Example ===\n")
    
    # Create a mock Wikipedia tracer for the optimizer
    tracer = WikipediaKnowledgeGraphTracer()
    
    # Initialize the Wikipedia optimizer
    wikipedia_optimizer = WikipediaKnowledgeGraphOptimizer(tracer=tracer)
    
    # Create a unified optimizer that includes the Wikipedia optimizer
    unified_optimizer = UnifiedGraphRAGQueryOptimizer(
        wikipedia_optimizer=wikipedia_optimizer,
        default_vector_weight=0.6,
        default_graph_weight=0.4
    )
    
    # Initialize LLM processor with the optimizer
    llm = LLMInterfaceFactory.create()
    processor = GraphRAGLLMProcessor(
        llm_interface=llm,
        query_optimizer=unified_optimizer
    )
    
    # Initialize reasoning enhancer with the processor
    enhancer = ReasoningEnhancer(
        llm_processor=processor,
        query_optimizer=unified_optimizer
    )
    
    # Create mock data
    documents = create_mock_documents()
    connections = create_mock_connections()
    
    # Extract Wikipedia document trace IDs
    doc_trace_ids = [doc.get("trace_id") for doc in documents if "trace_id" in doc]
    
    # Create a mock query vector
    query_vector = np.random.rand(768)
    
    # Perform optimized cross-document reasoning
    result = enhancer.optimize_and_reason(
        query="How do neural networks relate to large language models?",
        query_vector=query_vector,
        documents=documents,
        connections=connections,
        reasoning_depth="moderate",
        doc_trace_ids=doc_trace_ids
    )
    
    # Print the results
    print(f"Answer: {result['answer']}")
    print(f"Confidence: {result['confidence']}")
    
    # Print optimizer information if available
    if "optimizer_info" in result:
        print("\nOptimizer Information:")
        print(f"  Optimizer Type: {result['optimizer_info']['optimizer_type']}")
        print(f"  Vector Weight: {result['optimizer_info']['vector_weight']}")
        print(f"  Graph Weight: {result['optimizer_info']['graph_weight']}")


def run_ipld_example():
    """Run an example of optimizer-enhanced cross-document reasoning with IPLD-based knowledge graphs."""
    print("\n=== IPLD Knowledge Graph Example ===\n")
    
    # Initialize the IPLD optimizer
    ipld_optimizer = IPLDGraphRAGQueryOptimizer(
        vector_weight=0.5,
        graph_weight=0.5,
        max_cid_depth=2
    )
    
    # Create a unified optimizer that includes the IPLD optimizer
    unified_optimizer = UnifiedGraphRAGQueryOptimizer(
        ipld_optimizer=ipld_optimizer,
        default_vector_weight=0.5,
        default_graph_weight=0.5
    )
    
    # Initialize LLM processor with the optimizer
    llm = LLMInterfaceFactory.create()
    processor = GraphRAGLLMProcessor(
        llm_interface=llm,
        query_optimizer=unified_optimizer
    )
    
    # Initialize reasoning enhancer with the processor
    enhancer = ReasoningEnhancer(
        llm_processor=processor,
        query_optimizer=unified_optimizer
    )
    
    # Create mock data
    documents = create_mock_documents()
    connections = create_mock_connections()
    
    # Extract IPLD-based document root CIDs
    root_cids = [doc.get("root_cid") for doc in documents if "root_cid" in doc]
    
    # Create a mock query vector
    query_vector = np.random.rand(768)
    
    # Perform optimized cross-document reasoning
    result = enhancer.optimize_and_reason(
        query="What is the role of attention mechanisms in large language models?",
        query_vector=query_vector,
        documents=documents,
        connections=connections,
        reasoning_depth="moderate",
        root_cids=root_cids
    )
    
    # Print the results
    print(f"Answer: {result['answer']}")
    print(f"Confidence: {result['confidence']}")
    
    # Print optimizer information if available
    if "optimizer_info" in result:
        print("\nOptimizer Information:")
        print(f"  Optimizer Type: {result['optimizer_info']['optimizer_type']}")
        print(f"  Vector Weight: {result['optimizer_info']['vector_weight']}")
        print(f"  Graph Weight: {result['optimizer_info']['graph_weight']}")


def run_unified_example():
    """Run an example of optimizer-enhanced cross-document reasoning with mixed knowledge graph types."""
    print("\n=== Unified Multi-Graph Example ===\n")
    
    # Create a mock Wikipedia tracer for the optimizer
    tracer = WikipediaKnowledgeGraphTracer()
    
    # Initialize the component optimizers
    wikipedia_optimizer = WikipediaKnowledgeGraphOptimizer(tracer=tracer)
    ipld_optimizer = IPLDGraphRAGQueryOptimizer(
        vector_weight=0.5,
        graph_weight=0.5
    )
    
    # Create a unified optimizer that includes both component optimizers
    unified_optimizer = UnifiedGraphRAGQueryOptimizer(
        wikipedia_optimizer=wikipedia_optimizer,
        ipld_optimizer=ipld_optimizer,
        auto_detect_graph_type=True
    )
    
    # Initialize LLM processor with the optimizer
    llm = LLMInterfaceFactory.create()
    processor = GraphRAGLLMProcessor(
        llm_interface=llm,
        query_optimizer=unified_optimizer
    )
    
    # Initialize reasoning enhancer with the processor
    enhancer = ReasoningEnhancer(
        llm_processor=processor,
        query_optimizer=unified_optimizer
    )
    
    # Create mock data
    documents = create_mock_documents()
    connections = create_mock_connections()
    
    # Prepare graph specifications for multi-graph query
    graph_specs = []
    for doc in documents:
        if "trace_id" in doc:
            graph_specs.append({
                "graph_type": "wikipedia",
                "trace_id": doc["trace_id"],
                "weight": 1.0 / len(documents)
            })
        elif "root_cid" in doc:
            graph_specs.append({
                "graph_type": "ipld",
                "root_cid": doc["root_cid"],
                "weight": 1.0 / len(documents)
            })
    
    # Create a mock query vector
    query_vector = np.random.rand(768)
    
    # Perform optimized cross-document reasoning with auto-detection of graph types
    result = enhancer.optimize_and_reason(
        query="Explain how transformer architectures enable large language models.",
        query_vector=query_vector,
        documents=documents,
        connections=connections,
        reasoning_depth="deep"
    )
    
    # Print the results
    print(f"Answer: {result['answer']}")
    print(f"Confidence: {result['confidence']}")
    
    # Print optimizer information if available
    if "optimizer_info" in result:
        print("\nOptimizer Information:")
        print(f"  Optimizer Type: {result['optimizer_info']['optimizer_type']}")
        print(f"  Vector Weight: {result['optimizer_info']['vector_weight']}")
        print(f"  Graph Weight: {result['optimizer_info']['graph_weight']}")
    
    # Print implications for deep reasoning
    if "implications" in result:
        print("\nImplications:")
        for implication in result["implications"]:
            print(f"  - {implication}")


def main():
    """Run all examples."""
    print("=== GraphRAG Query Optimizer Integration Examples ===")
    
    # Run each example
    run_wikipedia_example()
    run_ipld_example()
    run_unified_example()
    
    print("\nExample complete.")


if __name__ == "__main__":
    main()