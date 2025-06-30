#!/usr/bin/env python3
"""
Comprehensive Integration Validation Script

Tests the complete ipfs_embeddings_py integration to verify all components
are working correctly after the migration.
"""

import sys
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Any

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class IntegrationValidator:
    """Comprehensive validation of the ipfs_embeddings_py integration."""
    
    def __init__(self):
        self.results = {
            "core_modules": {},
            "embedding_tools": {},
            "vector_stores": {},
            "mcp_tools": {},
            "tool_registration": {},
            "feature_flags": {}
        }
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0

    def test_passed(self, test_name: str, category: str):
        """Record a passed test."""
        self.results[category][test_name] = "PASSED"
        self.total_tests += 1
        self.passed_tests += 1
        logger.info(f"✅ {test_name}: PASSED")

    def test_failed(self, test_name: str, category: str, error: str):
        """Record a failed test."""
        self.results[category][test_name] = f"FAILED: {error}"
        self.total_tests += 1
        self.failed_tests += 1
        logger.error(f"❌ {test_name}: FAILED - {error}")

    def test_core_modules(self):
        """Test core module imports and functionality."""
        logger.info("🔍 Testing core modules...")
        
        # Test embeddings module
        try:
            from ipfs_datasets_py.embeddings import core, schema, chunker
            from ipfs_datasets_py.embeddings.core import EmbeddingCore
            self.test_passed("Embeddings Core Import", "core_modules")
        except Exception as e:
            self.test_failed("Embeddings Core Import", "core_modules", str(e))

        # Test vector stores module
        try:
            from ipfs_datasets_py.vector_stores import base, qdrant_store, elasticsearch_store, faiss_store
            from ipfs_datasets_py.vector_stores.base import VectorStoreBase
            self.test_passed("Vector Stores Import", "core_modules")
        except Exception as e:
            self.test_failed("Vector Stores Import", "core_modules", str(e))

        # Test main package exposure
        try:
            import ipfs_datasets_py
            # Check if new features are exposed
            has_embeddings = hasattr(ipfs_datasets_py, 'embeddings') or hasattr(ipfs_datasets_py, 'EmbeddingCore')
            has_vector_stores = hasattr(ipfs_datasets_py, 'vector_stores') or hasattr(ipfs_datasets_py, 'VectorStoreBase')
            
            if has_embeddings and has_vector_stores:
                self.test_passed("Main Package Exposure", "core_modules")
            else:
                self.test_failed("Main Package Exposure", "core_modules", "Features not exposed in main package")
        except Exception as e:
            self.test_failed("Main Package Exposure", "core_modules", str(e))

    def test_embedding_tools(self):
        """Test embedding tools functionality."""
        logger.info("🔍 Testing embedding tools...")
        
        # Test advanced embedding generation
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_embedding_generation import generate_embedding
            self.test_passed("Advanced Embedding Generation", "embedding_tools")
        except Exception as e:
            self.test_failed("Advanced Embedding Generation", "embedding_tools", str(e))

        # Test advanced search
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_search import semantic_search
            self.test_passed("Advanced Search", "embedding_tools")
        except Exception as e:
            self.test_failed("Advanced Search", "embedding_tools", str(e))

        # Test shard embeddings
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.shard_embeddings import shard_embeddings_by_dimension
            self.test_passed("Shard Embeddings", "embedding_tools")
        except Exception as e:
            self.test_failed("Shard Embeddings", "embedding_tools", str(e))

    def test_vector_stores(self):
        """Test vector store implementations."""
        logger.info("🔍 Testing vector stores...")
        
        # Test Qdrant store
        try:
            from ipfs_datasets_py.vector_stores.qdrant_store import QdrantVectorStore
            store = QdrantVectorStore("test_collection")
            self.test_passed("Qdrant Vector Store", "vector_stores")
        except Exception as e:
            self.test_failed("Qdrant Vector Store", "vector_stores", str(e))

        # Test Elasticsearch store
        try:
            from ipfs_datasets_py.vector_stores.elasticsearch_store import ElasticsearchVectorStore
            store = ElasticsearchVectorStore("test_index")
            self.test_passed("Elasticsearch Vector Store", "vector_stores")
        except Exception as e:
            self.test_failed("Elasticsearch Vector Store", "vector_stores", str(e))

        # Test FAISS store
        try:
            from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
            self.test_passed("FAISS Vector Store", "vector_stores")
        except Exception as e:
            self.test_failed("FAISS Vector Store", "vector_stores", str(e))

    async def test_mcp_tools(self):
        """Test MCP tools functionality."""
        logger.info("🔍 Testing MCP tools...")
        
        # Test analysis tools
        try:
            from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import cluster_analysis
            result = await cluster_analysis(algorithm="kmeans", n_clusters=3)
            if result.get("status") == "success":
                self.test_passed("Analysis Tools", "mcp_tools")
            else:
                self.test_failed("Analysis Tools", "mcp_tools", "Invalid result status")
        except Exception as e:
            self.test_failed("Analysis Tools", "mcp_tools", str(e))

        # Test workflow tools
        try:
            from ipfs_datasets_py.mcp_server.tools.workflow_tools.workflow_tools import workflow_orchestration
            result = await workflow_orchestration(workflow_name="test_workflow")
            if result.get("status") == "success":
                self.test_passed("Workflow Tools", "mcp_tools")
            else:
                self.test_failed("Workflow Tools", "mcp_tools", "Invalid result status")
        except Exception as e:
            self.test_failed("Workflow Tools", "mcp_tools", str(e))

        # Test monitoring tools
        try:
            from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import system_monitoring
            result = await system_monitoring()
            if result.get("status") == "success":
                self.test_passed("Monitoring Tools", "mcp_tools")
            else:
                self.test_failed("Monitoring Tools", "mcp_tools", "Invalid result status")
        except Exception as e:
            self.test_failed("Monitoring Tools", "mcp_tools", str(e))

    def test_tool_registration(self):
        """Test tool registration system."""
        logger.info("🔍 Testing tool registration...")
        
        # Test enhanced embedding tools registration
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.tool_registration import register_enhanced_embedding_tools, get_tool_manifest
            tools = register_enhanced_embedding_tools()
            manifest = get_tool_manifest()
            
            if len(tools) > 0 and manifest.get("total_tools", 0) > 0:
                self.test_passed("Enhanced Embedding Tools Registration", "tool_registration")
            else:
                self.test_failed("Enhanced Embedding Tools Registration", "tool_registration", "No tools registered")
        except Exception as e:
            self.test_failed("Enhanced Embedding Tools Registration", "tool_registration", str(e))

        # Test main tool registration
        try:
            from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry
            registry = MCPToolRegistry()
            self.test_passed("Main Tool Registry", "tool_registration")
        except Exception as e:
            self.test_failed("Main Tool Registry", "tool_registration", str(e))

    def test_feature_flags(self):
        """Test feature flags and integration status."""
        logger.info("🔍 Testing feature flags...")
        
        try:
            import ipfs_datasets_py
            
            # Check for feature flags
            if hasattr(ipfs_datasets_py, 'FEATURES'):
                features = ipfs_datasets_py.FEATURES
                self.test_passed("Feature Flags Available", "feature_flags")
                
                # Check specific features
                embedding_features = ['ENHANCED_EMBEDDINGS', 'VECTOR_STORES', 'ADVANCED_SEARCH']
                available_features = [f for f in embedding_features if features.get(f, False)]
                
                if len(available_features) > 0:
                    self.test_passed(f"Embedding Features ({len(available_features)} enabled)", "feature_flags")
                else:
                    self.test_failed("Embedding Features", "feature_flags", "No embedding features enabled")
            else:
                self.test_failed("Feature Flags Available", "feature_flags", "Feature flags not found")
                
        except Exception as e:
            self.test_failed("Feature Flags Test", "feature_flags", str(e))

    async def run_all_tests(self):
        """Run all validation tests."""
        logger.info("🚀 Starting comprehensive integration validation...")
        logger.info("=" * 60)
        
        # Run all test categories
        self.test_core_modules()
        self.test_embedding_tools()
        self.test_vector_stores()
        await self.test_mcp_tools()
        self.test_tool_registration()
        self.test_feature_flags()
        
        # Print summary
        logger.info("=" * 60)
        logger.info("📋 VALIDATION SUMMARY")
        logger.info("=" * 60)
        
        for category, tests in self.results.items():
            logger.info(f"\n📂 {category.upper()}:")
            for test_name, result in tests.items():
                status_icon = "✅" if result == "PASSED" else "❌"
                logger.info(f"  {status_icon} {test_name}: {result}")
        
        # Overall results
        success_rate = (self.passed_tests / self.total_tests * 100) if self.total_tests > 0 else 0
        logger.info(f"\n🎯 OVERALL RESULTS:")
        logger.info(f"  📊 Total Tests: {self.total_tests}")
        logger.info(f"  ✅ Passed: {self.passed_tests}")
        logger.info(f"  ❌ Failed: {self.failed_tests}")
        logger.info(f"  📈 Success Rate: {success_rate:.1f}%")
        
        if success_rate >= 80:
            logger.info(f"\n🎉 INTEGRATION STATUS: EXCELLENT ({success_rate:.1f}%)")
            logger.info("✅ Ready for Phase 4 - FastAPI Integration")
        elif success_rate >= 60:
            logger.info(f"\n⚠️  INTEGRATION STATUS: GOOD ({success_rate:.1f}%)")
            logger.info("🔧 Some issues need attention before Phase 4")
        else:
            logger.info(f"\n❌ INTEGRATION STATUS: NEEDS WORK ({success_rate:.1f}%)")
            logger.info("🚨 Significant issues need to be resolved")
        
        return success_rate >= 80

async def main():
    """Main validation function."""
    validator = IntegrationValidator()
    success = await validator.run_all_tests()
    
    if success:
        logger.info("\n🎯 Next Steps:")
        logger.info("  1. Begin Phase 4 - FastAPI Integration")
        logger.info("  2. Implement authentication and authorization")
        logger.info("  3. Add performance monitoring and metrics")
        logger.info("  4. Create comprehensive documentation")
    else:
        logger.info("\n🔧 Required Actions:")
        logger.info("  1. Fix failing tests")
        logger.info("  2. Update package __init__.py files")
        logger.info("  3. Verify tool registration system")
        logger.info("  4. Re-run validation")
    
    return success

if __name__ == "__main__":
    asyncio.run(main())
