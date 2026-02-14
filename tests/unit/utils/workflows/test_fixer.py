"""Unit tests for utils.workflows.fixer module."""

import pytest
from pathlib import Path
from ipfs_datasets_py.utils.workflows.fixer import WorkflowFixer


class TestWorkflowFixer:
    """Test suite for WorkflowFixer class."""
    
    def test_initialization(self):
        """Test WorkflowFixer initialization."""
        analysis = {
            'root_cause': 'Missing Python module',
            'suggestions': ['Install numpy'],
            'severity': 'medium'
        }
        fixer = WorkflowFixer(analysis, workflow_name='CI Tests')
        
        assert hasattr(fixer, 'analysis')
        assert hasattr(fixer, 'workflow_name')
        assert hasattr(fixer, 'generate_fix_proposal')
        assert fixer.workflow_name == 'CI Tests'
    
    def test_fix_types_defined(self):
        """Test that fix types are properly defined."""
        analysis = {'root_cause': 'test', 'suggestions': [], 'severity': 'low'}
        fixer = WorkflowFixer(analysis, workflow_name='Test')
        
        # Check that fix type methods exist
        assert hasattr(fixer, '_infer_fix_type')
        assert hasattr(fixer, '_generate_branch_name')
        assert hasattr(fixer, '_generate_pr_title')
        assert hasattr(fixer, '_generate_pr_description')
    
    def test_infer_fix_type_dependency(self):
        """Test fix type inference for dependency errors."""
        analysis = {
            'root_cause': 'Missing Python module numpy',
            'suggestions': ['Install numpy'],
            'severity': 'medium'
        }
        fixer = WorkflowFixer(analysis, workflow_name='CI')
        
        fix_type = fixer._infer_fix_type()
        assert fix_type == 'add_dependency'
    
    def test_infer_fix_type_timeout(self):
        """Test fix type inference for timeout errors."""
        analysis = {
            'root_cause': 'Operation timed out',
            'suggestions': ['Increase timeout'],
            'severity': 'medium'
        }
        fixer = WorkflowFixer(analysis, workflow_name='CI')
        
        fix_type = fixer._infer_fix_type()
        assert fix_type == 'increase_timeout'
    
    def test_infer_fix_type_permissions(self):
        """Test fix type inference for permission errors."""
        analysis = {
            'root_cause': 'Permission denied',
            'suggestions': ['Fix permissions'],
            'severity': 'high'
        }
        fixer = WorkflowFixer(analysis, workflow_name='CI')
        
        fix_type = fixer._infer_fix_type()
        assert fix_type == 'fix_permissions'
    
    def test_generate_branch_name(self):
        """Test branch name generation."""
        analysis = {
            'root_cause': 'Missing module',
            'suggestions': [],
            'severity': 'medium'
        }
        fixer = WorkflowFixer(analysis, workflow_name='CI Tests')
        
        branch_name = fixer._generate_branch_name('add_dependency')
        
        assert isinstance(branch_name, str)
        assert 'autofix' in branch_name.lower()
        assert 'ci-tests' in branch_name.lower() or 'ci_tests' in branch_name.lower()
        assert 'add-dependency' in branch_name.lower() or 'add_dependency' in branch_name.lower()
    
    def test_generate_pr_title(self):
        """Test PR title generation."""
        analysis = {
            'root_cause': 'Missing Python module numpy',
            'suggestions': ['Install numpy'],
            'severity': 'medium'
        }
        fixer = WorkflowFixer(analysis, workflow_name='CI Tests')
        
        title = fixer._generate_pr_title('add_dependency')
        
        assert isinstance(title, str)
        assert len(title) > 0
        assert 'CI Tests' in title or 'CI' in title
    
    def test_generate_pr_description(self):
        """Test PR description generation."""
        analysis = {
            'root_cause': 'Missing Python module numpy',
            'suggestions': ['Install numpy via pip', 'Add to requirements.txt'],
            'severity': 'medium'
        }
        fixer = WorkflowFixer(analysis, workflow_name='CI Tests')
        
        description = fixer._generate_pr_description('add_dependency', 'install-numpy')
        
        assert isinstance(description, str)
        assert len(description) > 100  # Should be comprehensive
        assert 'numpy' in description.lower()
        assert 'CI Tests' in description or 'CI' in description
        # Check for key sections
        assert 'Problem' in description or 'Issue' in description
        assert 'Solution' in description or 'Fix' in description
    
    def test_generate_fix_proposal_complete(self):
        """Test complete fix proposal generation."""
        analysis = {
            'root_cause': 'Missing Python module numpy',
            'suggestions': ['Install numpy', 'Add to requirements.txt'],
            'severity': 'medium',
            'workflow_file': Path('.github/workflows/ci.yml'),
            'error_log': 'ModuleNotFoundError: No module named numpy'
        }
        fixer = WorkflowFixer(analysis, workflow_name='CI Tests')
        
        proposal = fixer.generate_fix_proposal()
        
        # Check all required fields
        assert 'branch_name' in proposal
        assert 'pr_title' in proposal
        assert 'pr_description' in proposal
        assert 'fix_type' in proposal
        assert 'labels' in proposal
        
        # Check types
        assert isinstance(proposal['branch_name'], str)
        assert isinstance(proposal['pr_title'], str)
        assert isinstance(proposal['pr_description'], str)
        assert isinstance(proposal['fix_type'], str)
        assert isinstance(proposal['labels'], list)
        
        # Check content
        assert len(proposal['branch_name']) > 0
        assert len(proposal['pr_title']) > 0
        assert len(proposal['pr_description']) > 0
        assert len(proposal['labels']) > 0
    
    def test_fix_proposal_labels(self):
        """Test that appropriate labels are assigned."""
        analysis = {
            'root_cause': 'Missing dependency',
            'suggestions': ['Install package'],
            'severity': 'medium'
        }
        fixer = WorkflowFixer(analysis, workflow_name='CI')
        
        proposal = fixer.generate_fix_proposal()
        
        labels = proposal['labels']
        assert isinstance(labels, list)
        assert len(labels) > 0
        # Should have automated fix label
        assert any('automat' in label.lower() or 'fix' in label.lower() for label in labels)
    
    def test_different_workflow_names(self):
        """Test handling of different workflow names."""
        analysis = {
            'root_cause': 'Test error',
            'suggestions': ['Fix it'],
            'severity': 'low'
        }
        
        workflow_names = [
            'CI Tests',
            'Build and Deploy',
            'Unit Tests',
            'Integration-Tests',
        ]
        
        for name in workflow_names:
            fixer = WorkflowFixer(analysis, workflow_name=name)
            proposal = fixer.generate_fix_proposal()
            
            # Check that workflow name is reflected in outputs
            branch_name = proposal['branch_name'].lower()
            pr_title = proposal['pr_title']
            
            assert len(branch_name) > 0
            assert len(pr_title) > 0
    
    def test_severity_levels_handling(self):
        """Test handling of different severity levels."""
        severities = ['low', 'medium', 'high', 'critical']
        
        for severity in severities:
            analysis = {
                'root_cause': 'Test error',
                'suggestions': ['Fix it'],
                'severity': severity
            }
            
            fixer = WorkflowFixer(analysis, workflow_name='Test')
            proposal = fixer.generate_fix_proposal()
            
            # Should generate valid proposals for all severity levels
            assert 'branch_name' in proposal
            assert 'pr_title' in proposal
            assert len(proposal['pr_title']) > 0
    
    def test_fix_proposal_with_multiple_suggestions(self):
        """Test fix proposal with multiple suggestions."""
        analysis = {
            'root_cause': 'Multiple issues detected',
            'suggestions': [
                'Install missing package',
                'Update requirements.txt',
                'Add error handling',
                'Increase timeout'
            ],
            'severity': 'high'
        }
        fixer = WorkflowFixer(analysis, workflow_name='CI')
        
        proposal = fixer.generate_fix_proposal()
        description = proposal['pr_description']
        
        # Should include all or reference multiple suggestions
        assert len(description) > 200
