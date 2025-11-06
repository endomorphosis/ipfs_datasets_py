#!/usr/bin/env python3
"""
Comprehensive test suite for the auto-healing system.

This script validates all components of the auto-healing system:
- Failure analysis
- Fix generation
- Fix application
- Workflow configuration
"""

import json
import os
import sys
import tempfile
import yaml
from pathlib import Path
from typing import Dict, Any, List

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_workflow_failure import WorkflowFailureAnalyzer
from generate_workflow_fix import WorkflowFixGenerator


class AutoHealingSystemTester:
    """Test suite for auto-healing system."""
    
    def __init__(self):
        self.test_results = []
        self.temp_dir = None
        
    def run_all_tests(self) -> bool:
        """Run all tests and return overall success."""
        print("🧪 Starting Auto-Healing System Tests\n")
        print("=" * 60)
        
        tests = [
            self.test_analyzer_initialization,
            self.test_pattern_detection_dependency,
            self.test_pattern_detection_timeout,
            self.test_pattern_detection_permission,
            self.test_pattern_detection_network,
            self.test_pattern_detection_docker,
            self.test_fix_generator_initialization,
            self.test_fix_proposal_generation,
            self.test_branch_name_generation,
            self.test_pr_title_generation,
            self.test_workflow_yaml_validation,
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
        """Test that the analyzer can be initialized."""
        print("\n🔍 Test: Analyzer Initialization")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                analyzer = WorkflowFailureAnalyzer(
                    run_id="12345",
                    workflow_name="Test Workflow",
                    logs_dir=Path(tmp_dir)
                )
                
                assert analyzer.run_id == "12345"
                assert analyzer.workflow_name == "Test Workflow"
                assert analyzer.logs_dir == Path(tmp_dir)
                
                print("   ✅ PASSED: Analyzer initialized correctly")
                return {'name': 'analyzer_initialization', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'analyzer_initialization', 'passed': False, 'error': str(e)}
    
    def test_pattern_detection_dependency(self) -> Dict[str, Any]:
        """Test dependency error pattern detection."""
        print("\n🔍 Test: Dependency Error Pattern Detection")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                # Create test log with dependency error
                log_file = Path(tmp_dir) / "test.log"
                log_file.write_text("""
                Running tests...
                ERROR: ModuleNotFoundError: No module named 'pytest-asyncio'
                Test failed
                """)
                
                analyzer = WorkflowFailureAnalyzer(
                    run_id="12345",
                    workflow_name="Test Workflow",
                    logs_dir=Path(tmp_dir)
                )
                
                analysis = analyzer.analyze()
                
                assert analysis['error_type'] == 'Missing Dependency'
                assert analysis['fix_type'] == 'add_dependency'
                assert 'pytest-asyncio' in str(analysis.get('captured_values', []))
                assert analysis['fix_confidence'] >= 80
                
                print("   ✅ PASSED: Dependency error detected correctly")
                print(f"      - Error Type: {analysis['error_type']}")
                print(f"      - Confidence: {analysis['fix_confidence']}%")
                print(f"      - Captured: {analysis.get('captured_values', [])}")
                return {'name': 'pattern_detection_dependency', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'pattern_detection_dependency', 'passed': False, 'error': str(e)}
    
    def test_pattern_detection_timeout(self) -> Dict[str, Any]:
        """Test timeout error pattern detection."""
        print("\n🔍 Test: Timeout Error Pattern Detection")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                # Create test log with timeout error
                log_file = Path(tmp_dir) / "test.log"
                log_file.write_text("""
                Running long task...
                ERROR: timeout - operation took too long
                Job cancelled
                """)
                
                analyzer = WorkflowFailureAnalyzer(
                    run_id="12345",
                    workflow_name="Test Workflow",
                    logs_dir=Path(tmp_dir)
                )
                
                analysis = analyzer.analyze()
                
                assert analysis['error_type'] == 'Timeout'
                assert analysis['fix_type'] == 'increase_timeout'
                assert analysis['fix_confidence'] >= 90
                
                print("   ✅ PASSED: Timeout error detected correctly")
                print(f"      - Error Type: {analysis['error_type']}")
                print(f"      - Confidence: {analysis['fix_confidence']}%")
                return {'name': 'pattern_detection_timeout', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'pattern_detection_timeout', 'passed': False, 'error': str(e)}
    
    def test_pattern_detection_permission(self) -> Dict[str, Any]:
        """Test permission error pattern detection."""
        print("\n🔍 Test: Permission Error Pattern Detection")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                log_file = Path(tmp_dir) / "test.log"
                log_file.write_text("""
                Attempting operation...
                ERROR: 403 Forbidden - Permission denied
                Failed to complete
                """)
                
                analyzer = WorkflowFailureAnalyzer(
                    run_id="12345",
                    workflow_name="Test Workflow",
                    logs_dir=Path(tmp_dir)
                )
                
                analysis = analyzer.analyze()
                
                assert analysis['error_type'] == 'Permission Error'
                assert analysis['fix_type'] == 'fix_permissions'
                assert analysis['fix_confidence'] >= 70
                
                print("   ✅ PASSED: Permission error detected correctly")
                print(f"      - Error Type: {analysis['error_type']}")
                print(f"      - Confidence: {analysis['fix_confidence']}%")
                return {'name': 'pattern_detection_permission', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'pattern_detection_permission', 'passed': False, 'error': str(e)}
    
    def test_pattern_detection_network(self) -> Dict[str, Any]:
        """Test network error pattern detection."""
        print("\n🔍 Test: Network Error Pattern Detection")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                log_file = Path(tmp_dir) / "test.log"
                log_file.write_text("""
                Downloading package...
                ERROR: ConnectionError - Failed to fetch from server
                Retrying...
                """)
                
                analyzer = WorkflowFailureAnalyzer(
                    run_id="12345",
                    workflow_name="Test Workflow",
                    logs_dir=Path(tmp_dir)
                )
                
                analysis = analyzer.analyze()
                
                assert analysis['error_type'] == 'Network Error'
                assert analysis['fix_type'] == 'add_retry'
                
                print("   ✅ PASSED: Network error detected correctly")
                print(f"      - Error Type: {analysis['error_type']}")
                print(f"      - Confidence: {analysis['fix_confidence']}%")
                return {'name': 'pattern_detection_network', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'pattern_detection_network', 'passed': False, 'error': str(e)}
    
    def test_pattern_detection_docker(self) -> Dict[str, Any]:
        """Test Docker error pattern detection."""
        print("\n🔍 Test: Docker Error Pattern Detection")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                log_file = Path(tmp_dir) / "test.log"
                log_file.write_text("""
                Building Docker image...
                ERROR: Cannot connect to the Docker daemon at unix:///var/run/docker.sock
                Docker build failed
                """)
                
                analyzer = WorkflowFailureAnalyzer(
                    run_id="12345",
                    workflow_name="Test Workflow",
                    logs_dir=Path(tmp_dir)
                )
                
                analysis = analyzer.analyze()
                
                assert analysis['error_type'] == 'Docker Error'
                assert analysis['fix_type'] == 'fix_docker'
                
                print("   ✅ PASSED: Docker error detected correctly")
                print(f"      - Error Type: {analysis['error_type']}")
                print(f"      - Confidence: {analysis['fix_confidence']}%")
                return {'name': 'pattern_detection_docker', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'pattern_detection_docker', 'passed': False, 'error': str(e)}
    
    def test_fix_generator_initialization(self) -> Dict[str, Any]:
        """Test fix generator initialization."""
        print("\n🔍 Test: Fix Generator Initialization")
        
        try:
            analysis = {
                'run_id': '12345',
                'workflow_name': 'Test Workflow',
                'error_type': 'Missing Dependency',
                'fix_type': 'add_dependency',
                'root_cause': 'ModuleNotFoundError: pytest-asyncio',
                'fix_confidence': 90,
                'captured_values': ['pytest-asyncio'],
                'recommendations': ['Add pytest-asyncio to requirements.txt'],
            }
            
            generator = WorkflowFixGenerator(
                analysis=analysis,
                workflow_name='Test Workflow'
            )
            
            assert generator.analysis == analysis
            assert generator.workflow_name == 'Test Workflow'
            
            print("   ✅ PASSED: Fix generator initialized correctly")
            return {'name': 'fix_generator_initialization', 'passed': True}
            
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'fix_generator_initialization', 'passed': False, 'error': str(e)}
    
    def test_fix_proposal_generation(self) -> Dict[str, Any]:
        """Test fix proposal generation."""
        print("\n🔍 Test: Fix Proposal Generation")
        
        try:
            analysis = {
                'run_id': '12345',
                'workflow_name': 'Test Workflow',
                'error_type': 'Missing Dependency',
                'fix_type': 'add_dependency',
                'root_cause': 'ModuleNotFoundError: pytest-asyncio',
                'fix_confidence': 90,
                'captured_values': ['pytest-asyncio'],
                'recommendations': ['Add pytest-asyncio to requirements.txt'],
            }
            
            generator = WorkflowFixGenerator(
                analysis=analysis,
                workflow_name='Test Workflow'
            )
            
            proposal = generator.generate()
            
            assert 'branch_name' in proposal
            assert 'pr_title' in proposal
            assert 'pr_description' in proposal
            assert 'fixes' in proposal
            assert 'labels' in proposal
            assert proposal['fix_type'] == 'add_dependency'
            assert proposal['error_type'] == 'Missing Dependency'
            
            print("   ✅ PASSED: Fix proposal generated correctly")
            print(f"      - Branch: {proposal['branch_name']}")
            print(f"      - Title: {proposal['pr_title']}")
            print(f"      - Fixes: {len(proposal['fixes'])} fix(es)")
            return {'name': 'fix_proposal_generation', 'passed': True}
            
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'fix_proposal_generation', 'passed': False, 'error': str(e)}
    
    def test_branch_name_generation(self) -> Dict[str, Any]:
        """Test branch name generation."""
        print("\n🔍 Test: Branch Name Generation")
        
        try:
            analysis = {
                'run_id': '12345',
                'workflow_name': 'Test Workflow',
                'error_type': 'Timeout',
                'fix_type': 'increase_timeout',
                'root_cause': 'Job timed out',
                'fix_confidence': 95,
            }
            
            generator = WorkflowFixGenerator(
                analysis=analysis,
                workflow_name='Test Workflow'
            )
            
            proposal = generator.generate()
            branch_name = proposal['branch_name']
            
            assert branch_name.startswith('autofix/')
            assert 'test-workflow' in branch_name
            assert 'increase-timeout' in branch_name or 'timeout' in branch_name
            
            print("   ✅ PASSED: Branch name generated correctly")
            print(f"      - Branch: {branch_name}")
            return {'name': 'branch_name_generation', 'passed': True}
            
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'branch_name_generation', 'passed': False, 'error': str(e)}
    
    def test_pr_title_generation(self) -> Dict[str, Any]:
        """Test PR title generation."""
        print("\n🔍 Test: PR Title Generation")
        
        try:
            analysis = {
                'run_id': '12345',
                'workflow_name': 'Docker Build',
                'error_type': 'Docker Error',
                'fix_type': 'fix_docker',
                'root_cause': 'Docker daemon not accessible',
                'fix_confidence': 85,
            }
            
            generator = WorkflowFixGenerator(
                analysis=analysis,
                workflow_name='Docker Build'
            )
            
            proposal = generator.generate()
            pr_title = proposal['pr_title']
            
            assert 'Docker Error' in pr_title
            assert 'Docker Build' in pr_title
            assert pr_title.startswith('fix:')
            
            print("   ✅ PASSED: PR title generated correctly")
            print(f"      - Title: {pr_title}")
            return {'name': 'pr_title_generation', 'passed': True}
            
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'pr_title_generation', 'passed': False, 'error': str(e)}
    
    def test_workflow_yaml_validation(self) -> Dict[str, Any]:
        """Test workflow YAML validation."""
        print("\n🔍 Test: Workflow YAML Validation")
        
        try:
            # Try multiple possible locations
            possible_paths = [
                Path(__file__).parent.parent / 'workflows' / 'copilot-agent-autofix.yml',
                Path(__file__).parent.parent.parent / '.github' / 'workflows' / 'copilot-agent-autofix.yml',
            ]
            
            workflow_file = None
            for path in possible_paths:
                if path.exists():
                    workflow_file = path
                    break
            
            if not workflow_file:
                print(f"   ⚠️  SKIPPED: Workflow file not found")
                print(f"      Checked: {[str(p) for p in possible_paths]}")
                return {'name': 'workflow_yaml_validation', 'passed': True, 'skipped': True}
            
            with open(workflow_file, 'r') as f:
                workflow = yaml.safe_load(f)
            
            # Validate key sections
            assert 'name' in workflow, "Missing 'name' field"
            # Note: 'on' is parsed as boolean True by YAML parser
            assert True in workflow or 'on' in workflow, "Missing 'on' field"
            assert 'permissions' in workflow, "Missing 'permissions' field"
            assert 'jobs' in workflow, "Missing 'jobs' field"
            
            # Get the trigger configuration (could be under True or 'on')
            trigger_config = workflow.get(True) or workflow.get('on', {})
            
            # Validate trigger
            assert 'workflow_run' in trigger_config, "Missing 'workflow_run' trigger"
            assert 'workflow_dispatch' in trigger_config, "Missing 'workflow_dispatch' trigger"
            
            # Validate permissions
            permissions = workflow['permissions']
            assert permissions.get('contents') == 'write', "Incorrect 'contents' permission"
            assert permissions.get('pull-requests') == 'write', "Incorrect 'pull-requests' permission"
            assert permissions.get('issues') == 'write', "Incorrect 'issues' permission"
            assert permissions.get('actions') == 'read', "Incorrect 'actions' permission"
            
            print("   ✅ PASSED: Workflow YAML is valid")
            print(f"      - Name: {workflow['name']}")
            print(f"      - Triggers: {list(trigger_config.keys())}")
            print(f"      - File: {workflow_file}")
            return {'name': 'workflow_yaml_validation', 'passed': True}
            
        except AssertionError as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'workflow_yaml_validation', 'passed': False, 'error': str(e)}
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'workflow_yaml_validation', 'passed': False, 'error': str(e)}
    
    def test_end_to_end_dependency_fix(self) -> Dict[str, Any]:
        """Test end-to-end dependency fix flow."""
        print("\n🔍 Test: End-to-End Dependency Fix")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                # Create test log
                log_file = Path(tmp_dir) / "test.log"
                log_file.write_text("""
                Installing dependencies...
                ERROR: ModuleNotFoundError: No module named 'requests'
                Build failed
                """)
                
                # Step 1: Analyze
                analyzer = WorkflowFailureAnalyzer(
                    run_id="12345",
                    workflow_name="CI Build",
                    logs_dir=Path(tmp_dir)
                )
                analysis = analyzer.analyze()
                
                # Validate analysis
                assert analysis['error_type'] == 'Missing Dependency'
                assert 'requests' in str(analysis.get('captured_values', []))
                
                # Step 2: Generate fix
                generator = WorkflowFixGenerator(
                    analysis=analysis,
                    workflow_name='CI Build'
                )
                proposal = generator.generate()
                
                # Validate proposal
                assert proposal['fix_type'] == 'add_dependency'
                assert 'requests' in str(proposal)
                assert 'branch_name' in proposal
                assert 'pr_title' in proposal
                
                print("   ✅ PASSED: End-to-end dependency fix completed")
                print(f"      - Detected: {analysis['error_type']}")
                print(f"      - Package: requests")
                print(f"      - Branch: {proposal['branch_name']}")
                return {'name': 'e2e_dependency_fix', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'e2e_dependency_fix', 'passed': False, 'error': str(e)}
    
    def test_end_to_end_timeout_fix(self) -> Dict[str, Any]:
        """Test end-to-end timeout fix flow."""
        print("\n🔍 Test: End-to-End Timeout Fix")
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                # Create test log
                log_file = Path(tmp_dir) / "test.log"
                log_file.write_text("""
                Running tests...
                Tests running...
                ERROR: timeout - Job exceeded time limit
                Job cancelled
                """)
                
                # Step 1: Analyze
                analyzer = WorkflowFailureAnalyzer(
                    run_id="67890",
                    workflow_name="Test Suite",
                    logs_dir=Path(tmp_dir)
                )
                analysis = analyzer.analyze()
                
                # Validate analysis
                assert analysis['error_type'] == 'Timeout'
                assert analysis['fix_confidence'] >= 90
                
                # Step 2: Generate fix
                generator = WorkflowFixGenerator(
                    analysis=analysis,
                    workflow_name='Test Suite'
                )
                proposal = generator.generate()
                
                # Validate proposal
                assert proposal['fix_type'] == 'increase_timeout'
                assert 'timeout' in proposal['pr_title'].lower()
                
                print("   ✅ PASSED: End-to-end timeout fix completed")
                print(f"      - Detected: {analysis['error_type']}")
                print(f"      - Confidence: {analysis['fix_confidence']}%")
                print(f"      - Title: {proposal['pr_title']}")
                return {'name': 'e2e_timeout_fix', 'passed': True}
                
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return {'name': 'e2e_timeout_fix', 'passed': False, 'error': str(e)}
    
    def _print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for r in self.test_results if r['passed'])
        failed = sum(1 for r in self.test_results if not r['passed'])
        total = len(self.test_results)
        
        print(f"\nTotal Tests: {total}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"Success Rate: {(passed/total*100):.1f}%")
        
        if failed > 0:
            print("\n❌ Failed Tests:")
            for result in self.test_results:
                if not result['passed']:
                    print(f"   - {result['name']}")
                    if 'error' in result:
                        print(f"     Error: {result['error']}")
        
        print("\n" + "=" * 60)


def main():
    """Run all tests."""
    tester = AutoHealingSystemTester()
    success = tester.run_all_tests()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
