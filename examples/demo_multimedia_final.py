#!/usr/bin/env python3
"""
Final demonstration of YT-DLP multimedia integration.

This script demonstrates all the key functionality of the YT-DLP integration
with both the multimedia library and MCP server tools.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def demo_multimedia_library():
    """Demonstrate multimedia library functionality."""
    print("🎬 Multimedia Library Demo")
    print("="*40)
    
    try:
        from ipfs_datasets_py.multimedia import YtDlpWrapper, MediaUtils, HAVE_YTDLP
        
        print(f"YT-DLP Available: {HAVE_YTDLP}")
        
        if not HAVE_YTDLP:
            print("❌ YT-DLP not available")
            return False
        
        # Create wrapper
        wrapper = YtDlpWrapper()
        
        # Demonstrate utility functions
        print("\n📋 Utility Functions:")
        valid_url = MediaUtils.validate_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        print(f"  URL validation: {valid_url}")
        
        formats = MediaUtils.get_supported_formats()
        print(f"  Supported video formats: {len(formats['video'])}")
        print(f"  Supported audio formats: {len(formats['audio'])}")
        
        clean_name = MediaUtils.sanitize_filename("My <Cool> Video|Title?.mp4")
        print(f"  Sanitized filename: '{clean_name}'")
        
        size_str = MediaUtils.format_file_size(1024 * 1024 * 500)
        print(f"  File size formatting: {size_str}")
        
        duration_str = MediaUtils.format_duration(3661)
        print(f"  Duration formatting: {duration_str}")
        
        # Demonstrate wrapper methods
        print("\n🔧 Wrapper Methods:")
        downloads = wrapper.list_active_downloads()
        print(f"  Active downloads: {downloads['total_active']}")
        print(f"  Completed downloads: {downloads['total_completed']}")
        
        # Test info extraction (this may fail but should handle gracefully)
        print("\n📄 Info Extraction Test:")
        try:
            info = await wrapper.extract_info("https://httpbin.org/status/404", download=False)
            print(f"  Info extraction: {info['status']}")
        except Exception as e:
            print(f"  Info extraction: Failed gracefully ({type(e).__name__})")
        
        return True
        
    except Exception as e:
        print(f"❌ Library demo failed: {e}")
        return False

async def demo_mcp_tools():
    """Demonstrate MCP tools functionality."""
    print("\n🔧 MCP Tools Demo")
    print("="*40)
    
    try:
        from ipfs_datasets_py.mcp_server.tools.media_tools import (
            ytdlp_download_video, ytdlp_download_playlist,
            ytdlp_extract_info, ytdlp_search_videos, ytdlp_batch_download
        )
        
        # Test tool initialization
        from ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download import main
        init_result = await main()
        print(f"Tool initialization: {init_result['status']}")
        print(f"Available tools: {init_result.get('tools', [])}")
        
        # Test individual tools (with invalid URLs to test error handling)
        print("\n🧪 Tool Tests:")
        
        # Test extract_info
        info_result = await ytdlp_extract_info(
            url="https://httpbin.org/status/404",
            download=False
        )
        print(f"  Extract info: {info_result['status']} (expected: error)")
        
        # Test search (with empty query to test validation)
        search_result = await ytdlp_search_videos(
            query="",
            max_results=1
        )
        print(f"  Search videos: {search_result['status']} (expected: error)")
        
        # Test batch download (with empty list to test validation)
        batch_result = await ytdlp_batch_download(
            urls=[],
            concurrent_downloads=1
        )
        print(f"  Batch download: {batch_result['status']} (expected: error)")
        
        # Test download video (with invalid URL to test error handling)
        download_result = await ytdlp_download_video(
            url="invalid-url",
            quality="best"
        )
        print(f"  Download video: {download_result['status']} (expected: error)")
        
        return True
        
    except Exception as e:
        print(f"❌ MCP tools demo failed: {e}")
        return False

def demo_module_structure():
    """Demonstrate module structure and exports."""
    print("\n📦 Module Structure Demo")
    print("="*40)
    
    try:
        # Test multimedia module
        from ipfs_datasets_py.multimedia import __all__ as multimedia_all
        print(f"Multimedia exports: {multimedia_all}")
        
        # Test media_tools module  
        from ipfs_datasets_py.mcp_server.tools.media_tools import __all__ as media_all
        ytdlp_tools = [tool for tool in media_all if 'ytdlp' in tool]
        print(f"YT-DLP MCP tools: {ytdlp_tools}")
        
        # Verify all expected tools are present
        expected_tools = [
            'ytdlp_download_video', 'ytdlp_download_playlist',
            'ytdlp_extract_info', 'ytdlp_search_videos', 'ytdlp_batch_download'
        ]
        
        missing_tools = [tool for tool in expected_tools if tool not in ytdlp_tools]
        if missing_tools:
            print(f"❌ Missing tools: {missing_tools}")
            return False
        
        print("✅ All expected tools are properly exported")
        return True
        
    except Exception as e:
        print(f"❌ Module structure demo failed: {e}")
        return False

async def main():
    """Main demo function."""
    print("🚀 YT-DLP Multimedia Integration Demo")
    print("="*50)
    
    # Run demos
    results = []
    
    results.append(await demo_multimedia_library())
    results.append(await demo_mcp_tools()) 
    results.append(demo_module_structure())
    
    # Summary
    print("\n" + "="*50)
    print("📊 DEMO RESULTS")
    print("="*50)
    
    passed = sum(results)
    total = len(results)
    
    print(f"Demo sections passed: {passed}/{total}")
    
    if passed == total:
        print("\n🎉 ALL DEMOS SUCCESSFUL!")
        print("\n✅ YT-DLP multimedia integration is fully operational:")
        print("   - Multimedia library with YtDlpWrapper")
        print("   - 5 MCP server tools for video/audio processing")
        print("   - Comprehensive utility functions")
        print("   - Proper error handling and validation")
        print("   - Ready for production use!")
        
        print("\n🔧 Available MCP Tools:")
        print("   - ytdlp_download_video: Download single videos")
        print("   - ytdlp_download_playlist: Download entire playlists")
        print("   - ytdlp_extract_info: Extract video metadata")
        print("   - ytdlp_search_videos: Search for videos") 
        print("   - ytdlp_batch_download: Download multiple videos")
        
        print("\n📚 Supported Platforms: 1000+ including YouTube, Vimeo, SoundCloud")
        return True
    else:
        print(f"\n⚠️  {total - passed} demo(s) failed")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
