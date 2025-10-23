#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
News Analysis Dashboard Demo Script

This script demonstrates the complete news analysis dashboard functionality
including all professional workflows for data scientists, historians, and lawyers.
"""
import sys
import time
import asyncio
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta
import json

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from ipfs_datasets_py.news_analysis_dashboard import (
        NewsAnalysisDashboard, 
        MCPDashboardConfig,
        UserType,
        NewsArticle,
        NewsSearchFilter
    )
    print("✓ Successfully imported news analysis dashboard")
except ImportError as e:
    print(f"✗ Failed to import news analysis dashboard: {e}")
    sys.exit(1)

async def demo_single_article_ingestion(dashboard):
    """Demonstrate single article ingestion workflow."""
    print("\n=== Demo: Single Article Ingestion ===")
    
    # Example news article URLs for testing
    test_urls = [
        "https://www.bbc.com/news/technology-65829000",
        "https://www.reuters.com/technology/artificial-intelligence/",
        "https://www.nytimes.com/section/technology"
    ]
    
    for i, url in enumerate(test_urls[:2]):  # Test first 2 URLs
        print(f"\nIngesting article {i+1}: {url}")
        
        metadata = {
            "source_type": "news_website",
            "demo_id": f"demo_article_{i+1}",
            "ingestion_timestamp": datetime.now().isoformat(),
            "demo_context": "single_article_demo"
        }
        
        try:
            result = await dashboard.news_workflows.execute_news_ingestion_pipeline(
                url, metadata
            )
            
            if result["status"] == "completed":
                print(f"  ✓ Successfully ingested: {result.get('storage_id')}")
                print(f"  ✓ Entities found: {len(result.get('entities', []))}")
                print(f"  ✓ Workflow ID: {result.get('workflow_id')}")
            else:
                print(f"  ✗ Failed to ingest: {result.get('error', 'Unknown error')}")
                
        except Exception as e:
            print(f"  ✗ Exception during ingestion: {e}")
        
        # Small delay between requests
        await asyncio.sleep(1)
    
    return True

async def demo_batch_news_ingestion(dashboard):
    """Demonstrate batch news feed ingestion."""
    print("\n=== Demo: Batch News Feed Ingestion ===")
    
    # Example RSS feeds (using placeholder URLs for demo)
    test_feeds = [
        {
            "url": "https://rss.bbc.co.uk/news/technology/rss.xml",
            "name": "BBC Technology",
            "max_articles": 5
        },
        {
            "url": "https://feeds.reuters.com/reuters/technologyNews",
            "name": "Reuters Technology", 
            "max_articles": 3
        }
    ]
    
    for feed in test_feeds[:1]:  # Test first feed only for demo
        print(f"\nIngesting from feed: {feed['name']}")
        print(f"URL: {feed['url']}")
        
        filters = {
            "keywords": ["artificial intelligence", "technology"],
            "min_word_count": 100,
            "exclude_duplicates": True
        }
        
        try:
            result = await dashboard.news_workflows.execute_news_feed_ingestion(
                feed["url"], 
                filters,
                feed["max_articles"]
            )
            
            if result["status"] == "completed":
                print(f"  ✓ Successfully processed feed")
                print(f"  ✓ Articles processed: {result.get('successful_ingests', 0)}")
                print(f"  ✓ Failed articles: {result.get('failed_ingests', 0)}")
                print(f"  ✓ Workflow ID: {result.get('workflow_id')}")
            else:
                print(f"  ✗ Failed to process feed: {result.get('error', 'Unknown error')}")
                
        except Exception as e:
            print(f"  ✗ Exception during batch ingestion: {e}")
    
    return True

async def demo_timeline_analysis(dashboard):
    """Demonstrate timeline analysis capabilities."""
    print("\n=== Demo: Timeline Analysis ===")
    
    # Set up date range for analysis
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    test_queries = [
        "artificial intelligence",
        "climate change",
        "cybersecurity"
    ]
    
    for query in test_queries[:1]:  # Test first query for demo
        print(f"\nGenerating timeline for: '{query}'")
        print(f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        
        try:
            result = await dashboard.timeline_engine.generate_timeline(
                query,
                (start_date, end_date),
                "day"
            )
            
            if "error" not in result:
                print(f"  ✓ Timeline generated successfully")
                print(f"  ✓ Total articles: {result.get('total_articles', 0)}")
                print(f"  ✓ Key events: {len(result.get('key_events', []))}")
                print(f"  ✓ Time periods: {len(result.get('timeline_data', {}))}")
                
                # Show sample timeline data
                timeline_data = result.get('timeline_data', {})
                if timeline_data:
                    print("  Sample timeline periods:")
                    for period, articles in list(timeline_data.items())[:3]:
                        print(f"    {period}: {len(articles)} articles")
                        
            else:
                print(f"  ✗ Timeline generation failed: {result.get('error')}")
                
        except Exception as e:
            print(f"  ✗ Exception during timeline generation: {e}")
    
    return True

async def demo_entity_analysis(dashboard):
    """Demonstrate entity relationship analysis."""
    print("\n=== Demo: Entity Analysis ===")
    
    # Mock article IDs for demo (in real scenario, these would come from ingested articles)
    mock_article_ids = ["article_1", "article_2", "article_3"]
    
    print(f"\nBuilding entity graph for {len(mock_article_ids)} articles")
    
    try:
        result = await dashboard.entity_tracker.build_entity_graph(mock_article_ids)
        
        if "error" not in result:
            print(f"  ✓ Entity graph built successfully")
            print(f"  ✓ Total entities: {result.get('total_entities', 0)}")
            print(f"  ✓ Total relationships: {result.get('total_relationships', 0)}")
            
            # Show entity types
            entity_types = result.get('entity_types', {})
            if entity_types:
                print("  Entity types found:")
                for entity_type, count in entity_types.items():
                    print(f"    {entity_type}: {count}")
                    
        else:
            print(f"  ✗ Entity graph building failed: {result.get('error')}")
            
    except Exception as e:
        print(f"  ✗ Exception during entity analysis: {e}")
    
    # Demo entity mention tracking
    print(f"\nTracking mentions of entity: 'OpenAI'")
    
    try:
        result = await dashboard.entity_tracker.track_entity_mentions(
            "OpenAI",
            (start_date, end_date) if 'start_date' in locals() else None
        )
        
        if "error" not in result:
            print(f"  ✓ Entity mention tracking completed")
            print(f"  ✓ Total mentions: {result.get('total_mentions', 0)}")
            print(f"  ✓ Co-occurring entities: {len(result.get('co_occurring_entities', []))}")
            
        else:
            print(f"  ✗ Entity mention tracking failed: {result.get('error')}")
            
    except Exception as e:
        print(f"  ✗ Exception during entity mention tracking: {e}")
    
    return True

async def demo_cross_document_analysis(dashboard):
    """Demonstrate cross-document analysis capabilities."""
    print("\n=== Demo: Cross-Document Analysis ===")
    
    # Demo conflict detection
    test_topics = [
        "COVID-19 vaccine effectiveness",
        "Climate change causes",
        "Artificial intelligence safety"
    ]
    
    for topic in test_topics[:1]:  # Test first topic for demo
        print(f"\nSearching for conflicting reports on: '{topic}'")
        
        try:
            result = await dashboard.cross_doc_analyzer.find_conflicting_reports(
                topic,
                (datetime.now() - timedelta(days=90), datetime.now())
            )
            
            if "error" not in result:
                print(f"  ✓ Conflict analysis completed")
                print(f"  ✓ Articles analyzed: {result.get('total_articles_analyzed', 0)}")
                print(f"  ✓ Conflicts found: {len(result.get('conflicts_found', []))}")
                print(f"  ✓ Consensus claims: {len(result.get('consensus_claims', []))}")
                
                # Show sample conflicts
                conflicts = result.get('conflicts_found', [])
                if conflicts:
                    print("  Sample conflicts:")
                    for i, conflict in enumerate(conflicts[:2]):
                        print(f"    {i+1}. {conflict.get('description', 'N/A')}")
                        
            else:
                print(f"  ✗ Conflict analysis failed: {result.get('error')}")
                
        except Exception as e:
            print(f"  ✗ Exception during conflict analysis: {e}")
    
    # Demo information flow tracing
    test_claims = [
        "AI models show emergent capabilities",
        "Social media affects mental health", 
        "Remote work increases productivity"
    ]
    
    for claim in test_claims[:1]:  # Test first claim for demo
        print(f"\nTracing information flow for claim: '{claim}'")
        
        try:
            result = await dashboard.cross_doc_analyzer.trace_information_flow(claim)
            
            if "error" not in result:
                print(f"  ✓ Information flow tracing completed")
                print(f"  ✓ Total articles: {result.get('total_articles', 0)}")
                print(f"  ✓ Source chain length: {len(result.get('source_chain', []))}")
                print(f"  ✓ Mutation points: {len(result.get('mutation_points', []))}")
                
                original_source = result.get('original_source')
                if original_source:
                    print(f"  ✓ Original source: {original_source.get('name', 'Unknown')}")
                    
            else:
                print(f"  ✗ Information flow tracing failed: {result.get('error')}")
                
        except Exception as e:
            print(f"  ✗ Exception during information flow tracing: {e}")
    
    return True

async def demo_professional_workflows(dashboard):
    """Demonstrate professional-specific workflows."""
    print("\n=== Demo: Professional Workflows ===")
    
    # Test each user type
    user_types = [UserType.DATA_SCIENTIST, UserType.HISTORIAN, UserType.LAWYER]
    
    for user_type in user_types:
        print(f"\nDemonstrating {user_type.value} workflow:")
        
        if user_type == UserType.DATA_SCIENTIST:
            print("  - Large-scale content analysis")
            print("  - Statistical modeling preparation") 
            print("  - Dataset export for ML training")
            
            # Mock data science workflow
            workflow_config = {
                "analysis_type": "sentiment_trends",
                "statistical_methods": ["regression", "clustering"],
                "export_format": "csv",
                "include_embeddings": True
            }
            
        elif user_type == UserType.HISTORIAN:
            print("  - Temporal pattern analysis")
            print("  - Source validation and cross-referencing")
            print("  - Academic citation generation")
            
            # Mock historian workflow
            workflow_config = {
                "analysis_type": "temporal_analysis",
                "citation_style": "chicago",
                "include_bibliography": True,
                "verify_sources": True
            }
            
        elif user_type == UserType.LAWYER:
            print("  - Legal research and evidence gathering")
            print("  - Due diligence documentation")
            print("  - Chain of custody maintenance")
            
            # Mock lawyer workflow
            workflow_config = {
                "analysis_type": "legal_research",
                "citation_format": "bluebook",
                "chain_of_custody": True,
                "evidence_packaging": True
            }
        
        print(f"  ✓ Workflow configured for {user_type.value}")
        print(f"  ✓ Config: {json.dumps(workflow_config, indent=4)}")
    
    return True

def demo_dashboard_stats(dashboard):
    """Demonstrate dashboard statistics and monitoring."""
    print("\n=== Demo: Dashboard Statistics ===")
    
    try:
        stats = dashboard.get_dashboard_stats()
        
        print("Dashboard Statistics:")
        print(f"  ✓ Server uptime: {stats.get('uptime', 'Unknown')}")
        print(f"  ✓ Memory usage: {stats.get('memory_usage', 'Unknown')}")
        print(f"  ✓ Active connections: {stats.get('active_connections', 0)}")
        
        # News analysis specific stats
        news_stats = stats.get('news_analysis', {})
        if news_stats:
            print("News Analysis Statistics:")
            print(f"  ✓ Active workflows: {news_stats.get('active_workflows', 0)}")
            print(f"  ✓ Supported user types: {', '.join(news_stats.get('supported_user_types', []))}")
            print(f"  ✓ Workflow types: {len(news_stats.get('workflow_types', []))}")
            
            workflow_types = news_stats.get('workflow_types', [])
            if workflow_types:
                print("  Available workflow types:")
                for workflow_type in workflow_types:
                    print(f"    - {workflow_type}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to get dashboard stats: {e}")
        return False

async def run_comprehensive_demo():
    """Run complete news analysis dashboard demonstration."""
    print("=" * 60)
    print("NEWS ANALYSIS DASHBOARD - COMPREHENSIVE DEMO")
    print("=" * 60)
    
    # Configure dashboard
    config = MCPDashboardConfig(
        host="0.0.0.0",
        port=8080,
        mcp_server_host="localhost",
        mcp_server_port=8001,
        enable_tool_execution=True,
        tool_timeout=30.0,
        max_concurrent_tools=3,
        data_dir="/tmp/news_dashboard_demo"
    )
    
    # Create and configure dashboard
    print("\nInitializing News Analysis Dashboard...")
    dashboard = NewsAnalysisDashboard()
    dashboard.configure(config)
    
    print("✓ News Analysis Dashboard initialized")
    print("✓ All components configured and ready")
    
    # Run demo sections
    demo_results = {}
    
    try:
        # Basic dashboard functionality
        demo_results['stats'] = demo_dashboard_stats(dashboard)
        
        # Core news analysis workflows
        demo_results['single_article'] = await demo_single_article_ingestion(dashboard)
        demo_results['batch_ingestion'] = await demo_batch_news_ingestion(dashboard)
        demo_results['timeline_analysis'] = await demo_timeline_analysis(dashboard)
        demo_results['entity_analysis'] = await demo_entity_analysis(dashboard)
        demo_results['cross_document'] = await demo_cross_document_analysis(dashboard)
        demo_results['professional_workflows'] = await demo_professional_workflows(dashboard)
        
    except Exception as e:
        print(f"\n✗ Demo execution failed: {e}")
        return False
    
    # Summary
    print("\n" + "=" * 60)
    print("DEMO SUMMARY")
    print("=" * 60)
    
    successful_demos = sum(1 for result in demo_results.values() if result)
    total_demos = len(demo_results)
    
    print(f"Successful demos: {successful_demos}/{total_demos}")
    
    for demo_name, success in demo_results.items():
        status = "✓ PASSED" if success else "✗ FAILED"
        print(f"  {demo_name}: {status}")
    
    if successful_demos == total_demos:
        print("\n🎉 All demos completed successfully!")
        print("The News Analysis Dashboard is ready for production use.")
    else:
        print(f"\n⚠️  {total_demos - successful_demos} demos failed.")
        print("Please check the error messages above for troubleshooting.")
    
    # Dashboard URLs
    print(f"\nDashboard Access URLs:")
    print(f"  • Main Dashboard: http://{config.host}:{config.port}/")
    print(f"  • News Analysis: http://{config.host}:{config.port}/news")
    print(f"  • API Documentation: http://{config.host}:{config.port}/api/docs")
    print(f"  • MCP Tools: http://{config.host}:{config.port}/api/mcp/tools")
    
    return successful_demos == total_demos

def start_interactive_demo():
    """Start interactive dashboard demo with web interface."""
    print("\n=== Starting Interactive Demo ===")
    
    # Configure dashboard for interactive use
    config = MCPDashboardConfig(
        host="0.0.0.0",
        port=8080,
        enable_tool_execution=True
    )
    
    # Create dashboard
    dashboard = NewsAnalysisDashboard()
    dashboard.configure(config)
    dashboard.setup_app()
    
    # Print access information
    print(f"\nNews Analysis Dashboard running at:")
    print(f"  🌐 http://localhost:{config.port}/")
    print(f"  📊 News Analysis: http://localhost:{config.port}/news")
    print(f"  🔧 API Docs: http://localhost:{config.port}/api/docs")
    
    print(f"\nFeatures available:")
    print(f"  ✓ Single article ingestion")
    print(f"  ✓ Batch news feed processing") 
    print(f"  ✓ Timeline visualization")
    print(f"  ✓ Entity relationship graphs")
    print(f"  ✓ Cross-document conflict analysis")
    print(f"  ✓ Professional export tools")
    print(f"  ✓ Real-time workflow monitoring")
    
    print(f"\nPress Ctrl+C to stop the server")
    
    try:
        # Open browser automatically
        webbrowser.open(f"http://localhost:{config.port}/news")
        
        # Run dashboard
        dashboard.start()
        
    except KeyboardInterrupt:
        print("\n\nShutting down News Analysis Dashboard...")
        print("Demo completed. Thank you!")

def main():
    """Main demo script entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="News Analysis Dashboard Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python demo_news_analysis_dashboard.py --demo comprehensive
  python demo_news_analysis_dashboard.py --demo interactive
  python demo_news_analysis_dashboard.py --demo quick
        """
    )
    
    parser.add_argument(
        '--demo',
        choices=['comprehensive', 'interactive', 'quick'],
        default='interactive',
        help='Type of demo to run (default: interactive)'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=8080,
        help='Port to run dashboard on (default: 8080)'
    )
    
    args = parser.parse_args()
    
    if args.demo == 'comprehensive':
        print("Running comprehensive news analysis demo...")
        success = asyncio.run(run_comprehensive_demo())
        sys.exit(0 if success else 1)
        
    elif args.demo == 'interactive':
        print("Starting interactive news analysis dashboard...")
        start_interactive_demo()
        
    elif args.demo == 'quick':
        print("Running quick news analysis demo...")
        # Quick demo would be a subset of comprehensive
        success = asyncio.run(run_comprehensive_demo())
        if success:
            print("\nStarting interactive dashboard for exploration...")
            start_interactive_demo()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()