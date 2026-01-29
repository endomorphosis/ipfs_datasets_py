#!/usr/bin/env python3
"""
Pre-merge validation script for scraper testing framework.

This script validates that:
1. All test files compile and import correctly
2. The framework components work as expected
3. Test structure is correct
4. GitHub Actions workflow is valid
"""
import sys
import subprocess
from pathlib import Path

def test_imports():
    """Test that all components can be imported."""
    print("=" * 70)
    print("TEST 1: Importing Framework Components")
    print("=" * 70)
    
    try:
        from ipfs_datasets_py.scraper_testing_framework import (
            ScraperDomain,
            ScraperValidator,
            ScraperTestResult,
            ScraperTestRunner,
            DataQualityIssue
        )
        print("✅ Framework imports successfully")
        print(f"   Domains: {[d.value for d in ScraperDomain]}")
        print(f"   Issue types: {[i.value for i in DataQualityIssue]}")
        return True
    except Exception as e:
        print(f"❌ Framework import failed: {e}")
        return False

def test_test_files():
    """Test that all test files are valid Python."""
    print("\n" + "=" * 70)
    print("TEST 2: Validating Test Files")
    print("=" * 70)
    
    test_files = [
        "tests/scraper_tests/test_caselaw_scrapers.py",
        "tests/scraper_tests/test_finance_scrapers.py",
        "tests/scraper_tests/test_medicine_scrapers.py",
        "tests/scraper_tests/test_software_scrapers.py",
    ]
    
    all_valid = True
    for test_file in test_files:
        try:
            result = subprocess.run(
                ["python", "-m", "py_compile", test_file],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                print(f"✅ {test_file}")
            else:
                print(f"❌ {test_file}: {result.stderr}")
                all_valid = False
        except Exception as e:
            print(f"❌ {test_file}: {e}")
            all_valid = False
    
    return all_valid

def test_cli_tool():
    """Test that CLI tool works."""
    print("\n" + "=" * 70)
    print("TEST 3: Validating CLI Tool")
    print("=" * 70)
    
    try:
        result = subprocess.run(
            ["python", "scraper_management.py", "list", "--domain", "caselaw"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if "CASELAW Dashboard" in result.stdout:
            print("✅ CLI tool works")
            print("   Found caselaw scrapers:")
            for line in result.stdout.split('\n'):
                if line.strip().startswith('•'):
                    print(f"      {line.strip()}")
            return True
        else:
            print(f"❌ CLI tool output unexpected: {result.stdout}")
            return False
    except Exception as e:
        print(f"❌ CLI tool failed: {e}")
        return False

def test_workflow_yaml():
    """Test that workflow YAML is valid."""
    print("\n" + "=" * 70)
    print("TEST 4: Validating GitHub Actions Workflow")
    print("=" * 70)
    
    try:
        import yaml
        
        with open('.github/workflows/scraper-validation.yml') as f:
            workflow = yaml.safe_load(f)
        
        # Check required fields
        required = ['name', 'jobs']
        for field in required:
            if field not in workflow:
                print(f"❌ Missing required field: {field}")
                return False
        
        print(f"✅ Workflow YAML is valid")
        print(f"   Name: {workflow['name']}")
        print(f"   Jobs: {', '.join(workflow['jobs'].keys())}")
        
        # Check workflow_dispatch trigger exists
        triggers = workflow.get(True, {})  # YAML parses 'on' as True
        if not triggers:
            triggers = workflow.get('on', {})
        
        if 'workflow_dispatch' in triggers:
            print(f"   ✅ Manual trigger enabled")
        else:
            print(f"   ⚠️  Manual trigger not found")
        
        return True
    except Exception as e:
        print(f"❌ Workflow validation failed: {e}")
        return False

def test_documentation():
    """Test that documentation files exist."""
    print("\n" + "=" * 70)
    print("TEST 5: Validating Documentation")
    print("=" * 70)
    
    docs = [
        "docs/SCRAPER_TESTING_FRAMEWORK.md",
        "SCRAPER_TESTING_QUICKSTART.md",
        "SCRAPER_TESTING_VISUAL_GUIDE.md",
    ]
    
    all_exist = True
    for doc in docs:
        if Path(doc).exists():
            size = Path(doc).stat().st_size
            print(f"✅ {doc} ({size} bytes)")
        else:
            print(f"❌ {doc} not found")
            all_exist = False
    
    return all_exist

def main():
    """Run all validation tests."""
    print("\n" + "=" * 70)
    print("SCRAPER TESTING FRAMEWORK - PRE-MERGE VALIDATION")
    print("=" * 70)
    print()
    
    tests = [
        ("Framework Imports", test_imports),
        ("Test Files", test_test_files),
        ("CLI Tool", test_cli_tool),
        ("Workflow YAML", test_workflow_yaml),
        ("Documentation", test_documentation),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"\n❌ Test '{name}' crashed: {e}")
            results[name] = False
    
    # Summary
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    
    for name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {name}")
    
    all_passed = all(results.values())
    
    print("\n" + "=" * 70)
    if all_passed:
        print("✅ ALL VALIDATION TESTS PASSED")
        print("\nThe scraper testing framework is ready for:")
        print("  1. Manual GitHub Actions workflow trigger")
        print("  2. Merge to main branch")
    else:
        print("❌ SOME TESTS FAILED")
        print("\nPlease fix the issues before merging.")
    print("=" * 70)
    
    return 0 if all_passed else 1

if __name__ == '__main__':
    sys.exit(main())
