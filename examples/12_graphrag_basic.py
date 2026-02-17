"""
GraphRAG Basics - Knowledge Graph-Enhanced Retrieval

This example demonstrates GraphRAG (Graph Retrieval-Augmented Generation),
which combines knowledge graphs with vector search for enhanced information
retrieval and question answering.

Requirements:
    - transformers, torch: pip install transformers torch
    - faiss-cpu: pip install faiss-cpu

Usage:
    python examples/12_graphrag_basic.py
"""

import asyncio
from pathlib import Path
import tempfile


async def demo_basic_graphrag():
    """Demonstrate basic GraphRAG workflow."""
    print("\n" + "="*70)
    print("DEMO 1: Basic GraphRAG Workflow")
    print("="*70)
    
    print("\n📊 GraphRAG combines:")
    print("   1. Knowledge Graph: Structured relationships")
    print("   2. Vector Search: Semantic similarity")
    print("   3. RAG: Retrieval-Augmented Generation")
    
    example_code = '''
from ipfs_datasets_py.search import HybridVectorGraphSearch
from ipfs_datasets_py.ml.embeddings import IPFSEmbeddings
from ipfs_datasets_py.knowledge_graphs import KnowledgeGraphBuilder

# 1. Build knowledge graph from documents
documents = [
    "Python is a programming language created by Guido van Rossum.",
    "Python is widely used for web development, data science, and AI.",
    "Flask and Django are popular Python web frameworks."
]

builder = KnowledgeGraphBuilder()
graph = await builder.build_from_texts(documents)

print(f"Created graph with {len(graph.entities)} entities")

# 2. Create embeddings
embedder = IPFSEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
embeddings = await embedder.generate_embeddings(documents)

# 3. Initialize GraphRAG
graphrag = HybridVectorGraphSearch(
    graph=graph,
    embeddings=embeddings,
    documents=documents
)

# 4. Query with GraphRAG
query = "What is Python used for?"
results = await graphrag.search(
    query=query,
    top_k=3,
    use_graph=True,  # Enable graph traversal
    use_vector=True   # Enable vector search
)

# Results combine both graph and vector information
for result in results:
    print(f"Score: {result['score']:.3f}")
    print(f"Text: {result['text']}")
    print(f"Entities: {result['entities']}")
    print(f"Relationships: {result['relationships']}")
    '''
    
    print(example_code)


async def demo_entity_centric_retrieval():
    """Retrieve information about specific entities."""
    print("\n" + "="*70)
    print("DEMO 2: Entity-Centric Retrieval")
    print("="*70)
    
    print("\n🎯 Entity-Centric Retrieval")
    print("   Focus on specific entities and their context")
    
    example_code = '''
from ipfs_datasets_py.search import LogicAwareEntityExtractor

extractor = LogicAwareEntityExtractor()

# Extract entities with context
text = """
Apple Inc. was founded by Steve Jobs in 1976. The company is now
led by Tim Cook and produces products like the iPhone and MacBook.
"""

entities = await extractor.extract_with_context(text)

# Each entity has rich context
for entity in entities:
    print(f"Entity: {entity['name']}")
    print(f"Type: {entity['type']}")
    print(f"Context: {entity['context']}")
    print(f"Related entities: {entity['related']}")
    print()

# Search for entity-specific information
results = await graphrag.search_entity(
    entity_name="Apple Inc.",
    relation_types=["founded_by", "produces", "led_by"],
    depth=2  # Two hops in the graph
)

for result in results:
    print(f"Relation: {result['relation']}")
    print(f"Target: {result['target_entity']}")
    print(f"Confidence: {result['confidence']:.2f}")
    '''
    
    print(example_code)


async def demo_multi_hop_reasoning():
    """Perform multi-hop reasoning over knowledge graphs."""
    print("\n" + "="*70)
    print("DEMO 3: Multi-Hop Reasoning")
    print("="*70)
    
    print("\n🔗 Multi-Hop Reasoning")
    print("   Answer questions requiring multiple inference steps")
    
    example_code = '''
from ipfs_datasets_py.search import CrossDocumentReasoner

reasoner = CrossDocumentReasoner(
    knowledge_graph=graph,
    max_hops=3,
    reasoning_strategy="bidirectional"
)

# Question requiring multi-hop reasoning
question = "Who founded the company that makes the iPhone?"

# Reasoning path:
# 1. iPhone -> produced_by -> Apple Inc.
# 2. Apple Inc. -> founded_by -> Steve Jobs
# Answer: Steve Jobs

reasoning_result = await reasoner.answer_question(
    question=question,
    context_documents=documents
)

print(f"Question: {question}")
print(f"Answer: {reasoning_result['answer']}")
print(f"Confidence: {reasoning_result['confidence']:.2f}")

print("\\nReasoning path:")
for i, step in enumerate(reasoning_result['reasoning_path'], 1):
    print(f"{i}. {step['from']} --[{step['relation']}]--> {step['to']}")

print("\\nSupporting evidence:")
for evidence in reasoning_result['evidence']:
    print(f"- {evidence}")
    '''
    
    print(example_code)


async def demo_graphrag_with_documents():
    """Build GraphRAG from actual documents."""
    print("\n" + "="*70)
    print("DEMO 4: GraphRAG from Documents")
    print("="*70)
    
    print("\n📄 Building GraphRAG from Documents")
    
    example_code = '''
from ipfs_datasets_py.processors.file_converter import FileConverter
from ipfs_datasets_py.search import HybridVectorGraphSearch

# 1. Convert documents to text
converter = FileConverter()
document_files = ["doc1.pdf", "doc2.docx", "doc3.txt"]

texts = []
for file_path in document_files:
    result = await converter.convert(file_path, target_format='txt')
    if result.success:
        texts.append(result.content)

print(f"Converted {len(texts)} documents")

# 2. Build knowledge graph
builder = KnowledgeGraphBuilder()
graph = await builder.build_from_texts(texts)

print(f"Extracted {len(graph.entities)} entities")
print(f"Found {len(graph.relationships)} relationships")

# 3. Create GraphRAG system
embedder = IPFSEmbeddings()
embeddings = await embedder.generate_embeddings(texts)

graphrag = HybridVectorGraphSearch(
    graph=graph,
    embeddings=embeddings,
    documents=texts
)

# 4. Query the system
results = await graphrag.search(
    query="What are the main topics discussed?",
    top_k=5,
    use_graph=True,
    use_vector=True
)

for i, result in enumerate(results, 1):
    print(f"{i}. Score: {result['score']:.3f}")
    print(f"   {result['text'][:100]}...")
    '''
    
    print(example_code)


async def demo_logic_enhanced_rag():
    """Combine logic reasoning with RAG."""
    print("\n" + "="*70)
    print("DEMO 5: Logic-Enhanced RAG")
    print("="*70)
    
    print("\n🧠 Logic-Enhanced RAG")
    print("   Add logical constraints to retrieval")
    
    example_code = '''
from ipfs_datasets_py.search import LogicEnhancedRAG

# Create RAG with logic constraints
logic_rag = LogicEnhancedRAG(
    knowledge_graph=graph,
    embeddings=embeddings,
    logic_engine="fol"  # First-Order Logic
)

# Define logical constraints
constraints = [
    "entity(X, 'Person') & founded(X, Y) -> entity(Y, 'Company')",
    "produces(Company, Product) -> owns(Company, Product)",
]

logic_rag.add_constraints(constraints)

# Query with constraints
query = "Find all companies founded by people"
results = await logic_rag.search(
    query=query,
    constraints=constraints,
    verify_logic=True  # Verify results satisfy constraints
)

# Results are guaranteed to satisfy logical constraints
for result in results:
    print(f"Company: {result['company']}")
    print(f"Founder: {result['founder']}")
    print(f"Satisfies: {result['constraints_satisfied']}")
    '''
    
    print(example_code)


async def demo_graphrag_evaluation():
    """Evaluate GraphRAG performance."""
    print("\n" + "="*70)
    print("DEMO 6: GraphRAG Evaluation")
    print("="*70)
    
    print("\n📊 Evaluating GraphRAG Performance")
    
    example_code = '''
from ipfs_datasets_py.search import GraphRAGEvaluator

evaluator = GraphRAGEvaluator()

# Define test questions
test_cases = [
    {
        "question": "Who founded Apple?",
        "expected_answer": "Steve Jobs",
        "expected_entities": ["Apple Inc.", "Steve Jobs"],
    },
    # ... more test cases
]

# Evaluate
results = await evaluator.evaluate(
    graphrag=graphrag,
    test_cases=test_cases
)

# Metrics
print(f"Accuracy: {results['accuracy']:.2%}")
print(f"Precision: {results['precision']:.2%}")
print(f"Recall: {results['recall']:.2%}")
print(f"F1 Score: {results['f1_score']:.2%}")

# Detailed analysis
print("\\nPer-question results:")
for test_case, result in zip(test_cases, results['details']):
    print(f"Q: {test_case['question']}")
    print(f"  Correct: {result['correct']}")
    print(f"  Confidence: {result['confidence']:.2f}")
    '''
    
    print(example_code)


async def demo_graphrag_update():
    """Update GraphRAG with new information."""
    print("\n" + "="*70)
    print("DEMO 7: Updating GraphRAG")
    print("="*70)
    
    print("\n🔄 Incremental Updates")
    print("   Add new information without rebuilding")
    
    example_code = '''
# Add new documents
new_documents = [
    "Apple acquired Beats Electronics in 2014.",
    "Beats was founded by Dr. Dre and Jimmy Iovine."
]

# Update graph incrementally
for doc in new_documents:
    new_entities = await builder.extract_entities(doc)
    new_relations = await builder.extract_relationships(doc)
    
    graph.add_entities(new_entities)
    graph.add_relationships(new_relations)

print(f"Updated graph: {len(graph.entities)} entities")

# Update embeddings
new_embeddings = await embedder.generate_embeddings(new_documents)
graphrag.add_documents(new_documents, new_embeddings)

# Query with updated information
results = await graphrag.search(
    query="What companies did Apple acquire?",
    top_k=3
)

# Will now include information about Beats acquisition
    '''
    
    print(example_code)


def show_tips():
    """Show tips for GraphRAG."""
    print("\n" + "="*70)
    print("TIPS FOR GRAPHRAG")
    print("="*70)
    
    print("\n1. When to Use GraphRAG:")
    print("   - Complex queries requiring reasoning")
    print("   - Entity-centric information needs")
    print("   - Multi-document analysis")
    print("   - Structured knowledge domains")
    
    print("\n2. Graph Construction:")
    print("   - Use domain-specific entity extractors")
    print("   - Validate relationships before adding")
    print("   - Include entity types for better retrieval")
    print("   - Consider entity linking to external KBs")
    
    print("\n3. Hybrid Search:")
    print("   - Vector search: Good for semantic similarity")
    print("   - Graph search: Good for structured relationships")
    print("   - Combine both for best results")
    print("   - Weight by query type")
    
    print("\n4. Performance:")
    print("   - Index graph for fast traversal")
    print("   - Cache frequent queries")
    print("   - Limit graph depth for large graphs")
    print("   - Use approximate NN for vector search")
    
    print("\n5. Quality:")
    print("   - Evaluate with test questions")
    print("   - Monitor entity extraction accuracy")
    print("   - Validate relationship correctness")
    print("   - Use human feedback for improvement")
    
    print("\n6. Scaling:")
    print("   - Partition large graphs by domain")
    print("   - Use graph databases (Neo4j, etc.)")
    print("   - Distribute across multiple nodes")
    print("   - Incremental updates for efficiency")
    
    print("\n7. Applications:")
    print("   - Question answering systems")
    print("   - Research and analysis")
    print("   - Customer support")
    print("   - Knowledge management")
    
    print("\n8. Next Steps:")
    print("   - See 14_cross_document_reasoning.py for advanced multi-doc")
    print("   - See 15_graphrag_optimization.py for production systems")


async def main():
    """Run all GraphRAG demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - GRAPHRAG BASICS")
    print("="*70)
    
    await demo_basic_graphrag()
    await demo_entity_centric_retrieval()
    await demo_multi_hop_reasoning()
    await demo_graphrag_with_documents()
    await demo_logic_enhanced_rag()
    await demo_graphrag_evaluation()
    await demo_graphrag_update()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ GRAPHRAG EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
