#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dashboard Error Reporting API

Flask routes for receiving JavaScript errors from the MCP dashboard
and creating GitHub issues with auto-healing triggers.
"""

import logging
from typing import Dict, Any
from flask import Flask, request, jsonify, Blueprint
import os

from ipfs_datasets_py.mcp_server.tools.dashboard_tools import get_js_error_reporter

logger = logging.getLogger(__name__)


# Create a blueprint for dashboard error reporting
dashboard_errors_bp = Blueprint('dashboard_errors', __name__, url_prefix='/api')


@dashboard_errors_bp.route('/report-js-error', methods=['POST'])
def report_js_error():
    """
    Receive and process JavaScript errors from the dashboard.
    
    Expects JSON payload with:
    {
        "errors": [
            {
                "type": "error",
                "message": "Error message",
                "filename": "file.js",
                "lineno": 123,
                "colno": 45,
                "stack": "stack trace",
                "timestamp": "2024-01-01T00:00:00.000Z",
                "url": "http://...",
                "userAgent": "...",
                "consoleHistory": [...],
                "actionHistory": [...]
            }
        ],
        "reportedAt": "2024-01-01T00:00:00.000Z",
        "sessionId": "session_123"
    }
    
    Returns:
        JSON response with processing result
    """
    try:
        data = request.get_json(silent=True)
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'No JSON data provided'
            }), 400
        
        # Validate required fields
        if 'errors' not in data or not isinstance(data['errors'], list):
            return jsonify({
                'success': False,
                'error': 'Missing or invalid "errors" field'
            }), 400
        
        if not data['errors']:
            return jsonify({
                'success': False,
                'error': 'Empty errors array'
            }), 400
        
        # Get JavaScript error reporter
        reporter = get_js_error_reporter()
        
        # Process the error report
        result = reporter.process_error_report(
            data,
            create_issue=True,  # Always create GitHub issues
        )
        
        # Log the result
        if result.get('success'):
            error_count = result.get('report', {}).get('error_count', 0)
            logger.info(f"Processed JavaScript error report with {error_count} errors")
            
            if result.get('issue_created'):
                issue_url = result.get('issue_url', 'N/A')
                logger.info(f"Created GitHub issue: {issue_url}")
        else:
            logger.error(f"Failed to process error report: {result.get('error')}")
        
        # Return result
        status_code = 200 if result.get('success') else 500
        return jsonify(result), status_code
        
    except Exception as e:
        logger.error(f"Error in report_js_error endpoint: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Internal server error: {e}'
        }), 500


@dashboard_errors_bp.route('/js-error-stats', methods=['GET'])
def js_error_stats():
    """
    Get statistics about JavaScript error reports.
    
    Returns:
        JSON response with error statistics
    """
    try:
        reporter = get_js_error_reporter()
        stats = reporter.get_error_statistics()
        
        return jsonify({
            'success': True,
            'statistics': stats
        })
        
    except Exception as e:
        logger.error(f"Error in js_error_stats endpoint: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@dashboard_errors_bp.route('/js-error-history', methods=['GET'])
def js_error_history():
    """
    Get recent JavaScript error reports.
    
    Query parameters:
        limit: Maximum number of reports to return (default: 10, max: 100)
    
    Returns:
        JSON response with error history
    """
    try:
        limit = request.args.get('limit', 10, type=int)
        limit = min(limit, 100)  # Cap at 100
        
        reporter = get_js_error_reporter()
        history = reporter.error_history[-limit:]
        
        return jsonify({
            'success': True,
            'count': len(history),
            'history': history
        })
        
    except Exception as e:
        logger.error(f"Error in js_error_history endpoint: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


def setup_dashboard_error_routes(app: Flask):
    """
    Set up dashboard error reporting routes on a Flask application.
    
    Args:
        app: Flask application instance
    """
    app.register_blueprint(dashboard_errors_bp)
    logger.info("Dashboard error reporting routes registered")


def create_dashboard_error_api() -> Flask:
    """
    Create a standalone Flask app with dashboard error reporting endpoints.
    
    Returns:
        Flask application with dashboard error reporting routes
    """
    app = Flask(__name__)
    setup_dashboard_error_routes(app)
    
    @app.route('/health')
    def health():
        return jsonify({
            'status': 'healthy',
            'service': 'dashboard-error-reporting-api'
        })
    
    return app


if __name__ == '__main__':
    # Run standalone server for testing
    app = create_dashboard_error_api()
    debug_mode = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(host='127.0.0.1', port=5001, debug=debug_mode)
