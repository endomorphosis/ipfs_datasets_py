#!/usr/bin/env python3
"""
Script to reorganize root directory files into appropriate subdirectories.
This script moves files and updates all references to maintain functionality.
"""

import os
import shutil
import re
from pathlib import Path
from typing import List, Dict, Tuple

# Base directory
BASE_DIR = Path(__file__).parent.absolute()

# Define file categorization and destinations
FILE_MOVES = {
    # Test files -> tests/integration/
    'tests/integration/': [
        'test_all_11_states.py',
        'test_cache_interoperability.py',
        'test_caselaw_dashboard.py',
        'test_cli.py',
        'test_cli_installation.py',
        'test_copilot_methods.py',
        'test_dashboard_routes.py',
        'test_delaware.py',
        'test_enhanced_pr_monitor.py',
        'test_error_reporting_integration.py',
        'test_extras_windows.py',
        'test_in_tn.py',
        'test_integrated_cli.py',
        'test_legal_scrapers.py',
        'test_legal_scrapers_simple.py',
        'test_mcp_temporal_deontic_tools.py',
        'test_medicine_dashboard_integration.py',
        'test_medicine_syntax.py',
        'test_p2p_async.py',
        'test_playwright_states.py',
        'test_queue_system.py',
        'test_recap_scraping.py',
        'test_six_states.py',
        'test_submodule_integration.py',
        'test_temporal_deontic_rag.py',
        'test_unified_scraper.py',
        'test_web_archive_tools.py',
        'test_windows_install.py',
        'simple_test.py',
        'docker_test.py',
        '_test_with_faker.py',
        'comprehensive_cli_test.py',
    ],
    
    # Validation scripts -> scripts/validation/
    'scripts/validation/': [
        'validate_caselaw_setup.py',
        'validate_mcp_dashboard.py',
        'validate_platform_setup.py',
        'validate_scraper_framework.py',
        'validate_testing_framework.py',
        'check_indiana.py',
        'check_scraper_status.py',
        'comprehensive_runner_validation.py',
        'comprehensive_scraper_validation.py',
        'example_scraper_validation.py',
    ],
    
    # Installation/setup scripts -> scripts/setup/
    'scripts/setup/': [
        'install.py',
        'install_deps.py',
        'quick_setup.py',
        'ipfs_auto_install_config.py',
    ],
    
    # Debug scripts -> scripts/debug/
    'scripts/debug/': [
        'debug_caselaw.py',
        'debug_delaware_html.py',
        'inspect_pages.py',
    ],
    
    # Dashboard scripts -> scripts/dashboard/
    'scripts/dashboard/': [
        'capture_dashboard_screenshot.py',
        'take_dashboard_screenshots.py',
        'mcp_dashboard_tests.py',
        'demo_dashboards.py',
    ],
    
    # Migration helpers -> scripts/migration/
    'scripts/migration/': [
        'migrate_to_anyio.py',
        'anyio_migration_helpers.py',
        'cleanup_pytest_conflicts.py',
    ],
    
    # Demo scripts -> scripts/demo/
    'scripts/demo/': [
        'demo_cli.py',
        'demo_mcp_conversion.py',
        'demo_patent_scraper.py',
        'bulk_caselaw_demo.py',
        'bulk_processing_concept_demo.py',
        'caselaw_dashboard_demo.py',
        'fixed_caselaw_dashboard_demo.py',
        'comprehensive_legal_debugger_demo.py',
        'final_demonstration.py',
    ],
    
    # Management/utility scripts -> scripts/utilities/
    'scripts/utilities/': [
        'dependency_health_checker.py',
        'dependency_manager.py',
        'scraper_management.py',
        'final_documentation_verification.py',
    ],
    
    # Dashboard HTML files -> docs/dashboards/
    'docs/dashboards/': [
        'advanced_dashboard_final.html',
        'bulk_processing_dashboard_preview.html',
        'caselaw_dashboard_preview.html',
        'comprehensive_mcp_dashboard_final.html',
        'enhanced_dashboard_preview.html',
        'fixed_caselaw_dashboard.html',
        'fixed_dashboard_working.html',
        'maps_tab_demonstration.html',
        'mcp_dashboard_screenshot.html',
        'professional_desktop_dashboard.html',
        'working_mcp_dashboard.html',
    ],
}

# Files to keep in root
KEEP_IN_ROOT = [
    'setup.py',
    'requirements.txt',
    'README.md',
    'LICENSE',
    'CHANGELOG.md',
    'TODO.md',
    'CLAUDE.md',
    'pytest.ini',
    'pytest.ini.mcp',
    'mypy.ini',
    'ipfs_datasets_cli.py',  # Main CLI entry point
    'mcp_cli.py',  # Main MCP CLI entry point
    'enhanced_cli.py',  # Enhanced CLI
    'integrated_cli.py',  # Integrated CLI
    'comprehensive_distributed_cli.py',  # Distributed CLI
    'comprehensive_mcp_tools.py',  # MCP tools
]


def create_directories():
    """Create all necessary target directories."""
    print("Creating target directories...")
    for dest_dir in FILE_MOVES.keys():
        target = BASE_DIR / dest_dir
        target.mkdir(parents=True, exist_ok=True)
        print(f"  ✓ Created {dest_dir}")


def move_file(src: Path, dest: Path) -> bool:
    """Move a file from source to destination."""
    try:
        if not src.exists():
            print(f"  ⚠️  Source file not found: {src.name}")
            return False
        
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        print(f"  ✓ Moved {src.name} -> {dest.relative_to(BASE_DIR)}")
        return True
    except Exception as e:
        print(f"  ❌ Error moving {src.name}: {e}")
        return False


def move_files():
    """Move files to their new locations."""
    print("\nMoving files...")
    moved_files = {}
    
    for dest_dir, files in FILE_MOVES.items():
        print(f"\n📁 Moving to {dest_dir}:")
        for filename in files:
            src = BASE_DIR / filename
            dest = BASE_DIR / dest_dir / filename
            
            if move_file(src, dest):
                moved_files[filename] = dest_dir
    
    return moved_files


def update_workflow_files(moved_files: Dict[str, str]):
    """Update GitHub workflow files with new paths."""
    print("\nUpdating GitHub workflow files...")
    workflows_dir = BASE_DIR / '.github' / 'workflows'
    
    if not workflows_dir.exists():
        print("  ⚠️  No workflows directory found")
        return
    
    for workflow_file in workflows_dir.glob('*.yml'):
        content = workflow_file.read_text()
        original_content = content
        
        # Update test file paths
        for filename, dest_dir in moved_files.items():
            if filename.startswith('test_'):
                # Update direct python calls
                content = re.sub(
                    rf'python\s+{re.escape(filename)}',
                    f'python {dest_dir}{filename}',
                    content
                )
                content = re.sub(
                    rf'python3\s+{re.escape(filename)}',
                    f'python3 {dest_dir}{filename}',
                    content
                )
        
        if content != original_content:
            workflow_file.write_text(content)
            print(f"  ✓ Updated {workflow_file.name}")


def update_test_imports(moved_files: Dict[str, str]):
    """Update import statements in moved test files."""
    print("\nUpdating imports in moved test files...")
    
    for filename, dest_dir in moved_files.items():
        if not filename.endswith('.py'):
            continue
        
        file_path = BASE_DIR / dest_dir / filename
        if not file_path.exists():
            continue
        
        try:
            content = file_path.read_text()
            original_content = content
            
            # Update sys.path.insert for parent directory
            if "sys.path.insert(0, str(Path(__file__).parent))" in content:
                # Calculate relative path back to root
                depth = len(Path(dest_dir).parts)
                parent_path = "../" * depth
                content = content.replace(
                    "sys.path.insert(0, str(Path(__file__).parent))",
                    f"sys.path.insert(0, str(Path(__file__).parent / '{parent_path.rstrip('/')}'))"
                )
            
            # Update ipfs_datasets_cli.py references
            content = re.sub(
                r'python["\']?\s+ipfs_datasets_cli\.py',
                'python ../../ipfs_datasets_cli.py' if filename.startswith('test_') else 'python ipfs_datasets_cli.py',
                content
            )
            
            if content != original_content:
                file_path.write_text(content)
                print(f"  ✓ Updated imports in {filename}")
        
        except Exception as e:
            print(f"  ⚠️  Could not update {filename}: {e}")


def update_documentation(moved_files: Dict[str, str]):
    """Update documentation references to moved files."""
    print("\nUpdating documentation...")
    
    doc_files = [
        BASE_DIR / 'README.md',
        BASE_DIR / 'CLAUDE.md',
        BASE_DIR / 'docs' / 'README.md',
    ]
    
    for doc_file in doc_files:
        if not doc_file.exists():
            continue
        
        try:
            content = doc_file.read_text()
            original_content = content
            
            for filename, dest_dir in moved_files.items():
                # Update file references
                content = re.sub(
                    rf'`{re.escape(filename)}`',
                    f'`{dest_dir}{filename}`',
                    content
                )
                content = re.sub(
                    rf'\[{re.escape(filename)}\]',
                    f'[{dest_dir}{filename}]',
                    content
                )
            
            if content != original_content:
                doc_file.write_text(content)
                print(f"  ✓ Updated {doc_file.name}")
        
        except Exception as e:
            print(f"  ⚠️  Could not update {doc_file.name}: {e}")


def create_readme_files():
    """Create README files in new directories."""
    print("\nCreating README files in new directories...")
    
    readmes = {
        'scripts/validation/': "# Validation Scripts\n\nScripts for validating scrapers, setups, and frameworks.\n",
        'scripts/setup/': "# Setup Scripts\n\nInstallation and setup utilities.\n",
        'scripts/debug/': "# Debug Scripts\n\nDebugging and diagnostic tools.\n",
        'scripts/dashboard/': "# Dashboard Scripts\n\nDashboard testing and screenshot utilities.\n",
        'scripts/migration/': "# Migration Scripts\n\nMigration helpers and utilities.\n",
        'docs/dashboards/': "# Dashboard Previews\n\nHTML dashboard previews and demonstrations.\n",
    }
    
    for dir_path, content in readmes.items():
        readme_path = BASE_DIR / dir_path / 'README.md'
        if not readme_path.exists():
            readme_path.write_text(content)
            print(f"  ✓ Created {readme_path.relative_to(BASE_DIR)}")


def main():
    """Main reorganization function."""
    print("=" * 70)
    print("Root Directory Reorganization Script")
    print("=" * 70)
    
    # Create directories
    create_directories()
    
    # Move files
    moved_files = move_files()
    
    # Update references
    update_workflow_files(moved_files)
    update_test_imports(moved_files)
    update_documentation(moved_files)
    
    # Create README files
    create_readme_files()
    
    print("\n" + "=" * 70)
    print(f"✅ Reorganization complete! Moved {len(moved_files)} files.")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Review the changes with: git status")
    print("2. Test that imports still work")
    print("3. Run the test suite: pytest")
    print("4. Commit the changes")


if __name__ == '__main__':
    main()
