#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Automated PR Review System

Tests for the automated PR review system that uses GitHub Copilot agents.
"""

import json
import subprocess
from unittest.mock import Mock, patch, MagicMock
import pytest
import sys
import os

# Add scripts directory to path for import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))


def test_automated_pr_reviewer_import():
    """
    GIVEN the automated_pr_review module
    WHEN importing AutomatedPRReviewer
    THEN it should import successfully
    """
    from automated_pr_review import AutomatedPRReviewer
    assert AutomatedPRReviewer is not None


def test_automated_pr_reviewer_initialization():
    """
    GIVEN AutomatedPRReviewer class
    WHEN initializing with dry_run mode
    THEN it should create instance with correct attributes
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        # Mock gh --version check
        mock_run.return_value = Mock(returncode=0, stdout='gh version 2.40.0')
        
        reviewer = AutomatedPRReviewer(dry_run=True, min_confidence=70)
        
        assert reviewer.dry_run is True
        assert reviewer.min_confidence == 70
        mock_run.assert_called_once()


def test_criteria_weights_defined():
    """
    GIVEN AutomatedPRReviewer class
    WHEN checking CRITERIA_WEIGHTS
    THEN it should have expected criteria
    """
    from automated_pr_review import AutomatedPRReviewer
    
    weights = AutomatedPRReviewer.CRITERIA_WEIGHTS
    
    assert 'is_draft' in weights
    assert 'has_auto_fix_label' in weights
    assert 'workflow_failure' in weights
    assert 'has_do_not_merge_label' in weights
    assert weights['has_do_not_merge_label'] < 0  # Should be negative


def test_analyze_pr_draft_status():
    """
    GIVEN a draft PR
    WHEN analyzing it
    THEN it should increase confidence score and identify as draft
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        pr_details = {
            'number': 123,
            'title': 'Test Feature',
            'body': 'This is a test PR with enough description to pass the threshold',
            'isDraft': True,
            'labels': [],
            'files': [{'path': 'test.py'}],
            'mergeable': 'MERGEABLE',
            'updatedAt': '2025-10-31T12:00:00Z',
            'headRefName': 'feature/test'
        }
        
        analysis = reviewer.analyze_pr(pr_details)
        
        assert 'is_draft' in analysis['criteria_scores']
        assert analysis['task_type'] == 'implement_draft'
        assert 'Draft PR' in ' '.join(analysis['reasons'])


def test_analyze_pr_auto_fix_label():
    """
    GIVEN a PR with auto-fix label and workflow files
    WHEN analyzing it
    THEN it should have high confidence and workflow task type
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        pr_details = {
            'number': 124,
            'title': 'Fix workflow failure',
            'body': 'Auto-fix for workflow issue',
            'isDraft': False,
            'labels': [{'name': 'auto-fix'}],
            'files': [{'path': '.github/workflows/test.yml'}],
            'mergeable': 'MERGEABLE',
            'updatedAt': '2025-10-31T18:00:00Z',
            'headRefName': 'autohealing/fix-workflow'
        }
        
        analysis = reviewer.analyze_pr(pr_details)
        
        assert 'has_auto_fix_label' in analysis['criteria_scores']
        assert 'autohealing_pr' in analysis['criteria_scores']
        # Workflow task takes precedence when workflow files are present
        assert analysis['task_type'] == 'fix_workflow'
        assert analysis['confidence'] > 60


def test_analyze_pr_do_not_merge_blocks():
    """
    GIVEN a PR with do-not-merge label
    WHEN analyzing it
    THEN it should have zero confidence (blocked)
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        pr_details = {
            'number': 125,
            'title': 'Test PR',
            'body': 'Testing',
            'isDraft': True,
            'labels': [{'name': 'do-not-merge'}],
            'files': [{'path': 'test.py'}],
            'mergeable': 'MERGEABLE',
            'updatedAt': '2025-10-31T18:00:00Z',
            'headRefName': 'test'
        }
        
        analysis = reviewer.analyze_pr(pr_details)
        
        assert analysis['confidence'] == 0
        assert not analysis['should_invoke']


def test_analyze_pr_workflow_files():
    """
    GIVEN a PR with workflow files
    WHEN analyzing it
    THEN it should identify as workflow fix
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        pr_details = {
            'number': 126,
            'title': 'Fix GitHub Actions workflow',
            'body': 'Fixes workflow failure in CI pipeline',
            'isDraft': False,
            'labels': [],
            'files': [
                {'path': '.github/workflows/ci.yml'},
                {'path': 'scripts/test.py'}
            ],
            'mergeable': 'MERGEABLE',
            'updatedAt': '2025-10-31T18:00:00Z',
            'headRefName': 'fix-workflow'
        }
        
        analysis = reviewer.analyze_pr(pr_details)
        
        assert 'workflow_failure' in analysis['criteria_scores']
        assert analysis['task_type'] == 'fix_workflow'


def test_check_copilot_already_invoked():
    """
    GIVEN a PR with @copilot comment
    WHEN checking if Copilot was invoked
    THEN it should return True
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        pr_details = {
            'comments': [
                {'body': '@copilot please help with this'},
                {'body': 'Some other comment'}
            ]
        }
        
        result = reviewer.check_copilot_already_invoked(pr_details)
        assert result is True


def test_check_copilot_not_invoked():
    """
    GIVEN a PR without @copilot comment
    WHEN checking if Copilot was invoked
    THEN it should return False
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        pr_details = {
            'comments': [
                {'body': 'Normal comment'},
                {'body': 'Another comment'}
            ]
        }
        
        result = reviewer.check_copilot_already_invoked(pr_details)
        assert result is False


def test_create_copilot_comment_fix_task():
    """
    GIVEN a PR analysis for fix task
    WHEN creating Copilot comment
    THEN it should generate appropriate fix comment
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        pr_details = {
            'number': 127,
            'title': 'Fix issue',
            'body': 'Fixes #123',
            'isDraft': False,
            'labels': [{'name': 'auto-fix'}],
            'files': [],
            'mergeable': 'MERGEABLE',
            'updatedAt': '2025-10-31T18:00:00Z',
            'headRefName': 'fix'
        }
        
        analysis = {
            'task_type': 'implement_fix',
            'confidence': 85,
            'reasons': ['Auto-fix label', 'Has linked issue']
        }
        
        comment = reviewer.create_copilot_comment(pr_details, analysis)
        
        assert '@copilot' in comment
        assert 'implement the auto-fix' in comment.lower()
        assert '85%' in comment
        assert 'Auto-fix label' in comment


def test_create_copilot_comment_workflow_task():
    """
    GIVEN a PR analysis for workflow task
    WHEN creating Copilot comment
    THEN it should generate appropriate workflow fix comment
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        pr_details = {
            'number': 128,
            'title': 'Fix workflow',
            'body': 'Workflow fix',
            'isDraft': False,
            'labels': [],
            'files': [{'path': '.github/workflows/ci.yml'}],
            'mergeable': 'MERGEABLE',
            'updatedAt': '2025-10-31T18:00:00Z',
            'headRefName': 'fix-workflow'
        }
        
        analysis = {
            'task_type': 'fix_workflow',
            'confidence': 75,
            'reasons': ['Workflow fix needed']
        }
        
        comment = reviewer.create_copilot_comment(pr_details, analysis)
        
        assert '@copilot' in comment
        assert 'workflow' in comment.lower()
        assert '75%' in comment


def test_create_copilot_comment_review_task():
    """
    GIVEN a PR analysis for review task
    WHEN creating Copilot comment
    THEN it should generate appropriate review comment
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        pr_details = {
            'number': 129,
            'title': 'Feature addition',
            'body': 'Adds new feature',
            'isDraft': False,
            'labels': [],
            'files': [{'path': 'src/feature.py'}],
            'mergeable': 'MERGEABLE',
            'updatedAt': '2025-10-31T18:00:00Z',
            'headRefName': 'feature'
        }
        
        analysis = {
            'task_type': 'review',
            'confidence': 65,
            'reasons': ['Has description', 'Recent activity']
        }
        
        comment = reviewer.create_copilot_comment(pr_details, analysis)
        
        assert '@copilot /review' in comment
        assert '65%' in comment


def test_run_command_success():
    """
    GIVEN a valid command
    WHEN running it
    THEN it should return success result
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        # Mock successful gh --version
        mock_run.return_value = Mock(
            returncode=0,
            stdout='gh version 2.40.0',
            stderr=''
        )
        
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        # Reset mock for actual test
        mock_run.reset_mock()
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"test": "data"}',
            stderr=''
        )
        
        result = reviewer.run_command(['gh', 'pr', 'list'])
        
        assert result['success'] is True
        assert 'stdout' in result
        assert 'stderr' in result


def test_run_command_failure():
    """
    GIVEN a command that fails
    WHEN running it
    THEN it should return failure result
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        # Mock successful gh --version for init
        mock_run.return_value = Mock(returncode=0, stdout='gh version 2.40.0')
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        # Mock failed command
        mock_run.side_effect = subprocess.CalledProcessError(
            1, 'gh', stderr='Error occurred'
        )
        
        result = reviewer.run_command(['gh', 'invalid', 'command'])
        
        assert result['success'] is False
        assert 'error' in result


def test_min_confidence_threshold():
    """
    GIVEN different min_confidence values
    WHEN analyzing PRs
    THEN it should respect the threshold
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        
        # Low threshold
        reviewer_low = AutomatedPRReviewer(dry_run=True, min_confidence=30)
        assert reviewer_low.min_confidence == 30
        
        # High threshold
        reviewer_high = AutomatedPRReviewer(dry_run=True, min_confidence=80)
        assert reviewer_high.min_confidence == 80


def test_permission_issue_detection():
    """
    GIVEN a PR with permission-related keywords
    WHEN analyzing it
    THEN it should identify as permission issue
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        pr_details = {
            'number': 130,
            'title': 'Fix permission denied error',
            'body': 'This PR fixes permission issues in the workflow',
            'isDraft': False,
            'labels': [],
            'files': [{'path': '.github/workflows/test.yml'}],
            'mergeable': 'MERGEABLE',
            'updatedAt': '2025-10-31T18:00:00Z',
            'headRefName': 'fix-permissions'
        }
        
        analysis = reviewer.analyze_pr(pr_details)
        
        assert 'permission_issue' in analysis['criteria_scores']
        assert analysis['task_type'] == 'fix_permissions'


def test_large_pr_file_count():
    """
    GIVEN a PR with many files
    WHEN analyzing it
    THEN it should note the large scope
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        # Create a PR with 60 files
        files = [{'path': f'file{i}.py'} for i in range(60)]
        
        pr_details = {
            'number': 131,
            'title': 'Large refactoring',
            'body': 'Major refactoring across many files',
            'isDraft': False,
            'labels': [],
            'files': files,
            'mergeable': 'MERGEABLE',
            'updatedAt': '2025-10-31T18:00:00Z',
            'headRefName': 'refactor'
        }
        
        analysis = reviewer.analyze_pr(pr_details)
        
        # Should not get the reasonable file count bonus
        assert 'file_count_reasonable' not in analysis['criteria_scores']
        # Should mention large PR in reasons
        assert any('Large PR' in reason for reason in analysis['reasons'])


def test_merge_conflicts_detection():
    """
    GIVEN a PR with merge conflicts
    WHEN analyzing it
    THEN it should note the conflicts
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        pr_details = {
            'number': 132,
            'title': 'Feature with conflicts',
            'body': 'Feature PR',
            'isDraft': True,
            'labels': [],
            'files': [{'path': 'feature.py'}],
            'mergeable': 'CONFLICTING',
            'updatedAt': '2025-10-31T18:00:00Z',
            'headRefName': 'feature'
        }
        
        analysis = reviewer.analyze_pr(pr_details)
        
        # Should not get the no conflicts bonus
        assert 'no_conflicts' not in analysis['criteria_scores']
        # Should mention conflicts in reasons
        assert any('conflicts' in reason.lower() for reason in analysis['reasons'])


def test_wip_label_reduces_confidence():
    """
    GIVEN a PR with WIP label
    WHEN analyzing it
    THEN it should reduce confidence
    """
    from automated_pr_review import AutomatedPRReviewer
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0)
        reviewer = AutomatedPRReviewer(dry_run=True)
        
        # PR with WIP label
        pr_with_wip = {
            'number': 133,
            'title': 'WIP feature',
            'body': 'Work in progress',
            'isDraft': True,
            'labels': [{'name': 'WIP'}],
            'files': [{'path': 'feature.py'}],
            'mergeable': 'MERGEABLE',
            'updatedAt': '2025-10-31T18:00:00Z',
            'headRefName': 'feature'
        }
        
        analysis = reviewer.analyze_pr(pr_with_wip)
        
        assert 'has_wip_label' in analysis['criteria_scores']
        assert analysis['criteria_scores']['has_wip_label'] < 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
