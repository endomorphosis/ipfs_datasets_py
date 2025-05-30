#!/usr/bin/env python3
"""
Root Directory Cleanup Script
Organizes files created during the MCP migration process.
"""

import os
import shutil
from pathlib import Path

def create_cleanup_directories():
    """Create directories for organizing files."""
    directories = [
        "migration_docs",
        "migration_tests", 
        "migration_scripts",
        "migration_logs",
        "migration_temp"
    ]
    
    for dir_name in directories:
        Path(dir_name).mkdir(exist_ok=True)
        print(f"✅ Created directory: {dir_name}")

def organize_files():
    """Organize files by type and purpose."""
    
    # Files to keep in root (essential)
    keep_in_root = {
        'README.md',
        'LICENSE', 
        'requirements.txt',
        'pyproject.toml',
        'setup.py',
        'Dockerfile',
        '__init__.py',
        'pytest.ini',
        '.gitignore'
    }
    
    # Migration documentation
    migration_docs = {
        'CLAUDES_TOOLBOX_MIGRATION_ROADMAP.md',
        'CLEANUP_PLAN.md',
        'CLEANUP_SUMMARY.md', 
        'DEVELOPMENT_TOOLS_README.md',
        'DEVELOPMENT_TOOLS_REFERENCE.md',
        'FINAL_TESTING_SUMMARY.md',
        'LINTING_TOOLS_GUIDE.md',
        'MCP_CONFIGURATION_SUMMARY.md',
        'MCP_SERVER.md',
        'MCP_SERVER_RESTART_GUIDE.md',
        'MIGRATION_ANALYSIS.md',
        'MIGRATION_COMPLETION_REPORT.md',
        'MIGRATION_FINAL_SUMMARY.md',
        'MIGRATION_READY.txt',
        'MIGRATION_STATUS.md',
        'MIGRATION_STATUS_UPDATED.md',
        'MIGRATION_VERIFICATION_REPORT.md',
        'MODULE_CREATION_SUMMARY.md',
        'PHASE1_COMPLETE.md',
        'PHASE2_PLANNING.md', 
        'PHASE_1_IMPLEMENTATION.md',
        'README_FINAL_STEPS.md',
        'RESTART_NOW.md',
        'SERVER_RESTART_VERIFICATION.md',
        'VSCODE_INTEGRATION_TESTING.md',
        'VSCODE_MCP_GUIDE.md',
        'import_fix_summary.md',
        'mcp_test_analysis.md'
    }
    
    # Test files
    test_files = {
        'comprehensive_mcp_test.py',
        'comprehensive_mcp_tools_test.py',
        'comprehensive_mcp_tools_tester.py',
        'comprehensive_migration_test.py',
        'comprehensive_tool_test.py',
        'correct_import_test.py',
        'debug_config_paths.py',
        'debug_function_discovery.py',
        'debug_lint_test.py',
        'debug_lint_test_final.py',
        'debug_lint_test_fixed.py',
        'debug_mcp_format.py',
        'debug_test.py',
        'debug_tool.py',
        'diagnostic_test.py',
        'direct_test_runner_test.py',
        'direct_tool_test.py',
        'end_to_end_dev_tools_test.py',
        'end_to_end_test.py',
        'final_comprehensive_test_report.py',
        'final_status_check.py',
        'final_test_summary.py',
        'final_verification.py',
        'fixed_dev_tools_test.py',
        'full_diagnostic_test.py',
        'improved_mcp_tools_test.py',
        'minimal_import_test.py',
        'minimal_import_test_v2.py',
        'minimal_test.py',
        'minimal_test_runner_test.py',
        'quick_execution_test.py',
        'quick_import_test.py',
        'quick_integration_test.py',
        'run_all_tests.py',
        'simple_dev_tools_test.py',
        'simple_mcp_tools_test.py',
        'simple_run_test.py',
        'simple_test.py',
        'simple_test_runner.py',
        'simple_tool_check.py',
        'simple_tool_discovery.py',
        'simple_tool_test.py',
        'simple_web_archive_test.py',
        'test_all_mcp_tools.py',
        'test_analysis_and_generation.py',
        'test_config_only.py',
        'test_copilot_mcp_integration.py',
        'test_development_tools_import.py',
        'test_direct_config.py',
        'test_imports.py',
        'test_imports_final.py',
        'test_imports_fixed.py',
        'test_individual_tools.py',
        'test_mcp_discovery.py',
        'test_mcp_functionality.py',
        'test_mcp_runner.py',
        'test_mcp_setup.py',
        'test_mcp_startup.py',
        'test_mcp_tools_comprehensive.py',
        'test_multiple_tools.py',
        'test_phase1_status.py',
        'test_post_restart.py',
        'test_runner_debug.py',
        'test_runner_detailed_debug.py',
        'test_test_generator.py',
        'test_tool_imports_direct.py',
        'test_tools_directly.py',
        'test_validation_corrected.py',
        'test_validation_quick.py',
        'test_wrapper_behavior.py',
        'validate_phase1.py',
        'validate_tools.py',
        'vscode_integration_test.py'
    }
    
    # Script files
    script_files = {
        'COMPLETE_MIGRATION.py',
        'FINAL_VERIFICATION.py',
        'check_available_functions.py',
        'example.py',
        'fix_dataset_lint_issues.py',
        'generate_mcp_test_suite.py',
        'import_debug.py',
        'mcp_restart_guide.py',
        'mcp_tools_test_analyzer.py',
        'mcp_tools_test_generator.py',
        'migration_success_demo.py',
        'performance_profiler.py',
        'server_startup_test.py',
        'simple_mcp_test_generator.py',
        'simple_mcp_tools_discovery.py',
        'start_server.py',
        'verify_mcp_config.py'
    }
    
    # Log and temporary files
    log_temp_files = {
        'server.log',
        'mcp_test_results.json',
        'test_mcp_config.json',
        'start_mcp_server.sh'
    }
    
    # Generator files (special category)
    generator_files = {
        'test_generator_for_audit_tools.py',
        'test_generator_for_dataset_tools.py',
        'test_generator_for_graph_tools.py',
        'test_generator_for_ipfs_tools.py',
        'test_generator_for_provenance_tools.py',
        'test_generator_for_security_tools.py',
        'test_generator_for_vector_tools.py',
        'test_generator_for_web_archive_tools.py'
    }
    
    # Move files to appropriate directories
    file_categories = [
        (migration_docs, "migration_docs"),
        (test_files, "migration_tests"),
        (script_files, "migration_scripts"), 
        (log_temp_files, "migration_logs"),
        (generator_files, "migration_temp")
    ]
    
    moved_count = 0
    for file_set, target_dir in file_categories:
        for filename in file_set:
            if Path(filename).exists():
                try:
                    shutil.move(filename, f"{target_dir}/{filename}")
                    print(f"📁 Moved {filename} → {target_dir}/")
                    moved_count += 1
                except Exception as e:
                    print(f"❌ Error moving {filename}: {e}")
    
    print(f"\n✅ Moved {moved_count} files to organized directories")
    
    # Clean up wget logs
    wget_logs = [f for f in os.listdir('.') if f.startswith('wget-log')]
    for log_file in wget_logs:
        try:
            os.remove(log_file)
            print(f"🗑️  Removed {log_file}")
        except Exception as e:
            print(f"❌ Error removing {log_file}: {e}")

def create_organized_readme():
    """Create a README for the organized structure."""
    readme_content = """# IPFS Datasets MCP Server - Organized Structure

## 📁 Directory Organization

### Root Directory (Essential Files Only)
- `README.md` - Main project documentation
- `requirements.txt` - Python dependencies  
- `pyproject.toml` - Project configuration
- `setup.py` - Package setup
- `LICENSE` - Project license
- `.vscode/` - VS Code configuration (including MCP config)
- `ipfs_datasets_py/` - Main source code
- `config/` - Configuration files
- `docs/` - Documentation

### Migration Archive Directories

#### `migration_docs/`
- All migration documentation and guides
- Status reports and analysis files
- Configuration summaries

#### `migration_tests/`  
- All test files created during migration
- Comprehensive test suites
- Validation scripts

#### `migration_scripts/`
- Utility scripts created during migration
- Debug and diagnostic tools
- Migration helper scripts

#### `migration_logs/`
- Log files and test results
- Temporary configuration files
- Build artifacts

#### `migration_temp/`
- Generator scripts for test creation
- Temporary files and experiments

## 🎯 Migration Status: COMPLETE ✅

The MCP server migration is complete. All migration-related files have been organized into the above directories to keep the root clean while preserving the work history.

## 🚀 Next Steps

1. Restart MCP server in VS Code: `Ctrl+Shift+P` → "MCP: Restart All Servers"
2. Test tools availability in VS Code chat
3. Verify input validation is working
4. Begin using the migrated MCP server!
"""
    
    with open("MIGRATION_ORGANIZATION.md", "w") as f:
        f.write(readme_content)
    
    print("📋 Created MIGRATION_ORGANIZATION.md")

def main():
    print("🧹 Starting Root Directory Cleanup...")
    print("=" * 50)
    
    create_cleanup_directories()
    print()
    organize_files()
    print()
    create_organized_readme()
    
    print("\n" + "=" * 50)
    print("✅ Root Directory Cleanup Complete!")
    print("\n📁 Organized structure:")
    print("  - Essential files remain in root")
    print("  - Migration docs → migration_docs/")
    print("  - Test files → migration_tests/")
    print("  - Scripts → migration_scripts/")
    print("  - Logs → migration_logs/")
    print("  - Temp files → migration_temp/")
    
    print("\n🎯 Root directory is now clean and organized!")

if __name__ == "__main__":
    main()
