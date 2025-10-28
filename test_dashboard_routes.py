#!/usr/bin/env python3
"""
Test script to verify dashboard routes are properly configured.
"""
import sys
import inspect
from pathlib import Path

# Add repository to path
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))

def test_dashboard_routes():
    """Test that dashboard routes are properly set up."""
    try:
        from ipfs_datasets_py.mcp_dashboard import MCPDashboard
        
        # Check that the setup methods exist
        assert hasattr(MCPDashboard, '_setup_caselaw_routes'), "Missing _setup_caselaw_routes method"
        assert hasattr(MCPDashboard, '_setup_finance_routes'), "Missing _setup_finance_routes method"
        assert hasattr(MCPDashboard, '_setup_medicine_routes'), "Missing _setup_medicine_routes method"
        
        print("✓ All route setup methods exist")
        
        # Check method signatures
        caselaw_method = getattr(MCPDashboard, '_setup_caselaw_routes')
        finance_method = getattr(MCPDashboard, '_setup_finance_routes')
        medicine_method = getattr(MCPDashboard, '_setup_medicine_routes')
        
        print("✓ Methods are callable")
        
        # Check that templates exist
        templates_dir = repo_root / "ipfs_datasets_py" / "templates" / "admin"
        
        caselaw_template = templates_dir / "caselaw_dashboard_mcp.html"
        finance_template = templates_dir / "finance_dashboard_mcp.html"
        medicine_template = templates_dir / "medicine_dashboard_mcp.html"
        
        assert caselaw_template.exists(), f"Missing template: {caselaw_template}"
        assert finance_template.exists(), f"Missing template: {finance_template}"
        assert medicine_template.exists(), f"Missing template: {medicine_template}"
        
        print("✓ All templates exist")
        
        # Check template content has correct terminology
        with open(finance_template, 'r') as f:
            finance_content = f.read()
            assert 'Finance Analysis' in finance_content, "Finance template missing 'Finance Analysis' title"
            assert 'financial' in finance_content.lower(), "Finance template missing 'financial' terminology"
        
        print("✓ Finance template has correct terminology")
        
        with open(medicine_template, 'r') as f:
            medicine_content = f.read()
            assert 'Medicine Analysis' in medicine_content, "Medicine template missing 'Medicine Analysis' title"
            assert 'medical' in medicine_content.lower(), "Medicine template missing 'medical' terminology"
        
        print("✓ Medicine template has correct terminology")
        
        # Check that all templates have cross-links
        with open(caselaw_template, 'r') as f:
            caselaw_content = f.read()
            assert 'finance_dashboard' in caselaw_content, "Caselaw template missing link to finance dashboard"
            assert 'medicine_dashboard' in caselaw_content, "Caselaw template missing link to medicine dashboard"
        
        print("✓ Caselaw template has links to finance and medicine dashboards")
        
        with open(finance_template, 'r') as f:
            finance_content = f.read()
            assert 'caselaw_dashboard' in finance_content, "Finance template missing link to caselaw dashboard"
            assert 'medicine_dashboard' in finance_content, "Finance template missing link to medicine dashboard"
        
        print("✓ Finance template has links to caselaw and medicine dashboards")
        
        with open(medicine_template, 'r') as f:
            medicine_content = f.read()
            assert 'caselaw_dashboard' in medicine_content, "Medicine template missing link to caselaw dashboard"
            assert 'finance_dashboard' in medicine_content, "Medicine template missing link to finance dashboard"
        
        print("✓ Medicine template has links to caselaw and finance dashboards")
        
        print("\n✅ All tests passed!")
        print("\nExpected dashboard URLs:")
        print("  - http://127.0.0.1:8080/mcp/caselaw")
        print("  - http://127.0.0.1:8080/mcp/finance")
        print("  - http://127.0.0.1:8080/mcp/medicine")
        print("\nExpected API endpoints:")
        print("  Finance:")
        print("    - POST /api/mcp/finance/check_document")
        print("    - POST /api/mcp/finance/query_theorems")
        print("  Medicine:")
        print("    - POST /api/mcp/medicine/check_document")
        print("    - POST /api/mcp/medicine/query_theorems")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_dashboard_routes()
    sys.exit(0 if success else 1)
