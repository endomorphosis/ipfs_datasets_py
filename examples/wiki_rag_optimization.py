"""
Example script for using the RAG Query Optimizer with Wikipedia Knowledge Graphs.

This script demonstrates how to use the WikipediaKnowledgeGraphOptimizer to
optimize queries over Wikipedia-derived knowledge graphs, including:
- Basic query optimization with type and edge detection
- Cross-document query planning
- Performance analysis and tuning
"""

import numpy as np
from typing import Dict, List, Any
import json

from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor
from ipfs_datasets_py.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer
# TODO WikipediaKnowledgeGraphOptimizer is hallucinated. Needs to be implemented.
from ipfs_datasets_py.rag_query_optimizer import WikipediaKnowledgeGraphOptimizer 


def get_embedding(text: str) -> np.ndarray:
    """
    Get a mock embedding for a text.
    In a real application, this would use an embedding model.

    Args:
        text (str): Text to embed

    Returns:
        np.ndarray: Mock embedding vector
    """
    # Create a deterministic but somewhat unique embedding based on text
    hash_val = hash(text) % 1000
    np.random.seed(hash_val)
    return np.random.rand(768)  # Standard embedding size


def main():
    """Main demonstration function."""
    print("=== Wikipedia RAG Query Optimization Demo ===\n")

    # Initialize components
    print("Initializing components...")
    tracer = WikipediaKnowledgeGraphTracer()
    extractor = KnowledgeGraphExtractor(use_tracer=True)
    optimizer = WikipediaKnowledgeGraphOptimizer(tracer=tracer)

    # Extract knowledge graphs from Wikipedia pages with tracing
    print("\nExtracting knowledge graphs from Wikipedia pages...")
    wiki_pages = ["IPFS", "Blockchain", "Decentralized computing"]
    trace_ids = []

    for page in wiki_pages:
        print(f"- Processing page: {page}")
        try:
            # Extract and validate in a single step to get tracing
            result = extractor.extract_and_validate_wikipedia_graph(
                page_title=page,
                extraction_temperature=0.7,
                structure_temperature=0.5
            )
            if "trace_id" in result:
                trace_id = result["trace_id"]
                trace_ids.append(trace_id)
                print(f"  - Generated trace ID: {trace_id}")
        except Exception as e:
            print(f"  - Error processing page: {e}")

    # Demonstrate single-document query optimization
    print("\nOptimizing single-document queries...")
    queries = [
        "What is the architecture of IPFS and how does it handle content addressing?",
        "Who created the blockchain technology and when was it introduced?",
        "What are the security challenges in decentralized computing systems?"
    ]

    for i, query in enumerate(queries):
        print(f"\nQuery {i+1}: {query}")
        # Get query embedding
        query_vector = get_embedding(query)

        # Optimize for a specific trace if available
        trace_id = trace_ids[i] if i < len(trace_ids) else None

        # Optimize query
        plan = optimizer.optimize_query(
            query_text=query,
            query_vector=query_vector,
            trace_id=trace_id
        )

        # Print optimization results
        print("Query optimization results:")
        print(f"- Detected entity types: {', '.join(plan['detected_types'])}")
        print(f"- Important edge types: {', '.join(plan['important_edge_types'][:3])}...")
        print(f"- Vector/graph weights: {plan['weights']['vector']:.2f}/{plan['weights']['graph']:.2f}")
        print(f"- Max vector results: {plan['params']['max_vector_results']}")
        print(f"- Max traversal depth: {plan['params']['max_traversal_depth']}")

    # Demonstrate cross-document query optimization
    if len(trace_ids) >= 2:
        print("\nOptimizing cross-document queries...")
        cross_doc_query = "Compare the approach to decentralization in IPFS and blockchain technologies."
        query_vector = get_embedding(cross_doc_query)

        # Optimize cross-document query
        cross_doc_plan = optimizer.optimize_cross_document_query(
            query_text=cross_doc_query,
            query_vector=query_vector,
            doc_trace_ids=trace_ids
        )

        # Print cross-document optimization results
        print(f"Query: {cross_doc_query}")
        print("Cross-document optimization results:")
        print(f"- Connecting entities: {len(cross_doc_plan['connecting_entities'])}")
        print(f"- Traversal paths found: {len(cross_doc_plan['traversal_paths'])}")

        # Print top traversal path if available
        if cross_doc_plan['traversal_paths']:
            top_path = cross_doc_plan['traversal_paths'][0]
            print(f"- Top path connects through: {top_path['entity_name']} ({top_path['entity_type']})")
            print(f"- Starting document: {top_path['start_doc']}")
            print(f"- Connected documents: {len(top_path['connected_docs'])}")

    # Show optimizer statistics
    print("\nOptimizer usage statistics:")
    stats = optimizer.get_optimization_stats()
    print(json.dumps(stats, indent=2))

    print("\nDemo completed!")


if __name__ == "__main__":
    main()
