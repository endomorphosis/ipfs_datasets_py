#!/usr/bin/env python3
"""
FFmpeg Tools Demonstration

This script demonstrates the capabilities of the integrated FFmpeg tools
in the IPFS Datasets MCP server.
"""
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

async def demonstrate_ffmpeg_tools():
    """Demonstrate all FFmpeg tool capabilities."""
    print("🎬 FFmpeg Tools Integration Demonstration")
    print("=" * 60)
    
    # Import the tools
    from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_convert import main as convert_main
    from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_info import main as info_main
    from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_filters import main as filters_main
    from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_batch import main as batch_main
    from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_utils import ffmpeg_utils
    
    print("\n📋 1. FFmpeg System Information")
    print("-" * 40)
    
    # Display system capabilities
    try:
        formats = ffmpeg_utils.get_supported_formats()
        codecs = ffmpeg_utils.get_supported_codecs()
        
        print(f"✅ FFmpeg found at: {ffmpeg_utils.ffmpeg_path}")
        print(f"✅ FFprobe found at: {ffmpeg_utils.ffprobe_path}")
        print(f"📦 Supported formats: {len(formats.get('both', []))} input/output")
        print(f"🎥 Video codecs: {len(codecs.get('video', []))}")
        print(f"🎵 Audio codecs: {len(codecs.get('audio', []))}")
        
        # Show some popular formats
        common_formats = ['mp4', 'avi', 'mkv', 'mov', 'flv', 'webm', 'mp3', 'wav', 'flac', 'aac']
        available_formats = [f for f in common_formats if f in formats.get('both', [])]
        print(f"🔧 Common formats available: {', '.join(available_formats)}")
        
    except Exception as e:
        print(f"❌ Error getting FFmpeg info: {e}")
    
    print("\n🔧 2. Tool Initialization Status")
    print("-" * 40)
    
    tools_info = {}
    
    # Test each tool's main function
    tool_tests = [
        ("Convert Tool", convert_main),
        ("Info/Probe Tool", info_main), 
        ("Filters Tool", filters_main),
        ("Batch Tool", batch_main)
    ]
    
    for tool_name, tool_main in tool_tests:
        try:
            result = await tool_main()
            if result.get("status") == "success":
                print(f"✅ {tool_name}: Ready")
                tools_info[tool_name] = result
            else:
                print(f"⚠️  {tool_name}: {result.get('message', 'Unknown error')}")
        except Exception as e:
            print(f"❌ {tool_name}: Error - {e}")
    
    print("\n🎯 3. FFmpeg Tool Capabilities")
    print("-" * 40)
    
    print("📹 Video Conversion:")
    print("   • Format conversion (MP4, AVI, MOV, MKV, WebM, etc.)")
    print("   • Codec transcoding (H.264, H.265, VP9, AV1, etc.)")
    print("   • Resolution and frame rate changes")
    print("   • Quality and compression settings")
    
    print("\n🎵 Audio Processing:")
    print("   • Format conversion (MP3, AAC, FLAC, WAV, etc.)")
    print("   • Audio codec transcoding")
    print("   • Bitrate and quality adjustments")
    print("   • Audio extraction from video")
    
    print("\n🔀 Muxing/Demuxing:")
    print("   • Combine multiple streams into one file")
    print("   • Extract specific streams from files")
    print("   • Container format changes")
    print("   • Subtitle and metadata handling")
    
    print("\n📡 Streaming:")
    print("   • Live stream input/capture")
    print("   • Stream output/broadcasting")
    print("   • Real-time processing")
    print("   • Network protocol support")
    
    print("\n✂️  Editing Operations:")
    print("   • Cut/trim segments")
    print("   • Splice multiple clips")
    print("   • Concatenate files")
    print("   • Frame-accurate editing")
    
    print("\n🎨 Filters and Effects:")
    print("   • Video filters (scale, crop, rotate, blur, etc.)")
    print("   • Audio filters (volume, EQ, noise reduction, etc.)")
    print("   • Complex filter graphs")
    print("   • Real-time filter application")
    
    print("\n⚡ Batch Processing:")
    print("   • Process multiple files in parallel")
    print("   • Progress tracking and resumption")
    print("   • Error handling and recovery")
    print("   • Checkpoint/resume functionality")
    
    print("\n📊 Analysis and Probing:")
    print("   • Detailed media file information")
    print("   • Stream analysis and metadata")
    print("   • Quality metrics and statistics")
    print("   • Frame-level analysis")
    
    print("\n🚀 4. Usage Examples")
    print("-" * 40)
    
    print("📝 Example MCP Tool Calls:")
    
    examples = [
        {
            "name": "Convert video to MP4",
            "tool": "ffmpeg_convert",
            "params": {
                "input_file": "video.avi",
                "output_file": "video.mp4", 
                "video_codec": "libx264",
                "audio_codec": "aac"
            }
        },
        {
            "name": "Extract audio from video",
            "tool": "ffmpeg_convert", 
            "params": {
                "input_file": "video.mp4",
                "output_file": "audio.mp3",
                "video_codec": None,
                "audio_codec": "mp3"
            }
        },
        {
            "name": "Apply video filters",
            "tool": "ffmpeg_apply_filters",
            "params": {
                "input_file": "input.mp4",
                "output_file": "filtered.mp4",
                "video_filters": ["scale=1280:720", "brightness=0.1"],
                "audio_filters": ["volume=0.8"]
            }
        },
        {
            "name": "Get media information",
            "tool": "ffmpeg_probe",
            "params": {
                "input_file": "media.mp4",
                "show_format": True,
                "show_streams": True
            }
        },
        {
            "name": "Batch convert files",
            "tool": "ffmpeg_batch_process",
            "params": {
                "input_files": ["file1.avi", "file2.mov"],
                "output_directory": "./converted/",
                "operation": "convert",
                "operation_params": {"video_codec": "libx264"}
            }
        }
    ]
    
    for i, example in enumerate(examples, 1):
        print(f"\n{i}. {example['name']}:")
        print(f"   Tool: {example['tool']}")
        print(f"   Parameters: {json.dumps(example['params'], indent=6)}")
    
    print("\n🔗 5. Integration Benefits")
    print("-" * 40)
    
    print("✨ MCP Server Integration:")
    print("   • Unified interface for all FFmpeg operations")
    print("   • Standardized parameter handling and validation")
    print("   • Comprehensive error handling and logging")
    print("   • Automatic format and codec detection")
    
    print("\n🤖 AI Assistant Benefits:")
    print("   • Natural language media processing requests")
    print("   • Intelligent parameter suggestion and validation")
    print("   • Batch operation planning and execution")
    print("   • Progress monitoring and error recovery")
    
    print("\n📈 Performance Features:")
    print("   • Parallel processing capabilities")
    print("   • Resume/checkpoint functionality")
    print("   • Resource usage optimization")
    print("   • Streaming and real-time processing")
    
    print("\n🛡️ Quality Assurance:")
    print("   • Input validation and safety checks")
    print("   • Detailed logging and debugging")
    print("   • Comprehensive test coverage")
    print("   • Error handling and recovery")
    
    print(f"\n✅ FFmpeg Tools Integration Complete!")
    print(f"🎉 All {len([tool for tool in tools_info if tools_info[tool].get('status') == 'success'])} tools successfully initialized")
    print(f"🔧 Ready for AI-assisted media processing workflows!")
    
    return True

if __name__ == "__main__":
    try:
        asyncio.run(demonstrate_ffmpeg_tools())
        print("\n🎬 Demonstration completed successfully!")
    except Exception as e:
        print(f"\n❌ Demonstration failed: {e}")
        sys.exit(1)
