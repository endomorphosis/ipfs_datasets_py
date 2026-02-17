#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Error Reporting System Example

This script demonstrates the runtime error reporting system that automatically
creates GitHub issues from runtime errors.
"""

import os
import sys
import time

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ipfs_datasets_py.monitoring import (
    install_error_handlers,
    get_global_error_reporter,
    ErrorReporter
)


def example_manual_error_reporting():
    """Example of manual error reporting."""
    print("=" * 60)
    print("Example 1: Manual Error Reporting")
    print("=" * 60)
    
    # Create an error reporter (disabled for demo)
    reporter = ErrorReporter(enabled=False)
    
    # Report a generic error
    result = reporter.report_error(
        error_type='ValueError',
        error_message='Invalid configuration value: timeout must be positive',
        source='python',
        error_location='config.py:42',
        stack_trace='  File "config.py", line 42, in load_config\n    raise ValueError(...)',
        context={
            'config_file': '/etc/app/config.yaml',
            'setting': 'timeout',
            'value': -5
        }
    )
    
    print(f"Report result: {result}")
    print()


def example_exception_reporting():
    """Example of exception reporting."""
    print("=" * 60)
    print("Example 2: Exception Reporting")
    print("=" * 60)
    
    reporter = ErrorReporter(enabled=False)
    
    try:
        # Simulate an error
        data = {'key': 'value'}
        result = data['nonexistent_key']
    except KeyError as e:
        result = reporter.report_exception(
            e,
            source='python',
            context={
                'operation': 'data_processing',
                'user_id': 12345
            }
        )
        print(f"Exception reported: {result}")
    print()


def example_automatic_error_handling():
    """Example of automatic error handling."""
    print("=" * 60)
    print("Example 3: Automatic Error Handling")
    print("=" * 60)
    
    print("Installing global error handlers...")
    install_error_handlers()
    print("Error handlers installed!")
    
    print("\nNote: Any uncaught exceptions will now be automatically reported")
    print("      (if ERROR_REPORTING_ENABLED=true)")
    print()


def example_error_deduplication():
    """Example of error deduplication."""
    print("=" * 60)
    print("Example 4: Error Deduplication")
    print("=" * 60)
    
    reporter = ErrorReporter(enabled=True, min_report_interval=5)
    
    print("Reporting the same error multiple times...")
    for i in range(3):
        result = reporter.report_error(
            error_type='NetworkError',
            error_message='Connection timeout',
            source='python',
            error_location='network.py:100'
        )
        print(f"Attempt {i+1}: {'Reported' if result['success'] else 'Skipped (duplicate)'}")
        if i < 2:
            time.sleep(1)
    print()


def example_with_environment_variables():
    """Example showing environment variable configuration."""
    print("=" * 60)
    print("Example 5: Environment Variable Configuration")
    print("=" * 60)
    
    print("Current configuration:")
    print(f"  ERROR_REPORTING_ENABLED: {os.environ.get('ERROR_REPORTING_ENABLED', 'not set')}")
    print(f"  GITHUB_REPOSITORY: {os.environ.get('GITHUB_REPOSITORY', 'not set')}")
    print(f"  GITHUB_TOKEN: {'set' if os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN') else 'not set'}")
    
    print("\nTo enable error reporting, set:")
    print("  export ERROR_REPORTING_ENABLED=true")
    print("  export GITHUB_TOKEN=your_token_here")
    print()


def example_github_cli_status():
    """Example checking GitHub CLI availability."""
    print("=" * 60)
    print("Example 6: GitHub CLI Status")
    print("=" * 60)
    
    from ipfs_datasets_py.monitoring import GitHubIssueClient
    
    client = GitHubIssueClient()
    available = client.is_available()
    
    print(f"GitHub CLI available: {available}")
    if not available:
        print("\nTo install GitHub CLI:")
        print("  - Visit: https://cli.github.com/")
        print("  - After installation, authenticate with: gh auth login")
    print()


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("IPFS Datasets Python - Error Reporting System Examples")
    print("=" * 60 + "\n")
    
    print("This example demonstrates the runtime error reporting system")
    print("that automatically creates GitHub issues from runtime errors.")
    print()
    
    # Run examples
    example_manual_error_reporting()
    example_exception_reporting()
    example_automatic_error_handling()
    example_github_cli_status()
    example_with_environment_variables()
    
    # Only run deduplication example if error reporting is enabled
    if os.environ.get('ERROR_REPORTING_ENABLED', '').lower() == 'true':
        print("\n⚠️  ERROR_REPORTING_ENABLED is set to true!")
        print("The deduplication example will create real GitHub issues.")
        response = input("Continue? (y/n): ")
        if response.lower() == 'y':
            example_error_deduplication()
    else:
        print("\n✓ All examples completed (in dry-run mode)")
        print("  To enable real error reporting, set ERROR_REPORTING_ENABLED=true")
    
    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == '__main__':
    main()
