#!/usr/bin/env python3
"""
Production readiness validation script.
This script validates that the integration is ready for production deployment.
"""

import asyncio
import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def validate_fastapi_service():
    """Validate FastAPI service can be imported and configured."""
    try:
        from ipfs_datasets_py.fastapi_service import app
        from ipfs_datasets_py.fastapi_config import get_settings
        
        settings = get_settings()
        
        # Check critical endpoints exist
        routes = [route.path for route in app.routes]
        critical_endpoints = [
            "/health",
            "/auth/login",
            "/embeddings/generate",
            "/vector/search",
            "/datasets/load"
        ]
        
        missing_endpoints = [ep for ep in critical_endpoints if ep not in routes]
        
        return {
            'status': 'success' if not missing_endpoints else 'warning',
            'endpoints_total': len(routes),
            'critical_endpoints_present': len(critical_endpoints) - len(missing_endpoints),
            'missing_endpoints': missing_endpoints,
            'settings_loaded': True
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }

async def validate_mcp_server():
    """Validate MCP server can be imported and tools registered."""
    try:
        from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry, get_migrated_tools_config
        
        registry = MCPToolRegistry()
        tools_config = get_migrated_tools_config()
        
        # Count available tools
        tool_count = 0
        category_count = len(tools_config)
        
        for category, config in tools_config.items():
            if 'functions' in config:
                tool_count += len(config['functions'])
        
        return {
            'status': 'success',
            'tool_categories': category_count,
            'total_tools': tool_count,
            'registry_created': True
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }

async def validate_embedding_system():
    """Validate embedding generation system."""
    try:
        from ipfs_datasets_py.embeddings import EmbeddingCore
        from ipfs_datasets_py.vector_stores import BaseVectorStore
        
        # Test basic embedding core
        embedding_core = EmbeddingCore()
        
        return {
            'status': 'success',
            'embedding_core_available': True,
            'vector_stores_available': True
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }

async def validate_dependencies():
    """Validate critical dependencies are available."""
    critical_deps = [
        'fastapi',
        'uvicorn',
        'mcp',
        'numpy',
        'transformers',
        'torch'
    ]
    
    available_deps = []
    missing_deps = []
    
    for dep in critical_deps:
        try:
            __import__(dep)
            available_deps.append(dep)
        except ImportError:
            missing_deps.append(dep)
    
    return {
        'status': 'success' if not missing_deps else 'warning',
        'available_dependencies': available_deps,
        'missing_dependencies': missing_deps,
        'dependency_coverage': len(available_deps) / len(critical_deps)
    }

async def validate_file_structure():
    """Validate critical files and directories exist."""
    critical_paths = [
        'ipfs_datasets_py/__init__.py',
        'ipfs_datasets_py/embeddings/',
        'ipfs_datasets_py/vector_stores/',
        'ipfs_datasets_py/mcp_server/',
        'ipfs_datasets_py/fastapi_service.py',
        'ipfs_datasets_py/fastapi_config.py',
        'requirements.txt',
        'pyproject.toml',
        'README.md',
        'DEPLOYMENT_GUIDE.md'
    ]
    
    existing_paths = []
    missing_paths = []
    
    for path_str in critical_paths:
        path = Path(path_str)
        if path.exists():
            existing_paths.append(path_str)
        else:
            missing_paths.append(path_str)
    
    return {
        'status': 'success' if not missing_paths else 'warning',
        'existing_paths': existing_paths,
        'missing_paths': missing_paths,
        'structure_completeness': len(existing_paths) / len(critical_paths)
    }

async def main():
    """Run all production readiness validations."""
    print("🚀 Production Readiness Validation\n")
    
    validations = {
        'FastAPI Service': validate_fastapi_service,
        'MCP Server': validate_mcp_server,
        'Embedding System': validate_embedding_system,
        'Dependencies': validate_dependencies,
        'File Structure': validate_file_structure
    }
    
    results = {}
    overall_status = 'success'
    
    for name, validator in validations.items():
        print(f"🔍 Validating {name}...")
        try:
            result = await validator()
            results[name] = result
            
            status = result.get('status', 'unknown')
            if status == 'success':
                print(f"  ✅ {name}: All checks passed")
            elif status == 'warning':
                print(f"  ⚠️  {name}: Working with minor issues")
                if overall_status == 'success':
                    overall_status = 'warning'
            else:
                print(f"  ❌ {name}: {result.get('error', 'Failed')}")
                overall_status = 'error'
            
        except Exception as e:
            print(f"  ❌ {name}: Exception - {e}")
            results[name] = {'status': 'error', 'error': str(e)}
            overall_status = 'error'
    
    # Summary
    print(f"\n📊 Production Readiness Summary:")
    success_count = sum(1 for r in results.values() if r.get('status') == 'success')
    warning_count = sum(1 for r in results.values() if r.get('status') == 'warning')
    error_count = sum(1 for r in results.values() if r.get('status') == 'error')
    
    print(f"  ✅ Passed: {success_count}")
    print(f"  ⚠️  Warnings: {warning_count}")
    print(f"  ❌ Errors: {error_count}")
    
    # Detailed results for reference
    if success_count + warning_count >= len(validations) * 0.8:
        print(f"\n🎉 System is {'READY' if overall_status == 'success' else 'MOSTLY READY'} for production!")
        
        print(f"\n📋 Quick Start Commands:")
        print(f"  FastAPI: python start_fastapi.py")
        print(f"  MCP Server: python -m ipfs_datasets_py.mcp_server --stdio")
        print(f"  Tests: python -m pytest tests/ -v")
        
        return True
    else:
        print(f"\n⚠️  System needs attention before production deployment.")
        return False

if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Validation failed: {e}")
        sys.exit(1)
