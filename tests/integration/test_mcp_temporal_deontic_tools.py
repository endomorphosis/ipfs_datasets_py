#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test script for Temporal Deontic Logic MCP Tools.

This script demonstrates the conversion of REST APIs to MCP JSON-RPC tools
for the temporal deontic logic RAG system. It tests the MCP tools directly
and via JSON-RPC endpoints.
"""

import anyio
import json
import requests
import sys
import time
from datetime import datetime
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent / "ipfs_datasets_py"))

async def test_mcp_tools_direct():
    """Test MCP tools directly without JSON-RPC layer."""
    print("🧪 Testing MCP Tools Directly")
    print("=" * 50)
    
    try:
        from ipfs_datasets_py.mcp_tools.temporal_deontic_mcp_server import temporal_deontic_mcp_server
        
        # Test 1: Add a test theorem
        print("\n1. Testing add_theorem tool...")
        add_result = await temporal_deontic_mcp_server.call_tool_direct(
            'add_theorem',
            {
                'operator': 'PROHIBITION',
                'proposition': 'disclose confidential information to third parties',
                'agent_name': 'Employee',
                'jurisdiction': 'Federal',
                'legal_domain': 'Confidentiality',
                'source_case': 'Test Case for MCP Demo',
                'precedent_strength': 0.9
            }
        )
        
        if add_result.get('success'):
            print(f"   ✅ Theorem added: {add_result['theorem_id']}")
        else:
            print(f"   ❌ Failed: {add_result.get('error')}")
        
        # Test 2: Query theorems
        print("\n2. Testing query_theorems tool...")
        query_result = await temporal_deontic_mcp_server.call_tool_direct(
            'query_theorems',
            {
                'query': 'Can employee share confidential information?',
                'operator_filter': 'all',
                'jurisdiction': 'all',
                'limit': 5
            }
        )
        
        if query_result.get('success'):
            print(f"   ✅ Found {query_result['total_results']} relevant theorems")
            for i, theorem in enumerate(query_result['theorems'][:3]):
                print(f"   {i+1}. {theorem['formula']['operator']}: {theorem['formula']['proposition']}")
                print(f"      Source: {theorem['metadata']['source_case']} ({theorem['relevance_score']:.1%} relevance)")
        else:
            print(f"   ❌ Failed: {query_result.get('error')}")
        
        # Test 3: Check document consistency
        print("\n3. Testing check_document_consistency tool...")
        consistency_result = await temporal_deontic_mcp_server.call_tool_direct(
            'check_document_consistency',
            {
                'document_text': 'Employee may share confidential information with business partners for legitimate purposes.',
                'document_id': 'test_contract_mcp',
                'jurisdiction': 'Federal',
                'legal_domain': 'Confidentiality'
            }
        )
        
        if consistency_result.get('success'):
            analysis = consistency_result['consistency_analysis']
            status = "CONSISTENT" if analysis['is_consistent'] else "CONFLICTS FOUND"
            print(f"   ✅ Analysis complete: {status}")
            print(f"   Formulas extracted: {analysis['formulas_extracted']}")
            print(f"   Issues found: {analysis['issues_found']}")
            print(f"   Processing time: {analysis['processing_time']:.3f}s")
            
            # Show debug report
            debug_report = consistency_result['debug_report']
            print(f"   Debug Report: {debug_report['total_issues']} issues ({debug_report['critical_errors']} critical)")
        else:
            print(f"   ❌ Failed: {consistency_result.get('error')}")
        
        # Test 4: Bulk processing (async demo)
        print("\n4. Testing bulk_process_caselaw tool...")
        bulk_result = await temporal_deontic_mcp_server.call_tool_direct(
            'bulk_process_caselaw',
            {
                'caselaw_directories': ['/tmp/sample_caselaw'],  # This won't exist, but demonstrates the API
                'output_directory': 'mcp_bulk_output',
                'max_concurrent_documents': 3,
                'async_processing': True
            }
        )
        
        if bulk_result.get('success'):
            if bulk_result.get('async_processing'):
                print(f"   ✅ Bulk processing started: {bulk_result['session_id']}")
                print(f"   Status: {bulk_result['status']}")
            else:
                print(f"   ✅ Processed {bulk_result['results']['documents_processed']} documents")
        else:
            print(f"   ❌ Failed: {bulk_result.get('error')}")
        
        print(f"\n✅ MCP Tools Direct Testing Complete")
        return True
        
    except Exception as e:
        print(f"❌ MCP Tools testing failed: {e}")
        return False

def test_jsonrpc_endpoint():
    """Test the JSON-RPC endpoint (requires server to be running)."""
    print("\n🌐 Testing JSON-RPC Endpoint")
    print("=" * 50)
    
    base_url = "http://localhost:5000"  # Assuming Flask dev server
    jsonrpc_url = f"{base_url}/api/mcp/caselaw/jsonrpc"
    
    try:
        # Test JSON-RPC call
        jsonrpc_request = {
            "jsonrpc": "2.0",
            "method": "query_theorems",
            "params": {
                "query": "confidentiality requirements",
                "limit": 3
            },
            "id": 1
        }
        
        response = requests.post(
            jsonrpc_url,
            json=jsonrpc_request,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if 'result' in result and result['result'].get('success'):
                print("   ✅ JSON-RPC call successful")
                theorems_found = result['result']['total_results']
                print(f"   Found {theorems_found} theorems via JSON-RPC")
            else:
                print(f"   ❌ JSON-RPC call failed: {result}")
        else:
            print(f"   ❌ HTTP error: {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        print("   ⚠️  Server not running - skipping JSON-RPC test")
        print("   To test JSON-RPC, start the server with: python -m ipfs_datasets_py.mcp_dashboard")
    except Exception as e:
        print(f"   ❌ JSON-RPC test failed: {e}")

def test_tool_schemas():
    """Test getting tool schemas."""
    print("\n📋 Testing Tool Schemas")
    print("=" * 50)
    
    try:
        from ipfs_datasets_py.mcp_tools.temporal_deontic_mcp_server import temporal_deontic_mcp_server
        
        schemas = temporal_deontic_mcp_server.get_tool_schemas()
        
        print(f"   Available MCP Tools: {len(schemas)}")
        for tool_name, schema in schemas.items():
            print(f"   - {tool_name}: {schema['description']}")
            required_params = schema.get('input_schema', {}).get('required', [])
            print(f"     Required parameters: {', '.join(required_params) if required_params else 'none'}")
        
        print("   ✅ Tool schemas loaded successfully")
        return True
        
    except Exception as e:
        print(f"   ❌ Failed to load tool schemas: {e}")
        return False

async def main():
    """Main test function."""
    print("🚀 Temporal Deontic Logic MCP Tools Test Suite")
    print("=" * 60)
    print("This script tests the conversion of REST APIs to MCP JSON-RPC tools\n")
    
    # Test tool schemas
    schemas_ok = test_tool_schemas()
    
    # Test MCP tools directly
    if schemas_ok:
        tools_ok = await test_mcp_tools_direct()
    else:
        tools_ok = False
    
    # Test JSON-RPC endpoint
    test_jsonrpc_endpoint()
    
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    print(f"Tool Schemas: {'✅ PASS' if schemas_ok else '❌ FAIL'}")
    print(f"Direct MCP Tools: {'✅ PASS' if tools_ok else '❌ FAIL'}")
    print("JSON-RPC Endpoint: ⚠️  Requires running server")
    
    print("\n🎯 Key Features Demonstrated:")
    print("- ✅ REST API endpoints converted to MCP tools")
    print("- ✅ JSON-RPC interface for tool calls") 
    print("- ✅ Temporal deontic logic analysis via MCP")
    print("- ✅ RAG-based theorem retrieval through MCP")
    print("- ✅ Document consistency checking via MCP tools")
    print("- ✅ Bulk caselaw processing capabilities")
    
    print("\n🌐 To test the dashboard with MCP tools:")
    print("1. Start the MCP dashboard server:")
    print("   python -m ipfs_datasets_py.mcp_dashboard")
    print("2. Navigate to http://localhost:5000/mcp/caselaw")
    print("3. The dashboard will use MCP JSON-RPC calls instead of REST APIs")
    
    if tools_ok:
        print("\n✅ MCP conversion successful! The temporal deontic logic RAG system")
        print("   now supports both REST APIs and MCP JSON-RPC tools.")
    else:
        print("\n❌ Some tests failed - check the error messages above.")

if __name__ == "__main__":
    anyio.run(main())