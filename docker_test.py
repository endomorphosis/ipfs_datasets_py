#!/usr/bin/env python3
import requests
import json
import sys

def test_service(name, url, expected_keys=None):
    """Test a service endpoint"""
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ {name}: {data}")
            if expected_keys:
                missing = [key for key in expected_keys if key not in data]
                if missing:
                    print(f"⚠️  {name}: Missing keys: {missing}")
                else:
                    print(f"✅ {name}: All expected keys present")
            return True
        else:
            print(f"❌ {name}: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ {name}: {str(e)}")
        return False

def test_ipfs():
    """Test IPFS node"""
    try:
        response = requests.post("http://localhost:5001/api/v0/version", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ IPFS: {data}")
            return True
        else:
            print(f"❌ IPFS: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ IPFS: {str(e)}")
        return False

def main():
    print("🧪 Testing Docker ARM64 Setup...")
    print("=" * 50)
    
    tests = [
        ("MCP Server Health", "http://localhost:8000/health", ["status", "service"]),
        ("MCP Server Status", "http://localhost:8000/api/mcp/status", ["status", "tools_available", "version"]),
        ("Dashboard Status", "http://localhost:8899/api/mcp/status", ["status", "tools_available", "version"]),
    ]
    
    results = []
    
    # Test web services
    for name, url, keys in tests:
        results.append(test_service(name, url, keys))
    
    # Test IPFS
    results.append(test_ipfs())
    
    # Test dashboard web interface
    try:
        response = requests.get("http://localhost:8899/", timeout=10)
        if response.status_code == 200 and "MCP Dashboard" in response.text:
            print("✅ Dashboard Web Interface: Working")
            results.append(True)
        else:
            print("❌ Dashboard Web Interface: Failed")
            results.append(False)
    except Exception as e:
        print(f"❌ Dashboard Web Interface: {str(e)}")
        results.append(False)
    
    print("\n" + "=" * 50)
    passed = sum(results)
    total = len(results)
    print(f"📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! ARM64 Docker setup is working perfectly!")
        sys.exit(0)
    else:
        print("⚠️  Some tests failed. Check the logs above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
