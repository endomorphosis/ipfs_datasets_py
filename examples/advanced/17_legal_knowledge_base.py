"""
Legal Knowledge Base - Complete Legal Research System

This example demonstrates a production-ready legal research system combining
knowledge bases, web scraping, search engines, GraphRAG, and multi-language
support for comprehensive legal research.

Requirements:
    - beautifulsoup4, lxml: pip install beautifulsoup4 lxml
    - transformers, torch: pip install transformers torch
    - Optional: BRAVE_API_KEY environment variable

Usage:
    python examples/advanced/17_legal_knowledge_base.py
"""

import asyncio


async def demo_knowledge_base_search():
    """Search the legal entity knowledge base."""
    print("\n" + "="*70)
    print("DEMO 1: Legal Knowledge Base Search")
    print("="*70)
    
    print("\n📚 Knowledge Base (21,334 Entities)")
    print("   Search federal, state, and municipal entities")
    
    example_code = '''
from ipfs_datasets_py.processors.legal_scrapers import (
    KnowledgeBaseLoader,
    BraveLegalSearch
)

# Load knowledge base
kb_loader = KnowledgeBaseLoader()

# 935 federal entities (all branches)
federal = await kb_loader.load_federal_all_branches()
print(f"Federal entities: {len(federal)}")

# 13,256 state agencies (all 50 states)
state = await kb_loader.load_state_agencies()
print(f"State agencies: {len(state)}")

# 7,143 municipal entities
municipal = await kb_loader.load_municipal_entities()
print(f"Municipal entities: {len(municipal)}")

# Search knowledge base
results = await kb_loader.search(
    query="environmental protection",
    jurisdiction="federal",
    entity_types=["agency", "department"]
)

print(f"\\nSearch results:")
for entity in results:
    print(f"  {entity['name']}")
    print(f"  Type: {entity['type']}")
    print(f"  URL: {entity.get('url', 'N/A')}")
    print(f"  Jurisdiction: {entity['jurisdiction']}")
    '''
    
    print(example_code)


async def demo_natural_language_query():
    """Process natural language legal queries."""
    print("\n" + "="*70)
    print("DEMO 2: Natural Language Query Processing")
    print("="*70)
    
    print("\n🗣️  Natural Language Processing")
    print("   Convert plain English to structured searches")
    
    example_code = '''
from ipfs_datasets_py.processors.legal_scrapers import (
    QueryProcessor,
    BraveLegalSearch
)

processor = QueryProcessor()

# Natural language queries
queries = [
    "I want to file a complaint about workplace discrimination",
    "Need information on California environmental regulations",
    "How do I report municipal corruption in Chicago?"
]

for query in queries:
    print(f"\\nQuery: {query}")
    
    # Process query
    intent = await processor.process(query)
    
    print(f"  Detected complaint type: {intent.complaint_type}")
    print(f"  Jurisdiction: {intent.jurisdiction}")
    print(f"  Agency pattern: {intent.agency_pattern}")
    print(f"  Entities: {', '.join(intent.entities[:3])}")
    print(f"  Domains: {', '.join(intent.relevant_domains[:3])}")
    
    # Generate search terms
    terms = await intent.generate_search_terms()
    print(f"  Search terms: {', '.join(terms[:5])}")

# 14 supported complaint types:
complaint_types = [
    "employment_discrimination", "wage_theft", "workplace_safety",
    "consumer_fraud", "housing_discrimination", "environmental_violation",
    "civil_rights_violation", "healthcare_fraud", "tax_fraud",
    "securities_fraud", "antitrust_violation", "privacy_violation",
    "accessibility_violation", "general_complaint"
]
    '''
    
    print(example_code)


async def demo_multi_engine_search():
    """Search using multiple engines."""
    print("\n" + "="*70)
    print("DEMO 3: Multi-Engine Legal Search")
    print("="*70)
    
    print("\n🔍 Multi-Engine Search")
    print("   Brave, DuckDuckGo, Google CSE with fallback")
    
    example_code = '''
from ipfs_datasets_py.processors.legal_scrapers import MultiEngineLegalSearch

# Setup multi-engine search
search = MultiEngineLegalSearch(
    engines=["brave", "duckduckgo", "google_cse"],
    parallel_enabled=True,
    fallback_enabled=True
)

# Search with fallback
query = "OSHA workplace safety violations"
results = await search.search(
    query=query,
    max_results=20,
    filter_gov=True  # Only .gov domains
)

print(f"Search results: {len(results)}")
print(f"Engines used: {', '.join(results.engines_used)}")

# Results by engine
for engine, count in results.engine_counts.items():
    print(f"  {engine}: {count} results")

# Top results
for result in results.results[:5]:
    print(f"\\n  {result.title}")
    print(f"  URL: {result.url}")
    print(f"  Source: {result.engine}")
    print(f"  Snippet: {result.snippet[:100]}...")

# Performance
print(f"\\nSearch performance:")
print(f"  Total time: {results.search_time_ms}ms")
print(f"  Cache hits: {results.cache_hits}")
    '''
    
    print(example_code)


async def demo_web_archiving():
    """Archive and search historical legal content."""
    print("\n" + "="*70)
    print("DEMO 4: Web Archiving & Historical Search")
    print("="*70)
    
    print("\n🗄️  Web Archiving")
    print("   Common Crawl, Wayback Machine, parallel retrieval")
    
    example_code = '''
from ipfs_datasets_py.processors.legal_scrapers import (
    LegalWebArchiveSearch,
    ParallelWebArchiver
)

archive_search = LegalWebArchiveSearch()

# Search current + archived content
query = "FDA drug approval regulations"
results = await archive_search.unified_search(
    query=query,
    search_archives=True,
    max_results=10
)

print(f"Total results: {len(results)}")
print(f"Current content: {results.current_count}")
print(f"Archived content: {results.archived_count}")

# Results with dates
for result in results.results[:5]:
    print(f"\\n  {result.title}")
    print(f"  Date: {result.date or 'Current'}")
    print(f"  Source: {result.source}")  # current, wayback, common_crawl

# Archive URLs for future reference
urls = [result.url for result in results.results[:10]]
archiver = ParallelWebArchiver(max_workers=5)

archived = await archiver.archive_urls(
    urls=urls,
    methods=["common_crawl", "wayback", "web_archive"]
)

print(f"\\nArchived {len(archived)} URLs")
for url, archive_info in archived.items():
    print(f"  {url}")
    print(f"  Methods: {', '.join(archive_info.methods)}")
    '''
    
    print(example_code)


async def demo_legal_graphrag():
    """Use GraphRAG for legal research."""
    print("\n" + "="*70)
    print("DEMO 5: Legal GraphRAG")
    print("="*70)
    
    print("\n🕸️  Legal GraphRAG")
    print("   Entity extraction and relationship mapping")
    
    example_code = '''
from ipfs_datasets_py.processors.legal_scrapers import LegalGraphRAG

graphrag = LegalGraphRAG()

# Build knowledge graph from search results
query = "FTC antitrust enforcement actions"
results = await search.search(query, max_results=20)

# Extract entities and relationships
graph = await graphrag.build_graph_from_results(
    results=results,
    extract_entities=True,
    extract_relationships=True
)

print(f"Knowledge graph:")
print(f"  Entities: {len(graph.entities)}")
print(f"  Relationships: {len(graph.relationships)}")

# Entity types
entity_counts = graph.count_by_type()
for entity_type, count in entity_counts.items():
    print(f"  {entity_type}: {count}")

# Find entity relationships
entity = "Federal Trade Commission"
related = await graphrag.find_related_entities(
    entity=entity,
    relationship_types=["enforces", "regulates", "investigates"],
    max_hops=2
)

print(f"\\nEntities related to {entity}:")
for rel in related:
    print(f"  {rel.target_entity} ({rel.relationship_type})")
    print(f"  Evidence: {rel.evidence_count} sources")

# Subgraph extraction
subgraph = await graphrag.extract_subgraph(
    center_entity=entity,
    radius=2,
    min_edge_weight=0.5
)

# Visualize
await graphrag.visualize_subgraph(
    subgraph=subgraph,
    output_file="ftc_enforcement_graph.html"
)
    '''
    
    print(example_code)


async def demo_citation_extraction():
    """Extract and rank legal citations."""
    print("\n" + "="*70)
    print("DEMO 6: Citation Extraction & Ranking")
    print("="*70)
    
    print("\n📖 Citation Extraction")
    print("   Identify and rank legal citations")
    
    example_code = '''
from ipfs_datasets_py.processors.legal_scrapers import (
    SearchResultCitationExtractor
)

extractor = SearchResultCitationExtractor()

# Extract citations from search results
results = await search.search("Supreme Court precedents", max_results=10)

citations = await extractor.extract_citations(
    results=results,
    citation_types=["case_law", "statute", "regulation", "treaty"]
)

print(f"Extracted citations: {len(citations)}")

# Citations by type
for citation_type, count in citations.type_counts.items():
    print(f"  {citation_type}: {count}")

# Ranked citations
ranked = await extractor.rank_citations(
    citations=citations,
    ranking_method="authority"  # authority, frequency, or recency
)

print("\\nTop citations:")
for i, citation in enumerate(ranked[:10], 1):
    print(f"  {i}. {citation.full_citation}")
    print(f"     Type: {citation.type}")
    print(f"     Authority score: {citation.authority_score:.2f}")
    print(f"     Mentioned in: {citation.source_count} sources")

# Build citation network
network = await extractor.build_citation_network(citations)

print(f"\\nCitation network:")
print(f"  Nodes: {len(network.nodes)}")
print(f"  Edges: {len(network.edges)}")
print(f"  Clusters: {len(network.clusters)}")

# Export
await network.export("citations.json", format="json")
await network.export("citations.graphml", format="graphml")
    '''
    
    print(example_code)


async def demo_multi_language_support():
    """Search and translate international regulations."""
    print("\n" + "="*70)
    print("DEMO 7: Multi-Language Support")
    print("="*70)
    
    print("\n🌍 Multi-Language")
    print("   Search in English, Spanish, French, German, Chinese")
    
    example_code = '''
from ipfs_datasets_py.processors.legal_scrapers import MultiLanguageLegalSearch

ml_search = MultiLanguageLegalSearch(
    supported_languages=["en", "es", "fr", "de", "zh"]
)

# Search in Spanish
query_es = "regulaciones de privacidad de datos"
results = await ml_search.search(
    query=query_es,
    source_language="es",
    translate_results=True,
    target_language="en"
)

print(f"Spanish query results: {len(results)}")
for result in results[:3]:
    print(f"\\n  Original: {result.original_title}")
    print(f"  Translated: {result.translated_title}")
    print(f"  Language: {result.language}")
    print(f"  Translation confidence: {result.translation_confidence:.2f}")

# Multi-language knowledge base
kb_multilang = await ml_search.load_multilingual_kb(
    languages=["en", "es", "fr"]
)

print(f"\\nMultilingual knowledge base:")
for lang, entities in kb_multilang.items():
    print(f"  {lang}: {len(entities)} entities")

# Detect language
detected = await ml_search.detect_language(
    "Règlement général sur la protection des données"
)
print(f"\\nDetected language: {detected}")  # fr (French)
    '''
    
    print(example_code)


async def demo_complete_workflow():
    """Complete legal research workflow."""
    print("\n" + "="*70)
    print("DEMO 8: Complete Research Workflow")
    print("="*70)
    
    print("\n🔄 Complete Workflow")
    print("   End-to-end legal research pipeline")
    
    example_code = '''
from ipfs_datasets_py.processors.legal_scrapers import LegalResearchWorkflow

workflow = LegalResearchWorkflow()

# Define research query
research_query = """
Research federal and state regulations on data privacy,
focusing on California and New York laws, with comparison
to GDPR requirements. Include recent enforcement actions.
"""

# Execute complete workflow
report = await workflow.execute(
    query=research_query,
    steps=[
        "process_query",       # NLP processing
        "search_kb",           # Knowledge base search
        "multi_engine_search", # Web search
        "extract_entities",    # Entity extraction
        "build_graph",         # Knowledge graph
        "extract_citations",   # Citation extraction
        "archive_sources",     # Archive URLs
        "generate_report"      # Final report
    ],
    output_format="markdown"
)

print(f"Research Report Generated:")
print(f"  Query: {report.query}")
print(f"  Sources: {len(report.sources)}")
print(f"  Entities: {len(report.entities)}")
print(f"  Citations: {len(report.citations)}")
print(f"  Archived URLs: {len(report.archived_urls)}")

# Save report
await report.save("legal_research_report.md")
await report.save("legal_research_report.pdf", format="pdf")

# Report includes:
# - Executive summary
# - Key findings
# - Entity relationship diagram
# - Citation network
# - Full source list
# - Archived URL references
    '''
    
    print(example_code)


def show_tips():
    """Show tips for legal research."""
    print("\n" + "="*70)
    print("TIPS FOR LEGAL RESEARCH SYSTEM")
    print("="*70)
    
    print("\n1. Knowledge Base:")
    print("   - 21,334 entities (federal, state, municipal)")
    print("   - Update regularly from official sources")
    print("   - Validate entity URLs periodically")
    print("   - Track organizational changes")
    
    print("\n2. Query Processing:")
    print("   - 14 complaint types supported")
    print("   - Use natural language for best results")
    print("   - Include jurisdiction when known")
    print("   - Specify entity types if relevant")
    
    print("\n3. Search Strategy:")
    print("   - Start with Brave (fast, good gov focus)")
    print("   - Use DuckDuckGo as fallback (no API key)")
    print("   - Enable Google CSE for comprehensive results")
    print("   - Filter to .gov domains for official sources")
    
    print("\n4. Web Archiving:")
    print("   - Archive important URLs immediately")
    print("   - Use parallel archiving for speed (10-25x)")
    print("   - Check multiple archives (Common Crawl, Wayback)")
    print("   - Store WARC pointers for large datasets")
    
    print("\n5. GraphRAG:")
    print("   - Build graphs incrementally")
    print("   - Track entity relationships over time")
    print("   - Use for discovering hidden connections")
    print("   - Visualize for presentations")
    
    print("\n6. Citations:")
    print("   - Extract early in workflow")
    print("   - Rank by authority and recency")
    print("   - Build citation networks")
    print("   - Export in standard formats")
    
    print("\n7. Multi-Language:")
    print("   - 5 languages supported (en, es, fr, de, zh)")
    print("   - Auto-detect query language")
    print("   - Translate results as needed")
    print("   - Verify translations with native speakers")
    
    print("\n8. Production Deployment:")
    print("   - Cache search results (configurable TTL)")
    print("   - Rate limit API calls")
    print("   - Monitor for API changes")
    print("   - Backup knowledge base regularly")
    
    print("\n9. Legal Considerations:")
    print("   - Verify information with official sources")
    print("   - Include disclaimers in reports")
    print("   - Respect copyright and terms of service")
    print("   - Consult legal professionals for advice")
    
    print("\n10. Next Steps:")
    print("    - See 10_legal_data_scraping.py for basics")
    print("    - See 11_web_archiving.py for archiving details")


async def main():
    """Run all legal knowledge base demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - LEGAL KNOWLEDGE BASE")
    print("="*70)
    
    await demo_knowledge_base_search()
    await demo_natural_language_query()
    await demo_multi_engine_search()
    await demo_web_archiving()
    await demo_legal_graphrag()
    await demo_citation_extraction()
    await demo_multi_language_support()
    await demo_complete_workflow()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ LEGAL KNOWLEDGE BASE EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
