#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Dashboard Error Reporting API

Tests the Flask API endpoints that receive JavaScript errors from the dashboard.
"""

import json
import pytest
from unittest.mock import Mock, patch


pytest.importorskip("flask")

from ipfs_datasets_py.dashboards.dashboard_error_api import (
    create_dashboard_error_api,
    setup_dashboard_error_routes
)


@pytest.fixture
def app():
    """Create test Flask application."""
    test_app = create_dashboard_error_api()
    test_app.config['TESTING'] = True
    return test_app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


class TestDashboardErrorAPI:
    """Test suite for dashboard error reporting API endpoints."""
    
    def test_health_endpoint(self, client):
        """Test health check endpoint."""
        # WHEN: Calling health endpoint
        response = client.get('/health')
        
        # THEN: Should return healthy status
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'healthy'
        assert data['service'] == 'dashboard-error-reporting-api'
    
    @patch('ipfs_datasets_py.dashboards.dashboard_error_api.get_js_error_reporter')
    def test_report_js_error_success(self, mock_get_reporter, client):
        """Test successful JavaScript error reporting."""
        # GIVEN: Mocked reporter
        mock_reporter = Mock()
        mock_reporter.process_error_report.return_value = {
            'success': True,
            'issue_created': True,
            'issue_url': 'https://github.com/owner/repo/issues/1',
            'issue_number': 1,
            'report': {
                'error_count': 1,
                'session_id': 'session_123'
            }
        }
        mock_get_reporter.return_value = mock_reporter
        
        # WHEN: Posting error report
        error_data = {
            'errors': [{
                'type': 'error',
                'message': 'Test error',
                'timestamp': '2024-01-01T00:00:00.000Z'
            }],
            'reportedAt': '2024-01-01T00:00:00.000Z',
            'sessionId': 'session_123'
        }
        response = client.post(
            '/api/report-js-error',
            data=json.dumps(error_data),
            content_type='application/json'
        )
        
        # THEN: Should return success
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['issue_created'] is True
        assert data['issue_url'] == 'https://github.com/owner/repo/issues/1'
        mock_reporter.process_error_report.assert_called_once()
    
    def test_report_js_error_no_json(self, client):
        """Test error reporting without JSON data."""
        # WHEN: Posting without JSON
        response = client.post('/api/report-js-error')
        
        # THEN: Should return 400 error
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'No JSON data' in data['error']
    
    def test_report_js_error_missing_errors_field(self, client):
        """Test error reporting with missing errors field."""
        # WHEN: Posting without errors field
        response = client.post(
            '/api/report-js-error',
            data=json.dumps({'sessionId': 'test'}),
            content_type='application/json'
        )
        
        # THEN: Should return 400 error
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'errors' in data['error']
    
    def test_report_js_error_empty_errors_array(self, client):
        """Test error reporting with empty errors array."""
        # WHEN: Posting with empty errors array
        response = client.post(
            '/api/report-js-error',
            data=json.dumps({'errors': []}),
            content_type='application/json'
        )
        
        # THEN: Should return 400 error
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'Empty errors array' in data['error']
    
    @patch('ipfs_datasets_py.dashboards.dashboard_error_api.get_js_error_reporter')
    def test_report_js_error_processing_failure(self, mock_get_reporter, client):
        """Test handling of error processing failure."""
        # GIVEN: Reporter that returns failure
        mock_reporter = Mock()
        mock_reporter.process_error_report.return_value = {
            'success': False,
            'error': 'Processing failed'
        }
        mock_get_reporter.return_value = mock_reporter
        
        # WHEN: Posting error report
        error_data = {
            'errors': [{'type': 'error', 'message': 'Test'}]
        }
        response = client.post(
            '/api/report-js-error',
            data=json.dumps(error_data),
            content_type='application/json'
        )
        
        # THEN: Should return 500 error
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data['success'] is False
    
    @patch('ipfs_datasets_py.dashboards.dashboard_error_api.get_js_error_reporter')
    def test_report_js_error_exception(self, mock_get_reporter, client):
        """Test handling of unexpected exceptions."""
        # GIVEN: Reporter that raises exception
        mock_reporter = Mock()
        mock_reporter.process_error_report.side_effect = Exception('Unexpected error')
        mock_get_reporter.return_value = mock_reporter
        
        # WHEN: Posting error report
        error_data = {
            'errors': [{'type': 'error', 'message': 'Test'}]
        }
        response = client.post(
            '/api/report-js-error',
            data=json.dumps(error_data),
            content_type='application/json'
        )
        
        # THEN: Should return 500 error
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'Unexpected error' in data['error']
    
    @patch('ipfs_datasets_py.dashboards.dashboard_error_api.get_js_error_reporter')
    def test_js_error_stats_success(self, mock_get_reporter, client):
        """Test getting error statistics."""
        # GIVEN: Reporter with statistics
        mock_reporter = Mock()
        mock_reporter.get_error_statistics.return_value = {
            'total_reports': 10,
            'total_errors': 15,
            'error_types': {
                'error': 10,
                'unhandledrejection': 5
            }
        }
        mock_get_reporter.return_value = mock_reporter
        
        # WHEN: Getting statistics
        response = client.get('/api/js-error-stats')
        
        # THEN: Should return statistics
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['statistics']['total_reports'] == 10
        assert data['statistics']['total_errors'] == 15
    
    @patch('ipfs_datasets_py.dashboards.dashboard_error_api.get_js_error_reporter')
    def test_js_error_stats_exception(self, mock_get_reporter, client):
        """Test statistics endpoint with exception."""
        # GIVEN: Reporter that raises exception
        mock_reporter = Mock()
        mock_reporter.get_error_statistics.side_effect = Exception('Stats error')
        mock_get_reporter.return_value = mock_reporter
        
        # WHEN: Getting statistics
        response = client.get('/api/js-error-stats')
        
        # THEN: Should return error
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data['success'] is False
    
    @patch('ipfs_datasets_py.dashboards.dashboard_error_api.get_js_error_reporter')
    def test_js_error_history_success(self, mock_get_reporter, client):
        """Test getting error history."""
        # GIVEN: Reporter with history
        mock_reporter = Mock()
        mock_reporter.error_history = [
            {
                'session_id': 'session_1',
                'error_count': 2,
                'reported_at': '2024-01-01T00:00:00.000Z'
            },
            {
                'session_id': 'session_2',
                'error_count': 1,
                'reported_at': '2024-01-01T00:01:00.000Z'
            }
        ]
        mock_get_reporter.return_value = mock_reporter
        
        # WHEN: Getting history
        response = client.get('/api/js-error-history')
        
        # THEN: Should return history
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['count'] == 2
        assert len(data['history']) == 2
    
    @patch('ipfs_datasets_py.dashboards.dashboard_error_api.get_js_error_reporter')
    def test_js_error_history_with_limit(self, mock_get_reporter, client):
        """Test getting error history with limit parameter."""
        # GIVEN: Reporter with multiple history entries
        mock_reporter = Mock()
        mock_reporter.error_history = [{'id': i} for i in range(20)]
        mock_get_reporter.return_value = mock_reporter
        
        # WHEN: Getting history with limit of 5
        response = client.get('/api/js-error-history?limit=5')
        
        # THEN: Should return only 5 entries
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['count'] == 5
    
    @patch('ipfs_datasets_py.dashboards.dashboard_error_api.get_js_error_reporter')
    def test_js_error_history_max_limit(self, mock_get_reporter, client):
        """Test that history limit is capped at 100."""
        # GIVEN: Reporter with many history entries
        mock_reporter = Mock()
        mock_reporter.error_history = [{'id': i} for i in range(200)]
        mock_get_reporter.return_value = mock_reporter
        
        # WHEN: Getting history with limit of 150
        response = client.get('/api/js-error-history?limit=150')
        
        # THEN: Should return max 100 entries
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['count'] == 100
    
    @patch('ipfs_datasets_py.dashboards.dashboard_error_api.get_js_error_reporter')
    def test_js_error_history_exception(self, mock_get_reporter, client):
        """Test history endpoint with exception."""
        # GIVEN: Reporter that raises exception
        mock_reporter = Mock()
        mock_reporter.error_history = None  # Will cause error
        mock_get_reporter.side_effect = Exception('History error')
        
        # WHEN: Getting history
        response = client.get('/api/js-error-history')
        
        # THEN: Should return error
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data['success'] is False
    
    @patch('ipfs_datasets_py.dashboards.dashboard_error_api.get_js_error_reporter')
    def test_multiple_errors_in_single_report(self, mock_get_reporter, client):
        """Test reporting multiple errors in a single request."""
        # GIVEN: Mocked reporter
        mock_reporter = Mock()
        mock_reporter.process_error_report.return_value = {
            'success': True,
            'issue_created': True,
            'report': {'error_count': 3}
        }
        mock_get_reporter.return_value = mock_reporter
        
        # WHEN: Posting multiple errors
        error_data = {
            'errors': [
                {'type': 'error', 'message': 'Error 1'},
                {'type': 'error', 'message': 'Error 2'},
                {'type': 'unhandledrejection', 'message': 'Error 3'}
            ]
        }
        response = client.post(
            '/api/report-js-error',
            data=json.dumps(error_data),
            content_type='application/json'
        )
        
        # THEN: Should process all errors
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        call_args = mock_reporter.process_error_report.call_args[0][0]
        assert len(call_args['errors']) == 3


class TestAPIIntegration:
    """Integration tests for the API."""
    
    def test_setup_dashboard_error_routes(self):
        """Test that routes can be registered on an existing Flask app."""
        # GIVEN: A Flask app
        from flask import Flask
        app = Flask(__name__)
        
        # WHEN: Setting up routes
        setup_dashboard_error_routes(app)
        
        # THEN: Routes should be registered
        rules = [rule.rule for rule in app.url_map.iter_rules()]
        assert '/api/report-js-error' in rules
        assert '/api/js-error-stats' in rules
        assert '/api/js-error-history' in rules


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
