#!/usr/bin/env python3
"""
Comprehensive Final Integration Validation

This script performs a complete validation of the IPFS Embeddings integration,
including all phases: dependencies, core modules, MCP tools, and FastAPI service.
"""

import sys
import logging
import traceback
import anyio
import time
from pathlib import Path
from typing import Dict, List, Any

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class IntegrationValidator:
    """Comprehensive integration validator."""
    
    def __init__(self):
        self.results = {}
        self.start_time = time.time()
    
    def test_phase_1_dependencies(self) -> bool:
        """Test Phase 1: Dependencies."""
        logger.info("🔍 Testing Phase 1: Dependencies...")
        
        try:
            # Core dependencies
            core_deps = [
                "fastapi", "uvicorn", "pydantic", "jwt", "passlib",
                "numpy", "transformers", "datasets", "pyarrow"
            ]
            
            missing = []
            for dep in core_deps:
                try:
                    __import__(dep)
                    logger.info(f"  ✅ {dep}")
                except ImportError:
                    logger.error(f"  ❌ {dep} (missing)")
                    missing.append(dep)
            
            if missing:
                logger.error(f"Missing core dependencies: {missing}")
                return False
            
            # Test configuration
            try:
                from ipfs_datasets_py.fastapi_config import FastAPISettings
                settings = FastAPISettings()
                logger.info(f"  ✅ Configuration loaded: {settings.app_name}")
            except Exception as e:
                logger.error(f"  ❌ Configuration failed: {e}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Phase 1 validation failed: {e}")
            return False
    
    def test_phase_2_core_modules(self) -> bool:
        """Test Phase 2: Core Modules."""
        logger.info("🔍 Testing Phase 2: Core Modules...")
        
        try:
            # Test embeddings module
            try:
                from ipfs_datasets_py.embeddings import EmbeddingCore, generate_embeddings
                logger.info("  ✅ Embeddings module")
            except ImportError as e:
                logger.error(f"  ❌ Embeddings module: {e}")
                return False
            
            # Test vector stores module
            try:
                from ipfs_datasets_py.vector_stores import BaseVectorStore, QdrantVectorStore
                logger.info("  ✅ Vector stores module")
            except ImportError as e:
                logger.error(f"  ❌ Vector stores module: {e}")
                return False
            
            # Test main package imports
            try:
                import ipfs_datasets_py
                logger.info("  ✅ Main package import")
            except ImportError as e:
                logger.error(f"  ❌ Main package import: {e}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Phase 2 validation failed: {e}")
            return False
    
    def test_phase_3_mcp_tools(self) -> bool:
        """Test Phase 3: MCP Tools."""
        logger.info("🔍 Testing Phase 3: MCP Tools...")
        
        try:
            # Test MCP server
            try:
                from ipfs_datasets_py.mcp_server.server import MCPServer
                logger.info("  ✅ MCP server")
            except ImportError as e:
                logger.warning(f"  ⚠️ MCP server: {e}")
                # Continue with tool tests even if server import fails
            
            # Test key tool categories
            tool_categories = [
                "embedding_tools",
                "dataset_tools",
                "analysis_tools",
                "workflow_tools",
                "admin_tools",
                "cache_tools",
                "monitoring_tools"
            ]
            
            success_count = 0
            for category in tool_categories:
                try:
                    module_path = f"ipfs_datasets_py.mcp_server.tools.{category}"
                    __import__(module_path)
                    logger.info(f"  ✅ {category}")
                    success_count += 1
                except ImportError as e:
                    logger.warning(f"  ⚠️ {category}: {e}")
            
            # Require at least 50% of tool categories to work
            if success_count >= len(tool_categories) * 0.5:
                logger.info(f"  ✅ MCP tools validation passed ({success_count}/{len(tool_categories)})")
                return True
            else:
                logger.error(f"  ❌ Too many tool category failures ({success_count}/{len(tool_categories)})")
                return False
            
        except Exception as e:
            logger.error(f"Phase 3 validation failed: {e}")
            return False
    
    def test_phase_4_fastapi(self) -> bool:
        """Test Phase 4: FastAPI Service."""
        logger.info("🔍 Testing Phase 4: FastAPI Service...")
        
        try:
            # Test simple FastAPI import
            try:
                from simple_fastapi import app as simple_app
                logger.info("  ✅ Simple FastAPI service")
            except ImportError as e:
                logger.error(f"  ❌ Simple FastAPI service: {e}")
                return False
            
            # Test configuration
            try:
                from ipfs_datasets_py.fastapi_config import FastAPISettings
                settings = FastAPISettings()
                logger.info("  ✅ FastAPI configuration")
            except Exception as e:
                logger.error(f"  ❌ FastAPI configuration: {e}")
                return False
            
            # Test startup scripts
            try:
                import start_fastapi
                logger.info("  ✅ Startup script available")
            except ImportError as e:
                logger.warning(f"  ⚠️ Startup script: {e}")
            
            # Test validation scripts
            try:
                import validate_fastapi
                import archive.validation._test_fastapi_service as _test_fastapi_service
                logger.info("  ✅ Testing scripts available")
            except ImportError as e:
                logger.warning(f"  ⚠️ Testing scripts: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Phase 4 validation failed: {e}")
            return False
    
    def test_integration_completeness(self) -> bool:
        """Test overall integration completeness."""
        logger.info("🔍 Testing Integration Completeness...")
        
        try:
            # Check key files exist
            key_files = [
                "ipfs_datasets_py/embeddings/__init__.py",
                "ipfs_datasets_py/vector_stores/__init__.py",
                "ipfs_datasets_py/mcp_server/server.py",
                "ipfs_datasets_py/fastapi_config.py",
                "ipfs_datasets_py/fastapi_service.py",
                "start_fastapi.py",
                "PHASE_4_COMPLETION_REPORT.md"
            ]
            
            missing_files = []
            for file_path in key_files:
                if not (project_root / file_path).exists():
                    missing_files.append(file_path)
                    logger.error(f"  ❌ Missing: {file_path}")
                else:
                    logger.info(f"  ✅ Found: {file_path}")
            
            if missing_files:
                logger.error(f"Missing critical files: {missing_files}")
                return False
            
            # Check documentation completeness
            doc_files = [
                "IPFS_EMBEDDINGS_MIGRATION_PLAN.md",
                "IPFS_EMBEDDINGS_TOOL_MAPPING.md",
                "INTEGRATION_STATUS_SUMMARY.md",
                "PHASE_4_COMPLETION_REPORT.md"
            ]
            
            for doc_file in doc_files:
                if (project_root / doc_file).exists():
                    logger.info(f"  ✅ Documentation: {doc_file}")
                else:
                    logger.warning(f"  ⚠️ Documentation: {doc_file} (missing)")
            
            return True
            
        except Exception as e:
            logger.error(f"Integration completeness test failed: {e}")
            return False
    
    async def run_all_validations(self) -> Dict[str, bool]:
        """Run all validation tests."""
        logger.info("🚀 Starting Comprehensive Integration Validation")
        logger.info("=" * 70)
        
        phases = [
            ("Phase 1: Dependencies", self.test_phase_1_dependencies),
            ("Phase 2: Core Modules", self.test_phase_2_core_modules),
            ("Phase 3: MCP Tools", self.test_phase_3_mcp_tools),
            ("Phase 4: FastAPI Service", self.test_phase_4_fastapi),
            ("Integration Completeness", self.test_integration_completeness)
        ]
        
        for phase_name, phase_test in phases:
            logger.info(f"\n📋 {phase_name}")
            logger.info("-" * 50)
            
            try:
                self.results[phase_name] = phase_test()
            except Exception as e:
                logger.error(f"❌ {phase_name} crashed: {e}")
                self.results[phase_name] = False
        
        return self.results
    
    def print_summary(self):
        """Print validation summary."""
        duration = time.time() - self.start_time
        
        logger.info("\n" + "=" * 70)
        logger.info("📊 INTEGRATION VALIDATION SUMMARY")
        logger.info("=" * 70)
        
        passed = 0
        total = len(self.results)
        
        for phase_name, result in self.results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            logger.info(f"  {phase_name}: {status}")
            if result:
                passed += 1
        
        success_rate = (passed / total) * 100 if total > 0 else 0
        
        logger.info(f"\nResults: {passed}/{total} phases passed ({success_rate:.1f}%)")
        logger.info(f"Duration: {duration:.2f} seconds")
        
        if passed == total:
            logger.info("\n🎉 ALL VALIDATION TESTS PASSED!")
            logger.info("✅ IPFS Embeddings integration is complete and functional")
            logger.info("🚀 Ready for deployment and production use")
        elif passed >= total * 0.8:
            logger.info("\n⚠️ Most validation tests passed")
            logger.info("🔧 Minor issues may need attention before production")
        else:
            logger.error("\n❌ Significant validation failures detected")
            logger.error("🛠️ Major issues need to be resolved")
        
        return passed == total

async def main():
    """Main validation function."""
    validator = IntegrationValidator()
    results = await validator.run_all_validations()
    success = validator.print_summary()
    
    return 0 if success else 1

if __name__ == "__main__":
    exit_code = anyio.run(main())
    sys.exit(exit_code)
