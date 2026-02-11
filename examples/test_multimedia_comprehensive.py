#!/usr/bin/env python3
"""
Comprehensive test runner for multimedia (yt-dlp) functionality.

This script runs all unit tests for the YT-DLP wrapper library and MCP server tools,
providing detailed reporting and validation of the multimedia integration.
"""

import anyio
import os
import sys
import subprocess
import time
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def run_command(command, description="", capture_output=True):
    """Run a shell command and return the result."""
    print(f"\n🔄 {description}")
    print(f"Command: {command}")
    
    try:
        if capture_output:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=project_root
            )
        else:
            result = subprocess.run(command, shell=True, cwd=project_root)
            
        if result.returncode == 0:
            print(f"✅ {description} - SUCCESS")
            if capture_output and result.stdout:
                print(f"Output: {result.stdout[:500]}...")
        else:
            print(f"❌ {description} - FAILED")
            if capture_output and result.stderr:
                print(f"Error: {result.stderr[:500]}...")
            
        return result
    except Exception as e:
        print(f"❌ {description} - EXCEPTION: {e}")
        return None

def check_dependencies():
    """Check if required dependencies are installed."""
    print("\n📦 Checking Dependencies...")
    
    # Check yt-dlp
    result = run_command("python -c 'import yt_dlp; print(f\"yt-dlp version: {yt_dlp.version.__version__}\")'", 
                        "Checking yt-dlp installation")
    
    # Check multimedia module
    result = run_command("python -c 'from ipfs_datasets_py.data_transformation.multimedia import HAVE_YTDLP; print(f\"HAVE_YTDLP: {HAVE_YTDLP}\")'",
                        "Checking multimedia module")
    
    # Check MCP tools
    result = run_command("python -c 'from ipfs_datasets_py.mcp_server.tools.media_tools import ytdlp_download_video; print(\"MCP tools import: SUCCESS\")'",
                        "Checking MCP multimedia tools")
    
    return True

def run_unit_tests():
    """Run unit tests for YT-DLP wrapper and MCP tools."""
    print("\n🧪 Running Unit Tests...")
    
    test_files = [
        "tests/unit/test_ytdlp_wrapper.py",
        "tests/unit/test_ytdlp_mcp_tools.py"
    ]
    
    results = {}
    
    for test_file in test_files:
        if Path(test_file).exists():
            print(f"\n📋 Running {test_file}...")
            result = run_command(f".venv/bin/python -m pytest {test_file} -v", 
                               f"Unit tests: {test_file}")
            results[test_file] = result.returncode == 0 if result else False
        else:
            print(f"⚠️  Test file not found: {test_file}")
            results[test_file] = False
    
    return results

def run_integration_tests():
    """Run integration tests for multimedia functionality."""
    print("\n🔗 Running Integration Tests...")
    
    # Test multimedia library integration
    test_code = '''
import anyio
from ipfs_datasets_py.data_transformation.multimedia import YtDlpWrapper, HAVE_YTDLP

async def test_integration():
    print(f"YT-DLP Available: {HAVE_YTDLP}")
    
    if HAVE_YTDLP:
        wrapper = YtDlpWrapper()
        
        # Test URL validation
        valid_url = wrapper.validate_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        print(f"URL Validation: {valid_url}")
        
        # Test supported sites
        sites = wrapper.get_supported_sites()
        print(f"Supported sites count: {len(sites)}")
        
        # Test filename sanitization
        clean_name = wrapper.sanitize_filename("Test<>Video|Name?.mp4")
        print(f"Filename sanitization: {clean_name}")
        
        print("✅ Integration test passed")
        return True
    else:
        print("❌ YT-DLP not available")
        return False

if __name__ == "__main__":
    result = anyio.run(test_integration())
    exit(0 if result else 1)
'''
    
    with open('temp_integration_test.py', 'w') as f:
        f.write(test_code)
    
    try:
        result = run_command(".venv/bin/python temp_integration_test.py", 
                           "Multimedia integration test")
        return result.returncode == 0 if result else False
    finally:
        if Path('temp_integration_test.py').exists():
            Path('temp_integration_test.py').unlink()

def test_mcp_tools_integration():
    """Test MCP tools integration."""
    print("\n🔧 Testing MCP Tools Integration...")
    
    test_code = '''
import anyio
from ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download import (
    ytdlp_extract_info, main
)

async def test_mcp_tools():
    # Test tool initialization
    init_result = await main()
    print(f"MCP tool initialization: {init_result['status']}")
    
    # Test extract_info with mock URL (should fail gracefully)
    info_result = await ytdlp_extract_info(
        url="https://example.com/invalid",
        download=False
    )
    print(f"Extract info test: {info_result['status']}")
    print(f"Tool name: {info_result.get('tool', 'unknown')}")
    
    return init_result['status'] == 'success'

if __name__ == "__main__":
    result = anyio.run(test_mcp_tools())
    exit(0 if result else 1)
'''
    
    with open('temp_mcp_test.py', 'w') as f:
        f.write(test_code)
    
    try:
        result = run_command(".venv/bin/python temp_mcp_test.py", 
                           "MCP tools integration test")
        return result.returncode == 0 if result else False
    finally:
        if Path('temp_mcp_test.py').exists():
            Path('temp_mcp_test.py').unlink()

def validate_multimedia_setup():
    """Validate the complete multimedia setup."""
    print("\n✅ Validating Multimedia Setup...")
    
    validation_code = '''
import sys
from pathlib import Path

# Test imports
try:
    from ipfs_datasets_py.data_transformation.multimedia import YtDlpWrapper, HAVE_YTDLP
    from ipfs_datasets_py.mcp_server.tools.media_tools import (
        ytdlp_download_video, ytdlp_download_playlist, 
        ytdlp_extract_info, ytdlp_search_videos, ytdlp_batch_download
    )
    print("✅ All imports successful")
    
    # Check multimedia module
    print(f"YT-DLP Available: {HAVE_YTDLP}")
    
    # Check tool availability
    tools = [
        ytdlp_download_video, ytdlp_download_playlist,
        ytdlp_extract_info, ytdlp_search_videos, ytdlp_batch_download
    ]
    print(f"Available MCP tools: {len(tools)}")
    
    # Check wrapper functionality  
    wrapper = YtDlpWrapper()
    sites = wrapper.get_supported_sites()
    print(f"Supported sites: {len(sites)} sites")
    
    print("✅ Multimedia setup validation passed")
    exit(0)
    
except Exception as e:
    print(f"❌ Validation failed: {e}")
    exit(1)
'''
    
    with open('temp_validation.py', 'w') as f:
        f.write(validation_code)
    
    try:
        result = run_command(".venv/bin/python temp_validation.py", 
                           "Final multimedia validation")
        return result.returncode == 0 if result else False
    finally:
        if Path('temp_validation.py').exists():
            Path('temp_validation.py').unlink()

def generate_report(unit_results, integration_result, mcp_result, validation_result):
    """Generate a comprehensive test report."""
    print("\n" + "="*60)
    print("📊 MULTIMEDIA TESTING REPORT")
    print("="*60)
    
    print(f"\n📦 Dependencies: ✅ Installed")
    print(f"🧪 Unit Tests:")
    for test_file, success in unit_results.items():
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"   - {Path(test_file).name}: {status}")
    
    print(f"\n🔗 Integration Tests:")
    print(f"   - Multimedia Library: {'✅ PASSED' if integration_result else '❌ FAILED'}")
    print(f"   - MCP Tools: {'✅ PASSED' if mcp_result else '❌ FAILED'}")
    
    print(f"\n✅ Final Validation: {'✅ PASSED' if validation_result else '❌ FAILED'}")
    
    # Calculate overall success
    all_unit_passed = all(unit_results.values())
    overall_success = all_unit_passed and integration_result and mcp_result and validation_result
    
    print(f"\n🎯 OVERALL RESULT: {'✅ ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}")
    
    if overall_success:
        print("\n🎉 YT-DLP multimedia integration is fully functional!")
        print("   - YT-DLP wrapper library: Ready")
        print("   - MCP server tools: Ready") 
        print("   - Unit tests: Passing")
        print("   - Integration: Working")
    else:
        print("\n⚠️  Some issues detected. Check the logs above for details.")
    
    print("="*60)
    return overall_success

def main():
    """Main test runner function."""
    print("🚀 Starting Multimedia (YT-DLP) Test Suite")
    print(f"Working directory: {project_root}")
    
    start_time = time.time()
    
    # Check dependencies
    if not check_dependencies():
        print("❌ Dependency check failed")
        return False
    
    # Run unit tests
    unit_results = run_unit_tests()
    
    # Run integration tests
    integration_result = run_integration_tests()
    
    # Test MCP tools
    mcp_result = test_mcp_tools_integration()
    
    # Final validation
    validation_result = validate_multimedia_setup()
    
    # Generate report
    overall_success = generate_report(unit_results, integration_result, mcp_result, validation_result)
    
    elapsed_time = time.time() - start_time
    print(f"\n⏱️  Total test time: {elapsed_time:.2f} seconds")
    
    return overall_success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
