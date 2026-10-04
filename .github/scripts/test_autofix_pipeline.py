#!/usr/bin/env python3
"""
Test the workflow auto-fix pipeline end-to-end.

This script creates a mock workflow failure scenario and tests that:
1. The analyzer can detect and classify errors
2. The generator creates appropriate fix proposals
3. The system handles various error types correctly
"""

import json
import os
import tempfile
from pathlib import Path

# Import the actual modules
import sys
sys.path.insert(0, str(Path(__file__).parent))

from analyze_workflow_failure import WorkflowFailureAnalyzer
from generate_workflow_fix import WorkflowFixGenerator


def test_dependency_error():
    """Test handling of missing dependency errors."""
    print("\n🧪 Testing dependency error handling...")
    
    # Create mock log with dependency error
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir) / "logs"
        log_dir.mkdir()
        
        # Create a mock log file
        log_file = log_dir / "job_123.log"
        log_file.write_text("""
2024-10-30T10:00:00.000Z ##[group]Run pytest tests/
2024-10-30T10:00:01.000Z ERROR: ModuleNotFoundError: No module named 'pytest-asyncio'
2024-10-30T10:00:01.000Z Traceback (most recent call last):
2024-10-30T10:00:01.000Z   File "tests/test_async.py", line 5, in <module>
2024-10-30T10:00:01.000Z     import pytest_asyncio
2024-10-30T10:00:01.000Z ModuleNotFoundError: No module named 'pytest-asyncio'
2024-10-30T10:00:01.000Z ##[error]Process completed with exit code 1.
        """)
        
        # Run analyzer
        analyzer = WorkflowFailureAnalyzer(
            run_id="12345",
            workflow_name="Test Workflow",
            logs_dir=log_dir
        )
        
        analysis = analyzer.analyze()
        
        # Verify analysis
        assert analysis['error_type'] == 'Missing Dependency', f"Expected 'Missing Dependency', got {analysis['error_type']}"
        assert analysis['fix_type'] == 'add_dependency', f"Expected 'add_dependency', got {analysis['fix_type']}"
        assert 'pytest-asyncio' in str(analysis['captured_values']), "Expected 'pytest-asyncio' in captured values"
        assert analysis['fix_confidence'] >= 85, f"Expected confidence >= 85%, got {analysis['fix_confidence']}%"
        
        print(f"✅ Detected error type: {analysis['error_type']}")
        print(f"✅ Fix type: {analysis['fix_type']}")
        print(f"✅ Captured package: {analysis['captured_values']}")
        print(f"✅ Confidence: {analysis['fix_confidence']}%")
        
        # Test fix generation
        generator = WorkflowFixGenerator(
            analysis=analysis,
            workflow_name="Test Workflow"
        )
        
        proposal = generator.generate()
        
        # Verify proposal
        assert len(proposal['fixes']) > 0, "Expected at least one fix"
        assert any('pytest-asyncio' in str(fix) for fix in proposal['fixes']), "Expected pytest-asyncio in fixes"
        assert proposal['fix_type'] == 'add_dependency', f"Expected 'add_dependency', got {proposal['fix_type']}"
        
        print(f"✅ Generated {len(proposal['fixes'])} fix(es)")
        print(f"✅ Branch: {proposal['branch_name']}")
        print(f"✅ PR Title: {proposal['pr_title']}")


def test_timeout_error():
    """Test handling of timeout errors."""
    print("\n🧪 Testing timeout error handling...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir) / "logs"
        log_dir.mkdir()
        
        log_file = log_dir / "job_456.log"
        log_file.write_text("""
2024-10-30T10:00:00.000Z ##[group]Run docker build
2024-10-30T10:05:00.000Z Building image...
2024-10-30T10:10:00.000Z ERROR: Build timed out after 5 minutes
2024-10-30T10:10:00.000Z ##[error]The job running on runner has exceeded the maximum execution time.
        """)
        
        analyzer = WorkflowFailureAnalyzer(
            run_id="67890",
            workflow_name="Docker Build",
            logs_dir=log_dir
        )
        
        analysis = analyzer.analyze()
        
        assert analysis['error_type'] == 'Timeout', f"Expected 'Timeout', got {analysis['error_type']}"
        assert analysis['fix_type'] == 'increase_timeout', f"Expected 'increase_timeout', got {analysis['fix_type']}"
        assert analysis['fix_confidence'] >= 90, f"Expected confidence >= 90%, got {analysis['fix_confidence']}%"
        
        print(f"✅ Detected error type: {analysis['error_type']}")
        print(f"✅ Fix type: {analysis['fix_type']}")
        print(f"✅ Confidence: {analysis['fix_confidence']}%")
        
        generator = WorkflowFixGenerator(
            analysis=analysis,
            workflow_name="Docker Build"
        )
        
        proposal = generator.generate()
        
        assert len(proposal['fixes']) > 0, "Expected at least one fix"
        assert proposal['fix_type'] == 'increase_timeout'
        
        print(f"✅ Generated {len(proposal['fixes'])} fix(es)")


def test_permission_error():
    """Test handling of permission errors."""
    print("\n🧪 Testing permission error handling...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir) / "logs"
        log_dir.mkdir()
        
        log_file = log_dir / "job_789.log"
        log_file.write_text("""
2024-10-30T10:00:00.000Z ##[group]Create Pull Request
2024-10-30T10:00:01.000Z ERROR: Permission denied: Resource not accessible by integration
2024-10-30T10:00:01.000Z HttpError: 403 Forbidden
2024-10-30T10:00:01.000Z ##[error]Process completed with exit code 1.
        """)
        
        analyzer = WorkflowFailureAnalyzer(
            run_id="11111",
            workflow_name="PR Creation",
            logs_dir=log_dir
        )
        
        analysis = analyzer.analyze()
        
        assert analysis['error_type'] == 'Permission Error', f"Expected 'Permission Error', got {analysis['error_type']}"
        assert analysis['fix_type'] == 'fix_permissions', f"Expected 'fix_permissions', got {analysis['fix_type']}"
        
        print(f"✅ Detected error type: {analysis['error_type']}")
        print(f"✅ Fix type: {analysis['fix_type']}")
        print(f"✅ Confidence: {analysis['fix_confidence']}%")


def test_unknown_error():
    """Test handling of unknown errors."""
    print("\n🧪 Testing unknown error handling...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir) / "logs"
        log_dir.mkdir()
        
        log_file = log_dir / "job_999.log"
        log_file.write_text("""
2024-10-30T10:00:00.000Z ##[group]Run custom script
2024-10-30T10:00:01.000Z Something weird happened
2024-10-30T10:00:01.000Z This error pattern is completely unknown
2024-10-30T10:00:01.000Z ##[error]Process completed with exit code 1.
        """)
        
        analyzer = WorkflowFailureAnalyzer(
            run_id="22222",
            workflow_name="Custom Script",
            logs_dir=log_dir
        )
        
        analysis = analyzer.analyze()
        
        # Should still produce analysis even for unknown errors
        assert analysis['error_type'] is not None
        assert analysis['fix_type'] is not None
        
        print(f"✅ Handled unknown error gracefully")
        print(f"✅ Error type: {analysis['error_type']}")
        print(f"✅ Fix type: {analysis['fix_type']}")
        print(f"✅ Confidence: {analysis['fix_confidence']}%")


def main():
    """Run all tests."""
    print("=" * 60)
    print("🧪 Testing Workflow Auto-Fix Pipeline")
    print("=" * 60)
    
    tests = [
        ("Dependency Error", test_dependency_error),
        ("Timeout Error", test_timeout_error),
        ("Permission Error", test_permission_error),
        ("Unknown Error", test_unknown_error),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            test_func()
            passed += 1
            print(f"✅ {name} test passed")
        except AssertionError as e:
            failed += 1
            print(f"❌ {name} test failed: {e}")
        except Exception as e:
            failed += 1
            print(f"❌ {name} test error: {e}")
    
    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed > 0:
        sys.exit(1)
    else:
        print("\n✅ All tests passed!")
        sys.exit(0)


if __name__ == '__main__':
    main()
