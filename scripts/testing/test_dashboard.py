#!/usr/bin/env python3
"""
Test script to verify IPFS Datasets MCP Dashboard functionality
"""

import requests
import time
import sys

def test_dashboard():
    """Test the MCP dashboard functionality."""
    base_url = "http://127.0.0.1:8899"
    
    print("🧪 Testing IPFS Datasets MCP Dashboard")
    print("=" * 40)
    
    # Test basic connectivity
    print("1. Testing basic connectivity...")
    try:
        response = requests.get(f"{base_url}/mcp", timeout=10)
        if response.status_code == 200:
            print("   ✅ Dashboard accessible")
        else:
            print(f"   ❌ Dashboard returned {response.status_code}")
            return False
    except requests.ConnectionError:
        print("   ❌ Cannot connect to dashboard")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False
    
    # Test API endpoints
    print("2. Testing API endpoints...")
    endpoints = [
        "/api/mcp/status",
        "/api/mcp/tools",
        "/api/mcp/health"
    ]
    
    for endpoint in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=5)
            if response.status_code == 200:
                print(f"   ✅ {endpoint} - OK")
            else:
                print(f"   ⚠️  {endpoint} - Status {response.status_code}")
        except Exception as e:
            print(f"   ❌ {endpoint} - Error: {e}")
    
    print("\n✅ Dashboard testing complete!")
    return True

def wait_for_service(max_wait=60):
    """Wait for the service to become available."""
    print(f"⏳ Waiting up to {max_wait}s for service to start...")
    
    for i in range(max_wait):
        try:
            response = requests.get("http://127.0.0.1:8899/mcp", timeout=2)
            if response.status_code == 200:
                print(f"✅ Service ready after {i+1}s")
                return True
        except:
            pass
        time.sleep(1)
    
    print("❌ Service failed to start within timeout")
    return False

if __name__ == "__main__":
    if wait_for_service():
        success = test_dashboard()
        sys.exit(0 if success else 1)
    else:
        sys.exit(1)