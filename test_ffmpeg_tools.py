#!/usr/bin/env python3
"""
Test suite for FFmpeg MCP tools.

This script tests all FFmpeg media processing tools to ensure they're working correctly.
"""
import asyncio
import json
import sys
import tempfile
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

async def test_ffmpeg_tools():
    """Test all FFmpeg tools."""
    print("🎬 Testing FFmpeg MCP Tools")
    print("=" * 40)
    
    test_results = {
        "tools_tested": 0,
        "tools_passed": 0,
        "tools_failed": 0,
        "results": {}
    }
    
    # Test 1: FFmpeg Convert Tool
    print("\n1. Testing FFmpeg Convert Tool...")
    try:
        from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_convert import main as convert_main
        result = await convert_main()
        if result.get("status") == "success":
            print("✅ FFmpeg Convert tool initialized successfully")
            test_results["tools_passed"] += 1
        else:
            print(f"❌ FFmpeg Convert tool failed: {result}")
            test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_convert"] = result
    except Exception as e:
        print(f"❌ FFmpeg Convert tool error: {e}")
        test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_convert"] = {"status": "error", "error": str(e)}
    test_results["tools_tested"] += 1
    
    # Test 2: FFmpeg Mux/Demux Tool
    print("\n2. Testing FFmpeg Mux/Demux Tool...")
    try:
        from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_mux_demux import main as mux_main
        result = await mux_main()
        if result.get("status") == "success":
            print("✅ FFmpeg Mux/Demux tool initialized successfully")
            test_results["tools_passed"] += 1
        else:
            print(f"❌ FFmpeg Mux/Demux tool failed: {result}")
            test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_mux_demux"] = result
    except Exception as e:
        print(f"❌ FFmpeg Mux/Demux tool error: {e}")
        test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_mux_demux"] = {"status": "error", "error": str(e)}
    test_results["tools_tested"] += 1
    
    # Test 3: FFmpeg Stream Tool
    print("\n3. Testing FFmpeg Stream Tool...")
    try:
        from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_stream import main as stream_main
        result = await stream_main()
        if result.get("status") == "success":
            print("✅ FFmpeg Stream tool initialized successfully")
            test_results["tools_passed"] += 1
        else:
            print(f"❌ FFmpeg Stream tool failed: {result}")
            test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_stream"] = result
    except Exception as e:
        print(f"❌ FFmpeg Stream tool error: {e}")
        test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_stream"] = {"status": "error", "error": str(e)}
    test_results["tools_tested"] += 1
    
    # Test 4: FFmpeg Edit Tool
    print("\n4. Testing FFmpeg Edit Tool...")
    try:
        from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_edit import main as edit_main
        result = await edit_main()
        if result.get("status") == "success":
            print("✅ FFmpeg Edit tool initialized successfully")
            test_results["tools_passed"] += 1
        else:
            print(f"❌ FFmpeg Edit tool failed: {result}")
            test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_edit"] = result
    except Exception as e:
        print(f"❌ FFmpeg Edit tool error: {e}")
        test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_edit"] = {"status": "error", "error": str(e)}
    test_results["tools_tested"] += 1
    
    # Test 5: FFmpeg Info Tool
    print("\n5. Testing FFmpeg Info Tool...")
    try:
        from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_info import main as info_main
        result = await info_main()
        if result.get("status") == "success":
            print("✅ FFmpeg Info tool initialized successfully")
            test_results["tools_passed"] += 1
        else:
            print(f"❌ FFmpeg Info tool failed: {result}")
            test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_info"] = result
    except Exception as e:
        print(f"❌ FFmpeg Info tool error: {e}")
        test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_info"] = {"status": "error", "error": str(e)}
    test_results["tools_tested"] += 1
    
    # Test 6: FFmpeg Filters Tool
    print("\n6. Testing FFmpeg Filters Tool...")
    try:
        from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_filters import main as filters_main
        result = await filters_main()
        if result.get("status") == "success":
            print("✅ FFmpeg Filters tool initialized successfully")
            test_results["tools_passed"] += 1
        else:
            print(f"❌ FFmpeg Filters tool failed: {result}")
            test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_filters"] = result
    except Exception as e:
        print(f"❌ FFmpeg Filters tool error: {e}")
        test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_filters"] = {"status": "error", "error": str(e)}
    test_results["tools_tested"] += 1
    
    # Test 7: FFmpeg Batch Tool
    print("\n7. Testing FFmpeg Batch Tool...")
    try:
        from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_batch import main as batch_main
        result = await batch_main()
        if result.get("status") == "success":
            print("✅ FFmpeg Batch tool initialized successfully")
            test_results["tools_passed"] += 1
        else:
            print(f"❌ FFmpeg Batch tool failed: {result}")
            test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_batch"] = result
    except Exception as e:
        print(f"❌ FFmpeg Batch tool error: {e}")
        test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_batch"] = {"status": "error", "error": str(e)}
    test_results["tools_tested"] += 1
    
    # Test 8: FFmpeg Utils
    print("\n8. Testing FFmpeg Utils...")
    try:
        from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_utils import ffmpeg_utils
        # Test basic utilities
        supported_formats = ffmpeg_utils.get_supported_formats()
        supported_codecs = ffmpeg_utils.get_supported_codecs()
        
        if supported_formats and supported_codecs:
            print("✅ FFmpeg Utils working successfully")
            test_results["tools_passed"] += 1
            test_results["results"]["ffmpeg_utils"] = {
                "status": "success",
                "formats_count": len(supported_formats.get("both", [])),
                "codecs_count": len(supported_codecs.get("video", []) + supported_codecs.get("audio", []))
            }
        else:
            print("❌ FFmpeg Utils failed to get format/codec information")
            test_results["tools_failed"] += 1
            test_results["results"]["ffmpeg_utils"] = {"status": "error", "error": "Could not get format/codec info"}
    except Exception as e:
        print(f"❌ FFmpeg Utils error: {e}")
        test_results["tools_failed"] += 1
        test_results["results"]["ffmpeg_utils"] = {"status": "error", "error": str(e)}
    test_results["tools_tested"] += 1
    
    # Print final results
    print(f"\n🧪 FFmpeg Tools Test Summary")
    print(f"📊 Overall Results:")
    print(f"   Total tests run: {test_results['tools_tested']}")
    print(f"   Passed: {test_results['tools_passed']}")
    print(f"   Failed: {test_results['tools_failed']}")
    success_rate = (test_results['tools_passed'] / test_results['tools_tested'] * 100) if test_results['tools_tested'] > 0 else 0
    print(f"   Success rate: {success_rate:.1f}%")
    
    # Save detailed results
    results_file = "ffmpeg_tools_test_results.json"
    with open(results_file, 'w') as f:
        json.dump(test_results, f, indent=2)
    print(f"\n📄 Detailed results saved to: {results_file}")
    
    return test_results['tools_failed'] == 0

if __name__ == "__main__":
    try:
        success = asyncio.run(test_ffmpeg_tools())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n❌ Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        sys.exit(1)
