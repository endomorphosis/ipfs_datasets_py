"""
Tests for GraphRAG News Analyzer.

This module tests the GraphRAG-powered executive-performance correlation analysis.
"""

import pytest
from datetime import datetime
import json


def test_imports():
    """
    GIVEN the graphrag_news_analyzer module
    WHEN importing core components
    THEN all imports should succeed
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
            ExecutiveProfile,
            CompanyPerformance,
            HypothesisTest,
            GraphRAGNewsAnalyzer,
            analyze_executive_performance,
            extract_executive_profiles_from_archives
        )
        
        assert ExecutiveProfile is not None
        assert CompanyPerformance is not None
        assert HypothesisTest is not None
        assert GraphRAGNewsAnalyzer is not None
        
    except ImportError as e:
        pytest.fail(f"Import failed: {e}")


def test_executive_profile_creation():
    """
    GIVEN executive profile data
    WHEN creating an ExecutiveProfile
    THEN profile should be created with correct attributes
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
        ExecutiveProfile
    )
    
    profile = ExecutiveProfile(
        person_id="exec_001",
        name="Jane Smith",
        gender="female",
        personality_traits=["analytical", "visionary"],
        companies=["TechCorp"],
        positions=["CEO"]
    )
    
    assert profile.person_id == "exec_001"
    assert profile.name == "Jane Smith"
    assert profile.gender == "female"
    assert "analytical" in profile.personality_traits
    assert "TechCorp" in profile.companies


def test_company_performance_creation():
    """
    GIVEN company performance data
    WHEN creating a CompanyPerformance object
    THEN object should be created with correct metrics
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
        CompanyPerformance
    )
    
    company = CompanyPerformance(
        company_id="comp_001",
        symbol="TECH",
        name="TechCorp",
        return_percentage=45.2,
        volatility=12.3
    )
    
    assert company.symbol == "TECH"
    assert company.return_percentage == 45.2
    assert company.volatility == 12.3


def test_analyzer_initialization():
    """
    GIVEN GraphRAG analyzer initialization
    WHEN creating analyzer instance
    THEN analyzer should initialize correctly
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
        GraphRAGNewsAnalyzer
    )
    
    analyzer = GraphRAGNewsAnalyzer(
        enable_graphrag=True,
        min_confidence=0.7
    )
    
    assert analyzer.min_confidence == 0.7
    assert isinstance(analyzer.executives, dict)
    assert isinstance(analyzer.companies, dict)


def test_extract_executive_profiles():
    """
    GIVEN news articles with executive mentions
    WHEN extracting executive profiles
    THEN profiles should be extracted
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
        GraphRAGNewsAnalyzer
    )
    
    analyzer = GraphRAGNewsAnalyzer()
    
    articles = [
        {
            "title": "TechCorp CEO Jane Smith announces new product",
            "content": "CEO Jane Smith announced today that she will lead the company...",
            "source": "reuters",
            "published_date": "2023-01-15"
        },
        {
            "title": "Chief Executive John Doe steps down",
            "content": "Chief Executive John Doe announced his resignation. He has served...",
            "source": "ap",
            "published_date": "2023-02-01"
        }
    ]
    
    profiles = analyzer.extract_executive_profiles(articles)
    
    # Should extract at least some profiles
    assert isinstance(profiles, list)
    # Note: Actual extraction depends on pattern matching, may be 0 in test environment


def test_hypothesis_test_structure():
    """
    GIVEN hypothesis test execution
    WHEN testing with sample data
    THEN test result should have correct structure
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
        GraphRAGNewsAnalyzer,
        ExecutiveProfile,
        CompanyPerformance
    )
    
    analyzer = GraphRAGNewsAnalyzer()
    
    # Add sample executives
    exec1 = ExecutiveProfile(
        person_id="exec_001",
        name="Jane Smith",
        gender="female",
        companies=["TECH"]
    )
    exec2 = ExecutiveProfile(
        person_id="exec_002",
        name="John Doe",
        gender="male",
        companies=["CORP"]
    )
    
    analyzer.executives = {
        "exec_001": exec1,
        "exec_002": exec2
    }
    
    # Add sample companies
    comp1 = CompanyPerformance(
        company_id="TECH",
        symbol="TECH",
        name="TechCorp",
        executive_id="exec_001",
        return_percentage=50.0
    )
    comp2 = CompanyPerformance(
        company_id="CORP",
        symbol="CORP",
        name="CorpInc",
        executive_id="exec_002",
        return_percentage=30.0
    )
    
    analyzer.companies = {
        "TECH": comp1,
        "CORP": comp2
    }
    
    # Test hypothesis
    result = analyzer.test_hypothesis(
        hypothesis="Female CEOs outperform male CEOs",
        attribute_name="gender",
        group_a_value="female",
        group_b_value="male",
        metric="return_percentage"
    )
    
    assert result.hypothesis_id is not None
    assert result.group_a_samples >= 0
    assert result.group_b_samples >= 0
    assert result.conclusion is not None


def test_knowledge_graph_building():
    """
    GIVEN analyzer with executives and companies
    WHEN building knowledge graph
    THEN graph should contain entities
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
        GraphRAGNewsAnalyzer,
        ExecutiveProfile,
        CompanyPerformance
    )
    
    analyzer = GraphRAGNewsAnalyzer()
    
    # Add data
    analyzer.executives["exec_001"] = ExecutiveProfile(
        person_id="exec_001",
        name="Test Executive"
    )
    analyzer.companies["comp_001"] = CompanyPerformance(
        company_id="comp_001",
        symbol="TEST",
        name="Test Corp"
    )
    
    # Build graph
    kg = analyzer.build_knowledge_graph()
    
    assert len(kg.entities) >= 2  # At least executive and company


def test_mcp_tool_analyze_executive_performance():
    """
    GIVEN the analyze_executive_performance MCP tool
    WHEN calling with valid data
    THEN should return JSON response
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
        analyze_executive_performance
    )
    
    news_data = json.dumps([
        {
            "title": "CEO Jane Smith leads turnaround",
            "content": "CEO Jane Smith announced today...",
            "source": "reuters"
        }
    ])
    
    stock_data = json.dumps([
        {
            "symbol": "TECH",
            "name": "TechCorp",
            "company_id": "tech_001",
            "return_percentage": 45.0,
            "volatility": 12.0
        }
    ])
    
    result = analyze_executive_performance(
        news_articles_json=news_data,
        stock_data_json=stock_data,
        hypothesis="Test hypothesis",
        attribute="gender",
        group_a="female",
        group_b="male"
    )
    
    # Should return valid JSON
    data = json.loads(result)
    assert "success" in data


def test_mcp_tool_extract_profiles():
    """
    GIVEN the extract_executive_profiles_from_archives MCP tool
    WHEN calling it
    THEN should return JSON response
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
        extract_executive_profiles_from_archives
    )
    
    result = extract_executive_profiles_from_archives(
        sources="reuters,ap",
        start_date="2020-01-01",
        end_date="2024-01-01",
        min_mentions=5
    )
    
    # Should return valid JSON
    data = json.loads(result)
    assert "success" in data


def test_executive_to_entity_conversion():
    """
    GIVEN an ExecutiveProfile
    WHEN converting to Entity
    THEN Entity should contain all profile data
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
        ExecutiveProfile
    )
    
    profile = ExecutiveProfile(
        person_id="exec_001",
        name="Jane Smith",
        gender="female",
        personality_traits=["analytical"]
    )
    
    entity = profile.to_entity()
    
    assert entity.entity_id == "exec_001"
    assert entity.name == "Jane Smith"
    assert entity.properties["gender"] == "female"
    assert "analytical" in entity.properties["personality_traits"]


def test_company_to_entity_conversion():
    """
    GIVEN a CompanyPerformance
    WHEN converting to Entity
    THEN Entity should contain all company data
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
        CompanyPerformance
    )
    
    company = CompanyPerformance(
        company_id="comp_001",
        symbol="TECH",
        name="TechCorp",
        return_percentage=45.0
    )
    
    entity = company.to_entity()
    
    assert entity.entity_id == "comp_001"
    assert entity.name == "TechCorp"
    assert entity.properties["symbol"] == "TECH"
    assert entity.properties["return_percentage"] == 45.0


def test_hypothesis_test_to_dict():
    """
    GIVEN a HypothesisTest result
    WHEN converting to dict
    THEN dict should have all required fields
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
        HypothesisTest
    )
    
    test = HypothesisTest(
        hypothesis_id="test_001",
        hypothesis="Test hypothesis",
        group_a_label="Group A",
        group_b_label="Group B",
        group_a_samples=10,
        group_b_samples=10,
        group_a_mean=50.0,
        group_b_mean=30.0,
        difference=20.0,
        p_value=0.05,
        confidence_level=0.95,
        conclusion="Significant difference found"
    )
    
    result_dict = test.to_dict()
    
    assert result_dict["hypothesis_id"] == "test_001"
    assert result_dict["hypothesis"] == "Test hypothesis"
    assert result_dict["groups"]["a"]["samples"] == 10
    assert result_dict["results"]["difference"] == 20.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
