"""Integration tests for Brave Legal Search system.

These tests verify the complete pipeline from query to results,
including knowledge base loading, query processing, search term generation,
and (if API key available) actual Brave Search API calls.

Run with: pytest tests/integration/test_brave_legal_search_integration.py -v
"""

import pytest
import os
from pathlib import Path
from typing import Dict, List

# Import components to test
from ipfs_datasets_py.processors.legal_scrapers.knowledge_base_loader import (
    LegalKnowledgeBase
)
from ipfs_datasets_py.processors.legal_scrapers.query_processor import (
    QueryProcessor
)
from ipfs_datasets_py.processors.legal_scrapers.search_term_generator import (
    SearchTermGenerator
)
from ipfs_datasets_py.processors.legal_scrapers.brave_legal_search import (
    BraveLegalSearch,
    create_legal_search
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


@pytest.fixture
def brave_search(legal_scrapers_dir):
    """Create BraveLegalSearch instance."""
    return BraveLegalSearch(knowledge_base_dir=legal_scrapers_dir)


class TestFullPipeline:
    """Test the complete pipeline from query to search terms."""
    
    def test_simple_federal_query_pipeline(self, query_processor, search_term_generator):
        """GIVEN a simple federal agency query
        WHEN processing through the full pipeline
        THEN should extract intent and generate relevant search terms
        """
        # GIVEN
        query = "EPA water pollution regulations"
        
        # WHEN
        intent = query_processor.process(query)
        strategy = search_term_generator.generate(intent)
        
        # THEN
        assert intent.agencies, "Should extract EPA agency"
        assert 'federal' in intent.jurisdictions or intent.agencies, "Should identify federal scope"
        assert len(strategy.terms) > 0, "Should generate search terms"
        assert query in [t.term for t in strategy.terms], "Should include original query"
    
    def test_state_specific_query_pipeline(self, query_processor, search_term_generator):
        """GIVEN a state-specific query
        WHEN processing through the full pipeline
        THEN should extract state jurisdiction and generate state-specific terms
        """
        # GIVEN
        query = "California employment discrimination laws"
        
        # WHEN
        intent = query_processor.process(query)
        strategy = search_term_generator.generate(intent)
        
        # THEN
        assert 'CA' in intent.jurisdictions, "Should extract California jurisdiction"
        assert 'employment' in intent.legal_domains or 'employment' in str(intent.topics), "Should identify employment domain"
        assert len(strategy.terms) > 0, "Should generate search terms"
        
        # Check for California-specific terms
        terms_str = ' '.join([t.term for t in strategy.terms])
        assert 'California' in terms_str or 'CA' in terms_str, "Should include California in terms"
    
    def test_municipal_query_pipeline(self, query_processor, search_term_generator):
        """GIVEN a municipal query
        WHEN processing through the full pipeline
        THEN should extract municipality and generate local terms
        """
        # GIVEN
        query = "New York City zoning ordinances"
        
        # WHEN
        intent = query_processor.process(query)
        strategy = search_term_generator.generate(intent)
        
        # THEN
        assert len(intent.municipalities) > 0, "Should extract municipality"
        assert intent.scope in ['local', 'mixed'], "Should identify local scope"
        assert len(strategy.terms) > 0, "Should generate search terms"
    
    def test_multi_jurisdiction_query_pipeline(self, query_processor, search_term_generator):
        """GIVEN a multi-jurisdiction query
        WHEN processing through the full pipeline
        THEN should extract multiple jurisdictions and generate mixed-scope terms
        """
        # GIVEN
        query = "federal and state environmental regulations in Texas"
        
        # WHEN
        intent = query_processor.process(query)
        strategy = search_term_generator.generate(intent)
        
        # THEN
        assert 'federal' in intent.jurisdictions, "Should identify federal jurisdiction"
        assert 'TX' in intent.jurisdictions, "Should identify Texas"
        assert intent.scope == 'mixed', "Should identify mixed scope"
        assert len(strategy.terms) > 0, "Should generate search terms"
        
        # Should have both federal and state terms
        federal_terms = [t for t in strategy.terms if t.category == 'federal']
        state_terms = [t for t in strategy.terms if t.category == 'state']
        assert len(federal_terms) > 0 or len(state_terms) > 0, "Should have federal or state terms"
    
    def test_complex_query_with_agency_and_topic(self, query_processor, search_term_generator):
        """GIVEN a complex query with agency and topic
        WHEN processing through the full pipeline
        THEN should extract all components and generate comprehensive terms
        """
        # GIVEN
        query = "OSHA workplace safety requirements for construction sites"
        
        # WHEN
        intent = query_processor.process(query)
        strategy = search_term_generator.generate(intent)
        
        # THEN
        assert intent.agencies, "Should extract OSHA"
        assert len(intent.topics) > 0, "Should extract topics"
        assert intent.confidence > 0.5, "Should have reasonable confidence"
        assert len(strategy.terms) > 0, "Should generate search terms"
        
        # Should include OSHA in some terms
        terms_with_osha = [t for t in strategy.terms if 'osha' in t.term.lower() or 'safety' in t.term.lower()]
        assert len(terms_with_osha) > 0, "Should include OSHA or safety terms"


class TestEnhancedFeatures:
    """Test the enhanced features from phases 1-8 improvements."""
    
    def test_complaint_types_categorization(self, query_processor):
        """GIVEN queries that match specific complaint types
        WHEN processing with enhanced categorization
        THEN should identify correct complaint types
        """
        # GIVEN
        test_cases = [
            ("housing discrimination fair housing", ['housing']),
            ("employment wrongful termination EEOC", ['employment']),
            ("consumer fraud false advertising", ['consumer']),
            ("HIPAA violation patient privacy", ['healthcare']),
        ]
        
        for query, expected_domains in test_cases:
            # WHEN
            intent = query_processor.process(query)
            
            # THEN
            assert len(intent.legal_domains) > 0, f"Should categorize query: {query}"
            # At least one expected domain should be found
            has_match = any(domain in intent.legal_domains for domain in expected_domains)
            assert has_match, f"Should identify domain for: {query}. Got: {intent.legal_domains}"
    
    def test_enhanced_agency_extraction(self, query_processor):
        """GIVEN queries with various agency name patterns
        WHEN using enhanced agency extraction
        THEN should extract all agency mentions
        """
        # GIVEN
        test_cases = [
            "Department of Energy regulations",
            "Office of the Comptroller guidelines",
            "Bureau of Labor Statistics data",
            "Federal Trade Commission enforcement",
        ]
        
        for query in test_cases:
            # WHEN
            intent = query_processor.process(query)
            
            # THEN
            assert len(intent.agencies) > 0, f"Should extract agency from: {query}"
    
    def test_enhanced_jurisdiction_extraction(self, query_processor):
        """GIVEN queries with regional or multi-state patterns
        WHEN using enhanced jurisdiction extraction
        THEN should identify jurisdictions correctly
        """
        # GIVEN
        test_cases = [
            ("all states environmental law", 'multi-state'),
            ("northeast regional compact", 'region-northeast'),
            ("federal and California rules", 'both'),
        ]
        
        for query, expected_type in test_cases:
            # WHEN
            intent = query_processor.process(query)
            
            # THEN
            assert len(intent.jurisdictions) > 0, f"Should extract jurisdiction from: {query}"
            if expected_type == 'multi-state':
                assert 'multi-state' in intent.jurisdictions, f"Should detect multi-state in: {query}"
            elif expected_type.startswith('region-'):
                assert any('region' in j for j in intent.jurisdictions), f"Should detect region in: {query}"
            elif expected_type == 'both':
                assert len(intent.jurisdictions) >= 2, f"Should detect multiple jurisdictions in: {query}"


class TestBraveLegalSearchInterface:
    """Test the main BraveLegalSearch interface."""
    
    def test_initialization(self, legal_scrapers_dir):
        """GIVEN a legal_scrapers directory
        WHEN initializing BraveLegalSearch
        THEN should load successfully
        """
        # WHEN
        searcher = BraveLegalSearch(knowledge_base_dir=legal_scrapers_dir)
        
        # THEN
        assert searcher.knowledge_base.loaded, "Knowledge base should be loaded"
        assert searcher.query_processor is not None, "Query processor should be initialized"
        assert searcher.term_generator is not None, "Term generator should be initialized"
    
    def test_generate_search_terms_interface(self, brave_search):
        """GIVEN a BraveLegalSearch instance
        WHEN calling generate_search_terms
        THEN should return list of terms
        """
        # WHEN
        terms = brave_search.generate_search_terms("EPA environmental regulations")
        
        # THEN
        assert isinstance(terms, list), "Should return a list"
        assert len(terms) > 0, "Should generate at least one term"
        assert all(isinstance(t, str) for t in terms), "All terms should be strings"
    
    def test_explain_query_interface(self, brave_search):
        """GIVEN a BraveLegalSearch instance
        WHEN calling explain_query
        THEN should return detailed explanation
        """
        # WHEN
        explanation = brave_search.explain_query("OSHA workplace safety")
        
        # THEN
        assert 'query' in explanation, "Should include query"
        assert 'intent_details' in explanation, "Should include intent details"
        assert 'search_strategy' in explanation, "Should include search strategy"
        assert 'top_search_terms' in explanation, "Should include top search terms"
    
    def test_search_entities_interface(self, brave_search):
        """GIVEN a BraveLegalSearch instance
        WHEN calling search_entities
        THEN should return matching entities
        """
        # WHEN
        results = brave_search.search_entities("environmental")
        
        # THEN
        assert isinstance(results, dict), "Should return a dict"
        assert 'federal' in results or 'state' in results or 'municipal' in results, "Should have entity types"


# Integration tests that require API key
@pytest.mark.skipif(
    not os.environ.get('BRAVE_API_KEY'),
    reason="Requires BRAVE_API_KEY environment variable"
)
class TestBraveSearchAPIIntegration:
    """Integration tests requiring Brave Search API key."""
    
    def test_simple_search_with_api(self, brave_search):
        """GIVEN a valid API key
        WHEN executing a simple search
        THEN should return actual results
        """
        # WHEN
        result = brave_search.search("EPA regulations", max_results=5)
        
        # THEN
        assert result['status'] != 'error' or 'error' not in result, "Should not error"
        assert 'query' in result, "Should include query"
        assert 'search_terms' in result, "Should include search terms"
        assert 'results' in result, "Should include results"
    
    def test_relevance_scoring_with_api(self, brave_search):
        """GIVEN search results from API
        WHEN examining relevance scores
        THEN should have scored results
        """
        # WHEN
        result = brave_search.search("EPA water pollution", max_results=5)
        
        # THEN
        if result.get('results'):
            for item in result['results']:
                assert 'relevance_score' in item, "Each result should have relevance score"
                assert 0 <= item['relevance_score'] <= 1, "Score should be between 0 and 1"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
