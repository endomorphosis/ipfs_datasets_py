#!/usr/bin/env python3
"""
Comprehensive test suite for the auto-healing system - Refactored

Updated to use utils.workflows modules instead of local script imports.

This validates all components:
- Failure analysis (WorkflowAnalyzer from utils)
- Fix generation (WorkflowFixer from utils)
- End-to-end workflows

Usage:
    python test_autohealing_system_refactored.py
"""

import json
import os
import sys
import tempfile
import yaml
from pathlib import Path
from typing import Dict, Any, List

# Add repository root to path for imports
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import from utils modules - single source of truth
from ipfs_datasets_py.utils.workflows import WorkflowAnalyzer, WorkflowFixer


class AutoHealingSystemTester:
    """Test suite for auto-healing system using utils modules."""
    
    def __init__(self):
        self.test_results = []
        self.temp_dir = None
        
    def run_all_tests(self) -> bool:
        """Run all tests and return overall success."""
        print("🧪 Starting Auto-Healing System Tests")
        print("   (Using ipfs_datasets_py.utils.workflows modules)\n")
        print("=" * 60)
        
        tests = [
            self.test_analyzer_initialization,
            self.test_pattern_detection_dependency,
            self.test_pattern_detection_timeout,
            self.test_pattern_detection_permission,
            self.test_pattern_detection_rate_limit,
            self.test_fixer_initialization,
            self.test_fix_proposal_generation,
            self.test_branch_name_generation,
            self.test_pr_content_generation,
            self.test_end_to_end_dependency_fix,
            self.test_end_to_end_timeout_fix,
        ]
        
        for test in tests:
            try:
                result = test()
                self.test_results.append(result)
            except Exception as e:
                self.test_results.append({
                    'name': test.__name__,
                    'passed': False,
                    'error': str(e),
                })
        
        self._print_summary()
        return all(r['passed'] for r in self.test_results)
    
    def test_analyzer_initialization(self) -> Dict[str, Any]:
        """Test that WorkflowAnalyzer can be initialized."""
        print("\n🔍 Test: WorkflowAnalyzer Initialization")
        
        try:
            analyzer = WorkflowAnalyzer()
            
            assert hasattr(analyzer, 'analyze_failure')
            assert hasattr(analyzer, 'generate_report')
            assert hasattr(analyzer, '_generate_suggestions')
            assert hasattr(analyzer, '_determine_severity')
            
            print("   ✅ PASSED: WorkflowAnalyzer initialized correctly")
            return {'name': 'analyzer_initialization', 'passed': True}
            
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'analyzer_initialization', 'passed': False, 'error': str(e)}
    
    def test_pattern_detection_dependency(self) -> Dict[str, Any]:
        """Test dependency error pattern detection."""
        print("\n🔍 Test: Dependency Error Pattern Detection")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                # Create test workflow file
                workflow_file = Path(tmp_dir) / "test.yml"
                workflow_file.write_text("name: Test\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo test\n")
                
                # Create test error log
                error_log = "ModuleNotFoundError: No module named 'numpy'"
                
                # Analyze
                analyzer = WorkflowAnalyzer()
                result = analyzer.analyze_failure(workflow_file, error_log)
                
                assert result is not None
                assert 'root_cause' in result
                assert 'suggestions' in result
                
                # Should detect dependency issue
                root_cause_lower = result['root_cause'].lower()
                assert 'dependency' in root_cause_lower or 'module' in root_cause_lower
                
                print("   ✅ PASSED: Dependency pattern detected")
                return {'name': 'pattern_detection_dependency', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'pattern_detection_dependency', 'passed': False, 'error': str(e)}
    
    def test_pattern_detection_timeout(self) -> Dict[str, Any]:
        """Test timeout error pattern detection."""
        print("\n🔍 Test: Timeout Error Pattern Detection")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                workflow_file = Path(tmp_dir) / "test.yml"
                workflow_file.write_text("name: Test\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo test\n")
                
                error_log = "Error: The operation was canceled after timeout of 30 minutes"
                
                analyzer = WorkflowAnalyzer()
                result = analyzer.analyze_failure(workflow_file, error_log)
                
                assert result is not None
                root_cause_lower = result['root_cause'].lower()
                assert 'timeout' in root_cause_lower
                
                print("   ✅ PASSED: Timeout pattern detected")
                return {'name': 'pattern_detection_timeout', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'pattern_detection_timeout', 'passed': False, 'error': str(e)}
    
    def test_pattern_detection_permission(self) -> Dict[str, Any]:
        """Test permission error pattern detection."""
        print("\n🔍 Test: Permission Error Pattern Detection")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                workflow_file = Path(tmp_dir) / "test.yml"
                workflow_file.write_text("name: Test\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo test\n")
                
                error_log = "Error: Permission denied (publickey)"
                
                analyzer = WorkflowAnalyzer()
                result = analyzer.analyze_failure(workflow_file, error_log)
                
                assert result is not None
                root_cause_lower = result['root_cause'].lower()
                assert 'permission' in root_cause_lower or 'access' in root_cause_lower
                
                print("   ✅ PASSED: Permission pattern detected")
                return {'name': 'pattern_detection_permission', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'pattern_detection_permission', 'passed': False, 'error': str(e)}
    
    def test_pattern_detection_rate_limit(self) -> Dict[str, Any]:
        """Test rate limit error pattern detection."""
        print("\n🔍 Test: Rate Limit Error Pattern Detection")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                workflow_file = Path(tmp_dir) / "test.yml"
                workflow_file.write_text("name: Test\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo test\n")
                
                error_log = "Error: API rate limit exceeded"
                
                analyzer = WorkflowAnalyzer()
                result = analyzer.analyze_failure(workflow_file, error_log)
                
                assert result is not None
                root_cause_lower = result['root_cause'].lower()
                assert 'rate limit' in root_cause_lower
                
                print("   ✅ PASSED: Rate limit pattern detected")
                return {'name': 'pattern_detection_rate_limit', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'pattern_detection_rate_limit', 'passed': False, 'error': str(e)}
    
    def test_fixer_initialization(self) -> Dict[str, Any]:
        """Test that WorkflowFixer can be initialized."""
        print("\n🔍 Test: WorkflowFixer Initialization")
        
        try:
            # Create a sample analysis
            analysis = {
                'root_cause': 'Missing dependency: numpy',
                'severity': 'high',
                'suggestions': ['Install numpy package'],
                'error_type': 'dependency'
            }
            
            fixer = WorkflowFixer(analysis, workflow_name='Test Workflow')
            
            assert hasattr(fixer, 'generate_fix_proposal')
            assert hasattr(fixer, 'analysis')
            assert fixer.workflow_name == 'Test Workflow'
            
            print("   ✅ PASSED: WorkflowFixer initialized correctly")
            return {'name': 'fixer_initialization', 'passed': True}
            
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'fixer_initialization', 'passed': False, 'error': str(e)}
    
    def test_fix_proposal_generation(self) -> Dict[str, Any]:
        """Test fix proposal generation."""
        print("\n🔍 Test: Fix Proposal Generation")
        
        try:
            analysis = {
                'root_cause': 'Missing dependency: requests',
                'severity': 'high',
                'suggestions': ['Install requests package'],
                'error_type': 'dependency'
            }
            
            fixer = WorkflowFixer(analysis, workflow_name='CI Tests')
            proposal = fixer.generate_fix_proposal()
            
            assert proposal is not None
            assert 'branch_name' in proposal
            assert 'pr_title' in proposal
            assert 'pr_description' in proposal
            assert 'fixes' in proposal
            
            print("   ✅ PASSED: Fix proposal generated")
            return {'name': 'fix_proposal_generation', 'passed': True}
            
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'fix_proposal_generation', 'passed': False, 'error': str(e)}
    
    def test_branch_name_generation(self) -> Dict[str, Any]:
        """Test branch name generation."""
        print("\n🔍 Test: Branch Name Generation")
        
        try:
            analysis = {
                'root_cause': 'Timeout',
                'severity': 'medium',
                'suggestions': ['Increase timeout'],
                'error_type': 'timeout'
            }
            
            fixer = WorkflowFixer(analysis, workflow_name='Build')
            proposal = fixer.generate_fix_proposal()
            
            branch_name = proposal['branch_name']
            assert 'autofix' in branch_name
            assert 'timeout' in branch_name or 'build' in branch_name.lower()
            
            print(f"   ✅ PASSED: Branch name: {branch_name}")
            return {'name': 'branch_name_generation', 'passed': True}
            
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'branch_name_generation', 'passed': False, 'error': str(e)}
    
    def test_pr_content_generation(self) -> Dict[str, Any]:
        """Test PR title and description generation."""
        print("\n🔍 Test: PR Content Generation")
        
        try:
            analysis = {
                'root_cause': 'Permission denied',
                'severity': 'high',
                'suggestions': ['Add required permissions'],
                'error_type': 'permissions'
            }
            
            fixer = WorkflowFixer(analysis, workflow_name='Deploy')
            proposal = fixer.generate_fix_proposal()
            
            assert len(proposal['pr_title']) > 0
            assert len(proposal['pr_description']) > 0
            assert 'permission' in proposal['pr_description'].lower()
            
            print("   ✅ PASSED: PR content generated")
            return {'name': 'pr_content_generation', 'passed': True}
            
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'pr_content_generation', 'passed': False, 'error': str(e)}
    
    def test_end_to_end_dependency_fix(self) -> Dict[str, Any]:
        """Test end-to-end workflow for dependency fix."""
        print("\n🔍 Test: End-to-End Dependency Fix")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                # Create workflow
                workflow_file = Path(tmp_dir) / "ci.yml"
                workflow_file.write_text("name: CI\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n")
                
                # Simulate error
                error_log = "ModuleNotFoundError: No module named 'pytest'"
                
                # Step 1: Analyze
                analyzer = WorkflowAnalyzer()
                analysis = analyzer.analyze_failure(workflow_file, error_log)
                
                # Step 2: Generate fix
                fixer = WorkflowFixer(analysis, workflow_name='CI')
                proposal = fixer.generate_fix_proposal()
                
                # Validate pipeline
                assert analysis is not None
                assert proposal is not None
                assert 'pytest' in error_log
                assert len(proposal['fixes']) > 0
                
                print("   ✅ PASSED: End-to-end dependency fix workflow")
                return {'name': 'end_to_end_dependency', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'end_to_end_dependency', 'passed': False, 'error': str(e)}
    
    def test_end_to_end_timeout_fix(self) -> Dict[str, Any]:
        """Test end-to-end workflow for timeout fix."""
        print("\n🔍 Test: End-to-End Timeout Fix")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                workflow_file = Path(tmp_dir) / "build.yml"
                workflow_file.write_text("name: Build\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: npm run build\n")
                
                error_log = "Error: The operation was canceled after 30 minutes"
                
                # Analyze and fix
                analyzer = WorkflowAnalyzer()
                analysis = analyzer.analyze_failure(workflow_file, error_log)
                
                fixer = WorkflowFixer(analysis, workflow_name='Build')
                proposal = fixer.generate_fix_proposal()
                
                assert analysis is not None
                assert proposal is not None
                assert 'timeout' in analysis['root_cause'].lower()
                
                print("   ✅ PASSED: End-to-end timeout fix workflow")
                return {'name': 'end_to_end_timeout', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'end_to_end_timeout', 'passed': False, 'error': str(e)}
    
    def _print_summary(self):
        """Print test results summary."""
        print("\n" + "=" * 60)
        print("📊 Test Results Summary")
        print("=" * 60)
        
        passed = sum(1 for r in self.test_results if r['passed'])
        total = len(self.test_results)
        
        print(f"\nTotal tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {total - passed}")
        print(f"Success rate: {100 * passed / total:.1f}%\n")
        
        # Show failed tests
        failed_tests = [r for r in self.test_results if not r['passed']]
        if failed_tests:
            print("❌ Failed tests:")
            for test in failed_tests:
                print(f"   • {test['name']}")
                if 'error' in test:
                    print(f"     Error: {test['error']}")
        else:
            print("✅ All tests passed!")


def main():
    """Main entry point."""
    tester = AutoHealingSystemTester()
    success = tester.run_all_tests()
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
