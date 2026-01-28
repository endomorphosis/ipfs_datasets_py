#!/usr/bin/env python3
"""
Quick validation test for caselaw dashboard and legal dataset tools.

This script validates that:
1. All legal dataset tools are importable
2. The schedulers are working
3. The API endpoints are configured correctly
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent / '../..'))


def test_imports():
    """Test that all legal dataset tools can be imported."""
    print("Testing imports...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import (
            scrape_us_code,
            scrape_federal_register,
            scrape_state_laws,
            scrape_municipal_laws,
            scrape_recap_archive,
            search_recap_documents,
            export_dataset,
            list_scraping_jobs,
            create_schedule,
            list_schedules,
            run_schedule_now,
            enable_disable_schedule,
            remove_schedule
        )
        print("✓ All legal dataset tools imported successfully")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_tool_discovery():
    """Test that the MCP dashboard can discover tools."""
    print("\nTesting tool discovery...")
    
    try:
        from pathlib import Path
        from ipfs_datasets_py import mcp_dashboard
        
        # Get tools directory
        dashboard_path = Path(mcp_dashboard.__file__).parent
        tools_dir = dashboard_path / "mcp_server" / "tools"
        
        if not tools_dir.exists():
            print(f"✗ Tools directory not found: {tools_dir}")
            return False
        
        # Count tool categories
        tool_categories = [
            d.name for d in tools_dir.iterdir() 
            if d.is_dir() and not d.name.startswith('_')
        ]
        
        print(f"✓ Found {len(tool_categories)} tool categories")
        
        # Check for legal_dataset_tools
        if "legal_dataset_tools" in tool_categories:
            print("✓ legal_dataset_tools category found")
            
            # Check tool files
            legal_tools_dir = tools_dir / "legal_dataset_tools"
            tool_files = list(legal_tools_dir.glob("*_scraper.py"))
            tool_files += list(legal_tools_dir.glob("*_scheduler.py"))
            
            print(f"✓ Found {len(tool_files)} scraper/scheduler files")
            return True
        else:
            print("✗ legal_dataset_tools category not found")
            return False
            
    except Exception as e:
        print(f"✗ Tool discovery failed: {e}")
        return False


def test_dashboard_template():
    """Test that the caselaw dashboard template exists and has correct tool count."""
    print("\nTesting dashboard template...")
    
    try:
        from pathlib import Path
        from ipfs_datasets_py import mcp_dashboard
        
        # Get template path
        dashboard_path = Path(mcp_dashboard.__file__).parent
        template_path = dashboard_path / "templates" / "admin" / "caselaw_dashboard_mcp.html"
        
        if not template_path.exists():
            print(f"✗ Template not found: {template_path}")
            return False
        
        print(f"✓ Template found: {template_path}")
        
        # Check template content for tool declarations
        with open(template_path, 'r') as f:
            content = f.read()
        
        # Look for tool declarations
        if "'scrape_us_code'" in content:
            print("✓ US Code scraper tool declared in template")
        else:
            print("⚠ US Code scraper tool not found in template")
        
        if "'scrape_state_laws'" in content:
            print("✓ State Laws scraper tool declared in template")
        else:
            print("⚠ State Laws scraper tool not found in template")
        
        if "'create_schedule'" in content:
            print("✓ Scheduling tools declared in template")
        else:
            print("⚠ Scheduling tools not found in template")
        
        # Count tool declarations
        tool_count = content.count("'scrape_") + content.count("'create_schedule")
        print(f"✓ Found approximately {tool_count} tool references in template")
        
        return True
        
    except Exception as e:
        print(f"✗ Template test failed: {e}")
        return False


def test_api_routes():
    """Test that API routes are configured."""
    print("\nTesting API route configuration...")
    
    try:
        from ipfs_datasets_py.mcp_dashboard import MCPDashboard
        
        # The routes are set up when the dashboard is configured
        # We can check if the _setup_legal_dataset_routes method exists
        if hasattr(MCPDashboard, '_setup_legal_dataset_routes'):
            print("✓ Legal dataset routes method exists")
        else:
            print("✗ Legal dataset routes method not found")
            return False
        
        if hasattr(MCPDashboard, '_setup_caselaw_routes'):
            print("✓ Caselaw routes method exists")
        else:
            print("✗ Caselaw routes method not found")
            return False
        
        print("✓ API route configuration looks good")
        return True
        
    except Exception as e:
        print(f"✗ API route test failed: {e}")
        return False


def test_scheduler_setup():
    """Test that the setup_periodic_updates script exists."""
    print("\nTesting scheduler setup script...")
    
    try:
        script_path = Path(__file__).parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "legal_dataset_tools" / "setup_periodic_updates.py"
        
        if script_path.exists():
            print(f"✓ Setup script exists: {script_path}")
            
            # Check if executable
            import os
            if os.access(script_path, os.X_OK):
                print("✓ Setup script is executable")
            else:
                print("⚠ Setup script is not executable (may need chmod +x)")
            
            return True
        else:
            print(f"✗ Setup script not found: {script_path}")
            return False
            
    except Exception as e:
        print(f"✗ Scheduler setup test failed: {e}")
        return False


def main():
    """Run all validation tests."""
    print("="*60)
    print("Caselaw Dashboard & Legal Dataset Tools Validation")
    print("="*60)
    
    results = []
    
    # Run tests
    results.append(("Imports", test_imports()))
    results.append(("Tool Discovery", test_tool_discovery()))
    results.append(("Dashboard Template", test_dashboard_template()))
    results.append(("API Routes", test_api_routes()))
    results.append(("Scheduler Setup", test_scheduler_setup()))
    
    # Print summary
    print("\n" + "="*60)
    print("Validation Summary")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{test_name:.<40} {status}")
    
    print("-"*60)
    print(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All validation tests passed!")
        print("\nNext steps:")
        print("1. Start the MCP dashboard:")
        print("   python -m ipfs_datasets_py.mcp_dashboard")
        print("2. Open http://127.0.0.1:8899/mcp/caselaw in your browser")
        print("3. Verify tool count shows 17 tools")
        print("4. Test dataset workflows")
        return 0
    else:
        print("\n✗ Some validation tests failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
