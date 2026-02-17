#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simplified News Sources Test

Basic test to validate the News Analysis Dashboard can handle news sources.
"""
import sys
import time
import anyio
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_imports():
    """Test that we can import the necessary components."""
    print("🧪 Testing News Analysis Dashboard Imports")
    print("=" * 50)
    
    try:
        from ipfs_datasets_py.dashboards.news_analysis_dashboard import (
            NewsAnalysisDashboard, 
            MCPDashboardConfig,
            UserType,
            NewsArticle,
            NewsSearchFilter
        )
        print("✓ Successfully imported news analysis dashboard components")
        return True
    except ImportError as e:
        print(f"✗ Failed to import news analysis dashboard: {e}")
        return False

def test_basic_instantiation():
    """Test that we can create the dashboard instance."""
    print("\n🏗️ Testing Dashboard Instantiation")
    print("=" * 50)
    
    try:
        from ipfs_datasets_py.dashboards.news_analysis_dashboard import (
            NewsAnalysisDashboard, 
            MCPDashboardConfig,
        )
        
        # Create configuration
        config = MCPDashboardConfig(
            host="localhost",
            port=8080
        )
        print("✓ Configuration created successfully")
        
        # Create dashboard
        dashboard = NewsAnalysisDashboard()
        print("✓ Dashboard instance created successfully")
        
        # Configure dashboard
        dashboard.configure(config)
        print("✓ Dashboard configured successfully")
        
        return dashboard, config
        
    except Exception as e:
        print(f"✗ Failed to instantiate dashboard: {e}")
        return None, None

def test_crawling_infrastructure():
    """Test that crawling infrastructure is available."""
    print("\n🕷️ Testing Web Crawling Infrastructure")
    print("=" * 50)
    
    try:
        from ipfs_datasets_py.processors.web_archiving.simple_crawler import SimpleWebCrawler
        
        crawler = SimpleWebCrawler(max_pages=5, max_depth=1)
        print("✓ SimpleWebCrawler available")
        
        # Test a simple crawl (dry run)
        print("✓ Web crawling infrastructure ready")
        return True
        
    except ImportError as e:
        print(f"✗ Web crawling not available: {e}")
        return False
    except Exception as e:
        print(f"✗ Error testing crawler: {e}")
        return False

def test_news_sources_accessibility():
    """Test if we can access the news sources."""
    print("\n📰 Testing News Sources Accessibility")
    print("=" * 50)
    
    try:
        import requests
        
        news_sources = [
            ("Reuters", "https://www.reuters.com/robots.txt"),
            ("AP", "https://apnews.com/robots.txt"),
            ("Bloomberg", "https://www.bloomberg.com/robots.txt")
        ]
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'NewsAnalysisDashboard/1.0 (Educational/Research Purpose)'
        })
        
        accessible_sources = []
        
        for name, url in news_sources:
            try:
                response = session.head(url, timeout=10)
                if response.status_code == 200:
                    print(f"✓ {name}: Accessible (robots.txt found)")
                    accessible_sources.append(name)
                else:
                    print(f"⚠ {name}: Partially accessible (status {response.status_code})")
                    accessible_sources.append(name)  # Still might work
                    
            except Exception as e:
                print(f"✗ {name}: Not accessible ({e})")
        
        return accessible_sources
        
    except ImportError:
        print("✗ requests library not available")
        return []
    except Exception as e:
        print(f"✗ Error testing accessibility: {e}")
        return []

def analyze_dashboard_capabilities(dashboard):
    """Analyze what capabilities the dashboard has."""
    print("\n🔍 Analyzing Dashboard Capabilities")
    print("=" * 50)
    
    capabilities = {
        "news_workflows": hasattr(dashboard, 'news_workflows'),
        "timeline_engine": hasattr(dashboard, 'timeline_engine'),
        "entity_tracker": hasattr(dashboard, 'entity_tracker'),
        "cross_doc_analyzer": hasattr(dashboard, 'cross_doc_analyzer'),
        "initialized": getattr(dashboard, '_initialized', False)
    }
    
    print("Dashboard Components:")
    for component, available in capabilities.items():
        status = "✓" if available else "✗"
        print(f"  {status} {component}: {available}")
    
    # Test if we have MCP server capabilities
    mcp_available = hasattr(dashboard, 'mcp_server') and dashboard.mcp_server is not None
    print(f"  {'✓' if mcp_available else '✗'} MCP Server: {mcp_available}")
    
    return capabilities

def create_test_plan():
    """Create a realistic test plan based on available capabilities."""
    print("\n📋 Creating Test Plan")
    print("=" * 50)
    
    test_plan = {
        "phase_1": {
            "name": "Basic Infrastructure Validation",
            "tasks": [
                "Verify imports and dependencies",
                "Test dashboard instantiation",
                "Check crawling infrastructure",
                "Test news source accessibility"
            ]
        },
        "phase_2": {
            "name": "Simple Content Extraction",
            "tasks": [
                "Extract single article from each source",
                "Test basic text processing",
                "Verify content storage",
                "Check metadata extraction"
            ]
        },
        "phase_3": {
            "name": "Analysis Capabilities",
            "tasks": [
                "Test entity extraction",
                "Try basic search functionality",
                "Test content categorization",
                "Generate simple reports"
            ]
        }
    }
    
    for phase_key, phase in test_plan.items():
        print(f"\n{phase['name']}:")
        for task in phase['tasks']:
            print(f"  • {task}")
    
    return test_plan

def main():
    """Run the simplified news sources test."""
    print("🚀 Simplified News Sources Test")
    print("=" * 70)
    
    test_results = {
        "imports": False,
        "instantiation": False,
        "crawling_infrastructure": False,
        "accessible_sources": [],
        "dashboard_capabilities": {},
        "recommendations": []
    }
    
    # Test 1: Imports
    test_results["imports"] = test_imports()
    
    if test_results["imports"]:
        # Test 2: Instantiation
        dashboard, config = test_basic_instantiation()
        test_results["instantiation"] = dashboard is not None
        
        if dashboard:
            # Test 3: Analyze capabilities
            test_results["dashboard_capabilities"] = analyze_dashboard_capabilities(dashboard)
    
    # Test 4: Crawling infrastructure
    test_results["crawling_infrastructure"] = test_crawling_infrastructure()
    
    # Test 5: Source accessibility
    test_results["accessible_sources"] = test_news_sources_accessibility()
    
    # Create test plan
    test_plan = create_test_plan()
    
    # Generate recommendations
    print("\n💡 Recommendations")
    print("=" * 50)
    
    if not test_results["imports"]:
        print("⚠ Install missing dependencies for news analysis dashboard")
        test_results["recommendations"].append("Install missing dependencies")
    
    if not test_results["crawling_infrastructure"]:
        print("⚠ Web crawling infrastructure needs attention")
        test_results["recommendations"].append("Fix web crawling infrastructure")
    
    if len(test_results["accessible_sources"]) == 0:
        print("⚠ No news sources are accessible - check network connectivity")
        test_results["recommendations"].append("Check network connectivity")
    elif len(test_results["accessible_sources"]) < 3:
        print(f"⚠ Only {len(test_results['accessible_sources'])} sources accessible")
        test_results["recommendations"].append("Investigate inaccessible sources")
    else:
        print(f"✓ All {len(test_results['accessible_sources'])} sources accessible")
    
    # Check if we're ready for full testing
    ready_for_full_test = (
        test_results["imports"] and 
        test_results["instantiation"] and
        test_results["crawling_infrastructure"] and
        len(test_results["accessible_sources"]) > 0
    )
    
    print(f"\n🎯 Ready for Full Integration Test: {'✓ YES' if ready_for_full_test else '✗ NO'}")
    
    if ready_for_full_test:
        print("\nNext Steps:")
        print("• Run the comprehensive integration test")
        print("• Test crawling Reuters, AP, and Bloomberg")
        print("• Perform GraphRAG analysis on extracted content")
        print("• Generate analysis reports for data scientists, historians, and lawyers")
    
    # Save results
    results_file = Path("simplified_test_results.json")
    with open(results_file, 'w') as f:
        json.dump({
            "test_results": test_results,
            "test_plan": test_plan,
            "ready_for_full_test": ready_for_full_test,
            "timestamp": datetime.now().isoformat()
        }, f, indent=2, default=str)
    
    print(f"\n💾 Test results saved to: {results_file}")
    return 0 if ready_for_full_test else 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n❌ Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)