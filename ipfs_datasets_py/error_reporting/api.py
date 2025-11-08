#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Error Reporting API Endpoints

This module provides Flask API endpoints for receiving and processing
error reports from various sources (JavaScript, Docker, etc.).
"""

import logging
from typing import Dict, Any
from flask import Flask, request, jsonify

from ipfs_datasets_py.error_reporting import get_global_error_reporter

logger = logging.getLogger(__name__)


def setup_error_reporting_routes(app: Flask):
    """
    Set up error reporting routes on a Flask application.
    
    Args:
        app: Flask application instance
    """
    
    @app.route('/api/report-error', methods=['POST'])
    def report_error():
        """
        Receive and process error reports.
        
        Expects JSON payload with:
        - error_type: Type of error
        - error_message: Error message
        - source: Source of error (python, javascript, docker)
        - error_location: Optional location
        - stack_trace: Optional stack trace
        - context: Optional additional context
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({
                    'success': False,
                    'error': 'No JSON data provided'
                }), 400
            
            # Validate required fields
            required_fields = ['error_type', 'error_message', 'source']
            missing_fields = [f for f in required_fields if f not in data]
            if missing_fields:
                return jsonify({
                    'success': False,
                    'error': f'Missing required fields: {", ".join(missing_fields)}'
                }), 400
            
            # Get error reporter
            reporter = get_global_error_reporter()
            
            # Report the error
            result = reporter.report_error(
                error_type=data['error_type'],
                error_message=data['error_message'],
                source=data['source'],
                error_location=data.get('error_location'),
                stack_trace=data.get('stack_trace'),
                context=data.get('context', {})
            )
            
            # Return result
            status_code = 200 if result.get('success') else 500
            return jsonify(result), status_code
            
        except Exception as e:
            logger.error(f"Error in report_error endpoint: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/error-reporting/status', methods=['GET'])
    def error_reporting_status():
        """
        Get error reporting system status.
        """
        try:
            reporter = get_global_error_reporter()
            
            return jsonify({
                'success': True,
                'enabled': reporter.enabled,
                'github_available': reporter.github_client.is_available(),
                'reported_count': len(reporter._reported_errors)
            })
            
        except Exception as e:
            logger.error(f"Error in error_reporting_status endpoint: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    logger.info("Error reporting routes registered")


def create_error_reporting_app() -> Flask:
    """
    Create a standalone Flask app with error reporting endpoints.
    
    Returns:
        Flask application with error reporting routes
    """
    app = Flask(__name__)
    setup_error_reporting_routes(app)
    
    @app.route('/health')
    def health():
        return jsonify({
            'status': 'healthy',
            'service': 'error-reporting-api'
        })
    
    return app
