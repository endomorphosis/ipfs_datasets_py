#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demonstration of JavaScript Error Auto-Healing System

This script demonstrates the complete workflow of the JavaScript error
auto-healing system without needing a running dashboard.
"""

import sys
import json
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

# Load modules directly
def load_module(name, filepath):
    spec = importlib.util.spec_from_file_location(name, filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Get paths
script_dir = Path(__file__).parent
repo_dir = script_dir.parent.parent / 'ipfs_datasets_py'

# Load the error reporter
js_error_reporter = load_module(
    'js_error_reporter',
    repo_dir / 'mcp_server' / 'tools' / 'dashboard_tools' / 'js_error_reporter.py'
)


def print_section(title):
    """Print a section header."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


def demo_basic_error_reporting():
    """Demonstrate basic error reporting."""
    print_section("1. Basic Error Reporting")
    
    # Create reporter
    reporter = js_error_reporter.JavaScriptErrorReporter()
    
    # Simulate error data from dashboard
    error_data = {
        'errors': [{
            'type': 'error',
            'message': 'Cannot read property "data" of undefined',
            'filename': 'dashboard.js',
            'lineno': 42,
            'colno': 15,
            'stack': '''TypeError: Cannot read property "data" of undefined
    at loadDashboardData (dashboard.js:42:15)
    at initializeDashboard (dashboard.js:100:5)
    at DOMContentLoaded (dashboard.js:200:3)''',
            'timestamp': '2024-01-30T23:00:00.000Z',
            'url': 'http://localhost:8888/dashboard',
            'userAgent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0'
        }],
        'reportedAt': '2024-01-30T23:00:00.000Z',
        'sessionId': 'session_demo_123'
    }
    
    # Format the error report
    report = reporter.format_error_report(error_data)
    
    print("📝 Formatted Error Report:")
    print(json.dumps(report, indent=2))
    
    return reporter, report


def demo_error_with_context():
    """Demonstrate error with console history and user actions."""
    print_section("2. Error with Console History and User Actions")
    
    reporter = js_error_reporter.JavaScriptErrorReporter()
    
    # Simulate error with rich context
    error_data = {
        'errors': [{
            'type': 'unhandledrejection',
            'message': 'Failed to fetch: NetworkError',
            'stack': 'NetworkError: Failed to fetch\n    at fetchData (api.js:10:5)',
            'timestamp': '2024-01-30T23:01:00.000Z',
            'url': 'http://localhost:8888/dashboard',
            'userAgent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0',
            'consoleHistory': [
                {'level': 'log', 'message': 'Dashboard initialized', 'timestamp': '2024-01-30T23:00:00.000Z'},
                {'level': 'log', 'message': 'Loading user data...', 'timestamp': '2024-01-30T23:00:30.000Z'},
                {'level': 'warn', 'message': 'API response slow (2s)', 'timestamp': '2024-01-30T23:00:32.000Z'},
                {'level': 'error', 'message': 'Failed to load data', 'timestamp': '2024-01-30T23:01:00.000Z'}
            ],
            'actionHistory': [
                {'type': 'click', 'element': 'BUTTON', 'id': 'refresh-btn', 'timestamp': '2024-01-30T23:00:45.000Z'},
                {'type': 'submit', 'element': 'FORM', 'id': 'filter-form', 'timestamp': '2024-01-30T23:00:50.000Z'},
                {'type': 'click', 'element': 'A', 'id': 'nav-dashboard', 'timestamp': '2024-01-30T23:00:55.000Z'}
            ]
        }],
        'reportedAt': '2024-01-30T23:01:00.000Z',
        'sessionId': 'session_demo_456'
    }
    
    # Format and create issue body
    report = reporter.format_error_report(error_data)
    issue_body = reporter.create_github_issue_body(report)
    
    print("📋 GitHub Issue Body Preview:")
    print("-" * 70)
    print(issue_body)
    print("-" * 70)
    
    return reporter, report


def demo_error_statistics():
    """Demonstrate error statistics."""
    print_section("3. Error Statistics and History")
    
    reporter = js_error_reporter.JavaScriptErrorReporter()
    
    # Simulate multiple error reports
    error_types = [
        ('error', 'Syntax error in script'),
        ('error', 'Undefined variable'),
        ('unhandledrejection', 'Promise rejected'),
        ('error', 'Type error'),
        ('unhandledrejection', 'Async operation failed')
    ]
    
    print("📊 Adding error reports...")
    for error_type, message in error_types:
        error_data = {
            'errors': [{'type': error_type, 'message': message}],
            'sessionId': f'session_{error_type}_{message[:10]}'
        }
        reporter.process_error_report(error_data, create_issue=False)
        print(f"  ✓ Added {error_type}: {message}")
    
    # Get statistics
    stats = reporter.get_error_statistics()
    
    print("\n📈 Error Statistics:")
    print(json.dumps(stats, indent=2))
    
    return reporter


def demo_github_issue_creation():
    """Demonstrate GitHub issue creation (mocked)."""
    print_section("4. GitHub Issue Creation (Mocked)")
    
    print("🔧 Simulating GitHub issue creation...")
    print("   (In real usage, GitHub CLI would create an actual issue)")
    
    # Create reporter
    reporter = js_error_reporter.JavaScriptErrorReporter()
    
    error_data = {
        'errors': [{
            'type': 'error',
            'message': 'Demo error for issue creation',
            'stack': 'Error at demo.js:1:1'
        }],
        'sessionId': 'session_demo_issue'
    }
    
    # Process without creating issue (for demo)
    result = reporter.process_error_report(error_data, create_issue=False)
    
    # Simulate successful issue creation
    result['issue_created'] = True
    result['issue_url'] = 'https://github.com/endomorphosis/ipfs_datasets_py/issues/999'
    result['issue_number'] = 999
    
    print("\n✅ Result (Simulated):")
    print(json.dumps(result, indent=2))
    
    print(f"\n🎉 GitHub Issue Would Be Created!")
    print(f"   URL: {result.get('issue_url')}")
    print(f"   Number: #{result.get('issue_number')}")
    print(f"\n📝 Next Steps:")
    print("   1. Auto-healing workflow will be triggered")
    print("   2. Draft PR will be created")
    print("   3. GitHub Copilot will suggest fixes")
    print("   4. Human review and merge")


def demo_error_workflow():
    """Demonstrate the complete error workflow."""
    print_section("5. Complete Error Workflow")
    
    print("📋 Workflow Steps:")
    print("\n1️⃣  JavaScript Error Occurs in Dashboard")
    print("   → error_capture.js detects the error")
    print("   → Captures stack trace, console history, user actions")
    print("   → Sends POST request to /api/report-js-error")
    
    print("\n2️⃣  Backend Receives Error Report")
    print("   → dashboard_error_api.py receives the request")
    print("   → Validates error data")
    print("   → Passes to JavaScriptErrorReporter")
    
    print("\n3️⃣  Error Report Processing")
    print("   → Formats error data into structured report")
    print("   → Stores in error history")
    print("   → Creates GitHub issue if enabled")
    
    print("\n4️⃣  GitHub Issue Creation")
    print("   → Generates detailed issue body with context")
    print("   → Creates issue via GitHub CLI")
    print("   → Adds labels: bug, javascript, dashboard, auto-healing")
    
    print("\n5️⃣  Auto-Healing Trigger")
    print("   → Calls auto_healing_coordinator")
    print("   → Creates error pattern for javascript_error")
    print("   → Triggers GitHub Actions workflow")
    
    print("\n6️⃣  GitHub Actions Workflow")
    print("   → issue-to-draft-pr.yml detects new issue")
    print("   → Creates a new branch")
    print("   → Creates draft PR")
    print("   → Mentions @copilot for automated fixes")
    
    print("\n7️⃣  Automated Fix and Review")
    print("   → GitHub Copilot analyzes the error")
    print("   → Proposes/implements fixes")
    print("   → Human reviews the changes")
    print("   → Merges when ready")
    
    print("\n✅ Repository is healed automatically!")


def main():
    """Run all demonstrations."""
    print("\n" + "=" * 70)
    print("  JavaScript Error Auto-Healing System - Demonstration")
    print("=" * 70)
    
    try:
        # Run demonstrations
        demo_basic_error_reporting()
        demo_error_with_context()
        demo_error_statistics()
        demo_github_issue_creation()
        demo_error_workflow()
        
        print_section("Summary")
        print("✅ All demonstrations completed successfully!")
        print("\n📚 For more information, see:")
        print("   docs/javascript_error_auto_healing.md")
        print("\n🧪 Run tests with:")
        print("   python tests/unit_tests/test_js_error_reporter_standalone.py")
        print("\n🚀 Start the dashboard to see it in action:")
        print("   python -m ipfs_datasets_py.admin_dashboard")
        
    except Exception as e:
        print(f"\n❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
