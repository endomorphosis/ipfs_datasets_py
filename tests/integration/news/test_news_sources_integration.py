#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
News Sources Integration Test

Comprehensive test of the News Analysis Dashboard using Reuters, AP, and Bloomberg
financial news sources as requested. This test extracts a substantial corpus
and demonstrates the full analysis capabilities.
"""
import sys
import time
import anyio
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any
import requests
from dataclasses import asdict

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from ipfs_datasets_py.dashboards.news_analysis_dashboard import (
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

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NewsSourcesIntegrationTest:
    """
    Comprehensive integration test for major news sources.
    Tests crawling, ingestion, GraphRAG analysis, and graph exploration.
    """
    
    def __init__(self):
        """Initialize the test environment."""
        self.dashboard = None
        self.test_results = {
            "sources_tested": [],
            "articles_processed": 0,
            "entities_extracted": 0,
            "queries_executed": [],
            "graph_analysis": {},
            "performance_metrics": {},
            "errors": []
        }
        
        # News source configurations
        self.news_sources = {
            "reuters": {
                "name": "Reuters",
                "base_urls": [
                    "https://www.reuters.com/markets/",
                    "https://www.reuters.com/technology/",
                    "https://www.reuters.com/business/finance/"
                ],
                "max_pages": 20,
                "max_depth": 2
            },
            "ap": {
                "name": "Associated Press",
                "base_urls": [
                    "https://apnews.com/hub/business",
                    "https://apnews.com/hub/technology",
                    "https://apnews.com/hub/financial-markets"
                ],
                "max_pages": 15,
                "max_depth": 2
            },
            "bloomberg": {
                "name": "Bloomberg",
                "base_urls": [
                    "https://www.bloomberg.com/markets",
                    "https://www.bloomberg.com/technology",
                    "https://www.bloomberg.com/economics"
                ],
                "max_pages": 25,
                "max_depth": 2
            }
        }
        
    async def setup_dashboard(self):
        """Initialize the news analysis dashboard."""
        print("\n=== Setting Up News Analysis Dashboard ===")
        
        config = MCPDashboardConfig(
            host="localhost",
            port=8080
        )
        
        self.dashboard = NewsAnalysisDashboard()
        self.dashboard.configure(config)
        await self.dashboard.start()  # Use the inherited start method
        
        print("✓ Dashboard initialized and started")
        return True
        
    async def test_website_crawling(self, source_key: str, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """Test website crawling for a news source."""
        print(f"\n=== Testing Website Crawling: {source_config['name']} ===")
        
        crawl_results = {
            "source": source_key,
            "total_pages": 0,
            "successful_crawls": 0,
            "failed_crawls": 0,
            "crawl_ids": []
        }
        
        for url in source_config["base_urls"]:
            print(f"\nCrawling: {url}")
            
            crawl_config = {
                "max_pages": source_config["max_pages"],
                "max_depth": source_config["max_depth"],
                "include_patterns": [
                    "*/article/*", "*/story/*", "*/news/*", "*/markets/*",
                    "*/business/*", "*/technology/*", "*/finance/*"
                ],
                "exclude_patterns": [
                    "*/video/*", "*/gallery/*", "*/podcast/*",
                    "*cookie*", "*privacy*", "*terms*"
                ],
                "content_types": ["text/html", "application/pdf"]
            }
            
            try:
                # Start the crawl
                start_time = time.time()
                crawl_id = await self.dashboard.news_workflows.start_website_crawl(
                    url, crawl_config
                )
                crawl_results["crawl_ids"].append(crawl_id)
                
                # Monitor crawl progress
                max_wait_time = 300  # 5 minutes max per crawl
                wait_time = 0
                
                while wait_time < max_wait_time:
                    status = await self.dashboard.news_workflows.get_crawl_status(crawl_id)
                    
                    if status["status"] == "completed":
                        crawl_time = time.time() - start_time
                        pages_crawled = status.get("crawled_pages", 0)
                        
                        crawl_results["successful_crawls"] += 1
                        crawl_results["total_pages"] += pages_crawled
                        
                        print(f"  ✓ Crawl completed: {pages_crawled} pages in {crawl_time:.1f}s")
                        break
                    elif status["status"] == "failed":
                        crawl_results["failed_crawls"] += 1
                        print(f"  ✗ Crawl failed: {status.get('error', 'Unknown error')}")
                        break
                    else:
                        print(f"  ⏳ Crawling... {status.get('crawled_pages', 0)} pages")
                        await anyio.sleep(10)
                        wait_time += 10
                
                if wait_time >= max_wait_time:
                    crawl_results["failed_crawls"] += 1
                    print(f"  ⏰ Crawl timed out after {max_wait_time}s")
                    
            except Exception as e:
                crawl_results["failed_crawls"] += 1
                error_msg = f"Crawl exception for {url}: {e}"
                print(f"  ✗ {error_msg}")
                self.test_results["errors"].append(error_msg)
                
            # Brief pause between crawls
            await anyio.sleep(5)
        
        print(f"\n{source_config['name']} Crawling Summary:")
        print(f"  • Total pages crawled: {crawl_results['total_pages']}")
        print(f"  • Successful crawls: {crawl_results['successful_crawls']}")
        print(f"  • Failed crawls: {crawl_results['failed_crawls']}")
        
        return crawl_results
        
    async def test_graphrag_queries(self) -> Dict[str, Any]:
        """Test various GraphRAG queries on the extracted content."""
        print("\n=== Testing GraphRAG Queries ===")
        
        # Define comprehensive test queries
        test_queries = [
            {
                "type": "semantic",
                "query": "What are the latest trends in financial markets?",
                "userType": "data_scientist"
            },
            {
                "type": "entity",
                "query": "Federal Reserve",
                "userType": "historian",
                "hops": 2
            },
            {
                "type": "temporal", 
                "query": "market volatility trends",
                "userType": "data_scientist",
                "timeRange": "last_week"
            },
            {
                "type": "relationship",
                "userType": "lawyer",
                "entity1": "interest rates",
                "entity2": "inflation"
            },
            {
                "type": "cross_doc",
                "query": "economic policy changes",
                "userType": "historian"
            }
        ]
        
        query_results = {
            "total_queries": len(test_queries),
            "successful_queries": 0,
            "failed_queries": 0,
            "query_details": []
        }
        
        for i, query in enumerate(test_queries):
            print(f"\nExecuting query {i+1}/{len(test_queries)}: {query['type']}")
            print(f"  Query: {query.get('query', 'N/A')}")
            
            try:
                start_time = time.time()
                
                if query["type"] == "semantic":
                    result = await self.dashboard.news_graph_rag._execute_semantic_query(
                        query["query"], query
                    )
                elif query["type"] == "entity":
                    result = await self.dashboard.news_graph_rag._execute_entity_query(
                        query["query"], query
                    )
                elif query["type"] == "temporal":
                    result = await self.dashboard.news_graph_rag._execute_temporal_query(
                        query["query"], query
                    )
                elif query["type"] == "relationship":
                    result = await self.dashboard.news_graph_rag._execute_relationship_query(
                        query
                    )
                elif query["type"] == "cross_doc":
                    result = await self.dashboard.news_graph_rag._execute_cross_document_query(
                        query["query"], query
                    )
                
                query_time = time.time() - start_time
                
                query_detail = {
                    "type": query["type"],
                    "query": query.get("query", "N/A"),
                    "processing_time": query_time,
                    "results_count": len(result.get("results", [])),
                    "status": "success"
                }
                
                query_results["successful_queries"] += 1
                query_results["query_details"].append(query_detail)
                
                print(f"  ✓ Query completed: {len(result.get('results', []))} results in {query_time:.2f}s")
                
            except Exception as e:
                error_msg = f"Query failed: {e}"
                print(f"  ✗ {error_msg}")
                
                query_detail = {
                    "type": query["type"],
                    "query": query.get("query", "N/A"),
                    "error": str(e),
                    "status": "failed"
                }
                
                query_results["failed_queries"] += 1
                query_results["query_details"].append(query_detail)
                self.test_results["errors"].append(error_msg)
        
        print(f"\nGraphRAG Query Summary:")
        print(f"  • Successful queries: {query_results['successful_queries']}")
        print(f"  • Failed queries: {query_results['failed_queries']}")
        
        return query_results
        
    async def test_graph_exploration(self) -> Dict[str, Any]:
        """Test interactive graph exploration capabilities."""
        print("\n=== Testing Graph Exploration ===")
        
        graph_results = {
            "graph_statistics": {},
            "community_analysis": {},
            "path_analysis": {},
            "filtering_tests": {}
        }
        
        try:
            # Get overall graph statistics
            graph_data = await self.dashboard.news_graph_rag.get_knowledge_graph({})
            
            if graph_data and "nodes" in graph_data and "edges" in graph_data:
                nodes = graph_data["nodes"]
                edges = graph_data["edges"]
                
                graph_results["graph_statistics"] = {
                    "total_nodes": len(nodes),
                    "total_edges": len(edges),
                    "node_types": list(set(node.get("type", "unknown") for node in nodes)),
                    "edge_types": list(set(edge.get("type", "unknown") for edge in edges))
                }
                
                print(f"✓ Graph loaded: {len(nodes)} nodes, {len(edges)} edges")
                
                # Test community detection
                communities = await self.dashboard.news_graph_rag.detect_communities({})
                graph_results["community_analysis"] = {
                    "total_communities": len(communities.get("communities", [])),
                    "modularity_score": communities.get("modularity", 0)
                }
                print(f"✓ Community detection: {len(communities.get('communities', []))} communities")
                
                # Test path finding (if we have enough nodes)
                if len(nodes) >= 2:
                    source_node = nodes[0]["id"]
                    target_node = nodes[min(len(nodes)-1, 10)]["id"]  # Pick a node not too far
                    
                    shortest_path = await self.dashboard.news_graph_rag.find_shortest_path({
                        "source": source_node,
                        "target": target_node
                    })
                    
                    graph_results["path_analysis"] = {
                        "path_found": bool(shortest_path.get("path")),
                        "path_length": len(shortest_path.get("path", []))
                    }
                    print(f"✓ Path analysis: Path length {len(shortest_path.get('path', []))}")
                
                # Test filtering capabilities
                node_types = graph_results["graph_statistics"]["node_types"]
                if node_types:
                    test_type = node_types[0]
                    filtered_graph = await self.dashboard.news_graph_rag.get_knowledge_graph({
                        "nodeTypes": [test_type]
                    })
                    
                    graph_results["filtering_tests"] = {
                        "filter_type": test_type,
                        "original_nodes": len(nodes),
                        "filtered_nodes": len(filtered_graph.get("nodes", []))
                    }
                    print(f"✓ Filtering test: {len(filtered_graph.get('nodes', []))} nodes with type '{test_type}'")
                
            else:
                print("✗ No graph data available for exploration")
                
        except Exception as e:
            error_msg = f"Graph exploration failed: {e}"
            print(f"✗ {error_msg}")
            self.test_results["errors"].append(error_msg)
        
        return graph_results
        
    async def analyze_corpus_quality(self) -> Dict[str, Any]:
        """Analyze the quality and characteristics of the extracted corpus."""
        print("\n=== Analyzing Corpus Quality ===")
        
        corpus_analysis = {
            "content_diversity": {},
            "temporal_distribution": {},
            "entity_richness": {},
            "source_coverage": {}
        }
        
        try:
            # Get all stored articles
            all_articles = await self.dashboard.news_data_manager.get_all_articles()
            
            if all_articles:
                corpus_analysis["content_diversity"] = {
                    "total_articles": len(all_articles),
                    "unique_sources": len(set(article.source for article in all_articles)),
                    "avg_content_length": sum(len(article.content) for article in all_articles) / len(all_articles)
                }
                
                # Analyze temporal distribution
                dates = [article.published_date for article in all_articles if article.published_date]
                if dates:
                    date_range = max(dates) - min(dates)
                    corpus_analysis["temporal_distribution"] = {
                        "date_range_days": date_range.days,
                        "earliest_article": min(dates).isoformat(),
                        "latest_article": max(dates).isoformat()
                    }
                
                # Analyze entity richness
                all_entities = []
                for article in all_articles:
                    if article.entities:
                        all_entities.extend(article.entities)
                
                if all_entities:
                    entity_types = [entity.get("type") for entity in all_entities]
                    corpus_analysis["entity_richness"] = {
                        "total_entities": len(all_entities),
                        "unique_entity_types": len(set(entity_types)),
                        "top_entity_types": list(set(entity_types))[:10]
                    }
                
                print(f"✓ Corpus analysis completed:")
                print(f"  • {len(all_articles)} articles from {corpus_analysis['content_diversity']['unique_sources']} sources")
                print(f"  • {len(all_entities)} entities extracted")
                print(f"  • {date_range.days if dates else 0} days of content")
                
            else:
                print("✗ No articles found for corpus analysis")
                
        except Exception as e:
            error_msg = f"Corpus analysis failed: {e}"
            print(f"✗ {error_msg}")
            self.test_results["errors"].append(error_msg)
        
        return corpus_analysis
        
    async def run_comprehensive_test(self) -> Dict[str, Any]:
        """Run the complete integration test."""
        print("🚀 Starting Comprehensive News Sources Integration Test")
        print("=" * 70)
        
        start_time = time.time()
        
        try:
            # 1. Setup dashboard
            await self.setup_dashboard()
            
            # 2. Test website crawling for each source
            crawl_results = {}
            for source_key, source_config in self.news_sources.items():
                result = await self.test_website_crawling(source_key, source_config)
                crawl_results[source_key] = result
                self.test_results["sources_tested"].append(source_key)
                self.test_results["articles_processed"] += result["total_pages"]
            
            # 3. Allow time for processing
            print("\n⏳ Waiting for content processing to complete...")
            await anyio.sleep(30)  # Give time for background processing
            
            # 4. Test GraphRAG queries
            query_results = await self.test_graphrag_queries()
            self.test_results["queries_executed"] = query_results["query_details"]
            
            # 5. Test graph exploration
            graph_results = await self.test_graph_exploration()
            self.test_results["graph_analysis"] = graph_results
            
            # 6. Analyze corpus quality
            corpus_results = await self.analyze_corpus_quality()
            
            # 7. Calculate performance metrics
            total_time = time.time() - start_time
            self.test_results["performance_metrics"] = {
                "total_test_time": total_time,
                "sources_per_minute": len(self.news_sources) / (total_time / 60),
                "pages_per_minute": self.test_results["articles_processed"] / (total_time / 60)
            }
            
            # 8. Generate comprehensive report
            await self.generate_test_report(crawl_results, query_results, graph_results, corpus_results)
            
        except Exception as e:
            error_msg = f"Comprehensive test failed: {e}"
            print(f"\n✗ {error_msg}")
            self.test_results["errors"].append(error_msg)
        
        finally:
            if self.dashboard:
                await self.dashboard.stop()
        
        return self.test_results
        
    async def generate_test_report(self, crawl_results: Dict, query_results: Dict, 
                                 graph_results: Dict, corpus_results: Dict):
        """Generate a comprehensive test report."""
        print("\n" + "=" * 70)
        print("📊 COMPREHENSIVE TEST REPORT")
        print("=" * 70)
        
        # Overall summary
        print(f"\n📈 OVERALL SUMMARY")
        print(f"  • Sources tested: {len(self.test_results['sources_tested'])}")
        print(f"  • Total pages processed: {self.test_results['articles_processed']}")
        print(f"  • Total test time: {self.test_results['performance_metrics']['total_test_time']:.1f}s")
        print(f"  • Processing rate: {self.test_results['performance_metrics']['pages_per_minute']:.1f} pages/minute")
        
        # Crawling results
        print(f"\n🕷️ CRAWLING RESULTS")
        for source, results in crawl_results.items():
            print(f"  • {source.upper()}: {results['total_pages']} pages ({results['successful_crawls']}/{len(self.news_sources[source]['base_urls'])} URLs)")
        
        # Query results
        print(f"\n🔎 GRAPHRAG QUERY RESULTS")
        print(f"  • Queries executed: {query_results['successful_queries']}/{query_results['total_queries']}")
        for query in query_results['query_details']:
            if query['status'] == 'success':
                print(f"  • {query['type']}: {query['results_count']} results in {query['processing_time']:.2f}s")
        
        # Graph exploration
        print(f"\n🕸️ GRAPH EXPLORATION RESULTS")
        if graph_results.get('graph_statistics'):
            stats = graph_results['graph_statistics']
            print(f"  • Knowledge graph: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
            print(f"  • Node types: {', '.join(stats['node_types'][:5])}")
            
        # Corpus quality
        print(f"\n📚 CORPUS QUALITY ANALYSIS")
        if corpus_results.get('content_diversity'):
            diversity = corpus_results['content_diversity']
            print(f"  • Articles extracted: {diversity['total_articles']}")
            print(f"  • Unique sources: {diversity['unique_sources']}")
            print(f"  • Average content length: {diversity['avg_content_length']:.0f} characters")
        
        # Errors and issues
        if self.test_results["errors"]:
            print(f"\n⚠️ ISSUES ENCOUNTERED")
            for error in self.test_results["errors"][:5]:  # Show first 5 errors
                print(f"  • {error}")
            if len(self.test_results["errors"]) > 5:
                print(f"  • ... and {len(self.test_results['errors']) - 5} more issues")
        
        # Save detailed results
        results_file = Path("news_sources_test_results.json")
        with open(results_file, 'w') as f:
            json.dump({
                "test_results": self.test_results,
                "crawl_results": crawl_results,
                "query_results": query_results,
                "graph_results": graph_results,
                "corpus_results": corpus_results
            }, f, indent=2, default=str)
        
        print(f"\n💾 Detailed results saved to: {results_file}")
        print("\n✅ Comprehensive test completed!")

async def main():
    """Main test execution function."""
    test = NewsSourcesIntegrationTest()
    results = await test.run_comprehensive_test()
    
    # Print final status
    if results["errors"]:
        print(f"\n⚠️ Test completed with {len(results['errors'])} issues")
        return 1
    else:
        print(f"\n✅ All tests passed successfully!")
        return 0

if __name__ == "__main__":
    try:
        exit_code = anyio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n❌ Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        sys.exit(1)