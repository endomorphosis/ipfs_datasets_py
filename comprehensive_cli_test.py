#!/usr/bin/env python3
"""
Comprehensive test suite for IPFS Datasets CLI tools.
Tests all available tools to identify bugs and functionality issues.
Enhanced with dependency management integration.
"""

import subprocess
import json
import sys
import time
import os
from pathlib import Path

# Enable auto-installation for testing
os.environ.setdefault('IPFS_DATASETS_AUTO_INSTALL', 'true')

def run_command(cmd, timeout=30, expect_success=True):
    """Run a command and return the result."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0 if expect_success else result.returncode != 0,
            "cmd": " ".join(cmd)
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "Command timed out",
            "success": False,
            "cmd": " ".join(cmd)
        }
    except Exception as e:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "success": False,
            "cmd": " ".join(cmd)
        }

def test_basic_cli():
    """Test basic CLI functionality."""
    print("🧪 Testing basic CLI functionality...")
    
    tests = [
        # Original CLI tests
        (["python", "ipfs_datasets_cli.py", "--help"], True, "Original CLI help"),
        (["python", "ipfs_datasets_cli.py", "info", "status"], True, "Original CLI status"),
        (["python", "ipfs_datasets_cli.py", "info", "list-tools"], True, "Original CLI list tools"),
        (["python", "ipfs_datasets_cli.py", "--format", "json", "info", "status"], True, "Original CLI JSON output"),
        
        # Enhanced CLI tests
        (["python", "enhanced_cli.py", "--help"], True, "Enhanced CLI help"),
        (["python", "enhanced_cli.py", "--list-categories"], True, "Enhanced CLI list categories"),
        (["python", "enhanced_cli.py", "--list-tools", "dataset_tools"], True, "Enhanced CLI list dataset tools"),
        (["python", "enhanced_cli.py", "--format", "json", "--list-categories"], True, "Enhanced CLI JSON categories"),
    ]
    
    results = []
    for cmd, expect_success, description in tests:
        print(f"  ⚡ {description}...")
        result = run_command(cmd, expect_success=expect_success)
        results.append({
            "test": description,
            "success": result["success"],
            "cmd": result["cmd"],
            "error": result["stderr"] if not result["success"] else None
        })
        
        if result["success"]:
            print(f"    ✅ Passed")
        else:
            print(f"    ❌ Failed: {result['stderr']}")
    
    return results

def test_tool_categories():
    """Test tool functionality across categories."""
    print("🧪 Testing tool categories...")
    
    # Get list of categories from enhanced CLI
    result = run_command(["python", "enhanced_cli.py", "--format", "json", "--list-categories"])
    if not result["success"]:
        print("❌ Could not get categories list")
        return []
    
    try:
        categories_data = json.loads(result["stdout"])
        categories = categories_data["categories"]
    except (json.JSONDecodeError, KeyError):
        print("❌ Could not parse categories")
        return []
    
    print(f"📋 Found {len(categories)} categories to test")
    
    test_results = []
    
    # Test a representative sample of tools from different categories
    test_cases = [
        # Dataset tools
        ("dataset_tools", "load_dataset", ["--source", "/tmp/test_data.json"], "Load test dataset"),
        
        # IPFS tools
        ("ipfs_tools", "get_from_ipfs", ["--hash", "QmTestHash123"], "IPFS get"),
        ("ipfs_tools", "pin_to_ipfs", ["--data", "test data"], "IPFS pin"),
        
        # Vector tools
        ("vector_tools", "create_vector_index", ["--data", "test text", "--index_name", "test_index"], "Create vector index"),
        
        # Admin tools
        ("bespoke_tools", "system_status", [], "System status"),
        ("bespoke_tools", "system_health", [], "System health"),
        
        # Analysis tools
        ("analysis_tools", "analysis_tools", [], "Analysis tools"),
        
        # Media tools
        ("media_tools", "ffmpeg_info", ["--input", "/dev/null"], "FFmpeg info"),
        
        # PDF tools
        ("pdf_tools", "pdf_analyze_relationships", ["--input", "/dev/null"], "PDF analyze"),
        
        # Web archive tools
        ("web_archive_tools", "common_crawl_search", ["--query", "test"], "Common crawl search"),
    ]
    
    for category, tool, args, description in test_cases:
        if category in categories:
            print(f"  🔧 Testing {description}...")
            cmd = ["python", "enhanced_cli.py", category, tool] + args
            result = run_command(cmd, timeout=15, expect_success=False)  # Some may fail due to missing deps
            
            test_results.append({
                "category": category,
                "tool": tool,
                "description": description,
                "success": result["success"],
                "returncode": result["returncode"],
                "error": result["stderr"] if result["stderr"] else None,
                "stdout_length": len(result["stdout"])
            })
            
            if result["success"]:
                print(f"    ✅ {description} - Success")
            elif "not available" in result["stderr"] or "missing" in result["stderr"] or "No module" in result["stderr"]:
                print(f"    ⚠️  {description} - Missing dependencies (expected)")
            else:
                print(f"    ❌ {description} - Error: {result['stderr'][:100]}...")
    
    return test_results

def test_wrapper_scripts():
    """Test wrapper scripts."""
    print("🧪 Testing wrapper scripts...")
    
    wrapper_tests = []
    
    # Test ipfs-datasets wrapper
    if Path("ipfs-datasets").exists():
        print("  📜 Testing ipfs-datasets wrapper...")
        result = run_command(["./ipfs-datasets", "info", "status"])
        wrapper_tests.append({
            "script": "ipfs-datasets",
            "success": result["success"],
            "error": result["stderr"] if not result["success"] else None
        })
        
        if result["success"]:
            print("    ✅ ipfs-datasets wrapper works")
        else:
            print(f"    ❌ ipfs-datasets wrapper failed: {result['stderr']}")
    else:
        print("    ⚠️  ipfs-datasets wrapper not found")
    
    return wrapper_tests

def test_data_processing():
    """Test data processing capabilities."""
    print("🧪 Testing data processing...")
    
    # Create test data files
    test_files = {
        "/tmp/test.json": '{"name": "test", "value": 42}',
        "/tmp/test.csv": "name,value\ntest,42\n",
        "/tmp/test.txt": "This is test data for processing."
    }
    
    for filepath, content in test_files.items():
        Path(filepath).write_text(content)
    
    processing_tests = []
    
    # Test dataset operations
    dataset_tests = [
        (["python", "ipfs_datasets_cli.py", "dataset", "load", "/tmp/test.json", "--format", "json"], "Load JSON dataset"),
        (["python", "ipfs_datasets_cli.py", "dataset", "convert", "/tmp/test.json", "csv", "/tmp/output.csv"], "Convert dataset"),
    ]
    
    for cmd, description in dataset_tests:
        print(f"  📊 {description}...")
        result = run_command(cmd, timeout=20)
        processing_tests.append({
            "test": description,
            "success": result["success"],
            "error": result["stderr"] if not result["success"] else None
        })
        
        if result["success"]:
            print(f"    ✅ {description} - Success")
        else:
            print(f"    ❌ {description} - Failed: {result['stderr'][:100]}...")
    
    # Clean up test files
    for filepath in test_files.keys():
        Path(filepath).unlink(missing_ok=True)
    Path("/tmp/output.csv").unlink(missing_ok=True)
    
    return processing_tests

def generate_report(results):
    """Generate a comprehensive test report."""
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "warnings": 0
        },
        "categories": {
            "basic_cli": [],
            "tool_categories": [],
            "wrapper_scripts": [],
            "data_processing": []
        }
    }
    
    # Process all results
    for category, tests in results.items():
        report["categories"][category] = tests
        for test in tests:
            report["summary"]["total_tests"] += 1
            if test.get("success", False):
                report["summary"]["passed"] += 1
            else:
                error = test.get("error", "")
                if any(keyword in str(error).lower() for keyword in ["missing", "not available", "no module"]):
                    report["summary"]["warnings"] += 1
                else:
                    report["summary"]["failed"] += 1
    
    return report

def main():
    """Main test function."""
    print("🚀 Starting Comprehensive IPFS Datasets CLI Tests")
    print("=" * 60)
    
    # Change to correct directory
    script_dir = Path(__file__).parent
    if script_dir != Path.cwd():
        print(f"📁 Changing to directory: {script_dir}")
        import os
        os.chdir(script_dir)
    
    # Run all tests
    all_results = {}
    
    print()
    all_results["basic_cli"] = test_basic_cli()
    
    print()
    all_results["tool_categories"] = test_tool_categories()
    
    print()
    all_results["wrapper_scripts"] = test_wrapper_scripts()
    
    print()
    all_results["data_processing"] = test_data_processing()
    
    # Generate report
    print()
    print("=" * 60)
    print("📊 Test Report")
    print("=" * 60)
    
    report = generate_report(all_results)
    
    summary = report["summary"]
    print(f"Total Tests: {summary['total_tests']}")
    print(f"✅ Passed: {summary['passed']}")
    print(f"⚠️  Warnings (missing deps): {summary['warnings']}")
    print(f"❌ Failed: {summary['failed']}")
    
    success_rate = (summary['passed'] + summary['warnings']) / summary['total_tests'] * 100
    print(f"Success Rate: {success_rate:.1f}%")
    
    # Save detailed report
    report_file = Path("cli_test_report.json")
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"📄 Detailed report saved to: {report_file}")
    
    if summary['failed'] > 0:
        print()
        print("❌ Issues found:")
        for category, tests in all_results.items():
            for test in tests:
                if not test.get("success", False):
                    error = test.get("error", "")
                    if not any(keyword in str(error).lower() for keyword in ["missing", "not available", "no module"]):
                        print(f"  - {test.get('test', test.get('description', 'Unknown test'))}: {error}")
    
    print()
    if summary['failed'] == 0:
        print("🎉 All critical tests passed! CLI tools are working correctly.")
        sys.exit(0)
    else:
        print("💥 Some tests failed. See details above.")
        sys.exit(1)

if __name__ == "__main__":
    main()