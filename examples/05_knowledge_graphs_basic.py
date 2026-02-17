"""
Knowledge Graphs - Extract Entities and Relationships

This example demonstrates how to extract structured knowledge from text using
the knowledge graph extraction capabilities. Knowledge graphs represent entities
(people, places, organizations) and their relationships.

Requirements:
    - transformers, torch (for NLP models)
    - Optional: spacy for advanced NER

Usage:
    python examples/05_knowledge_graphs_basic.py
"""

import asyncio
from pathlib import Path


async def demo_basic_entity_extraction():
    """Extract entities from simple text."""
    print("\n" + "="*70)
    print("DEMO 1: Basic Entity Extraction")
    print("="*70)
    
    try:
        from ipfs_datasets_py.knowledge_graphs.entity_extractor import EntityExtractor
        
        # Sample text
        text = """
        Apple Inc. was founded by Steve Jobs, Steve Wozniak, and Ronald Wayne in 
        Cupertino, California in 1976. The company is now headquartered in Apple Park
        and is led by CEO Tim Cook. Apple's products include the iPhone, iPad, and Mac.
        """
        
        print("\n📝 Input text:")
        print(f"   {text.strip()[:100]}...")
        
        # Extract entities
        print("\n🔍 Extracting entities...")
        extractor = EntityExtractor()
        entities = await extractor.extract(text)
        
        # Group by type
        by_type = {}
        for entity in entities:
            entity_type = entity.get('type', 'UNKNOWN')
            if entity_type not in by_type:
                by_type[entity_type] = []
            by_type[entity_type].append(entity['text'])
        
        # Display results
        print("\n✅ Extracted Entities:")
        for entity_type, items in sorted(by_type.items()):
            print(f"\n   {entity_type}:")
            for item in items:
                print(f"      - {item}")
        
        return entities
        
    except ImportError as e:
        print(f"\n❌ Missing dependencies: {e}")
        print("   Install with: pip install transformers torch")
        return None
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def demo_relationship_extraction():
    """Extract relationships between entities."""
    print("\n" + "="*70)
    print("DEMO 2: Relationship Extraction")
    print("="*70)
    
    try:
        from ipfs_datasets_py.knowledge_graphs.relationship_extractor import (
            RelationshipExtractor
        )
        
        text = """
        Microsoft was founded by Bill Gates and Paul Allen. 
        Satya Nadella is the current CEO of Microsoft.
        The company is based in Redmond, Washington.
        """
        
        print("\n📝 Input text:")
        print(f"   {text.strip()}")
        
        print("\n🔍 Extracting relationships...")
        extractor = RelationshipExtractor()
        relationships = await extractor.extract(text)
        
        print("\n✅ Extracted Relationships:")
        for i, rel in enumerate(relationships, 1):
            print(f"\n   {i}. {rel.get('subject', '?')} "
                  f"--[{rel.get('predicate', '?')}]--> "
                  f"{rel.get('object', '?')}")
            if 'confidence' in rel:
                print(f"      Confidence: {rel['confidence']:.2f}")
        
        return relationships
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def demo_knowledge_graph_creation():
    """Create a complete knowledge graph from text."""
    print("\n" + "="*70)
    print("DEMO 3: Knowledge Graph Creation")
    print("="*70)
    
    try:
        from ipfs_datasets_py.knowledge_graphs.graph_builder import KnowledgeGraphBuilder
        
        text = """
        The Python programming language was created by Guido van Rossum.
        It was first released in 1991. Python is known for its simplicity
        and readability. Many companies like Google, Netflix, and NASA use Python.
        The language is maintained by the Python Software Foundation.
        """
        
        print("\n📝 Creating knowledge graph from text...")
        print(f"   {text.strip()[:80]}...")
        
        # Build graph
        builder = KnowledgeGraphBuilder()
        graph = await builder.build_from_text(text)
        
        # Display graph statistics
        print("\n📊 Knowledge Graph Statistics:")
        print(f"   Entities: {len(graph.entities)}")
        print(f"   Relationships: {len(graph.relationships)}")
        
        # Show entities
        print("\n   Entities:")
        for entity in graph.entities[:5]:  # Show first 5
            print(f"      - {entity.name} ({entity.type})")
        
        # Show relationships
        print("\n   Relationships:")
        for rel in graph.relationships[:5]:  # Show first 5
            print(f"      - {rel.source} -> {rel.target} [{rel.type}]")
        
        return graph
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def demo_graph_querying():
    """Query a knowledge graph."""
    print("\n" + "="*70)
    print("DEMO 4: Knowledge Graph Querying")
    print("="*70)
    
    try:
        from ipfs_datasets_py.knowledge_graphs import (
            KnowledgeGraphBuilder,
            GraphQuery
        )
        
        # Create a graph
        text = """
        Amazon was founded by Jeff Bezos in Seattle in 1994.
        Andy Jassy is the current CEO of Amazon. Amazon Web Services (AWS)
        is a subsidiary of Amazon. AWS provides cloud computing services.
        """
        
        print("\n📝 Building knowledge graph...")
        builder = KnowledgeGraphBuilder()
        graph = await builder.build_from_text(text)
        
        # Query the graph
        print("\n🔍 Querying knowledge graph...")
        query = GraphQuery(graph)
        
        # Find all entities related to Amazon
        print("\n   Query 1: Find entities related to 'Amazon'")
        related = await query.find_related("Amazon", max_hops=1)
        for entity in related[:5]:
            print(f"      - {entity.name} ({entity.type})")
        
        # Find paths between entities
        print("\n   Query 2: Find path from 'Jeff Bezos' to 'AWS'")
        paths = await query.find_paths("Jeff Bezos", "AWS", max_hops=3)
        if paths:
            for path in paths[:2]:  # Show first 2 paths
                path_str = " -> ".join(path)
                print(f"      - {path_str}")
        else:
            print("      No paths found")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def demo_graph_visualization():
    """Visualize a knowledge graph."""
    print("\n" + "="*70)
    print("DEMO 5: Knowledge Graph Visualization")
    print("="*70)
    
    print("\n📊 Graph visualization example")
    print("   (Requires matplotlib or graphviz)")
    
    # Example code (commented as it requires visualization libraries)
    """
    try:
        from ipfs_datasets_py.knowledge_graphs import KnowledgeGraphBuilder
        from ipfs_datasets_py.knowledge_graphs.visualizer import GraphVisualizer
        
        # Create graph
        text = "Sample text for graph creation..."
        builder = KnowledgeGraphBuilder()
        graph = await builder.build_from_text(text)
        
        # Visualize
        visualizer = GraphVisualizer()
        visualizer.render(graph, output_file="knowledge_graph.png")
        
        print("   ✅ Graph saved to knowledge_graph.png")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
    """
    
    print("\n   💡 Tip: Use GraphVisualizer to create visual representations")
    print("   of your knowledge graphs for better understanding")


def show_tips():
    """Show tips for working with knowledge graphs."""
    print("\n" + "="*70)
    print("TIPS FOR KNOWLEDGE GRAPHS")
    print("="*70)
    
    print("\n1. Entity Extraction:")
    print("   - Use spaCy for better NER accuracy")
    print("   - Fine-tune models on domain-specific data")
    print("   - Consider entity linking to external knowledge bases")
    
    print("\n2. Relationship Extraction:")
    print("   - Combine rule-based and ML approaches")
    print("   - Validate relationships with external sources")
    print("   - Use dependency parsing for better accuracy")
    
    print("\n3. Graph Storage:")
    print("   - Use Neo4j for large-scale graphs")
    print("   - IPLD backend for decentralized storage")
    print("   - Consider graph databases for complex queries")
    
    print("\n4. Applications:")
    print("   - Question answering systems")
    print("   - Document understanding and summarization")
    print("   - Knowledge base construction")
    print("   - Semantic search enhancement")
    
    print("\n5. Next Steps:")
    print("   - See 12_graphrag_basic.py for RAG with knowledge graphs")
    print("   - See 14_cross_document_reasoning.py for multi-doc graphs")


async def main():
    """Run all knowledge graph demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - KNOWLEDGE GRAPHS")
    print("="*70)
    
    await demo_basic_entity_extraction()
    await demo_relationship_extraction()
    await demo_knowledge_graph_creation()
    await demo_graph_querying()
    await demo_graph_visualization()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ KNOWLEDGE GRAPH EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
