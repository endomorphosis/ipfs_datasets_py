#!/usr/bin/env python3
"""
Simple debug test to check MCP tools
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

async def simple_test():
    """Simple test"""
    print("🚀 Starting Simple Debug Test")
    
    # Test dataset tools
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
        print("✅ Dataset tools import successful")
        
        result = await load_dataset(source="imdb", options={"split": "test[:5]"})
        print(f"Load dataset result: {result.get('status', 'unknown')}")
        
    except Exception as e:
        print(f"❌ Dataset tools error: {e}")
        import traceback
        print(traceback.format_exc())
    
    # Test audit tools (non-async)
    try:
        from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event
        print("✅ Audit tools import successful")
        
        result = record_audit_event(action="test_action")
        print(f"Audit result: {result.get('status', 'unknown')}")
        
    except Exception as e:
        print(f"❌ Audit tools error: {e}")
        import traceback
        print(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(simple_test())
