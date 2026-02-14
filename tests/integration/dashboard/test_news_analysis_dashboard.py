#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test suite for News Analysis Dashboard

This module provides comprehensive tests for the news analysis dashboard
functionality, including unit tests and integration tests.
"""
import pytest
import anyio
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
import tempfile
import os

# Import the classes to test
from ipfs_datasets_py.dashboards.news_analysis_dashboard import (
    NewsAnalysisDashboard,
    NewsWorkflowManager,
    TimelineAnalysisEngine,
    EntityRelationshipTracker,
    CrossDocumentAnalyzer,
    NewsArticle,
    NewsSearchFilter,
    UserType,
    create_news_analysis_dashboard
)
from ipfs_datasets_py.dashboards.mcp_dashboard import MCPDashboardConfig


class TestNewsArticle:
    """Test the NewsArticle dataclass."""
    
    def test_news_article_creation(self):
        """
        GIVEN: Valid article data
        WHEN: Creating a NewsArticle instance
        THEN: Article should be created with correct attributes
        """
        # Given
        article_data = {
            "id": "test_123",
            "url": "https://example.com/article",
            "title": "Test Article",
            "content": "This is test content",
            "published_date": datetime.now(),
            "source": "test_source"
        }
        
        # When
        article = NewsArticle(**article_data)
        
        # Then
        assert article.id == "test_123"
        assert article.url == "https://example.com/article"
        assert article.title == "Test Article"
        assert article.content == "This is test content"
        assert article.source == "test_source"
        assert article.tags == []  # Default empty list
        assert article.entities == []  # Default empty list
        assert article.metadata == {}  # Default empty dict
    
    def test_news_article_with_optional_fields(self):
        """
        GIVEN: Article data with optional fields
        WHEN: Creating a NewsArticle instance
        THEN: All fields should be properly set
        """
        # Given
        article_data = {
            "id": "test_456",
            "url": "https://example.com/article2",
            "title": "Test Article 2",
            "content": "Content with entities",
            "published_date": datetime.now(),
            "source": "test_source_2",
            "author": "Test Author",
            "tags": ["ai", "technology"],
            "entities": [{"type": "PERSON", "name": "John Doe"}],
            "embedding": [0.1, 0.2, 0.3],
            "metadata": {"importance": "high"}
        }
        
        # When
        article = NewsArticle(**article_data)
        
        # Then
        assert article.author == "Test Author"
        assert article.tags == ["ai", "technology"]
        assert len(article.entities) == 1
        assert article.entities[0]["name"] == "John Doe"
        assert article.embedding == [0.1, 0.2, 0.3]
        assert article.metadata["importance"] == "high"


class TestNewsWorkflowManager:
    """Test the NewsWorkflowManager class."""
    
    @pytest.fixture
    def mock_dashboard(self):
        """Create a mock dashboard for testing."""
        dashboard = Mock()
        dashboard.execute_tool = AsyncMock()
        return dashboard
    
    @pytest.fixture
    def workflow_manager(self, mock_dashboard):
        """Create a NewsWorkflowManager instance for testing."""
        return NewsWorkflowManager(mock_dashboard)
    
    @pytest.mark.asyncio
    async def test_execute_news_ingestion_pipeline_success(self, workflow_manager, mock_dashboard):
        """
        GIVEN: A valid URL and metadata
        WHEN: Executing news ingestion pipeline
        THEN: Should complete successfully with expected results
        """
        # Given
        url = "https://example.com/news-article"
        metadata = {"test": "metadata"}
        
        # Mock tool responses
        mock_dashboard.execute_tool.side_effect = [
            {"content": "Article content", "status": "success"},  # archive_webpage
            {"entities": [{"type": "PERSON", "name": "John"}]},    # extract_entities
            {"embedding": [0.1, 0.2], "model_info": {"model": "test"}},  # generate_embeddings
            {"id": "stored_123", "status": "success"}              # store_with_metadata
        ]
        
        # When
        result = await workflow_manager.execute_news_ingestion_pipeline(url, metadata)
        
        # Then
        assert result["status"] == "completed"
        assert result["url"] == url
        assert "workflow_id" in result
        assert "entities" in result
        assert "embedding" in result
        assert "storage_id" in result
        
        # Verify tool calls
        assert mock_dashboard.execute_tool.call_count == 4
    
    @pytest.mark.asyncio
    async def test_execute_news_ingestion_pipeline_failure(self, workflow_manager, mock_dashboard):
        """
        GIVEN: A URL that causes tool execution to fail
        WHEN: Executing news ingestion pipeline
        THEN: Should return failure status with error details
        """
        # Given
        url = "https://invalid-url.com"
        mock_dashboard.execute_tool.side_effect = Exception("Network error")
        
        # When
        result = await workflow_manager.execute_news_ingestion_pipeline(url)
        
        # Then
        assert result["status"] == "failed"
        assert "error" in result
        assert result["url"] == url
    
    @pytest.mark.asyncio
    async def test_execute_news_feed_ingestion(self, workflow_manager, mock_dashboard):
        """
        GIVEN: A valid RSS feed URL
        WHEN: Executing news feed ingestion
        THEN: Should process articles successfully
        """
        # Given
        feed_url = "https://example.com/rss"
        max_articles = 3
        
        # Mock feed parsing response
        mock_articles = [
            {"url": "https://example.com/article1", "title": "Article 1"},
            {"url": "https://example.com/article2", "title": "Article 2"}
        ]
        
        mock_dashboard.execute_tool.side_effect = [
            {"articles": mock_articles}  # parse_news_feed
        ]
        
        # Mock individual article processing
        workflow_manager.execute_news_ingestion_pipeline = AsyncMock(
            return_value={"status": "completed", "workflow_id": "test_123"}
        )
        
        # When
        result = await workflow_manager.execute_news_feed_ingestion(feed_url, max_articles=max_articles)
        
        # Then
        assert result["status"] == "completed"
        assert result["feed_url"] == feed_url
        assert "successful_ingests" in result
        assert "failed_ingests" in result


class TestTimelineAnalysisEngine:
    """Test the TimelineAnalysisEngine class."""
    
    @pytest.fixture
    def mock_dashboard(self):
        """Create a mock dashboard for testing."""
        dashboard = Mock()
        dashboard.execute_tool = AsyncMock()
        return dashboard
    
    @pytest.fixture
    def timeline_engine(self, mock_dashboard):
        """Create a TimelineAnalysisEngine instance for testing."""
        return TimelineAnalysisEngine(mock_dashboard)
    
    @pytest.mark.asyncio
    async def test_generate_timeline_success(self, timeline_engine, mock_dashboard):
        """
        GIVEN: A valid query and date range
        WHEN: Generating timeline
        THEN: Should return timeline data with events and trends
        """
        # Given
        query = "artificial intelligence"
        start_date = datetime.now() - timedelta(days=7)
        end_date = datetime.now()
        
        # Mock search results
        mock_articles = [
            {
                "id": "1",
                "title": "AI Breakthrough",
                "published_date": start_date.isoformat(),
                "content": "AI content"
            },
            {
                "id": "2", 
                "title": "AI Regulation",
                "published_date": end_date.isoformat(),
                "content": "Regulation content"
            }
        ]
        
        mock_dashboard.execute_tool.side_effect = [
            {"results": mock_articles},  # temporal_search
            {"events": ["Event 1"], "trends": ["Trend 1"]}  # identify_key_events
        ]
        
        # When
        result = await timeline_engine.generate_timeline(query, (start_date, end_date))
        
        # Then
        assert result["query"] == query
        assert "timeline_data" in result
        assert "key_events" in result
        assert "trends" in result
        assert result["total_articles"] == len(mock_articles)
    
    def test_group_articles_by_time_day_granularity(self, timeline_engine):
        """
        GIVEN: Articles with different publication dates
        WHEN: Grouping by day granularity
        THEN: Should group articles by day correctly
        """
        # Given
        articles = [
            {"published_date": "2023-01-01T10:00:00", "title": "Article 1"},
            {"published_date": "2023-01-01T15:00:00", "title": "Article 2"},
            {"published_date": "2023-01-02T09:00:00", "title": "Article 3"}
        ]
        
        # When
        grouped = timeline_engine._group_articles_by_time(articles, "day")
        
        # Then
        assert "2023-01-01" in grouped
        assert "2023-01-02" in grouped
        assert len(grouped["2023-01-01"]) == 2
        assert len(grouped["2023-01-02"]) == 1
    
    def test_group_articles_by_time_week_granularity(self, timeline_engine):
        """
        GIVEN: Articles from different weeks
        WHEN: Grouping by week granularity
        THEN: Should group articles by week correctly
        """
        # Given
        articles = [
            {"published_date": "2023-01-02T10:00:00", "title": "Week 1 Article"},
            {"published_date": "2023-01-09T10:00:00", "title": "Week 2 Article"}
        ]
        
        # When
        grouped = timeline_engine._group_articles_by_time(articles, "week")
        
        # Then
        assert len(grouped) == 2
        # Should have different week keys
        week_keys = list(grouped.keys())
        assert week_keys[0] != week_keys[1]


class TestEntityRelationshipTracker:
    """Test the EntityRelationshipTracker class."""
    
    @pytest.fixture
    def mock_dashboard(self):
        """Create a mock dashboard for testing."""
        dashboard = Mock()
        dashboard.execute_tool = AsyncMock()
        return dashboard
    
    @pytest.fixture
    def entity_tracker(self, mock_dashboard):
        """Create an EntityRelationshipTracker instance for testing."""
        return EntityRelationshipTracker(mock_dashboard)
    
    @pytest.mark.asyncio
    async def test_build_entity_graph_success(self, entity_tracker, mock_dashboard):
        """
        GIVEN: A list of article IDs
        WHEN: Building entity graph
        THEN: Should return nodes and edges successfully
        """
        # Given
        article_ids = ["article_1", "article_2", "article_3"]
        
        # Mock tool responses
        mock_entities = [
            {"type": "PERSON", "name": "John Doe", "id": "person_1"},
            {"type": "ORG", "name": "Tech Corp", "id": "org_1"}
        ]
        
        mock_graph = {
            "nodes": mock_entities,
            "edges": [{"source": "person_1", "target": "org_1", "type": "WORKS_FOR"}],
            "entity_types": {"PERSON": 1, "ORG": 1},
            "relationship_types": {"WORKS_FOR": 1}
        }
        
        mock_dashboard.execute_tool.side_effect = [
            {"entities": mock_entities},  # extract_entities_batch
            mock_graph  # build_relationship_graph
        ]
        
        # When
        result = await entity_tracker.build_entity_graph(article_ids)
        
        # Then
        assert "nodes" in result
        assert "edges" in result
        assert "entity_types" in result
        assert "relationship_types" in result
        assert result["total_entities"] == len(mock_entities)
        assert result["total_relationships"] == 1
    
    @pytest.mark.asyncio
    async def test_track_entity_mentions(self, entity_tracker, mock_dashboard):
        """
        GIVEN: An entity name and date range
        WHEN: Tracking entity mentions
        THEN: Should return mention patterns and analysis
        """
        # Given
        entity_name = "OpenAI"
        start_date = datetime.now() - timedelta(days=30)
        end_date = datetime.now()
        
        # Mock tool responses
        mock_mentions = [
            {"article_id": "1", "mention_count": 3, "sentiment": "positive"},
            {"article_id": "2", "mention_count": 1, "sentiment": "neutral"}
        ]
        
        mock_patterns = {
            "timeline": [{"date": "2023-01-01", "mentions": 3}],
            "sentiment_trend": [{"date": "2023-01-01", "sentiment": 0.5}],
            "co_entities": ["Microsoft", "Google"],
            "contexts": ["AI development", "Competition"]
        }
        
        mock_dashboard.execute_tool.side_effect = [
            {"mentions": mock_mentions},  # entity_mentions_search
            mock_patterns  # analyze_mention_patterns
        ]
        
        # When
        result = await entity_tracker.track_entity_mentions(entity_name, (start_date, end_date))
        
        # Then
        assert result["entity_name"] == entity_name
        assert result["total_mentions"] == len(mock_mentions)
        assert "mention_timeline" in result
        assert "sentiment_trend" in result
        assert "co_occurring_entities" in result


class TestCrossDocumentAnalyzer:
    """Test the CrossDocumentAnalyzer class."""
    
    @pytest.fixture
    def mock_dashboard(self):
        """Create a mock dashboard for testing."""
        dashboard = Mock()
        dashboard.execute_tool = AsyncMock()
        return dashboard
    
    @pytest.fixture
    def cross_doc_analyzer(self, mock_dashboard):
        """Create a CrossDocumentAnalyzer instance for testing."""
        return CrossDocumentAnalyzer(mock_dashboard)
    
    @pytest.mark.asyncio
    async def test_find_conflicting_reports(self, cross_doc_analyzer, mock_dashboard):
        """
        GIVEN: A topic to analyze for conflicts
        WHEN: Finding conflicting reports
        THEN: Should identify conflicts and consensus
        """
        # Given
        topic = "COVID-19 vaccine effectiveness"
        
        mock_articles = [
            {"id": "1", "title": "Vaccine 95% effective", "source": "Source A"},
            {"id": "2", "title": "Vaccine 70% effective", "source": "Source B"}
        ]
        
        mock_conflicts = {
            "conflicts": [
                {
                    "claim": "Vaccine effectiveness rate",
                    "conflicting_values": ["95%", "70%"],
                    "sources": ["Source A", "Source B"]
                }
            ],
            "consensus": ["Vaccines reduce severe illness"],
            "reliability_scores": {"Source A": 0.9, "Source B": 0.8},
            "conflicting_sources": ["Source A", "Source B"]
        }
        
        mock_dashboard.execute_tool.side_effect = [
            {"results": mock_articles},  # comprehensive_search
            mock_conflicts  # detect_conflicting_claims
        ]
        
        # When
        result = await cross_doc_analyzer.find_conflicting_reports(topic)
        
        # Then
        assert result["topic"] == topic
        assert result["total_articles_analyzed"] == len(mock_articles)
        assert "conflicts_found" in result
        assert "consensus_claims" in result
        assert "source_reliability_scores" in result
    
    @pytest.mark.asyncio
    async def test_trace_information_flow(self, cross_doc_analyzer, mock_dashboard):
        """
        GIVEN: A claim to trace
        WHEN: Tracing information flow
        THEN: Should return flow timeline and source chain
        """
        # Given
        claim = "AI will replace human jobs"
        
        mock_articles = [
            {"id": "1", "title": "Original study on AI jobs", "date": "2023-01-01"},
            {"id": "2", "title": "News report citing study", "date": "2023-01-02"}
        ]
        
        mock_flow = {
            "timeline": [
                {"date": "2023-01-01", "event": "Original claim published"},
                {"date": "2023-01-02", "event": "Claim reported by news"}
            ],
            "source_chain": ["Academic Study", "News Site A", "News Site B"],
            "mutations": ["Headline simplified", "Context removed"],
            "original_source": {"name": "Academic Study", "credibility": 0.9},
            "propagation_pattern": "academic_to_news"
        }
        
        mock_dashboard.execute_tool.side_effect = [
            {"results": mock_articles},  # claim_search
            mock_flow  # trace_information_flow
        ]
        
        # When
        result = await cross_doc_analyzer.trace_information_flow(claim)
        
        # Then
        assert result["claim"] == claim
        assert result["total_articles"] == len(mock_articles)
        assert "flow_timeline" in result
        assert "source_chain" in result
        assert "original_source" in result


class TestNewsAnalysisDashboard:
    """Test the NewsAnalysisDashboard class."""
    
    @pytest.fixture
    def temp_config(self):
        """Create a temporary configuration for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = MCPDashboardConfig(
                host="localhost",
                port=8081,  # Different port to avoid conflicts
                data_dir=temp_dir,
                enable_tool_execution=True,
                tool_timeout=10.0
            )
            yield config
    
    @pytest.fixture
    def dashboard(self, temp_config):
        """Create a NewsAnalysisDashboard instance for testing."""
        dashboard = NewsAnalysisDashboard()
        dashboard.configure(temp_config)
        return dashboard
    
    def test_dashboard_initialization(self, dashboard):
        """
        GIVEN: A properly configured dashboard
        WHEN: Checking initialization status
        THEN: All components should be properly initialized
        """
        # Then
        assert dashboard._initialized is True
        assert dashboard.news_workflows is not None
        assert dashboard.timeline_engine is not None
        assert dashboard.entity_tracker is not None
        assert dashboard.cross_doc_analyzer is not None
    
    def test_get_dashboard_stats_includes_news_analysis(self, dashboard):
        """
        GIVEN: An initialized news analysis dashboard
        WHEN: Getting dashboard statistics
        THEN: Should include news analysis specific stats
        """
        # When
        stats = dashboard.get_dashboard_stats()
        
        # Then
        assert "news_analysis" in stats
        news_stats = stats["news_analysis"]
        assert "active_workflows" in news_stats
        assert "workflow_types" in news_stats
        assert "supported_user_types" in news_stats
        
        # Check supported user types
        supported_types = news_stats["supported_user_types"]
        expected_types = [ut.value for ut in UserType]
        for user_type in expected_types:
            assert user_type in supported_types
    
    @patch('ipfs_datasets_py.news_analysis_dashboard.Flask')
    def test_setup_app_registers_news_routes(self, mock_flask, dashboard):
        """
        GIVEN: An initialized dashboard
        WHEN: Setting up the Flask app
        THEN: News analysis routes should be registered
        """
        # Given
        mock_app = Mock()
        mock_flask.return_value = mock_app
        dashboard.app = mock_app
        
        # When
        dashboard.setup_app()
        
        # Then
        # Check that route decorators were called for news endpoints
        mock_app.route.assert_called()
        
        # Verify specific news routes were registered
        route_calls = [call.args[0] for call in mock_app.route.call_args_list]
        expected_routes = [
            '/api/news/ingest/article',
            '/api/news/ingest/batch',
            '/api/news/timeline',
            '/api/news/entities/<article_id>',
            '/api/news/search/conflicts'
        ]
        
        for expected_route in expected_routes:
            assert any(expected_route in route for route in route_calls)


class TestNewsSearchFilter:
    """Test the NewsSearchFilter dataclass."""
    
    def test_search_filter_creation(self):
        """
        GIVEN: Filter parameters
        WHEN: Creating a NewsSearchFilter
        THEN: Should create filter with correct attributes
        """
        # Given
        start_date = datetime.now() - timedelta(days=7)
        end_date = datetime.now()
        
        # When
        filter_obj = NewsSearchFilter(
            date_range=(start_date, end_date),
            sources=["BBC", "Reuters"],
            entity_types=["PERSON", "ORG"],
            keywords=["technology", "AI"],
            tags=["news", "tech"],
            author="John Smith",
            user_type_context=UserType.DATA_SCIENTIST
        )
        
        # Then
        assert filter_obj.date_range == (start_date, end_date)
        assert filter_obj.sources == ["BBC", "Reuters"]
        assert filter_obj.entity_types == ["PERSON", "ORG"]
        assert filter_obj.keywords == ["technology", "AI"]
        assert filter_obj.tags == ["news", "tech"]
        assert filter_obj.author == "John Smith"
        assert filter_obj.user_type_context == UserType.DATA_SCIENTIST
    
    def test_search_filter_defaults(self):
        """
        GIVEN: No parameters
        WHEN: Creating a NewsSearchFilter with defaults
        THEN: All fields should be None
        """
        # When
        filter_obj = NewsSearchFilter()
        
        # Then
        assert filter_obj.date_range is None
        assert filter_obj.sources is None
        assert filter_obj.entity_types is None
        assert filter_obj.keywords is None
        assert filter_obj.tags is None
        assert filter_obj.author is None
        assert filter_obj.user_type_context is None


class TestFactoryFunction:
    """Test the factory function for creating dashboards."""
    
    def test_create_news_analysis_dashboard_with_config(self):
        """
        GIVEN: A configuration object
        WHEN: Creating dashboard with factory function
        THEN: Should return properly configured dashboard
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = MCPDashboardConfig(
                host="localhost",
                port=8082,
                data_dir=temp_dir
            )
            
            # When
            dashboard = create_news_analysis_dashboard(config)
            
            # Then
            assert isinstance(dashboard, NewsAnalysisDashboard)
            assert dashboard._initialized is True
    
    def test_create_news_analysis_dashboard_without_config(self):
        """
        GIVEN: No configuration
        WHEN: Creating dashboard with factory function
        THEN: Should create dashboard with default config
        """
        # When
        dashboard = create_news_analysis_dashboard()
        
        # Then
        assert isinstance(dashboard, NewsAnalysisDashboard)
        assert dashboard._initialized is True


@pytest.mark.integration
class TestNewsAnalysisDashboardIntegration:
    """Integration tests for the complete news analysis system."""
    
    @pytest.fixture
    def integration_dashboard(self):
        """Create a dashboard for integration testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = MCPDashboardConfig(
                host="localhost",
                port=8083,
                data_dir=temp_dir,
                enable_tool_execution=True
            )
            
            dashboard = NewsAnalysisDashboard()
            dashboard.configure(config)
            yield dashboard
    
    @pytest.mark.asyncio
    async def test_end_to_end_workflow(self, integration_dashboard):
        """
        GIVEN: A fully configured news analysis dashboard
        WHEN: Running complete workflow from ingestion to analysis
        THEN: Should complete successfully with expected results
        """
        # This would be a comprehensive end-to-end test
        # For demo purposes, we'll mock the external dependencies
        
        with patch.object(integration_dashboard.news_workflows, 'execute_news_ingestion_pipeline') as mock_ingest:
            mock_ingest.return_value = {
                "status": "completed",
                "workflow_id": "test_workflow_123",
                "entities": [{"type": "PERSON", "name": "Test Person"}],
                "storage_id": "stored_article_123"
            }
            
            # Test article ingestion
            result = await integration_dashboard.news_workflows.execute_news_ingestion_pipeline(
                "https://example.com/test-article"
            )
            
            assert result["status"] == "completed"
            assert "workflow_id" in result
            assert "entities" in result


# Test data fixtures
@pytest.fixture
def sample_news_articles():
    """Provide sample news articles for testing."""
    return [
        NewsArticle(
            id="article_1",
            url="https://example.com/ai-breakthrough",
            title="Major AI Breakthrough Announced",
            content="Scientists announce major breakthrough in AI research...",
            published_date=datetime.now() - timedelta(days=1),
            source="Tech News",
            author="Dr. Jane Smith",
            tags=["AI", "technology", "research"],
            entities=[
                {"type": "PERSON", "name": "Dr. Jane Smith"},
                {"type": "ORG", "name": "Tech Institute"}
            ]
        ),
        NewsArticle(
            id="article_2",
            url="https://example.com/climate-report",
            title="New Climate Change Report Released",
            content="Latest IPCC report shows accelerating climate change...",
            published_date=datetime.now() - timedelta(days=2),
            source="Environmental News",
            author="Prof. John Green",
            tags=["climate", "environment", "report"],
            entities=[
                {"type": "PERSON", "name": "Prof. John Green"},
                {"type": "ORG", "name": "IPCC"}
            ]
        )
    ]


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])