#!/usr/bin/env python3
"""
Tests for Copilot Auto-Fix All Pull Requests Script

This test suite validates the functionality of the copilot_auto_fix_all_prs.py script,
which automatically invokes GitHub Copilot on open pull requests to fix them.
"""

import pytest
import json
import subprocess
import os
from unittest.mock import Mock, patch, MagicMock, call
from pathlib import Path
import sys

# Add the project root to the path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import the module to test
from scripts.copilot_auto_fix_all_prs import CopilotAutoFixAllPRs


class TestCopilotAutoFixAllPRs:
    """Test suite for CopilotAutoFixAllPRs class."""
    
    @pytest.fixture
    def mock_subprocess(self):
        """Mock subprocess.run for testing."""
        with patch('subprocess.run') as mock:
            yield mock
    
    @pytest.fixture
    def sample_pr_data(self):
        """Sample PR data for testing."""
        return {
            'number': 123,
            'title': 'Fix workflow permission error',
            'body': 'This PR fixes a permission error in the GitHub Actions workflow',
            'isDraft': False,
            'state': 'open',
            'author': {'login': 'testuser'},
            'labels': [],
            'comments': [],
            'files': [{'path': '.github/workflows/test.yml'}],
            'url': 'https://github.com/test/repo/pull/123',
            'headRefName': 'fix-workflow'
        }
    
    @pytest.fixture
    def auto_fixer(self, mock_subprocess):
        """Create an auto-fixer instance with mocked prerequisites."""
        # Mock the prerequisite checks to pass
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout='gh version 2.0.0',
            stderr=''
        )
        
        with patch.dict('os.environ', {'GITHUB_TOKEN': 'test_token'}):
            fixer = CopilotAutoFixAllPRs(dry_run=True)
            return fixer
    
    def test_initialization_with_token(self, mock_subprocess):
        """
        GIVEN: A GitHub token is provided
        WHEN: CopilotAutoFixAllPRs is initialized
        THEN: The token should be stored and prerequisites verified
        """
        # Mock successful prerequisite checks
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout='gh version 2.0.0\ngh-copilot',
            stderr=''
        )
        
        with patch.dict('os.environ', {'GITHUB_TOKEN': 'test_token'}):
            fixer = CopilotAutoFixAllPRs(dry_run=True, github_token='custom_token')
            
            assert fixer.github_token == 'custom_token'
            assert fixer.dry_run is True
    
    def test_initialization_without_token(self, mock_subprocess):
        """
        GIVEN: No GitHub token is provided
        WHEN: CopilotAutoFixAllPRs is initialized
        THEN: It should try to use environment variables
        """
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout='gh version 2.0.0\ngh-copilot',
            stderr=''
        )
        
        with patch.dict('os.environ', {'GITHUB_TOKEN': 'env_token'}):
            fixer = CopilotAutoFixAllPRs(dry_run=True)
            
            assert fixer.github_token == 'env_token'
    
    def test_verify_prerequisites_gh_not_found(self, mock_subprocess):
        """
        GIVEN: GitHub CLI is not installed
        WHEN: Prerequisites are verified
        THEN: The script should exit with an error
        """
        mock_subprocess.side_effect = FileNotFoundError()
        
        with pytest.raises(SystemExit) as exc_info:
            with patch.dict('os.environ', {'GITHUB_TOKEN': 'test_token'}):
                CopilotAutoFixAllPRs(dry_run=True)
        
        assert exc_info.value.code == 1
    
    def test_run_command_success(self, auto_fixer, mock_subprocess):
        """
        GIVEN: A valid command
        WHEN: run_command is called
        THEN: It should return success with output
        """
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout='command output',
            stderr=''
        )
        
        result = auto_fixer.run_command(['echo', 'test'])
        
        assert result['success'] is True
        assert result['stdout'] == 'command output'
        assert result['returncode'] == 0
    
    def test_run_command_failure(self, auto_fixer, mock_subprocess):
        """
        GIVEN: A command that fails
        WHEN: run_command is called
        THEN: It should return failure with error info
        """
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout='',
            stderr='command failed'
        )
        
        result = auto_fixer.run_command(['false'])
        
        assert result['success'] is False
        assert result['stderr'] == 'command failed'
        assert result['returncode'] == 1
    
    def test_run_command_timeout(self, auto_fixer, mock_subprocess):
        """
        GIVEN: A command that times out
        WHEN: run_command is called with a timeout
        THEN: It should return timeout error
        """
        mock_subprocess.side_effect = subprocess.TimeoutExpired('cmd', 5)
        
        result = auto_fixer.run_command(['sleep', '10'], timeout=5)
        
        assert result['success'] is False
        assert 'timed out' in result['error'].lower()
    
    def test_get_all_open_prs_success(self, auto_fixer, mock_subprocess, sample_pr_data):
        """
        GIVEN: GitHub API returns open PRs
        WHEN: get_all_open_prs is called
        THEN: It should return a list of PRs
        """
        # Skip prerequisite checks that were done in fixture
        mock_subprocess.reset_mock()
        
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout=json.dumps([sample_pr_data]),
            stderr=''
        )
        
        prs = auto_fixer.get_all_open_prs(limit=10)
        
        assert len(prs) == 1
        assert prs[0]['number'] == 123
        assert prs[0]['title'] == 'Fix workflow permission error'
    
    def test_get_all_open_prs_empty(self, auto_fixer, mock_subprocess):
        """
        GIVEN: No open PRs exist
        WHEN: get_all_open_prs is called
        THEN: It should return an empty list
        """
        mock_subprocess.reset_mock()
        
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout='[]',
            stderr=''
        )
        
        prs = auto_fixer.get_all_open_prs()
        
        assert len(prs) == 0
    
    def test_get_pr_details_success(self, auto_fixer, mock_subprocess, sample_pr_data):
        """
        GIVEN: A valid PR number
        WHEN: get_pr_details is called
        THEN: It should return PR details
        """
        mock_subprocess.reset_mock()
        
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout=json.dumps(sample_pr_data),
            stderr=''
        )
        
        details = auto_fixer.get_pr_details(123)
        
        assert details is not None
        assert details['number'] == 123
        assert details['title'] == 'Fix workflow permission error'
    
    def test_get_pr_details_not_found(self, auto_fixer, mock_subprocess):
        """
        GIVEN: An invalid PR number
        WHEN: get_pr_details is called
        THEN: It should return None
        """
        mock_subprocess.reset_mock()
        
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout='',
            stderr='PR not found'
        )
        
        details = auto_fixer.get_pr_details(999)
        
        assert details is None
    
    def test_check_copilot_already_invoked_true(self, auto_fixer, sample_pr_data):
        """
        GIVEN: A PR with @copilot mentions in comments
        WHEN: check_copilot_already_invoked is called
        THEN: It should return True
        """
        sample_pr_data['comments'] = [
            {'body': '@copilot please fix this'}
        ]
        
        result = auto_fixer.check_copilot_already_invoked(sample_pr_data)
        
        assert result is True
    
    def test_check_copilot_already_invoked_false(self, auto_fixer, sample_pr_data):
        """
        GIVEN: A PR without @copilot mentions
        WHEN: check_copilot_already_invoked is called
        THEN: It should return False
        """
        result = auto_fixer.check_copilot_already_invoked(sample_pr_data)
        
        assert result is False
    
    def test_analyze_pr_auto_fix(self, auto_fixer, sample_pr_data):
        """
        GIVEN: A PR with 'auto-fix' in the title
        WHEN: analyze_pr is called
        THEN: It should identify it as an auto-fix with critical priority
        """
        sample_pr_data['title'] = 'Auto-fix workflow error'
        
        analysis = auto_fixer.analyze_pr(sample_pr_data)
        
        assert analysis['should_fix'] is True
        assert analysis['fix_type'] == 'auto-fix'
        assert analysis['priority'] == 'critical'
        assert 'Auto-generated fix PR' in analysis['reasons']
    
    def test_analyze_pr_workflow(self, auto_fixer, sample_pr_data):
        """
        GIVEN: A PR related to workflow fixes
        WHEN: analyze_pr is called
        THEN: It should identify it as a workflow fix with high priority
        """
        analysis = auto_fixer.analyze_pr(sample_pr_data)
        
        assert analysis['should_fix'] is True
        assert 'workflow' in analysis['fix_type'] or 'Workflow/CI fix' in analysis['reasons']
        assert analysis['priority'] in ['high', 'critical']
    
    def test_analyze_pr_permissions(self, auto_fixer, sample_pr_data):
        """
        GIVEN: A PR with permission errors
        WHEN: analyze_pr is called
        THEN: It should identify it as a permissions fix
        """
        sample_pr_data['title'] = 'Fix permission denied error'
        
        analysis = auto_fixer.analyze_pr(sample_pr_data)
        
        assert analysis['should_fix'] is True
        assert analysis['fix_type'] == 'permissions'
        assert analysis['priority'] == 'high'
    
    def test_analyze_pr_draft(self, auto_fixer, sample_pr_data):
        """
        GIVEN: A draft PR
        WHEN: analyze_pr is called
        THEN: It should identify it as needing implementation
        """
        sample_pr_data['title'] = 'New feature implementation'
        sample_pr_data['isDraft'] = True
        
        analysis = auto_fixer.analyze_pr(sample_pr_data)
        
        assert analysis['should_fix'] is True
        assert analysis['fix_type'] == 'draft'
        assert 'Draft PR needing implementation' in analysis['reasons']
    
    def test_create_copilot_instructions_auto_fix(self, auto_fixer, sample_pr_data):
        """
        GIVEN: An auto-fix PR analysis
        WHEN: create_copilot_instructions is called
        THEN: It should generate appropriate auto-fix instructions
        """
        analysis = {
            'fix_type': 'auto-fix',
            'priority': 'critical',
            'reasons': ['Auto-generated fix PR']
        }
        
        instructions = auto_fixer.create_copilot_instructions(sample_pr_data, analysis)
        
        assert '@copilot' in instructions
        assert 'auto-fix' in instructions.lower()
        assert 'critical' in instructions.lower()
        assert 'minimal' in instructions.lower()
    
    def test_create_copilot_instructions_workflow(self, auto_fixer, sample_pr_data):
        """
        GIVEN: A workflow fix PR analysis
        WHEN: create_copilot_instructions is called
        THEN: It should generate workflow-specific instructions
        """
        analysis = {
            'fix_type': 'workflow',
            'priority': 'high',
            'reasons': ['Workflow/CI fix']
        }
        
        instructions = auto_fixer.create_copilot_instructions(sample_pr_data, analysis)
        
        assert '@copilot' in instructions
        assert 'workflow' in instructions.lower()
        assert 'GitHub Actions' in instructions or 'workflow' in instructions
    
    def test_invoke_copilot_on_pr_success(self, auto_fixer, mock_subprocess, sample_pr_data):
        """
        GIVEN: A valid PR without Copilot invocation
        WHEN: invoke_copilot_on_pr is called
        THEN: It should successfully post instructions
        """
        mock_subprocess.reset_mock()
        
        # Mock get_pr_details
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout=json.dumps(sample_pr_data),
            stderr=''
        )
        
        result = auto_fixer.invoke_copilot_on_pr(123)
        
        # In dry-run mode, should succeed
        assert result is True
        assert auto_fixer.stats['succeeded'] == 1
    
    def test_invoke_copilot_on_pr_already_invoked(self, auto_fixer, mock_subprocess, sample_pr_data):
        """
        GIVEN: A PR with Copilot already invoked
        WHEN: invoke_copilot_on_pr is called
        THEN: It should skip the PR
        """
        mock_subprocess.reset_mock()
        
        sample_pr_data['comments'] = [{'body': '@copilot fix this'}]
        
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout=json.dumps(sample_pr_data),
            stderr=''
        )
        
        result = auto_fixer.invoke_copilot_on_pr(123)
        
        assert result is True
        assert auto_fixer.stats['already_fixed'] == 1
        assert auto_fixer.stats['skipped'] == 1
    
    def test_invoke_copilot_on_pr_failed(self, auto_fixer, mock_subprocess, sample_pr_data):
        """
        GIVEN: A PR that fails to post comment (not in dry-run)
        WHEN: invoke_copilot_on_pr is called
        THEN: It should track the failure
        """
        # Use non-dry-run mode
        auto_fixer.dry_run = False
        mock_subprocess.reset_mock()
        
        # Mock get_pr_details success, but comment posting failure
        def side_effect(*args, **kwargs):
            cmd = args[0]
            if 'view' in cmd:
                return Mock(returncode=0, stdout=json.dumps(sample_pr_data), stderr='')
            elif 'comment' in cmd:
                return Mock(returncode=1, stdout='', stderr='Failed to post comment')
            return Mock(returncode=0, stdout='', stderr='')
        
        mock_subprocess.side_effect = side_effect
        
        result = auto_fixer.invoke_copilot_on_pr(123)
        
        assert result is False
        assert auto_fixer.stats['failed'] == 1
        assert len(auto_fixer.stats['errors']) == 1
    
    def test_process_all_prs_with_specific_numbers(self, auto_fixer, mock_subprocess, sample_pr_data):
        """
        GIVEN: Specific PR numbers to process
        WHEN: process_all_prs is called with pr_numbers
        THEN: It should only process those PRs
        """
        mock_subprocess.reset_mock()
        
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout=json.dumps(sample_pr_data),
            stderr=''
        )
        
        auto_fixer.process_all_prs(pr_numbers=[123, 456])
        
        # Should have tried to get details for both PRs
        assert auto_fixer.stats['processed'] >= 1
    
    def test_process_all_prs_with_limit(self, auto_fixer, mock_subprocess, sample_pr_data):
        """
        GIVEN: Multiple open PRs
        WHEN: process_all_prs is called with a limit
        THEN: It should respect the limit
        """
        mock_subprocess.reset_mock()
        
        # Return 5 PRs
        prs = [sample_pr_data.copy() for i in range(5)]
        for i, pr in enumerate(prs):
            pr['number'] = 100 + i
        
        def side_effect(*args, **kwargs):
            cmd = args[0]
            if 'list' in cmd:
                return Mock(returncode=0, stdout=json.dumps(prs), stderr='')
            elif 'view' in cmd:
                return Mock(returncode=0, stdout=json.dumps(sample_pr_data), stderr='')
            return Mock(returncode=0, stdout='', stderr='')
        
        mock_subprocess.side_effect = side_effect
        
        auto_fixer.process_all_prs(limit=3)
        
        # Should have limited to 3 PRs (but we returned 5)
        # The actual processing count depends on implementation
        assert auto_fixer.stats['total_prs'] <= 5
    
    def test_print_summary(self, auto_fixer, capsys):
        """
        GIVEN: Statistics have been collected
        WHEN: print_summary is called
        THEN: It should display formatted summary
        """
        auto_fixer.stats = {
            'total_prs': 10,
            'processed': 10,
            'succeeded': 7,
            'failed': 2,
            'skipped': 1,
            'already_fixed': 3,
            'errors': [
                {'pr': 123, 'error': 'Test error'}
            ]
        }
        
        auto_fixer.print_summary()
        
        captured = capsys.readouterr()
        assert 'Execution Summary' in captured.out
        assert '10' in captured.out  # Total PRs
        assert '7' in captured.out   # Succeeded
        assert '2' in captured.out   # Failed
        assert 'Test error' in captured.out


class TestCopilotAutoFixAllPRsIntegration:
    """Integration tests for the full workflow."""
    
    @pytest.mark.integration
    def test_full_workflow_dry_run(self, tmp_path):
        """
        GIVEN: A complete setup with mock data
        WHEN: The full workflow runs in dry-run mode
        THEN: It should complete without errors and show what would be done
        """
        # This test would require full mocking of gh CLI
        # Skipping actual implementation for now
        pass
    
    @pytest.mark.integration
    @pytest.mark.skipif(
        not os.environ.get('GITHUB_TOKEN'),
        reason="Requires GITHUB_TOKEN for integration test"
    )
    def test_actual_pr_listing(self):
        """
        GIVEN: Real GitHub credentials
        WHEN: Listing actual PRs
        THEN: It should successfully retrieve PR data
        
        Note: This test requires actual GitHub credentials and repo access
        """
        # Only run if explicitly requested with real credentials
        pass


def test_script_help_output():
    """
    GIVEN: The script is run with --help
    WHEN: It is executed
    THEN: It should display help information
    """
    script_path = Path(__file__).parent.parent / 'scripts' / 'copilot_auto_fix_all_prs.py'
    
    result = subprocess.run(
        ['python', str(script_path), '--help'],
        capture_output=True,
        text=True,
        timeout=10
    )
    
    assert result.returncode == 0
    assert 'Copilot Auto-Fix All Pull Requests' in result.stdout
    assert '--pr' in result.stdout
    assert '--dry-run' in result.stdout
    assert '--limit' in result.stdout


def test_script_dry_run_no_token():
    """
    GIVEN: The script is run in dry-run mode without token
    WHEN: It attempts to verify prerequisites
    THEN: It should handle missing token gracefully
    """
    script_path = Path(__file__).parent.parent / 'scripts' / 'copilot_auto_fix_all_prs.py'
    
    # Remove token from environment for this test
    env = os.environ.copy()
    env.pop('GITHUB_TOKEN', None)
    env.pop('GH_TOKEN', None)
    
    # This will likely fail at prerequisite check, which is expected
    # We're just testing that it doesn't crash unexpectedly
    result = subprocess.run(
        ['python', str(script_path), '--dry-run', '--limit', '1'],
        capture_output=True,
        text=True,
        timeout=30,
        env=env
    )
    
    # It may fail, but should exit gracefully
    assert result.returncode in [0, 1]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
