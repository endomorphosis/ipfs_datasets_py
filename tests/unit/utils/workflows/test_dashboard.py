"""Unit tests for utils.workflows.dashboard module."""

import pytest
import json
from pathlib import Path
from ipfs_datasets_py.utils.workflows.dashboard import DashboardGenerator


class TestDashboardGenerator:
    """Test suite for DashboardGenerator class."""
    
    def test_initialization(self):
        """Test DashboardGenerator initialization."""
        dashboard = DashboardGenerator(repo='owner/repo')
        
        assert hasattr(dashboard, 'repo')
        assert hasattr(dashboard, 'load_all_metrics')
        assert hasattr(dashboard, 'aggregate_metrics')
        assert hasattr(dashboard, 'generate_report')
        assert dashboard.repo == 'owner/repo'
    
    def test_initialization_with_defaults(self):
        """Test initialization with default parameters."""
        dashboard = DashboardGenerator()
        
        assert hasattr(dashboard, 'repo')
        assert dashboard.repo == 'unknown/unknown'
    
    def test_aggregate_metrics_structure(self):
        """Test that aggregated metrics have correct structure."""
        dashboard = DashboardGenerator(repo='test/repo')
        
        # Create sample metrics data
        dashboard.metrics_data = [
            {
                'workflow_name': 'CI',
                'api_calls': {'gh pr list': 5, 'gh issue create': 2},
                'total_calls': 7,
                'timestamp': '2024-01-01T00:00:00'
            },
            {
                'workflow_name': 'Deploy',
                'api_calls': {'gh pr list': 3},
                'total_calls': 3,
                'timestamp': '2024-01-01T01:00:00'
            }
        ]
        
        aggregated = dashboard.aggregate_metrics()
        
        assert 'total_calls' in aggregated
        assert 'total_cost' in aggregated
        assert 'by_call_type' in aggregated
        assert 'by_workflow' in aggregated
        assert 'timeline' in aggregated
        
        # Check calculations
        assert aggregated['total_calls'] == 10  # 7 + 3
        assert isinstance(aggregated['by_call_type'], dict)
        assert isinstance(aggregated['by_workflow'], dict)
    
    def test_generate_report_text_format(self):
        """Test text format report generation."""
        dashboard = DashboardGenerator(repo='test/repo')
        dashboard.metrics_data = [
            {
                'workflow_name': 'CI',
                'api_calls': {'gh pr list': 5},
                'total_calls': 5,
                'timestamp': '2024-01-01'
            }
        ]
        
        aggregated = dashboard.aggregate_metrics()
        report = dashboard.generate_report(format='text', aggregated=aggregated)
        
        assert isinstance(report, str)
        assert len(report) > 0
        assert 'GitHub API' in report or 'API' in report
        assert 'test/repo' in report
    
    def test_generate_report_markdown_format(self):
        """Test markdown format report generation."""
        dashboard = DashboardGenerator(repo='test/repo')
        dashboard.metrics_data = [
            {
                'workflow_name': 'CI',
                'api_calls': {'gh pr list': 5},
                'total_calls': 5,
                'timestamp': '2024-01-01'
            }
        ]
        
        aggregated = dashboard.aggregate_metrics()
        report = dashboard.generate_report(format='markdown', aggregated=aggregated)
        
        assert isinstance(report, str)
        assert len(report) > 0
        # Markdown indicators
        assert '#' in report or '##' in report
        assert '|' in report or '-' in report  # Tables
    
    def test_generate_report_html_format(self):
        """Test HTML format report generation."""
        dashboard = DashboardGenerator(repo='test/repo')
        dashboard.metrics_data = [
            {
                'workflow_name': 'CI',
                'api_calls': {'gh pr list': 5},
                'total_calls': 5,
                'timestamp': '2024-01-01'
            }
        ]
        
        aggregated = dashboard.aggregate_metrics()
        report = dashboard.generate_report(format='html', aggregated=aggregated)
        
        assert isinstance(report, str)
        assert len(report) > 0
        # HTML indicators
        assert '<html' in report.lower()
        assert '</html>' in report.lower()
        assert '<body' in report.lower()
    
    def test_generate_report_invalid_format(self):
        """Test that invalid format raises error or defaults."""
        dashboard = DashboardGenerator(repo='test/repo')
        dashboard.metrics_data = []
        
        aggregated = dashboard.aggregate_metrics()
        
        # Should either raise error or default to a valid format
        try:
            report = dashboard.generate_report(format='invalid', aggregated=aggregated)
            # If no error, should still be a valid string
            assert isinstance(report, str)
        except (ValueError, KeyError):
            # Expected to raise error for invalid format
            pass
    
    def test_aggregate_metrics_empty_data(self):
        """Test aggregation with empty metrics data."""
        dashboard = DashboardGenerator(repo='test/repo')
        dashboard.metrics_data = []
        
        aggregated = dashboard.aggregate_metrics()
        
        assert 'total_calls' in aggregated
        assert aggregated['total_calls'] == 0
        assert 'by_call_type' in aggregated
        assert isinstance(aggregated['by_call_type'], dict)
    
    def test_aggregate_metrics_by_call_type(self):
        """Test that metrics are correctly aggregated by call type."""
        dashboard = DashboardGenerator(repo='test/repo')
        dashboard.metrics_data = [
            {
                'workflow_name': 'CI',
                'api_calls': {'gh pr list': 5, 'gh issue create': 2},
                'total_calls': 7,
            },
            {
                'workflow_name': 'Deploy',
                'api_calls': {'gh pr list': 3, 'gh pr create': 1},
                'total_calls': 4,
            }
        ]
        
        aggregated = dashboard.aggregate_metrics()
        by_call_type = aggregated['by_call_type']
        
        assert 'gh pr list' in by_call_type
        assert by_call_type['gh pr list'] == 8  # 5 + 3
        assert by_call_type['gh issue create'] == 2
        assert by_call_type['gh pr create'] == 1
    
    def test_aggregate_metrics_by_workflow(self):
        """Test that metrics are correctly aggregated by workflow."""
        dashboard = DashboardGenerator(repo='test/repo')
        dashboard.metrics_data = [
            {
                'workflow_name': 'CI',
                'total_calls': 7,
            },
            {
                'workflow_name': 'CI',
                'total_calls': 3,
            },
            {
                'workflow_name': 'Deploy',
                'total_calls': 5,
            }
        ]
        
        aggregated = dashboard.aggregate_metrics()
        by_workflow = aggregated['by_workflow']
        
        assert 'CI' in by_workflow
        assert 'Deploy' in by_workflow
        # CI should have combined counts from both entries
        assert isinstance(by_workflow['CI'], dict)
        assert isinstance(by_workflow['Deploy'], dict)
    
    def test_save_report(self, tmp_path):
        """Test saving report to file."""
        dashboard = DashboardGenerator(repo='test/repo')
        dashboard.metrics_data = [
            {
                'workflow_name': 'CI',
                'api_calls': {'gh pr list': 5},
                'total_calls': 5,
            }
        ]
        
        aggregated = dashboard.aggregate_metrics()
        report = dashboard.generate_report(format='text', aggregated=aggregated)
        
        output_file = tmp_path / 'dashboard.txt'
        dashboard.save_report(report, output_file)
        
        assert output_file.exists()
        assert output_file.read_text() == report
    
    def test_suggestions_generation(self):
        """Test that suggestions are generated for high usage."""
        dashboard = DashboardGenerator(repo='test/repo')
        
        # Create high API usage scenario
        dashboard.metrics_data = [
            {
                'workflow_name': 'CI',
                'api_calls': {'gh pr list': 100},  # High usage
                'total_calls': 100,
            }
        ]
        
        aggregated = dashboard.aggregate_metrics()
        
        # Check if suggestions field exists
        assert 'suggestions' in aggregated or 'recommendations' in aggregated
    
    def test_multiple_workflows_aggregation(self):
        """Test aggregation across multiple workflows."""
        dashboard = DashboardGenerator(repo='test/repo')
        
        workflows = ['CI', 'Deploy', 'Tests', 'Build']
        dashboard.metrics_data = [
            {
                'workflow_name': wf,
                'api_calls': {'gh pr list': 5},
                'total_calls': 5,
            }
            for wf in workflows
        ]
        
        aggregated = dashboard.aggregate_metrics()
        by_workflow = aggregated['by_workflow']
        
        # Should have all workflows
        for wf in workflows:
            assert wf in by_workflow
        
        # Total should be sum of all
        assert aggregated['total_calls'] == 20  # 5 * 4
