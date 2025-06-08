#!/usr/bin/env python3
"""
FastAPI Integration Validation Script

This script validates that the FastAPI service can be imported and initialized correctly.
"""

import sys
import logging
import traceback
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def test_import_fastapi_service():
    """Test importing the FastAPI service module."""
    try:
        logger.info("🔍 Testing FastAPI service import...")
        
        # Test import of main module
        from ipfs_datasets_py.fastapi_service import app, settings
        logger.info("✅ FastAPI service module imported successfully")
        
        # Test app instance
        if app is not None:
            logger.info(f"✅ FastAPI app instance created: {app.title}")
        else:
            logger.error("❌ FastAPI app instance is None")
            return False
        
        # Test settings
        if settings is not None:
            logger.info(f"✅ Settings loaded: {settings.app_name} v{settings.app_version}")
        else:
            logger.error("❌ Settings instance is None")
            return False
        
        return True
        
    except ImportError as e:
        logger.error(f"❌ Import error: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error during import: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def test_fastapi_config():
    """Test FastAPI configuration."""
    try:
        logger.info("🔍 Testing FastAPI configuration...")
        
        from ipfs_datasets_py.fastapi_config import FastAPISettings
        
        # Create settings instance
        settings = FastAPISettings()
        logger.info(f"✅ Configuration loaded: {settings.app_name}")
        logger.info(f"  - Environment: {settings.environment}")
        logger.info(f"  - Debug mode: {settings.debug}")
        logger.info(f"  - Host: {settings.host}")
        logger.info(f"  - Port: {settings.port}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Configuration test failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def test_fastapi_routes():
    """Test FastAPI routes are properly defined."""
    try:
        logger.info("🔍 Testing FastAPI routes...")
        
        from ipfs_datasets_py.fastapi_service import app
        
        # Get all routes
        routes = []
        for route in app.routes:
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                routes.append((route.path, list(route.methods)))
        
        logger.info(f"✅ Found {len(routes)} routes:")
        
        # Expected key routes
        expected_routes = [
            "/health",
            "/auth/login",
            "/embeddings/generate",
            "/datasets/load",
            "/tools/list",
            "/admin/stats"
        ]
        
        found_routes = [path for path, _ in routes]
        
        for expected in expected_routes:
            if expected in found_routes:
                logger.info(f"  ✅ {expected}")
            else:
                logger.warning(f"  ⚠️ {expected} (not found)")
        
        return len(routes) > 0
        
    except Exception as e:
        logger.error(f"❌ Routes test failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def test_dependencies():
    """Test that required dependencies are available."""
    try:
        logger.info("🔍 Testing dependencies...")
        
        # Test core dependencies
        dependencies = [
            "fastapi",
            "uvicorn",
            "pydantic",
            "jwt",
            "passlib",
            "aiohttp"
        ]
        
        missing = []
        for dep in dependencies:
            try:
                __import__(dep)
                logger.info(f"  ✅ {dep}")
            except ImportError:
                logger.warning(f"  ⚠️ {dep} (missing)")
                missing.append(dep)
        
        if missing:
            logger.warning(f"Missing dependencies: {missing}")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Dependencies test failed: {e}")
        return False

def test_mcp_integration():
    """Test MCP integration components."""
    try:
        logger.info("🔍 Testing MCP integration...")
        
        # Test MCP server import
        try:
            from ipfs_datasets_py.mcp_server.server import MCPServer
            logger.info("  ✅ MCP server import")
        except ImportError as e:
            logger.warning(f"  ⚠️ MCP server import failed: {e}")
            return False
        
        # Test tool imports
        tool_categories = [
            "embedding_tools",
            "dataset_tools", 
            "analysis_tools",
            "workflow_tools",
            "admin_tools"
        ]
        
        for category in tool_categories:
            try:
                module_path = f"ipfs_datasets_py.mcp_server.tools.{category}"
                __import__(module_path)
                logger.info(f"  ✅ {category}")
            except ImportError as e:
                logger.warning(f"  ⚠️ {category}: {e}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ MCP integration test failed: {e}")
        return False

def main():
    """Main validation function."""
    logger.info("🚀 FastAPI Integration Validation")
    logger.info("=" * 50)
    
    tests = [
        ("Dependencies", test_dependencies),
        ("FastAPI Config", test_fastapi_config),
        ("FastAPI Service Import", test_import_fastapi_service),
        ("FastAPI Routes", test_fastapi_routes),
        ("MCP Integration", test_mcp_integration)
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        logger.info(f"\n📋 Running {test_name} test...")
        try:
            results[test_name] = test_func()
        except Exception as e:
            logger.error(f"❌ {test_name} test crashed: {e}")
            results[test_name] = False
    
    # Print summary
    logger.info("\n" + "=" * 50)
    logger.info("📊 Validation Results:")
    
    passed = 0
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"  {test_name}: {status}")
        if result:
            passed += 1
    
    logger.info(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All validation tests passed! FastAPI service is ready.")
        return 0
    else:
        logger.warning(f"⚠️ {total - passed} validation tests failed")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
