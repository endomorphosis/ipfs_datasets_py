"""
Cross-Document Reasoning - Multi-Document Analysis

This example demonstrates cross-document reasoning capabilities for analyzing
and connecting information across multiple documents, including entity linking,
relationship discovery, and multi-document question answering.

Requirements:
    - transformers, torch: pip install transformers torch
    - Core ipfs_datasets_py dependencies

Usage:
    python examples/14_cross_document_reasoning.py
"""

import asyncio
import tempfile
from pathlib import Path


async def demo_entity_linking():
    """Link entities across multiple documents."""
    print("\n" + "="*70)
    print("DEMO 1: Cross-Document Entity Linking")
    print("="*70)
    
    print("\n🔗 Entity Linking")
    print("   Identify same entities mentioned across documents")
    
    example_code = '''
from ipfs_datasets_py.search import CrossDocumentReasoner

# Multiple documents about related topics
documents = [
    {
        "id": "doc1",
        "text": "Apple Inc. was founded by Steve Jobs in 1976. The company is based in Cupertino."
    },
    {
        "id": "doc2", 
        "text": "Steve Jobs co-founded Apple Computer with Steve Wozniak. Jobs left Apple in 1985."
    },
    {
        "id": "doc3",
        "text": "The iPhone was introduced by Apple's CEO in 2007. This revolutionized smartphones."
    }
]

# Initialize reasoner
reasoner = CrossDocumentReasoner()

# Link entities across documents
entity_links = await reasoner.link_entities(documents)

print("Entity links found:")
for entity, mentions in entity_links.items():
    print(f"\\n{entity}:")
    for mention in mentions:
        print(f"  - Doc {mention['doc_id']}: {mention['context']}")

# Results show:
# - "Apple Inc." and "Apple Computer" and "Apple" are linked
# - "Steve Jobs" and "Jobs" are linked
# - Ambiguous mentions are resolved using context
    '''
    
    print(example_code)


async def demo_relationship_discovery():
    """Discover relationships across documents."""
    print("\n" + "="*70)
    print("DEMO 2: Cross-Document Relationship Discovery")
    print("="*70)
    
    print("\n🕸️  Relationship Discovery")
    print("   Find connections between entities across documents")
    
    example_code = '''
from ipfs_datasets_py.search import CrossDocumentReasoner

reasoner = CrossDocumentReasoner()

# Discover relationships
relationships = await reasoner.discover_relationships(
    documents=documents,
    min_confidence=0.7
)

print("Discovered relationships:")
for rel in relationships:
    print(f"\\n{rel['source']} --[{rel['type']}]--> {rel['target']}")
    print(f"  Confidence: {rel['confidence']:.2f}")
    print(f"  Supporting documents: {', '.join(rel['doc_ids'])}")
    print(f"  Evidence:")
    for evidence in rel['evidence']:
        print(f"    - {evidence}")

# Example output:
# Steve Jobs --[founded]--> Apple Inc.
#   Confidence: 0.95
#   Supporting documents: doc1, doc2
#   Evidence:
#     - "was founded by Steve Jobs"
#     - "co-founded Apple Computer with"
    '''
    
    print(example_code)


async def demo_temporal_analysis():
    """Analyze temporal relationships across documents."""
    print("\n" + "="*70)
    print("DEMO 3: Temporal Analysis")
    print("="*70)
    
    print("\n⏱️  Temporal Analysis")
    print("   Construct timelines from multiple documents")
    
    example_code = '''
from ipfs_datasets_py.search import TemporalReasoner

temporal = TemporalReasoner()

# Extract temporal events
events = await temporal.extract_events(documents)

# Build timeline
timeline = await temporal.build_timeline(
    events=events,
    resolve_conflicts=True
)

print("Timeline:")
for year, events_list in sorted(timeline.items()):
    print(f"\\n{year}:")
    for event in events_list:
        print(f"  - {event['description']}")
        print(f"    Source: Doc {event['doc_id']}")
        print(f"    Confidence: {event['confidence']:.2f}")

# Detect conflicts
conflicts = await temporal.find_conflicts(events)
if conflicts:
    print("\\nTemporal conflicts detected:")
    for conflict in conflicts:
        print(f"  - {conflict['description']}")
        print(f"    Conflicting events:")
        for event in conflict['events']:
            print(f"      {event['time']}: {event['description']}")
    '''
    
    print(example_code)


async def demo_multi_document_qa():
    """Answer questions using multiple documents."""
    print("\n" + "="*70)
    print("DEMO 4: Multi-Document Question Answering")
    print("="*70)
    
    print("\n❓ Multi-Document QA")
    print("   Answer questions requiring information from multiple docs")
    
    example_code = '''
from ipfs_datasets_py.search import MultiDocumentQA

qa = MultiDocumentQA(
    documents=documents,
    max_context_docs=3
)

# Questions requiring multi-document reasoning
questions = [
    "When was Apple founded and by whom?",
    "What revolutionary product did Apple introduce in 2007?",
    "Who left Apple in 1985?",
]

for question in questions:
    answer = await qa.answer(
        question=question,
        return_sources=True
    )
    
    print(f"\\nQ: {question}")
    print(f"A: {answer['answer']}")
    print(f"Confidence: {answer['confidence']:.2f}")
    print(f"Sources:")
    for source in answer['sources']:
        print(f"  - Doc {source['doc_id']}: {source['excerpt']}")
    '''
    
    print(example_code)


async def demo_contradiction_detection():
    """Detect contradictions across documents."""
    print("\n" + "="*70)
    print("DEMO 5: Contradiction Detection")
    print("="*70)
    
    print("\n⚠️  Contradiction Detection")
    print("   Find conflicting information across documents")
    
    example_code = '''
from ipfs_datasets_py.search import ContradictionDetector

detector = ContradictionDetector()

# Add a document with contradictory information
contradictory_doc = {
    "id": "doc4",
    "text": "Apple Inc. was founded in 1977 by Steve Jobs and Bill Gates."
}

all_docs = documents + [contradictory_doc]

# Detect contradictions
contradictions = await detector.find_contradictions(all_docs)

print("Contradictions found:")
for contradiction in contradictions:
    print(f"\\nStatement 1: {contradiction['statement1']}")
    print(f"  From: Doc {contradiction['doc1']}")
    
    print(f"Statement 2: {contradiction['statement2']}")
    print(f"  From: Doc {contradiction['doc2']}")
    
    print(f"Type: {contradiction['type']}")  # temporal, factual, logical
    print(f"Confidence: {contradiction['confidence']:.2f}")

# Resolve contradictions
resolutions = await detector.resolve_contradictions(
    contradictions=contradictions,
    strategy="majority_vote"  # or "source_reliability", "temporal"
)

for resolution in resolutions:
    print(f"\\nResolved: {resolution['correct_statement']}")
    print(f"Reasoning: {resolution['reasoning']}")
    '''
    
    print(example_code)


async def demo_document_clustering():
    """Cluster documents by topic and relationships."""
    print("\n" + "="*70)
    print("DEMO 6: Document Clustering")
    print("="*70)
    
    print("\n📊 Document Clustering")
    print("   Group related documents together")
    
    example_code = '''
from ipfs_datasets_py.search import DocumentClusterer

clusterer = DocumentClusterer(
    method="entity_overlap",  # or "semantic", "hybrid"
    num_clusters=3
)

# Cluster documents
clusters = await clusterer.cluster(documents)

print("Document clusters:")
for i, cluster in enumerate(clusters, 1):
    print(f"\\nCluster {i}: {cluster['label']}")
    print(f"Documents: {len(cluster['doc_ids'])}")
    print(f"Key entities: {', '.join(cluster['key_entities'])}")
    print(f"Key topics: {', '.join(cluster['key_topics'])}")
    
    for doc_id in cluster['doc_ids']:
        print(f"  - {doc_id}")

# Find document similarities
similarities = await clusterer.compute_similarities(documents)

print("\\nMost similar document pairs:")
for pair in similarities[:5]:
    print(f"  {pair['doc1']} <-> {pair['doc2']}: {pair['score']:.2f}")
    '''
    
    print(example_code)


async def demo_information_fusion():
    """Fuse information from multiple sources."""
    print("\n" + "="*70)
    print("DEMO 7: Information Fusion")
    print("="*70)
    
    print("\n🔀 Information Fusion")
    print("   Combine information from multiple documents into coherent view")
    
    example_code = '''
from ipfs_datasets_py.search import InformationFuser

fuser = InformationFuser(
    conflict_resolution="source_reliability",
    confidence_threshold=0.7
)

# Fuse information about an entity
entity = "Apple Inc."
fused_info = await fuser.fuse_entity_information(
    entity=entity,
    documents=documents
)

print(f"Fused information about {entity}:")
print(f"\\nFacts:")
for fact in fused_info['facts']:
    print(f"  - {fact['statement']}")
    print(f"    Confidence: {fact['confidence']:.2f}")
    print(f"    Sources: {', '.join(fact['sources'])}")

print(f"\\nRelationships:")
for rel in fused_info['relationships']:
    print(f"  - {rel['type']}: {rel['target']}")
    print(f"    Confidence: {rel['confidence']:.2f}")

print(f"\\nTimeline:")
for event in fused_info['timeline']:
    print(f"  - {event['year']}: {event['description']}")

# Generate summary
summary = await fuser.generate_summary(
    entity=entity,
    max_length=200
)

print(f"\\nSummary:")
print(f"{summary}")
    '''
    
    print(example_code)


def show_tips():
    """Show tips for cross-document reasoning."""
    print("\n" + "="*70)
    print("TIPS FOR CROSS-DOCUMENT REASONING")
    print("="*70)
    
    print("\n1. Entity Linking:")
    print("   - Use string similarity for simple cases")
    print("   - Add context-aware disambiguation")
    print("   - Link to external knowledge bases")
    print("   - Handle acronyms and abbreviations")
    
    print("\n2. Relationship Discovery:")
    print("   - Extract from multiple documents")
    print("   - Use confidence scores")
    print("   - Validate with external sources")
    print("   - Consider temporal aspects")
    
    print("\n3. Contradiction Handling:")
    print("   - Detect early in pipeline")
    print("   - Consider source reliability")
    print("   - Check temporal order")
    print("   - Flag for human review if needed")
    
    print("\n4. Performance:")
    print("   - Process documents in parallel")
    print("   - Cache entity extractions")
    print("   - Use incremental updates")
    print("   - Index for fast lookup")
    
    print("\n5. Quality:")
    print("   - Set confidence thresholds")
    print("   - Validate against ground truth")
    print("   - Human-in-the-loop for critical decisions")
    print("   - Monitor accuracy over time")
    
    print("\n6. Scaling:")
    print("   - Partition by time or topic")
    print("   - Use approximate methods for large collections")
    print("   - Distributed processing")
    print("   - Hierarchical clustering")
    
    print("\n7. Applications:")
    print("   - Research and literature review")
    print("   - Fact-checking and verification")
    print("   - Intelligence analysis")
    print("   - Knowledge base construction")
    
    print("\n8. Next Steps:")
    print("   - See 12_graphrag_basic.py for graph integration")
    print("   - See 15_graphrag_optimization.py for production systems")


async def main():
    """Run all cross-document reasoning demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - CROSS-DOCUMENT REASONING")
    print("="*70)
    
    await demo_entity_linking()
    await demo_relationship_discovery()
    await demo_temporal_analysis()
    await demo_multi_document_qa()
    await demo_contradiction_detection()
    await demo_document_clustering()
    await demo_information_fusion()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ CROSS-DOCUMENT REASONING EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
