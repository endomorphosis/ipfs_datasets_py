#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Demo script for testing the MCP-enabled Investigation Dashboard

This script demonstrates how to use the unified investigation dashboard
with MCP tools and JSON-RPC communication.
"""
import asyncio
import json
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import the investigation components
try:
    from ipfs_datasets_py.investigation_mcp_client import create_investigation_mcp_client
    from ipfs_datasets_py.mcp_investigation_dashboard import MCPInvestigationDashboard, MCPInvestigationDashboardConfig
except ImportError as e:
    logger.error(f"Import failed: {e}")
    print("Please run from the correct directory or install the package")
    exit(1)


async def test_mcp_client():
    """Test the MCP client communication."""
    logger.info("Testing MCP Client Communication...")
    
    client = create_investigation_mcp_client()
    
    try:
        async with client:
            # Test basic connectivity
            logger.info("Testing MCP server connectivity...")
            
            # Create sample corpus data
            corpus_data = {
                "documents": [
                    {
                        "id": "doc1",
                        "title": "Sample News Article About Tech Companies",
                        "content": "This is a sample article about Apple Inc. and Microsoft Corporation. Both companies must comply with privacy regulations. Apple may share user data under certain conditions, but Microsoft cannot share data without explicit consent.",
                        "source": "Tech News Daily",
                        "date": "2024-01-15T10:00:00Z"
                    },
                    {
                        "id": "doc2", 
                        "title": "Government Regulation Update",
                        "content": "New regulations state that technology companies shall implement stronger privacy protections. Companies are required to obtain user consent before data processing. However, Apple is allowed to process data for system optimization.",
                        "source": "Government Bulletin",
                        "date": "2024-01-14T15:30:00Z"
                    }
                ]
            }
            
            # Test entity analysis
            logger.info("Testing entity analysis...")
            entity_result = await client.call_tool('analyze_entities', {
                'corpus_data': json.dumps(corpus_data),
                'analysis_type': 'comprehensive',
                'entity_types': ['PERSON', 'ORG', 'GPE'],
                'confidence_threshold': 0.8
            })
            logger.info(f"Entity analysis completed: {len(entity_result.get('content', []))}")
            
            # Test deontological analysis 
            logger.info("Testing deontological analysis...")
            legal_result = await client.call_tool('analyze_deontological_conflicts', {
                'corpus_data': json.dumps(corpus_data),
                'conflict_types': ['direct', 'conditional', 'jurisdictional'],
                'severity_threshold': 'medium'
            })
            logger.info(f"Deontological analysis completed: {len(legal_result.get('content', []))}")
            
            # Test relationship mapping
            logger.info("Testing relationship mapping...")
            relationship_result = await client.call_tool('map_relationships', {
                'corpus_data': json.dumps(corpus_data),
                'min_strength': 0.5,
                'max_depth': 3
            })
            logger.info(f"Relationship mapping completed: {len(relationship_result.get('content', []))}")
            
            logger.info("✅ All MCP client tests passed!")
            return True
            
    except Exception as e:
        logger.error(f"❌ MCP client test failed: {e}")
        return False


async def test_article_ingestion():
    """Test article ingestion through MCP."""
    logger.info("Testing Article Ingestion...")
    
    client = create_investigation_mcp_client()
    
    try:
        async with client:
            # Test single article ingestion
            logger.info("Testing single article ingestion...")
            article_result = await client.call_tool('ingest_news_article', {
                'url': 'https://example.com/sample-article',
                'source_type': 'news',
                'analysis_type': 'comprehensive',
                'metadata': json.dumps({'category': 'technology', 'priority': 'high'})
            })
            
            logger.info(f"Article ingestion result: {article_result}")
            
            # Test website crawling
            logger.info("Testing website crawling...")
            website_result = await client.call_tool('ingest_website', {
                'base_url': 'https://example.com',
                'max_pages': 10,
                'max_depth': 2,
                'url_patterns': json.dumps({'include': ['news', 'articles']}),
                'content_types': json.dumps(['text/html'])
            })
            
            logger.info(f"Website crawling result: {website_result}")
            
            logger.info("✅ Article ingestion tests passed!")
            return True
            
    except Exception as e:
        logger.error(f"❌ Article ingestion test failed: {e}")
        return False


async def test_workflow_execution():
    """Test complete workflow execution."""
    logger.info("Testing Workflow Execution...")
    
    client = create_investigation_mcp_client()
    
    try:
        async with client:
            # Define a comprehensive analysis workflow
            workflow_steps = [
                {
                    'step_name': 'entity_analysis',
                    'tool_name': 'analyze_entities',
                    'arguments': {
                        'corpus_data': json.dumps({
                            "documents": [
                                {
                                    "id": "workflow_doc",
                                    "title": "Corporate Ethics Case Study",
                                    "content": "XYZ Corporation must ensure data privacy compliance. The company may collect user information for service improvement, but cannot sell data to third parties. Employees should report any privacy violations immediately.",
                                    "source": "Corporate Ethics Review",
                                    "date": "2024-01-16T09:00:00Z"
                                }
                            ]
                        }),
                        'analysis_type': 'comprehensive',
                        'confidence_threshold': 0.85
                    }
                },
                {
                    'step_name': 'legal_analysis',
                    'tool_name': 'analyze_deontological_conflicts',
                    'arguments': {
                        'corpus_data': json.dumps({
                            "documents": [
                                {
                                    "id": "workflow_doc",
                                    "title": "Corporate Ethics Case Study",
                                    "content": "XYZ Corporation must ensure data privacy compliance. The company may collect user information for service improvement, but cannot sell data to third parties. Employees should report any privacy violations immediately.",
                                    "source": "Corporate Ethics Review",
                                    "date": "2024-01-16T09:00:00Z"
                                }
                            ]
                        }),
                        'conflict_types': ['direct', 'conditional'],
                        'severity_threshold': 'low'
                    }
                }
            ]
            
            # Execute workflow steps
            workflow_results = {}
            for step in workflow_steps:
                step_name = step['step_name']
                logger.info(f"Executing workflow step: {step_name}")
                
                result = await client.call_tool(step['tool_name'], step['arguments'])
                workflow_results[step_name] = result
                
                logger.info(f"Step {step_name} completed successfully")
            
            logger.info(f"✅ Workflow execution completed with {len(workflow_results)} steps!")
            return True
            
    except Exception as e:
        logger.error(f"❌ Workflow execution test failed: {e}")
        return False


async def demo_dashboard_creation():
    """Demonstrate dashboard creation and configuration."""
    logger.info("Demonstrating Dashboard Creation...")
    
    try:
        # Create dashboard configuration
        config = MCPInvestigationDashboardConfig(
            mcp_server_url="http://localhost:8080",
            mcp_endpoint="/mcp/call-tool",
            default_timeout=60,
            enable_caching=True,
            cache_duration=300
        )
        
        # Create dashboard instance
        dashboard = MCPInvestigationDashboard(config)
        
        logger.info(f"Dashboard created with config: {config}")
        logger.info(f"MCP endpoint: {dashboard.mcp_client.base_url}{dashboard.mcp_client.endpoint}")
        
        # Test dashboard MCP client
        test_result = await dashboard.mcp_client.call_tool('health_check', {})
        logger.info(f"Dashboard MCP client test: {test_result}")
        
        logger.info("✅ Dashboard creation demonstration completed!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Dashboard creation demo failed: {e}")
        return False


async def run_comprehensive_demo():
    """Run comprehensive demonstration of all MCP investigation features."""
    logger.info("🚀 Starting Comprehensive MCP Investigation Dashboard Demo")
    logger.info("=" * 60)
    
    test_results = {}
    
    # Run all test components
    test_results['mcp_client'] = await test_mcp_client()
    test_results['article_ingestion'] = await test_article_ingestion()
    test_results['workflow_execution'] = await test_workflow_execution()
    test_results['dashboard_creation'] = await demo_dashboard_creation()
    
    # Summary
    logger.info("=" * 60)
    logger.info("📊 Demo Results Summary:")
    
    for test_name, result in test_results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        logger.info(f"  {test_name}: {status}")
    
    all_passed = all(test_results.values())
    overall_status = "✅ ALL TESTS PASSED" if all_passed else "❌ SOME TESTS FAILED"
    
    logger.info(f"\n🎯 Overall Result: {overall_status}")
    
    if all_passed:
        logger.info("""
🎉 MCP Investigation Dashboard Demo Completed Successfully!

The unified investigation dashboard is now ready with:
- MCP tool integration for all analysis operations
- JSON-RPC communication with centralized MCP server  
- Entity analysis, relationship mapping, and deontological reasoning
- Data ingestion for articles, websites, and document collections
- Workflow management for complex investigation processes
- Professional dashboard interface for researchers and analysts

Next Steps:
1. Start the MCP server: python -m ipfs_datasets_py.mcp_server.server
2. Access the dashboard: http://localhost:8080/investigation
3. Begin investigating your data with the unified interface
        """)
    else:
        logger.info("""
⚠️  Some tests failed. Please check the MCP server is running and configured correctly.
        
To start the MCP server:
python -m ipfs_datasets_py.mcp_server.server --host localhost --port 8080
        """)
    
    return all_passed


if __name__ == "__main__":
    print("MCP Investigation Dashboard Demo")
    print("================================")
    
    try:
        result = asyncio.run(run_comprehensive_demo())
        exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\nDemo interrupted by user")
        exit(1)
    except Exception as e:
        logger.error(f"Demo failed with unexpected error: {e}")
        exit(1)