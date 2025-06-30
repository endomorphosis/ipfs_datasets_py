#!/usr/bin/env python3
"""
Comprehensive test runner for YT-DLP multimedia integration.

This script runs all tests for the yt-dlp integration including:
- Unit tests for the YtDlpWrapper library
- Unit tests for the MCP server tools
- Integration tests for the complete multimedia system
"""

import asyncio
import sys
import time
import subprocess
from pathlib import Path
from typing import Dict, List, Any

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def run_command(command: List[str], description: str) -> Dict[str, Any]:
    """
    Run a command and return results.
    
    Args:
        command: Command to run as list of strings
        description: Description of what the command does
        
    Returns:
        Dict containing execution results
    """
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(command)}")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        duration = time.time() - start_time
        
        return {
            "description": description,
            "command": command,
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration": duration
        }
        
    except subprocess.TimeoutExpired:
        return {
            "description": description,
            "command": command,
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "Command timed out after 5 minutes",
            "duration": time.time() - start_time
        }
    except Exception as e:
        return {
            "description": description,
            "command": command,
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "duration": time.time() - start_time
        }


def print_result(result: Dict[str, Any]) -> None:
    """Print test result in a formatted way."""
    status = "✅ PASSED" if result["success"] else "❌ FAILED"
    duration = f"{result['duration']:.2f}s"
    
    print(f"\n{status} - {result['description']} ({duration})")
    
    if result["stdout"]:
        print("\nSTDOUT:")
        print(result["stdout"])
    
    if result["stderr"] and not result["success"]:
        print("\nSTDERR:")
        print(result["stderr"])


def main():
    """Run comprehensive multimedia tests."""
    print("🎬 YT-DLP Multimedia Integration Test Suite")
    print("=" * 80)
    
    # Test configurations
    test_configs = [
        {
            "command": [
                sys.executable, "-m", "pytest", 
                "tests/unit/test_ytdlp_wrapper.py",
                "-v", "--tb=short"
            ],
            "description": "YT-DLP Wrapper Library Unit Tests"
        },
        {
            "command": [
                sys.executable, "-m", "pytest",
                "tests/unit/test_ytdlp_mcp_tools.py", 
                "-v", "--tb=short"
            ],
            "description": "YT-DLP MCP Server Tools Unit Tests"
        },
        {
            "command": [
                sys.executable, "-m", "pytest",
                "tests/integration/test_multimedia_integration.py",
                "-v", "--tb=short"
            ],
            "description": "Multimedia System Integration Tests"
        },
        {
            "command": [
                sys.executable, "-m", "pytest",
                "tests/unit/test_ytdlp_wrapper.py",
                "tests/unit/test_ytdlp_mcp_tools.py",
                "--cov=ipfs_datasets_py.multimedia",
                "--cov=ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download",
                "--cov-report=term-missing",
                "--cov-report=html:htmlcov_ytdlp"
            ],
            "description": "Coverage Analysis for YT-DLP Components"
        },
        {
            "command": [
                sys.executable, "-c", """
import asyncio
from ipfs_datasets_py.multimedia import YtDlpWrapper, MediaProcessor, MediaUtils, HAVE_YTDLP
from ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download import main

async def test_imports():
    print('✓ YtDlpWrapper imported successfully')
    print('✓ MediaProcessor imported successfully') 
    print('✓ MediaUtils imported successfully')
    print(f'✓ HAVE_YTDLP = {HAVE_YTDLP}')
    
    result = await main()
    print(f'✓ MCP tool main() = {result[\"status\"]}')
    print('✓ All imports and basic functionality working')

asyncio.run(test_imports())
"""
            ],
            "description": "Import and Basic Functionality Test"
        }
    ]
    
    # Run all tests
    results = []
    for config in test_configs:
        result = run_command(config["command"], config["description"])
        print_result(result)
        results.append(result)
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 TEST SUMMARY")
    print("=" * 80)
    
    total_tests = len(results)
    passed_tests = sum(1 for r in results if r["success"])
    failed_tests = total_tests - passed_tests
    total_duration = sum(r["duration"] for r in results)
    
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests} ✅")
    print(f"Failed: {failed_tests} ❌")
    print(f"Success Rate: {passed_tests/total_tests*100:.1f}%")
    print(f"Total Duration: {total_duration:.2f}s")
    
    # Detailed results
    print(f"\n{'='*80}")
    print("📋 DETAILED RESULTS")
    print(f"{'='*80}")
    
    for i, result in enumerate(results, 1):
        status_icon = "✅" if result["success"] else "❌"
        print(f"{i}. {status_icon} {result['description']} ({result['duration']:.2f}s)")
        if not result["success"]:
            print(f"   Error: {result['stderr'][:100]}...")
    
    # Exit with appropriate code
    if failed_tests > 0:
        print(f"\n❌ {failed_tests} test(s) failed!")
        return 1
    else:
        print(f"\n✅ All {passed_tests} tests passed!")
        return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
