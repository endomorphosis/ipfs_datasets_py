#!/usr/bin/env python3
"""
Preview script for project reorganization.
Shows what files would be moved without actually moving them.
"""

import os
from pathlib import Path
from collections import defaultdict

def preview_reorganization():
    """Preview what the reorganization would do."""
    root_path = Path(".")
    
    # Essential files that stay in root
    essential_root_files = {
        'README.md', 'LICENSE', 'requirements.txt', 'pyproject.toml', 
        'setup.py', 'Dockerfile', 'pytest.ini', 'uv.lock', '.gitignore',
        '__init__.py'
    }
    
    # Migration documentation patterns
    migration_doc_patterns = [
        'MCP_', 'COMPLETE_', 'FINAL_', 'MIGRATION_', 'RESTART_', 'SERVER_',
        'IMPLEMENTATION_', 'DOCUMENTATION_', 'PHASE', 'VERIFICATION_',
        'CLEANUP_', 'FFMPEG_', 'PDF_', 'YTDLP_', 'POST_'
    ]
    
    # Test file patterns  
    test_patterns = [
        'test_', 'comprehensive_', 'debug_', 'simple_', 'quick_', 'minimal_',
        'run_', 'validate_', 'check_', 'final_', 'direct_'
    ]
    
    # Script patterns
    script_patterns = [
        'fix_', 'verify_', 'install_', 'mcp_', 'dependency_', 'project_',
        'migration_', 'list_', 'server_'
    ]
    
    # Active examples to keep accessible
    active_examples = {
        'demo_multimedia_final.py',
        'validate_multimedia_simple.py', 
        'test_multimedia_comprehensive.py',
        'demo_mcp_server.py'
    }
    
    # Log and result files
    log_result_patterns = [
        '.log', '.json', '_output', '_results', '_status'
    ]
    
    # Scan and classify files
    classifications = defaultdict(list)
    
    for item in root_path.iterdir():
        if item.is_file():
            filename = item.name
            
            # Skip hidden files and directories  
            if filename.startswith('.') and filename not in essential_root_files:
                continue
                
            # Essential root files
            if filename in essential_root_files:
                classifications['✅ KEEP IN ROOT'].append(filename)
            
            # Active examples
            elif filename in active_examples:
                classifications['📝 MOVE TO examples/'].append(filename)
            
            # Migration documentation
            elif (any(filename.startswith(pattern) for pattern in migration_doc_patterns) and 
                  filename.endswith('.md')):
                classifications['📚 MOVE TO archive/migration_docs/'].append(filename)
            
            # Test files
            elif (any(filename.startswith(pattern) for pattern in test_patterns) and 
                  filename.endswith('.py')):
                classifications['🧪 MOVE TO archive/migration_tests/'].append(filename)
            
            # Utility scripts
            elif (any(filename.startswith(pattern) for pattern in script_patterns) and 
                  filename.endswith('.py')):
                classifications['🔧 MOVE TO archive/migration_scripts/'].append(filename)
            
            # Log and result files
            elif any(filename.endswith(pattern) for pattern in log_result_patterns):
                classifications['📊 MOVE TO archive/development_history/'].append(filename)
            
            # Unknown files
            else:
                classifications['❓ MOVE TO archive/experiments/ (REVIEW NEEDED)'].append(filename)
    
    # Display preview
    print("🔍 PROJECT REORGANIZATION PREVIEW")
    print("=" * 80)
    print(f"📁 Total files in root directory: {sum(len(files) for files in classifications.values())}")
    print()
    
    for category, files in classifications.items():
        if files:
            print(f"{category} ({len(files)} files)")
            print("-" * 60)
            for filename in sorted(files):
                print(f"  • {filename}")
            print()
    
    # Summary statistics
    keep_count = len(classifications['✅ KEEP IN ROOT'])
    move_count = sum(len(files) for category, files in classifications.items() 
                    if not category.startswith('✅'))
    
    print("📊 REORGANIZATION SUMMARY")
    print("=" * 80)
    print(f"✅ Files to keep in root: {keep_count}")
    print(f"📦 Files to move: {move_count}")
    print(f"📁 Final root directory size: {keep_count} files")
    print()
    
    if keep_count <= 15:
        print("🎯 ✅ Target achieved: Root directory will have ≤15 files")
    else:
        print("⚠️ Target missed: Root directory will still have >15 files")
    
    print()
    print("🚀 TO PROCEED WITH REORGANIZATION:")
    print("   Run: python enhanced_reorganization_script.py")
    print()
    print("📋 WHAT WILL HAPPEN:")
    print("   1. Create backup of current state")
    print("   2. Create organized directory structure") 
    print("   3. Move files to appropriate locations")
    print("   4. Create navigation and index files")
    print("   5. Generate rollback script")
    print("   6. Validate the reorganization")
    print()


if __name__ == "__main__":
    preview_reorganization()
