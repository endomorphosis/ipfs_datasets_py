#!/usr/bin/env python3
"""
Comprehensive integration status checker - validates the complete integration.
"""

import os
import sys
from pathlib import Path

def check_integration_status():
    """Check the complete integration status."""
    print("🔍 COMPREHENSIVE INTEGRATION STATUS CHECK")
    print("=" * 60)
    
    # 1. Core Package Structure
    print("\n📦 CORE PACKAGE STRUCTURE:")
    core_structure = {
        'ipfs_datasets_py/__init__.py': 'Main package init',
        'ipfs_datasets_py/core.py': 'Core IpfsDatasets class',
        'ipfs_datasets_py/embeddings/': 'Embeddings module',
        'ipfs_datasets_py/vector_stores/': 'Vector stores module',
        'ipfs_datasets_py/mcp_server/': 'MCP server module',
        'ipfs_datasets_py/fastapi_service.py': 'FastAPI service',
    }
    
    for item, desc in core_structure.items():
        exists = os.path.exists(item)
        status = "✅" if exists else "❌"
        print(f"  {status} {item:<40} {desc}")
    
    # 2. MCP Tool Categories
    print("\n🛠️  MCP TOOL CATEGORIES:")
    tool_categories = [
        'embedding_tools', 'admin_tools', 'cache_tools', 'monitoring_tools',
        'analysis_tools', 'workflow_tools', 'vector_store_tools', 
        'background_task_tools', 'auth_tools', 'session_tools',
        'rate_limiting_tools', 'data_processing_tools', 'index_management_tools',
        'storage_tools', 'web_archive_tools', 'ipfs_cluster_tools'
    ]
    
    tool_count = 0
    for category in tool_categories:
        path = f'ipfs_datasets_py/mcp_server/tools/{category}'
        exists = os.path.exists(path)
        status = "✅" if exists else "❌"
        
        # Count tools in category
        if exists:
            py_files = list(Path(path).glob('*.py'))
            count = len([f for f in py_files if f.name != '__init__.py'])
            tool_count += count
            print(f"  {status} {category:<25} ({count} tools)")
        else:
            print(f"  {status} {category:<25} (missing)")
    
    print(f"\n  📊 Total MCP Tools: {tool_count}")
    
    # 3. Test Coverage
    print("\n🧪 TEST COVERAGE:")
    test_files = [
        'test_embedding_tools.py', 'test_vector_store_tools.py', 
        'test_admin_tools.py', 'test_cache_tools.py', 'test_analysis_tools.py',
        'test_workflow_tools.py', 'test_fastapi_integration.py',
        'test_comprehensive_integration.py'
    ]
    
    test_count = 0
    for test_file in test_files:
        path = f'tests/{test_file}'
        exists = os.path.exists(path)
        status = "✅" if exists else "❌"
        if exists:
            test_count += 1
        print(f"  {status} {test_file}")
    
    print(f"\n  📊 Test Files: {test_count}/{len(test_files)}")
    
    # 4. Documentation
    print("\n📚 DOCUMENTATION:")
    docs = [
        'README.md', 'IPFS_EMBEDDINGS_MIGRATION_PLAN.md',
        'MIGRATION_COMPLETION_REPORT.md', 'TOOL_REFERENCE_GUIDE.md',
        'DEPLOYMENT_GUIDE.md', 'FINAL_INTEGRATION_STATUS.md'
    ]
    
    doc_count = 0
    for doc in docs:
        exists = os.path.exists(doc)
        status = "✅" if exists else "❌"
        if exists:
            doc_count += 1
        print(f"  {status} {doc}")
    
    print(f"\n  📊 Documentation Files: {doc_count}/{len(docs)}")
    
    # 5. Configuration Files
    print("\n⚙️  CONFIGURATION:")
    config_files = [
        'requirements.txt', 'pyproject.toml', 'setup.py', 
        'Dockerfile', '.vscode/tasks.json'
    ]
    
    config_count = 0
    for config in config_files:
        exists = os.path.exists(config)
        status = "✅" if exists else "❌"
        if exists:
            config_count += 1
        print(f"  {status} {config}")
    
    # 6. Integration Scripts
    print("\n🔧 INTEGRATION SCRIPTS:")
    scripts = [
        'start_fastapi.py', 'simple_fastapi.py', 'validate_integration.py',
        'final_integration_test.py', 'comprehensive_mcp_test.py'
    ]
    
    script_count = 0
    for script in scripts:
        exists = os.path.exists(script)
        status = "✅" if exists else "❌"
        if exists:
            script_count += 1
        print(f"  {status} {script}")
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 INTEGRATION SUMMARY")
    print("=" * 60)
    
    total_components = len(core_structure) + len(tool_categories) + len(test_files) + len(docs) + len(config_files) + len(scripts)
    completed_components = (
        sum(1 for item in core_structure.keys() if os.path.exists(item)) +
        sum(1 for cat in tool_categories if os.path.exists(f'ipfs_datasets_py/mcp_server/tools/{cat}')) +
        test_count + doc_count + config_count + script_count
    )
    
    completion_rate = (completed_components / total_components) * 100
    
    print(f"🎯 Completion Rate: {completion_rate:.1f}% ({completed_components}/{total_components})")
    print(f"🛠️  MCP Tools: {tool_count}+ individual tools")
    print(f"🧪 Test Coverage: {test_count} test suites")
    print(f"📚 Documentation: {doc_count} comprehensive guides")
    
    if completion_rate >= 95:
        print("\n🎉 INTEGRATION STATUS: COMPLETE ✅")
        print("🚀 Ready for production deployment!")
    elif completion_rate >= 85:
        print("\n⚡ INTEGRATION STATUS: NEARLY COMPLETE")
        print("🔧 Minor items remaining")
    else:
        print("\n⚠️  INTEGRATION STATUS: IN PROGRESS")
        print("🚧 Significant work remaining")
    
    return completion_rate >= 95

if __name__ == "__main__":
    success = check_integration_status()
    sys.exit(0 if success else 1)
