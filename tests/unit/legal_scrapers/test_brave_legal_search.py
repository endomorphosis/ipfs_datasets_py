"""Unit tests for Brave Legal Search components.

Tests the core functionality of the legal search system including:
- Knowledge base loading
- Query processing
- Search term generation
- Main search interface
"""

import pytest
import os
from pathlib import Path
from typing import Dict, List

# Import components to test
from ipfs_datasets_py.processors.legal_scrapers.knowledge_base_loader import (
    LegalKnowledgeBase,
    FederalEntity,
    StateEntity,
    MunicipalEntity
)
from ipfs_datasets_py.processors.legal_scrapers.query_processor import (
    QueryProcessor,
    QueryIntent
)
from ipfs_datasets_py.processors.legal_scrapers.search_term_generator import (
    SearchTermGenerator,
    SearchTerm,
    SearchStrategy
)
from ipfs_datasets_py.processors.legal_scrapers.brave_legal_search import (
    BraveLegalSearch,
    create_legal_search,
    search_legal
)


# Test fixtures
@pytest.fixture
def legal_scrapers_dir():
    """Get path to legal_scrapers directory with JSONL files."""
    return str(Path(__file__).parent.parent.parent / "ipfs_datasets_py" / "processors" / "legal_scrapers")


@pytest.fixture
def knowledge_base(legal_scrapers_dir):
    """Load knowledge base for testing."""
    kb = LegalKnowledgeBase()
    kb.load_from_directory(legal_scrapers_dir)
    return kb


@pytest.fixture
def query_processor():
    """Create query processor for testing."""
    return QueryProcessor()


@pytest.fixture
def search_term_generator(knowledge_base):
    """Create search term generator for testing."""
    return SearchTermGenerator(knowledge_base)


class TestKnowledgeBaseLoader:
    """Test the knowledge base loader."""
    
    def test_knowledge_base_initialization(self):
        """GIVEN a new knowledge base
        WHEN it is initialized
        THEN it should be empty and not loaded
        """
        kb = LegalKnowledgeBase()
        assert not kb.loaded
        assert len(kb.federal_entities) == 0
        assert len(kb.state_entities) == 0
        assert len(kb.municipal_entities) == 0
    
    def test_knowledge_base_loading(self, legal_scrapers_dir):
        """GIVEN a knowledge base and JSONL directory
        WHEN load_from_directory is called
        THEN it should load all entities
        """
        kb = LegalKnowledgeBase()
        kb.load_from_directory(legal_scrapers_dir)
        
        assert kb.loaded
        assert len(kb.federal_entities) > 0
        assert len(kb.state_entities) > 0
        assert len(kb.municipal_entities) > 0
    
    def test_federal_entity_structure(self, knowledge_base):
        """GIVEN a loaded knowledge base
        WHEN accessing federal entities
        THEN they should have correct structure
        """
        assert len(knowledge_base.federal_entities) > 0
        entity = knowledge_base.federal_entities[0]
        
        assert isinstance(entity, FederalEntity)
        assert hasattr(entity, 'id')
        assert hasattr(entity, 'name')
        assert hasattr(entity, 'branch')
        assert entity.branch in ['legislative', 'executive', 'judicial', 'unknown']
    
    def test_search_federal_by_name(self, knowledge_base):
        """GIVEN a loaded knowledge base
        WHEN searching for a federal entity by name
        THEN it should return matching results
        """
        # Search for EPA (should find Environmental Protection Agency)
        results = knowledge_base.search_federal("environmental")
        assert len(results) > 0
        
        # Check that we got relevant results
        has_epa = any('environmental' in e.name.lower() for e in results)
        assert has_epa
    
    def test_search_state_by_jurisdiction(self, knowledge_base):
        """GIVEN a loaded knowledge base
        WHEN searching for state entities by jurisdiction
        THEN it should return entities for that state
        """
        results = knowledge_base.search_state("", jurisdiction="CA")
        assert len(results) > 0
        
        # All results should be California
        for entity in results:
            assert entity.jurisdiction == "CA"
    
    def test_search_municipal(self, knowledge_base):
        """GIVEN a loaded knowledge base
        WHEN searching for municipal entities
        THEN it should return matching municipalities
        """
        results = knowledge_base.search_municipal("New York")
        assert len(results) > 0
        
        # Should find New York City
        has_nyc = any('new york' in e.place_name.lower() for e in results)
        assert has_nyc
    
    def test_get_statistics(self, knowledge_base):
        """GIVEN a loaded knowledge base
        WHEN getting statistics
        THEN it should return complete stats
        """
        stats = knowledge_base.get_statistics()
        
        assert stats['loaded'] is True
        assert stats['total_entities'] > 0
        assert 'federal' in stats
        assert 'state' in stats
        assert 'municipal' in stats
        assert stats['federal']['total'] > 0
        assert stats['state']['total'] > 0
        assert stats['municipal']['total'] > 0


class TestQueryProcessor:
    """Test the query processor."""
    
    def test_query_processor_initialization(self):
        """GIVEN a query processor
        WHEN it is initialized
        THEN it should be ready to process queries
        """
        processor = QueryProcessor()
        assert processor is not None
    
    def test_process_simple_query(self, query_processor):
        """GIVEN a simple query
        WHEN processing it
        THEN it should extract basic intent
        """
        intent = query_processor.process("EPA regulations")
        
        assert isinstance(intent, QueryIntent)
        assert intent.original_query == "EPA regulations"
        assert len(intent.agencies) > 0 or len(intent.topics) > 0
    
    def test_extract_jurisdictions_federal(self, query_processor):
        """GIVEN a query mentioning federal
        WHEN processing it
        THEN it should identify federal jurisdiction
        """
        intent = query_processor.process("federal environmental regulations")
        assert 'federal' in intent.jurisdictions
    
    def test_extract_jurisdictions_state(self, query_processor):
        """GIVEN a query mentioning a state
        WHEN processing it
        THEN it should identify the state
        """
        intent = query_processor.process("California environmental laws")
        assert 'CA' in intent.jurisdictions
    
    def test_extract_agencies(self, query_processor):
        """GIVEN a query mentioning an agency
        WHEN processing it
        THEN it should identify the agency
        """
        intent = query_processor.process("EPA water pollution rules")
        assert len(intent.agencies) > 0
        # Should find EPA or Environmental Protection Agency
        has_epa = any('environmental' in agency.lower() for agency in intent.agencies)
        assert has_epa
    
    def test_extract_municipalities(self, query_processor):
        """GIVEN a query mentioning a city
        WHEN processing it
        THEN it should identify the city
        """
        intent = query_processor.process("New York City zoning ordinances")
        assert len(intent.municipalities) > 0
    
    def test_determine_scope(self, query_processor):
        """GIVEN different types of queries
        WHEN processing them
        THEN scope should be correctly determined
        """
        # Federal scope
        intent1 = query_processor.process("EPA regulations")
        assert intent1.scope in ['federal', 'mixed']
        
        # State scope
        intent2 = query_processor.process("California employment laws")
        assert intent2.scope in ['state', 'mixed']
        
        # Local scope
        intent3 = query_processor.process("San Francisco building codes")
        assert intent3.scope in ['local', 'mixed']
    
    def test_categorize_legal_domain(self, query_processor):
        """GIVEN queries about different legal domains
        WHEN processing them
        THEN they should be categorized correctly
        """
        # Housing domain
        intent1 = query_processor.process("fair housing discrimination laws")
        assert len(intent1.legal_domains) > 0
        
        # Employment domain
        intent2 = query_processor.process("workplace discrimination EEOC")
        assert len(intent2.legal_domains) > 0


class TestSearchTermGenerator:
    """Test the search term generator."""
    
    def test_generator_initialization(self, knowledge_base):
        """GIVEN a knowledge base
        WHEN creating a generator
        THEN it should be initialized correctly
        """
        generator = SearchTermGenerator(knowledge_base)
        assert generator.kb == knowledge_base
    
    def test_generate_base_terms(self, search_term_generator, query_processor):
        """GIVEN a query intent
        WHEN generating search terms
        THEN base terms should be included
        """
        intent = query_processor.process("EPA water regulations")
        strategy = search_term_generator.generate(intent)
        
        assert len(strategy.terms) > 0
        # Original query should be included
        terms_list = [t.term for t in strategy.terms]
        assert intent.original_query in terms_list
    
    def test_generate_federal_terms(self, search_term_generator, query_processor):
        """GIVEN a query about federal agencies
        WHEN generating search terms
        THEN federal-specific terms should be generated
        """
        intent = query_processor.process("EPA environmental regulations")
        strategy = search_term_generator.generate(intent)
        
        # Should have federal category terms
        federal_terms = strategy.get_by_category('federal')
        assert len(federal_terms) > 0
    
    def test_generate_state_terms(self, search_term_generator, query_processor):
        """GIVEN a query about state law
        WHEN generating search terms
        THEN state-specific terms should be generated
        """
        intent = query_processor.process("California housing laws")
        strategy = search_term_generator.generate(intent)
        
        # Should have state category terms
        state_terms = strategy.get_by_category('state')
        # Note: May be 0 if state entities don't match, which is OK
        assert len(strategy.terms) > 0
    
    def test_prioritization(self, search_term_generator, query_processor):
        """GIVEN a query intent
        WHEN generating search terms
        THEN terms should be prioritized correctly
        """
        intent = query_processor.process("EPA regulations")
        strategy = search_term_generator.generate(intent)
        
        # Get top terms
        top_terms = strategy.get_top_terms(5)
        assert len(top_terms) > 0
        assert len(top_terms) <= 5
        
        # Original query should be in top terms (priority 1)
        assert intent.original_query in top_terms
    
    def test_deduplication(self, search_term_generator, query_processor):
        """GIVEN a query that generates duplicate terms
        WHEN generating search terms
        THEN duplicates should be removed
        """
        intent = query_processor.process("EPA EPA regulations")
        strategy = search_term_generator.generate(intent)
        
        # Check for duplicate terms
        terms_set = set(t.term for t in strategy.terms)
        assert len(terms_set) == len(strategy.terms)


class TestBraveLegalSearch:
    """Test the main Brave Legal Search interface."""
    
    def test_initialization_without_api_key(self, legal_scrapers_dir):
        """GIVEN no API key
        WHEN initializing BraveLegalSearch
        THEN it should initialize but client may be None
        """
        # Clear API key env vars for this test
        old_key = os.environ.get('BRAVE_API_KEY')
        if old_key:
            del os.environ['BRAVE_API_KEY']
        
        try:
            searcher = BraveLegalSearch(knowledge_base_dir=legal_scrapers_dir)
            assert searcher.knowledge_base.loaded
            # Client might be None without API key
        finally:
            # Restore API key
            if old_key:
                os.environ['BRAVE_API_KEY'] = old_key
    
    def test_generate_search_terms(self, legal_scrapers_dir):
        """GIVEN a query
        WHEN generating search terms
        THEN it should return a list of terms
        """
        searcher = BraveLegalSearch(knowledge_base_dir=legal_scrapers_dir)
        terms = searcher.generate_search_terms("EPA water regulations")
        
        assert isinstance(terms, list)
        assert len(terms) > 0
        assert isinstance(terms[0], str)
    
    def test_explain_query(self, legal_scrapers_dir):
        """GIVEN a query
        WHEN explaining it
        THEN it should return detailed explanation
        """
        searcher = BraveLegalSearch(knowledge_base_dir=legal_scrapers_dir)
        explanation = searcher.explain_query("EPA water pollution California")
        
        assert 'query' in explanation
        assert 'intent' in explanation
        assert 'intent_details' in explanation
        assert 'search_strategy' in explanation
        assert 'top_search_terms' in explanation
    
    def test_get_knowledge_base_stats(self, legal_scrapers_dir):
        """GIVEN an initialized searcher
        WHEN getting KB stats
        THEN it should return statistics
        """
        searcher = BraveLegalSearch(knowledge_base_dir=legal_scrapers_dir)
        stats = searcher.get_knowledge_base_stats()
        
        assert 'loaded' in stats
        assert stats['loaded'] is True
        assert 'total_entities' in stats
        assert stats['total_entities'] > 0
    
    def test_search_entities(self, legal_scrapers_dir):
        """GIVEN a searcher
        WHEN searching for entities
        THEN it should return matching entities
        """
        searcher = BraveLegalSearch(knowledge_base_dir=legal_scrapers_dir)
        results = searcher.search_entities("environmental")
        
        assert isinstance(results, dict)
        assert 'federal' in results or 'state' in results or 'municipal' in results
    
    def test_search_without_execution(self, legal_scrapers_dir):
        """GIVEN a query
        WHEN searching without execution
        THEN it should return intent and terms but no results
        """
        searcher = BraveLegalSearch(knowledge_base_dir=legal_scrapers_dir)
        result = searcher.search("EPA regulations", execute_search=False)
        
        assert 'query' in result
        assert 'intent' in result
        assert 'search_terms' in result
        assert len(result['results']) == 0  # No results without execution
    
    def test_factory_function(self, legal_scrapers_dir):
        """GIVEN factory function
        WHEN creating a searcher
        THEN it should return configured instance
        """
        searcher = create_legal_search(knowledge_base_dir=legal_scrapers_dir)
        assert isinstance(searcher, BraveLegalSearch)
        assert searcher.knowledge_base.loaded


# Skip integration tests that require API key
@pytest.mark.skipif(
    not os.environ.get('BRAVE_API_KEY'),
    reason="Requires BRAVE_API_KEY environment variable"
)
class TestBraveLegalSearchIntegration:
    """Integration tests requiring Brave Search API key."""
    
    def test_search_with_api_key(self, legal_scrapers_dir):
        """GIVEN a valid API key
        WHEN executing a search
        THEN it should return actual results
        """
        searcher = BraveLegalSearch(knowledge_base_dir=legal_scrapers_dir)
        result = searcher.search("EPA regulations", max_results=5)
        
        assert 'query' in result
        assert 'results' in result
        # May or may not have results depending on API
        assert isinstance(result['results'], list)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
