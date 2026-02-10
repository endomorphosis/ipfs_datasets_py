#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dashboard Error Reporting API

Flask routes for receiving JavaScript errors from the MCP dashboard
and creating GitHub issues with auto-healing triggers.
"""

import logging
from typing import Dict, Any
try:
    from flask import Flask, request, jsonify, Blueprint  # type: ignore
    _FLASK_AVAILABLE = True
except ImportError:  # pragma: no cover
    Flask = None  # type: ignore
    request = None  # type: ignore
    jsonify = None  # type: ignore
    Blueprint = None  # type: ignore
    _FLASK_AVAILABLE = False
import os

from ipfs_datasets_py.mcp_server.tools.dashboard_tools import get_js_error_reporter

logger = logging.getLogger(__name__)


class _DummyBlueprint:
    def __init__(self, *args, **kwargs):
        pass

    def route(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator


# Create a blueprint for dashboard error reporting (or a no-op shim if Flask is missing)
dashboard_errors_bp = (
    Blueprint('dashboard_errors', __name__, url_prefix='/api')
    if _FLASK_AVAILABLE
    else _DummyBlueprint('dashboard_errors', __name__)
)


@dashboard_errors_bp.route('/report-js-error', methods=['POST'])
def report_js_error():
    """Receive and process JavaScript errors from the dashboard."""
    if not _FLASK_AVAILABLE:
        raise ImportError("Flask is required for dashboard error API (pip install flask)")

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

        reporter = get_js_error_reporter()
        result = reporter.process_error_report(
            data,
            create_issue=True,
        )

        if result.get('success'):
            error_count = result.get('report', {}).get('error_count', 0)
            logger.info("Processed JavaScript error report with %s errors", error_count)

            if result.get('issue_created'):
                issue_url = result.get('issue_url', 'N/A')
                logger.info("Created GitHub issue: %s", issue_url)
        else:
            logger.error("Failed to process error report: %s", result.get('error'))

        status_code = 200 if result.get('success') else 500
        return jsonify(result), status_code

    except Exception as e:
        logger.error("Error in report_js_error endpoint: %s", e, exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Internal server error: {e}'
        }), 500


@dashboard_errors_bp.route('/js-error-stats', methods=['GET'])
def js_error_stats():
    """Get statistics about JavaScript error reports."""
    if not _FLASK_AVAILABLE:
        raise ImportError("Flask is required for dashboard error API (pip install flask)")

    try:
        reporter = get_js_error_reporter()
        stats = reporter.get_error_statistics()

        return jsonify({
            'success': True,
            'statistics': stats
        })

    except Exception as e:
        logger.error("Error in js_error_stats endpoint: %s", e, exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@dashboard_errors_bp.route('/js-error-history', methods=['GET'])
def js_error_history():
    """Get recent JavaScript error reports."""
    if not _FLASK_AVAILABLE:
        raise ImportError("Flask is required for dashboard error API (pip install flask)")

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
        logger.error("Error in js_error_history endpoint: %s", e, exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

def setup_dashboard_error_routes(app: 'Flask'):
    """
    Set up dashboard error reporting routes on a Flask application.
    
    Args:
        app: Flask application instance
    """
    if not _FLASK_AVAILABLE:
        raise ImportError("Flask is required for dashboard error API (pip install flask)")
    app.register_blueprint(dashboard_errors_bp)
    logger.info("Dashboard error reporting routes registered")


def create_dashboard_error_api() -> 'Flask':
    """
    Create a standalone Flask app with dashboard error reporting endpoints.
    
    Returns:
        Flask application with dashboard error reporting routes
    """
    if not _FLASK_AVAILABLE:
        raise ImportError("Flask is required for dashboard error API (pip install flask)")
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
