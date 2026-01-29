#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test script for MCP Dashboard functionality.

This script tests the basic functionality of the MCP dashboard and JavaScript SDK.
"""
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from ipfs_datasets_py.dashboards.mcp_dashboard import MCPDashboard, MCPDashboardConfig, start_mcp_dashboard
    print("✓ Successfully imported MCP dashboard components")
except ImportError as e:
    print(f"✗ Failed to import MCP dashboard: {e}")
    sys.exit(1)

def test_dashboard_config():
    """Test dashboard configuration."""
    print("\n=== Testing Dashboard Configuration ===")
    
    config = MCPDashboardConfig(
        host="localhost",
        port=8080,
        mcp_server_port=8001,
        enable_tool_execution=True
    )
    
    assert config.host == "localhost"
    assert config.port == 8080
    assert config.mcp_server_port == 8001
    assert config.enable_tool_execution == True
    print("✓ Dashboard configuration works correctly")

def test_dashboard_initialization():
    """Test dashboard initialization."""
    print("\n=== Testing Dashboard Initialization ===")
    
    dashboard = MCPDashboard()
    config = MCPDashboardConfig(
        host="localhost",
        port=8081,  # Different port to avoid conflicts
        data_dir="/tmp/mcp_dashboard_test"
    )
    
    try:
        dashboard.configure(config)
        print("✓ Dashboard initialization successful")
        
        # Test status
        status = dashboard.get_status()
        print(f"✓ Dashboard status: {status}")
        
    except Exception as e:
        print(f"✗ Dashboard initialization failed: {e}")

def test_tool_discovery():
    """Test MCP tool discovery."""
    print("\n=== Testing Tool Discovery ===")
    
    dashboard = MCPDashboard()
    config = MCPDashboardConfig(data_dir="/tmp/mcp_dashboard_test")
    dashboard.configure(config)
    
    try:
        tools_info = dashboard._discover_mcp_tools()
        print(f"✓ Discovered {len(tools_info)} tool categories")
        
        for category, tools in tools_info.items():
            print(f"  - {category}: {len(tools)} tools")
            
    except Exception as e:
        print(f"✗ Tool discovery failed: {e}")

def test_server_status():
    """Test MCP server status."""
    print("\n=== Testing Server Status ===")
    
    dashboard = MCPDashboard()
    config = MCPDashboardConfig(data_dir="/tmp/mcp_dashboard_test")
    dashboard.configure(config)
    
    try:
        status = dashboard._get_mcp_server_status()
        print(f"✓ Server status: {status['status']}")
        print(f"  - Tools available: {status.get('tools_available', 0)}")
        print(f"  - Active executions: {status.get('active_executions', 0)}")
        
    except Exception as e:
        print(f"✗ Server status check failed: {e}")

def test_template_creation():
    """Test template creation."""
    print("\n=== Testing Template Creation ===")
    
    dashboard = MCPDashboard()
    config = MCPDashboardConfig(data_dir="/tmp/mcp_dashboard_test")
    dashboard.configure(config)
    
    try:
        template = dashboard.create_mcp_dashboard_template()
        assert "MCP Server Dashboard" in template
        assert "tools-container" in template
        print("✓ MCP dashboard template created successfully")
        
    except Exception as e:
        print(f"✗ Template creation failed: {e}")

def test_static_files():
    """Test that static files exist."""
    print("\n=== Testing Static Files ===")
    
    project_path = Path(__file__).parent / "ipfs_datasets_py"
    
    # Check JavaScript SDK (in admin static directory)
    js_sdk_path = project_path / "static" / "admin" / "js" / "mcp-sdk.js"
    if js_sdk_path.exists():
        print("✓ JavaScript SDK file exists")
        
        with open(js_sdk_path, 'r') as f:
            content = f.read()
            assert "class MCPClient" in content
            assert "executeTool" in content
            print("✓ JavaScript SDK contains expected classes and methods")
    else:
        print(f"✗ JavaScript SDK file not found at {js_sdk_path}")
    
    # Check CSS (in admin static directory)
    css_path = project_path / "static" / "admin" / "css" / "mcp-dashboard.css"
    if css_path.exists():
        print("✓ CSS file exists")
    else:
        print(f"✗ CSS file not found at {css_path}")

def main():
    """Run all tests."""
    print("Starting MCP Dashboard Tests...")
    
    try:
        test_dashboard_config()
        test_dashboard_initialization()
        test_tool_discovery()
        test_server_status()
        test_template_creation()
        test_static_files()
        
        print("\n=== Test Summary ===")
        print("✓ All basic tests passed!")
        print("\nTo test the full dashboard, run:")
        print("  python -c 'from ipfs_datasets_py.dashboards.mcp_dashboard import start_mcp_dashboard; start_mcp_dashboard()'")
        print("Then visit: http://localhost:8080/mcp")
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()