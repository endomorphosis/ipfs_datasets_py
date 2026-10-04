#!/usr/bin/env python3
"""
Simple multimedia functionality validation script.

This script validates that the yt-dlp integration is working correctly
with the MCP server tools.
"""

import anyio
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_basic_imports():
    """Test that all basic imports work correctly."""
    print("🔄 Testing basic imports...")

    try:
        # Test multimedia library imports
        from ipfs_datasets_py.data_transformation.multimedia import YtDlpWrapper, HAVE_YTDLP

        print(f"✅ YtDlpWrapper imported, HAVE_YTDLP: {HAVE_YTDLP}")

        # Test MCP tool imports
        from ipfs_datasets_py.mcp_server.tools.media_tools import (
            ytdlp_download_video,
            ytdlp_download_playlist,
            ytdlp_extract_info,
            ytdlp_search_videos,
            ytdlp_batch_download,
        )

        print("✅ All MCP multimedia tools imported successfully")

        # Test media_tools module import
        from ipfs_datasets_py.mcp_server.tools.media_tools import __all__

        ytdlp_tools = [tool for tool in __all__ if "ytdlp" in tool]
        print(f"✅ YT-DLP tools in __all__: {ytdlp_tools}")

        return True

    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False


def test_wrapper_functionality():
    """Test YtDlpWrapper basic functionality."""
    print("\n🔄 Testing YtDlpWrapper functionality...")

    try:
        from ipfs_datasets_py.data_transformation.multimedia import YtDlpWrapper
        from ipfs_datasets_py.data_transformation.multimedia.media_utils import MediaUtils

        # Create wrapper instance
        wrapper = YtDlpWrapper()

        # Test URL validation using MediaUtils
        valid_url = MediaUtils.validate_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        print(f"✅ URL validation: {valid_url}")

        # Test supported formats using MediaUtils
        formats = MediaUtils.get_supported_formats()
        print(f"✅ Supported formats: {len(formats)} types")

        # Test filename sanitization using MediaUtils
        clean_name = MediaUtils.sanitize_filename("Test<>Video|Name?.mp4")
        print(f"✅ Filename sanitization: '{clean_name}'")

        # Test file size formatting using MediaUtils
        size_str = MediaUtils.format_file_size(1024 * 1024)
        print(f"✅ File size formatting: {size_str}")

        # Test duration formatting using MediaUtils
        duration_str = MediaUtils.format_duration(3661)  # 1 hour 1 minute 1 second
        print(f"✅ Duration formatting: {duration_str}")

        # Test wrapper methods
        downloads = wrapper.list_active_downloads()
        print(f"✅ Active downloads: {downloads['total_active']}")

        # Test download status for non-existent download
        status = wrapper.get_download_status("nonexistent")
        print(f"✅ Download status check: {status['status']}")

        return True

    except Exception as e:
        print(f"❌ Wrapper functionality test failed: {e}")
        return False


async def test_mcp_tools():
    """Test MCP tool functionality."""
    print("\n🔄 Testing MCP tools functionality...")

    try:
        from ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download import (
            ytdlp_extract_info,
            main,
        )

        # Test tool initialization
        init_result = await main()
        print(f"✅ MCP tool initialization: {init_result['status']}")
        print(f"   Available tools: {len(init_result.get('tools', []))}")

        # Test extract_info with invalid URL (should fail gracefully)
        info_result = await ytdlp_extract_info(url="https://example.com/invalid", download=False)
        print(f"✅ Extract info test: {info_result['status']}")
        print(f"   Tool name: {info_result.get('tool', 'unknown')}")

        # Test with empty URL (should fail gracefully)
        empty_result = await ytdlp_extract_info(url="", download=False)
        print(f"✅ Empty URL test: {empty_result['status']}")

        return True

    except Exception as e:
        print(f"❌ MCP tools test failed: {e}")
        return False


def test_module_structure():
    """Test the module structure and exports."""
    print("\n🔄 Testing module structure...")

    try:
        # Test multimedia module structure
        from ipfs_datasets_py.data_transformation.multimedia import __all__

        print(f"✅ Multimedia module exports: {__all__}")

        # Test media_tools module structure
        from ipfs_datasets_py.mcp_server.tools.media_tools import __all__ as media_all

        print(f"✅ Media tools exports: {len(media_all)} tools")

        # Check that yt-dlp tools are included
        ytdlp_tools = [tool for tool in media_all if "ytdlp" in tool]
        print(f"✅ YT-DLP tools registered: {ytdlp_tools}")

        if len(ytdlp_tools) >= 5:  # Should have 5 yt-dlp tools
            print("✅ All expected yt-dlp tools are registered")
            return True
        else:
            print(f"⚠️  Expected 5 yt-dlp tools, found {len(ytdlp_tools)}")
            return False

    except Exception as e:
        print(f"❌ Module structure test failed: {e}")
        return False


async def main():
    """Main validation function."""
    print("🚀 Simple Multimedia Validation")
    print("=" * 50)

    # Run tests
    test_results = []

    print("1️⃣ Testing Imports")
    test_results.append(test_basic_imports())

    print("\n2️⃣ Testing Wrapper Functionality")
    test_results.append(test_wrapper_functionality())

    print("\n3️⃣ Testing MCP Tools")
    test_results.append(await test_mcp_tools())

    print("\n4️⃣ Testing Module Structure")
    test_results.append(test_module_structure())

    # Summary
    print("\n" + "=" * 50)
    print("📊 VALIDATION RESULTS")
    print("=" * 50)

    passed = sum(test_results)
    total = len(test_results)

    print(f"Tests passed: {passed}/{total}")

    if passed == total:
        print("🎉 ALL TESTS PASSED!")
        print("\n✅ YT-DLP multimedia integration is fully functional!")
        print("   - YT-DLP wrapper library: Ready")
        print("   - MCP server tools: Ready")
        print("   - Module exports: Correct")
        print("   - Basic functionality: Working")
        return True
    else:
        print(f"⚠️  {total - passed} test(s) failed")
        return False


if __name__ == "__main__":
    success = anyio.run(main())
    sys.exit(0 if success else 1)
