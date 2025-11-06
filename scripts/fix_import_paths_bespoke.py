#!/usr/bin/env python3
"""
Auto-generated script to fix MCP tool import paths for bespoke_tools migration.
Updated to reference new bespoke_tools directory structure.
"""

import re
from pathlib import Path

def fix_import_paths():
    """Fix all invalid import paths for bespoke_tools migration."""
    fixes = [
        # tests/test_vector_tools.py - vector store tools moved to bespoke_tools
        (
            Path('tests/test_vector_tools.py'),
            r'from ipfs_datasets_py.mcp_server.tools.vector_store_tools.list_indices import list_indices',
            'from ipfs_datasets_py.mcp_server.tools.bespoke_tools.list_indices import list_indices',
        ),
        (
            Path('tests/test_vector_tools.py'),
            r'from ipfs_datasets_py.mcp_server.tools.vector_store_tools.delete_index import delete_index',
            'from ipfs_datasets_py.mcp_server.tools.bespoke_tools.delete_index import delete_index',
        ),
        
        # tests/test_comprehensive_integration.py - admin, cache, workflow tools moved to bespoke_tools
        (
            Path('tests/test_comprehensive_integration.py'),
            r'from ipfs_datasets_py.mcp_server.tools.admin_tools.system_health import system_health',
            'from ipfs_datasets_py.mcp_server.tools.bespoke_tools.system_health import system_health',
        ),
        (
            Path('tests/test_comprehensive_integration.py'),
            r'from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_stats import cache_stats',
            'from ipfs_datasets_py.mcp_server.tools.bespoke_tools.cache_stats import cache_stats',
        ),
        (
            Path('tests/test_comprehensive_integration.py'),
            r'from ipfs_datasets_py.mcp_server.tools.workflow_tools.execute_workflow import execute_workflow',
            'from ipfs_datasets_py.mcp_server.tools.bespoke_tools.execute_workflow import execute_workflow',
        ),
        
        # archive/validation/final_integration_test.py - vector store and admin tools
        (
            Path('archive/validation/final_integration_test.py'),
            r'from ipfs_datasets_py.mcp_server.tools.vector_store_tools.create_vector_store import create_vector_store',
            'from ipfs_datasets_py.mcp_server.tools.bespoke_tools.create_vector_store import create_vector_store',
        ),
        (
            Path('archive/validation/final_integration_test.py'),
            r'from ipfs_datasets_py.mcp_server.tools.admin_tools.system_status import system_status',
            'from ipfs_datasets_py.mcp_server.tools.bespoke_tools.system_status import system_status',
        ),
    ]
    
    fixes_applied = 0
    files_processed = set()
    
    for file_path, old_import, new_import in fixes:
        if file_path.exists():
            with open(file_path, 'r') as f:
                content = f.read()
            
            if old_import in content:
                content = content.replace(old_import, new_import)
                with open(file_path, 'w') as f:
                    f.write(content)
                print(f'Fixed: {file_path}')
                fixes_applied += 1
                files_processed.add(str(file_path))
            else:
                print(f'Warning: Pattern not found in {file_path}')
        else:
            print(f'Warning: File not found: {file_path}')
    
    print(f'\n✅ Applied {fixes_applied} fixes across {len(files_processed)} files')
    print('🎯 All tools moved to bespoke_tools directory and imports updated')

if __name__ == '__main__':
    fix_import_paths()
