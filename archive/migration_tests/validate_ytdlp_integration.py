#!/usr/bin/env python3
"""
Quick validation script for YT-DLP multimedia integration.

This script performs basic validation of the newly added yt-dlp functionality
to ensure everything is properly integrated and accessible.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


async def validate_multimedia_library():
    """Validate the multimedia library components."""
    print("🔍 Validating multimedia library...")
    
    try:
        # Test imports
        from ipfs_datasets_py.multimedia import (
            YtDlpWrapper, FFmpegWrapper, MediaProcessor, MediaUtils,
            HAVE_YTDLP, HAVE_FFMPEG
        )
        print("✓ All multimedia components imported successfully")
        
        # Test feature flags
        print(f"✓ YT-DLP available: {HAVE_YTDLP}")
        print(f"✓ FFmpeg available: {HAVE_FFMPEG}")
        
        # Test YtDlpWrapper initialization
        wrapper = YtDlpWrapper(enable_logging=False)
        print("✓ YtDlpWrapper initialized successfully")
        
        # Test MediaProcessor initialization
        processor = MediaProcessor(enable_logging=False)
        capabilities = processor.get_capabilities()
        print(f"✓ MediaProcessor capabilities: {list(capabilities.keys())}")
        
        # Test MediaUtils functionality
        assert MediaUtils.get_file_type("test.mp4") == "video"
        assert MediaUtils.get_file_type("test.mp3") == "audio"
        assert MediaUtils.is_media_file("test.mp4") is True
        print("✓ MediaUtils functionality working")
        
        return True
        
    except Exception as e:
        print(f"❌ Multimedia library validation failed: {e}")
        return False


async def validate_mcp_tools():
    """Validate the MCP server tools."""
    print("\n🔍 Validating MCP server tools...")
    
    try:
        # Test imports
        from ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download import (
            ytdlp_download_video,
            ytdlp_download_playlist,
            ytdlp_extract_info,
            ytdlp_search_videos,
            ytdlp_batch_download,
            main
        )
        print("✓ All MCP tools imported successfully")
        
        # Test main function
        result = await main()
        assert result["status"] == "success"
        assert len(result["tools"]) == 5
        print(f"✓ MCP tools registration: {result['status']}")
        print(f"✓ Available tools: {', '.join(result['tools'])}")
        
        return True
        
    except Exception as e:
        print(f"❌ MCP tools validation failed: {e}")
        return False


async def validate_media_tools_module():
    """Validate the media_tools module integration."""
    print("\n🔍 Validating media_tools module integration...")
    
    try:
        # Test media_tools imports
        from ipfs_datasets_py.mcp_server.tools.media_tools import (
            ytdlp_download_video,
            ytdlp_download_playlist,
            ytdlp_extract_info,
            ytdlp_search_videos,
            ytdlp_batch_download
        )
        print("✓ YT-DLP tools available in media_tools module")
        
        # Test that all tools are in __all__
        from ipfs_datasets_py.mcp_server.tools.media_tools import __all__
        ytdlp_tools = [
            "ytdlp_download_video",
            "ytdlp_download_playlist", 
            "ytdlp_extract_info",
            "ytdlp_search_videos",
            "ytdlp_batch_download"
        ]
        
        for tool in ytdlp_tools:
            assert tool in __all__, f"{tool} not in __all__"
        
        print(f"✓ All YT-DLP tools properly exported in __all__")
        print(f"✓ Total media tools available: {len(__all__)}")
        
        return True
        
    except Exception as e:
        print(f"❌ Media tools module validation failed: {e}")
        return False


async def validate_error_handling():
    """Validate error handling when yt-dlp is not available."""
    print("\n🔍 Validating error handling...")
    
    try:
        from unittest.mock import patch
        from ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download import ytdlp_download_video
        
        # Test behavior when yt-dlp is not available
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.HAVE_YTDLP', False):
            result = await ytdlp_download_video("https://example.com/test")
            assert result["status"] == "error"
            assert "not available" in result["error"]
        
        print("✓ Error handling working correctly when yt-dlp unavailable")
        
        return True
        
    except Exception as e:
        print(f"❌ Error handling validation failed: {e}")
        return False


async def validate_tool_parameters():
    """Validate tool parameter handling."""
    print("\n🔍 Validating tool parameter handling...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download import (
            ytdlp_download_video, ytdlp_extract_info, ytdlp_search_videos
        )
        
        # Test invalid parameters
        result = await ytdlp_download_video("")
        assert result["status"] == "error"
        
        result = await ytdlp_extract_info("")
        assert result["status"] == "error"
        
        result = await ytdlp_search_videos("")
        assert result["status"] == "error"
        
        print("✓ Parameter validation working correctly")
        
        return True
        
    except Exception as e:
        print(f"❌ Parameter validation failed: {e}")
        return False


async def main():
    """Run comprehensive validation."""
    print("🎬 YT-DLP Multimedia Integration Validation")
    print("=" * 60)
    
    validations = [
        ("Multimedia Library", validate_multimedia_library),
        ("MCP Tools", validate_mcp_tools),
        ("Media Tools Module", validate_media_tools_module),
        ("Error Handling", validate_error_handling),
        ("Parameter Validation", validate_tool_parameters)
    ]
    
    results = []
    for name, validation_func in validations:
        try:
            result = await validation_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ {name} validation crashed: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 VALIDATION SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status} - {name}")
    
    print(f"\nOverall: {passed}/{total} validations passed")
    
    if passed == total:
        print("🎉 All validations passed! YT-DLP integration is ready!")
        return 0
    else:
        print("⚠️  Some validations failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
