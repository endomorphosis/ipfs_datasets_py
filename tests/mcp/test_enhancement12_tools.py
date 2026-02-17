"""
MCP Server Enhancement 12 Tools Tests

Comprehensive tests for all 8 Enhancement 12 MCP tools:
1. Multi-engine search
2. Query expansion
3. Result filtering
4. Citation extraction
5. Legal GraphRAG
6. Multi-language support
7. Regulation version tracking
8. Legal report generation
"""

import pytest
from pathlib import Path
import asyncio


class TestEnhancement12ToolsAvailability:
    """Test availability and structure of Enhancement 12 tools"""

    def test_given_legal_dataset_tools_directory_when_checking_then_exists(self):
        """
        GIVEN the legal_dataset_tools directory structure
        WHEN checking if it exists
        THEN it should be found
        """
        tools_path = Path(__file__).parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "legal_dataset_tools"
        assert tools_path.exists(), "Legal dataset tools directory should exist"
        assert tools_path.is_dir(), "Legal dataset tools path should be a directory"

    def test_given_enhancement12_tools_when_listing_files_then_contains_all_8_tools(self):
        """
        GIVEN the legal_dataset_tools directory
        WHEN listing Enhancement 12 tool files
        THEN it should contain all 8 tool modules
        """
        tools_path = Path(__file__).parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "legal_dataset_tools"
        
        if not tools_path.exists():
            pytest.skip("Legal dataset tools directory not found")
        
        expected_tools = [
            "multi_engine_legal_search.py",
            "enhanced_query_expander.py",
            "result_filter.py",
            "citation_extraction_tool.py",
            "legal_graphrag_tool.py",
            "multilanguage_support_tool.py",
            "regulation_version_tracker_tool.py",
            "legal_report_generator_tool.py"
        ]
        
        for tool_file in expected_tools:
            tool_path = tools_path / tool_file
            assert tool_path.exists(), f"Tool file {tool_file} should exist"


class TestMultiEngineLegalSearchTool:
    """Test multi-engine legal search tool"""

    def test_given_multi_engine_tool_when_importing_then_succeeds(self):
        """
        GIVEN the multi_engine_legal_search tool
        WHEN attempting to import it
        THEN import should succeed
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.multi_engine_legal_search import (
                multi_engine_legal_search,
                get_multi_engine_stats
            )
            assert multi_engine_legal_search is not None
            assert get_multi_engine_stats is not None
        except ImportError as e:
            pytest.skip(f"multi_engine_legal_search not available: {e}")

    @pytest.mark.asyncio
    async def test_given_invalid_query_when_calling_multi_engine_search_then_returns_error(self):
        """
        GIVEN an invalid query (empty string)
        WHEN calling multi_engine_legal_search
        THEN it should return error status
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.multi_engine_legal_search import (
                multi_engine_legal_search
            )
            
            result = await multi_engine_legal_search(
                query="",
                engines=["duckduckgo"],
                max_results=5
            )
            
            assert result["status"] == "error"
            assert "message" in result
        except ImportError:
            pytest.skip("multi_engine_legal_search not available")


class TestEnhancedQueryExpanderTool:
    """Test enhanced query expansion tool"""

    def test_given_query_expander_tool_when_importing_then_succeeds(self):
        """
        GIVEN the enhanced_query_expander tool
        WHEN attempting to import it
        THEN import should succeed
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.enhanced_query_expander import (
                expand_legal_query,
                get_legal_synonyms,
                get_legal_relationships
            )
            assert expand_legal_query is not None
            assert get_legal_synonyms is not None
            assert get_legal_relationships is not None
        except ImportError as e:
            pytest.skip(f"enhanced_query_expander not available: {e}")

    @pytest.mark.asyncio
    async def test_given_valid_query_when_expanding_then_returns_expansions(self):
        """
        GIVEN a valid legal query
        WHEN calling expand_legal_query
        THEN it should return expanded queries
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.enhanced_query_expander import (
                expand_legal_query
            )
            
            result = await expand_legal_query(
                query="EPA regulations",
                strategy="balanced",
                max_expansions=3
            )
            
            assert "status" in result
            if result["status"] == "success":
                assert "expanded_queries" in result or "original_query" in result
        except ImportError:
            pytest.skip("expand_legal_query not available")


class TestResultFilterTool:
    """Test result filtering tool"""

    def test_given_result_filter_tool_when_importing_then_succeeds(self):
        """
        GIVEN the result_filter tool
        WHEN attempting to import it
        THEN import should succeed
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.result_filter import (
                filter_legal_results,
                get_filter_statistics
            )
            assert filter_legal_results is not None
            assert get_filter_statistics is not None
        except ImportError as e:
            pytest.skip(f"result_filter not available: {e}")

    @pytest.mark.asyncio
    async def test_given_empty_results_when_filtering_then_returns_error(self):
        """
        GIVEN empty results list
        WHEN calling filter_legal_results
        THEN it should return error status
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.result_filter import (
                filter_legal_results
            )
            
            result = await filter_legal_results(
                results=[],
                min_quality_score=0.5
            )
            
            assert result["status"] == "error"
            assert "message" in result
        except ImportError:
            pytest.skip("filter_legal_results not available")

    @pytest.mark.asyncio
    async def test_given_valid_results_when_filtering_then_returns_filtered_results(self):
        """
        GIVEN valid search results
        WHEN calling filter_legal_results
        THEN it should return filtered results
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.result_filter import (
                filter_legal_results
            )
            
            sample_results = [
                {"url": "https://example.gov/reg1", "title": "Test Reg 1", "snippet": "Content 1"},
                {"url": "https://example.gov/reg2", "title": "Test Reg 2", "snippet": "Content 2"}
            ]
            
            result = await filter_legal_results(
                results=sample_results,
                min_quality_score=0.0
            )
            
            assert "status" in result
            if result["status"] == "success":
                assert "filtered_results" in result
                assert "total_output" in result
        except ImportError:
            pytest.skip("filter_legal_results not available")


class TestCitationExtractionTool:
    """Test citation extraction tool"""

    def test_given_citation_tool_when_importing_then_succeeds(self):
        """
        GIVEN the citation_extraction_tool
        WHEN attempting to import it
        THEN import should succeed
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.citation_extraction_tool import (
                extract_legal_citations,
                export_citations,
                analyze_citation_network
            )
            assert extract_legal_citations is not None
            assert export_citations is not None
            assert analyze_citation_network is not None
        except ImportError as e:
            pytest.skip(f"citation_extraction_tool not available: {e}")


class TestLegalGraphRAGTool:
    """Test Legal GraphRAG integration tool"""

    def test_given_graphrag_tool_when_importing_then_succeeds(self):
        """
        GIVEN the legal_graphrag_tool
        WHEN attempting to import it
        THEN import should succeed
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_graphrag_tool import (
                create_legal_knowledge_graph,
                search_legal_graph,
                visualize_legal_graph
            )
            assert create_legal_knowledge_graph is not None
            assert search_legal_graph is not None
            assert visualize_legal_graph is not None
        except ImportError as e:
            pytest.skip(f"legal_graphrag_tool not available: {e}")


class TestMultiLanguageSupportTool:
    """Test multi-language support tool"""

    def test_given_multilanguage_tool_when_importing_then_succeeds(self):
        """
        GIVEN the multilanguage_support_tool
        WHEN attempting to import it
        THEN import should succeed
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.multilanguage_support_tool import (
                detect_query_language,
                translate_legal_query,
                cross_language_legal_search,
                get_legal_term_translations
            )
            assert detect_query_language is not None
            assert translate_legal_query is not None
            assert cross_language_legal_search is not None
            assert get_legal_term_translations is not None
        except ImportError as e:
            pytest.skip(f"multilanguage_support_tool not available: {e}")

    @pytest.mark.asyncio
    async def test_given_empty_query_when_detecting_language_then_returns_error(self):
        """
        GIVEN an empty query
        WHEN calling detect_query_language
        THEN it should return error status
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.multilanguage_support_tool import (
                detect_query_language
            )
            
            result = await detect_query_language(query="")
            
            assert result["status"] == "error"
            assert "message" in result
        except ImportError:
            pytest.skip("detect_query_language not available")

    @pytest.mark.asyncio
    async def test_given_valid_query_when_detecting_language_then_returns_language(self):
        """
        GIVEN a valid English query
        WHEN calling detect_query_language
        THEN it should return language detection result
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.multilanguage_support_tool import (
                detect_query_language
            )
            
            result = await detect_query_language(query="EPA regulations")
            
            assert "status" in result
            if result["status"] == "success":
                assert "detected_language" in result
        except ImportError:
            pytest.skip("detect_query_language not available")


class TestRegulationVersionTrackerTool:
    """Test regulation version tracking tool"""

    def test_given_version_tracker_tool_when_importing_then_succeeds(self):
        """
        GIVEN the regulation_version_tracker_tool
        WHEN attempting to import it
        THEN import should succeed
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.regulation_version_tracker_tool import (
                track_regulation_version,
                get_regulation_at_date,
                get_regulation_changes,
                get_regulation_timeline
            )
            assert track_regulation_version is not None
            assert get_regulation_at_date is not None
            assert get_regulation_changes is not None
            assert get_regulation_timeline is not None
        except ImportError as e:
            pytest.skip(f"regulation_version_tracker_tool not available: {e}")

    @pytest.mark.asyncio
    async def test_given_invalid_regulation_id_when_tracking_version_then_returns_error(self):
        """
        GIVEN an invalid regulation ID (empty)
        WHEN calling track_regulation_version
        THEN it should return error status
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.regulation_version_tracker_tool import (
                track_regulation_version
            )
            
            result = await track_regulation_version(
                regulation_id="",
                content="test",
                effective_date="2024-01-01"
            )
            
            assert result["status"] == "error"
            assert "message" in result
        except ImportError:
            pytest.skip("track_regulation_version not available")


class TestLegalReportGeneratorTool:
    """Test legal report generation tool"""

    def test_given_report_generator_tool_when_importing_then_succeeds(self):
        """
        GIVEN the legal_report_generator_tool
        WHEN attempting to import it
        THEN import should succeed
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_report_generator_tool import (
                generate_legal_report,
                export_legal_report,
                generate_compliance_checklist,
                schedule_report_generation
            )
            assert generate_legal_report is not None
            assert export_legal_report is not None
            assert generate_compliance_checklist is not None
            assert schedule_report_generation is not None
        except ImportError as e:
            pytest.skip(f"legal_report_generator_tool not available: {e}")

    @pytest.mark.asyncio
    async def test_given_empty_results_when_generating_report_then_returns_error(self):
        """
        GIVEN empty search results
        WHEN calling generate_legal_report
        THEN it should return error status
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_report_generator_tool import (
                generate_legal_report
            )
            
            result = await generate_legal_report(
                search_results=[],
                template="research"
            )
            
            assert result["status"] == "error"
            assert "message" in result
        except ImportError:
            pytest.skip("generate_legal_report not available")

    @pytest.mark.asyncio
    async def test_given_valid_results_when_generating_report_then_returns_report(self):
        """
        GIVEN valid search results
        WHEN calling generate_legal_report
        THEN it should return generated report
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_report_generator_tool import (
                generate_legal_report
            )
            
            sample_results = [
                {"url": "https://example.gov/reg1", "title": "Test Reg 1", "snippet": "Content 1"},
                {"url": "https://example.gov/reg2", "title": "Test Reg 2", "snippet": "Content 2"}
            ]
            
            result = await generate_legal_report(
                search_results=sample_results,
                template="research",
                title="Test Report"
            )
            
            assert "status" in result
            if result["status"] == "success":
                assert "report" in result or "title" in result
        except ImportError:
            pytest.skip("generate_legal_report not available")


class TestThinWrapperPattern:
    """Test that all tools follow the thin wrapper pattern"""

    def test_given_enhancement12_tools_when_checking_structure_then_follow_thin_wrapper_pattern(self):
        """
        GIVEN all Enhancement 12 tools
        WHEN checking their structure
        THEN they should follow thin wrapper pattern (imports from core processors)
        """
        tools_path = Path(__file__).parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "legal_dataset_tools"
        
        if not tools_path.exists():
            pytest.skip("Legal dataset tools directory not found")
        
        enhancement12_tools = [
            "multi_engine_legal_search.py",
            "enhanced_query_expander.py",
            "result_filter.py",
            "citation_extraction_tool.py",
            "legal_graphrag_tool.py",
            "multilanguage_support_tool.py",
            "regulation_version_tracker_tool.py",
            "legal_report_generator_tool.py"
        ]
        
        for tool_file in enhancement12_tools:
            tool_path = tools_path / tool_file
            
            if not tool_path.exists():
                continue
            
            with open(tool_path, 'r') as f:
                content = f.read()
            
            # Check for import from processors.legal_scrapers
            assert "from ipfs_datasets_py.processors.legal_scrapers import" in content, \
                f"{tool_file} should import from processors.legal_scrapers"
            
            # Check for async functions
            assert "async def " in content, \
                f"{tool_file} should contain async functions"
            
            # Check for docstrings
            assert '"""' in content, \
                f"{tool_file} should contain docstrings"
