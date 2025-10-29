#!/usr/bin/env python3
"""
Analyze GitHub Actions workflow failures to identify root causes and suggest fixes.

This script parses workflow logs, identifies common failure patterns, and provides
structured analysis for the auto-fix system.
"""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any


class WorkflowFailureAnalyzer:
    """Analyzes workflow failures and suggests fixes."""
    
    # Common failure patterns and their fixes
    FAILURE_PATTERNS = {
        'dependency_error': {
            'patterns': [
                r'ModuleNotFoundError: No module named [\'"](\w+)[\'"]',
                r'ImportError: cannot import name [\'"](\w+)[\'"]',
                r'Could not find a version that satisfies.*\s+(\S+)',
                r'ERROR: No matching distribution found for (\S+)',
                r'pip.*failed.*package.*(\w+)',
            ],
            'error_type': 'Missing Dependency',
            'fix_type': 'add_dependency',
            'confidence': 90,
        },
        'syntax_error': {
            'patterns': [
                r'SyntaxError: (.+)',
                r'IndentationError: (.+)',
                r'TabError: (.+)',
                r'invalid syntax',
            ],
            'error_type': 'Syntax Error',
            'fix_type': 'fix_syntax',
            'confidence': 85,
        },
        'test_failure': {
            'patterns': [
                r'FAILED (.+?) - (.+)',
                r'ERROR (.+?) - (.+)',
                r'AssertionError: (.+)',
                r'Test failed: (.+)',
            ],
            'error_type': 'Test Failure',
            'fix_type': 'fix_test',
            'confidence': 70,
        },
        'timeout': {
            'patterns': [
                r'timeout',
                r'timed out',
                r'deadline exceeded',
                r'operation took too long',
            ],
            'error_type': 'Timeout',
            'fix_type': 'increase_timeout',
            'confidence': 95,
        },
        'permission_error': {
            'patterns': [
                r'Permission denied',
                r'PermissionError',
                r'Access denied',
                r'Forbidden',
                r'401 Unauthorized',
                r'403 Forbidden',
            ],
            'error_type': 'Permission Error',
            'fix_type': 'fix_permissions',
            'confidence': 80,
        },
        'network_error': {
            'patterns': [
                r'ConnectionError',
                r'Network error',
                r'Failed to fetch',
                r'Unable to download',
                r'Connection refused',
                r'Could not resolve host',
            ],
            'error_type': 'Network Error',
            'fix_type': 'add_retry',
            'confidence': 75,
        },
        'docker_error': {
            'patterns': [
                r'docker.*error',
                r'Cannot connect to the Docker daemon',
                r'Docker build failed',
                r'Error response from daemon',
            ],
            'error_type': 'Docker Error',
            'fix_type': 'fix_docker',
            'confidence': 85,
        },
        'resource_error': {
            'patterns': [
                r'out of memory',
                r'OOM',
                r'MemoryError',
                r'disk.*full',
                r'No space left on device',
            ],
            'error_type': 'Resource Exhaustion',
            'fix_type': 'increase_resources',
            'confidence': 90,
        },
        'env_variable_missing': {
            'patterns': [
                r'Environment variable.*not set',
                r'KeyError.*env',
                r'Missing required.*variable',
            ],
            'error_type': 'Missing Environment Variable',
            'fix_type': 'add_env_variable',
            'confidence': 95,
        },
    }
    
    def __init__(self, run_id: str, workflow_name: str, logs_dir: Path):
        self.run_id = run_id
        self.workflow_name = workflow_name
        self.logs_dir = Path(logs_dir)
        self.analysis: Dict[str, Any] = {}
    
    def analyze(self) -> Dict[str, Any]:
        """Perform comprehensive failure analysis."""
        print(f"🔍 Analyzing workflow failure for run {self.run_id}...")
        
        # Read all log files
        logs = self._read_logs()
        
        # Extract errors from logs
        errors = self._extract_errors(logs)
        
        # Identify failure patterns
        patterns = self._identify_patterns(errors)
        
        # Determine root cause
        root_cause = self._determine_root_cause(patterns)
        
        # Generate fix recommendations
        recommendations = self._generate_recommendations(root_cause, patterns)
        
        # Compile analysis
        self.analysis = {
            'run_id': self.run_id,
            'workflow_name': self.workflow_name,
            'error_type': root_cause.get('error_type', 'Unknown'),
            'fix_type': root_cause.get('fix_type', 'manual'),
            'root_cause': root_cause.get('description', 'Could not determine root cause'),
            'fix_confidence': root_cause.get('confidence', 50),
            'errors': errors,
            'patterns_found': [p['type'] for p in patterns],
            'recommendations': recommendations,
            'affected_files': self._extract_affected_files(errors),
            'log_snippets': self._extract_relevant_snippets(logs, errors),
        }
        
        return self.analysis
    
    def _read_logs(self) -> Dict[str, str]:
        """Read all log files from the logs directory."""
        logs = {}
        
        for log_file in self.logs_dir.glob('*.log'):
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    logs[log_file.name] = f.read()
            except Exception as e:
                print(f"⚠️  Warning: Could not read {log_file}: {e}")
        
        return logs
    
    def _extract_errors(self, logs: Dict[str, str]) -> List[Dict[str, str]]:
        """Extract error messages from logs."""
        errors = []
        
        # Common error indicators
        error_indicators = [
            r'ERROR:',
            r'Error:',
            r'FAILED',
            r'Failed',
            r'Exception:',
            r'Traceback',
            r'Fatal:',
            r'❌',
        ]
        
        for log_name, content in logs.items():
            for line_num, line in enumerate(content.split('\n'), 1):
                for indicator in error_indicators:
                    if re.search(indicator, line, re.IGNORECASE):
                        errors.append({
                            'log_file': log_name,
                            'line_number': line_num,
                            'message': line.strip(),
                            'context': self._get_context(content, line_num, 3),
                        })
                        break
        
        return errors
    
    def _get_context(self, content: str, line_num: int, context_lines: int) -> List[str]:
        """Get surrounding context for an error line."""
        lines = content.split('\n')
        start = max(0, line_num - context_lines - 1)
        end = min(len(lines), line_num + context_lines)
        return lines[start:end]
    
    def _identify_patterns(self, errors: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Identify known failure patterns in errors."""
        patterns = []
        
        for error in errors:
            message = error['message']
            
            for pattern_name, pattern_info in self.FAILURE_PATTERNS.items():
                for regex in pattern_info['patterns']:
                    match = re.search(regex, message, re.IGNORECASE)
                    if match:
                        patterns.append({
                            'type': pattern_name,
                            'error_type': pattern_info['error_type'],
                            'fix_type': pattern_info['fix_type'],
                            'confidence': pattern_info['confidence'],
                            'matched_text': match.group(0),
                            'captured_values': match.groups() if match.groups() else [],
                            'error_ref': error,
                        })
                        break
        
        return patterns
    
    def _determine_root_cause(self, patterns: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Determine the most likely root cause from identified patterns."""
        if not patterns:
            return {
                'error_type': 'Unknown',
                'fix_type': 'manual',
                'description': 'Could not identify specific failure pattern',
                'confidence': 30,
            }
        
        # Sort patterns by confidence
        patterns_sorted = sorted(patterns, key=lambda p: p['confidence'], reverse=True)
        
        # Use the highest confidence pattern as root cause
        top_pattern = patterns_sorted[0]
        
        return {
            'error_type': top_pattern['error_type'],
            'fix_type': top_pattern['fix_type'],
            'description': top_pattern['matched_text'],
            'confidence': top_pattern['confidence'],
            'captured_values': top_pattern['captured_values'],
        }
    
    def _generate_recommendations(
        self, 
        root_cause: Dict[str, Any], 
        patterns: List[Dict[str, Any]]
    ) -> List[str]:
        """Generate fix recommendations based on analysis."""
        recommendations = []
        
        fix_type = root_cause.get('fix_type', 'manual')
        
        if fix_type == 'add_dependency':
            if root_cause.get('captured_values'):
                package = root_cause['captured_values'][0]
                recommendations.append(f"Add '{package}' to requirements.txt")
                recommendations.append(f"Add pip install step for '{package}' in workflow")
        
        elif fix_type == 'increase_timeout':
            recommendations.append("Increase timeout value in workflow configuration")
            recommendations.append("Consider optimizing the slow step")
            recommendations.append("Add timeout parameter to the failing command")
        
        elif fix_type == 'fix_permissions':
            recommendations.append("Add appropriate permissions to workflow configuration")
            recommendations.append("Check GITHUB_TOKEN permissions")
            recommendations.append("Verify file/directory permissions in workflow")
        
        elif fix_type == 'add_retry':
            recommendations.append("Add retry logic for network operations")
            recommendations.append("Add continue-on-error for non-critical steps")
            recommendations.append("Consider using actions/retry@v2")
        
        elif fix_type == 'fix_docker':
            recommendations.append("Check Docker service availability")
            recommendations.append("Verify Dockerfile syntax and build context")
            recommendations.append("Add Docker setup steps if missing")
        
        elif fix_type == 'increase_resources':
            recommendations.append("Use a larger runner (e.g., ubuntu-latest-4-cores)")
            recommendations.append("Add resource cleanup steps")
            recommendations.append("Optimize memory usage in the workflow")
        
        elif fix_type == 'add_env_variable':
            if root_cause.get('captured_values'):
                recommendations.append(f"Add missing environment variable to workflow")
                recommendations.append("Check if variable is in repository secrets")
        
        elif fix_type == 'fix_syntax':
            recommendations.append("Review and fix syntax errors in code")
            recommendations.append("Add linting step before tests")
            recommendations.append("Use syntax checking in pre-commit hooks")
        
        elif fix_type == 'fix_test':
            recommendations.append("Review failing test cases")
            recommendations.append("Update test expectations if code behavior changed")
            recommendations.append("Check test dependencies and fixtures")
        
        else:
            recommendations.append("Manual review required")
            recommendations.append("Check logs for specific error details")
        
        return recommendations
    
    def _extract_affected_files(self, errors: List[Dict[str, str]]) -> List[str]:
        """Extract file paths mentioned in errors."""
        files = set()
        
        # Common file path patterns
        file_patterns = [
            r'File "([^"]+)"',
            r'in ([^\s]+\.py)',
            r'([^\s]+\.yml)',
            r'([^\s]+\.yaml)',
            r'([^\s]+\.json)',
        ]
        
        for error in errors:
            message = error['message']
            for pattern in file_patterns:
                matches = re.findall(pattern, message)
                files.update(matches)
        
        return sorted(list(files))
    
    def _extract_relevant_snippets(
        self, 
        logs: Dict[str, str], 
        errors: List[Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """Extract relevant log snippets around errors."""
        snippets = []
        
        for error in errors[:5]:  # Limit to first 5 errors
            snippets.append({
                'log_file': error['log_file'],
                'line_number': error['line_number'],
                'context': error['context'],
            })
        
        return snippets


def main():
    parser = argparse.ArgumentParser(
        description='Analyze GitHub Actions workflow failures'
    )
    parser.add_argument('--run-id', required=True, help='Workflow run ID')
    parser.add_argument('--workflow-name', required=True, help='Workflow name')
    parser.add_argument('--logs-dir', required=True, help='Directory containing log files')
    parser.add_argument('--output', required=True, help='Output file for analysis results')
    
    args = parser.parse_args()
    
    # Perform analysis
    analyzer = WorkflowFailureAnalyzer(
        run_id=args.run_id,
        workflow_name=args.workflow_name,
        logs_dir=Path(args.logs_dir),
    )
    
    analysis = analyzer.analyze()
    
    # Write results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(analysis, f, indent=2)
    
    print(f"✅ Analysis complete: {output_path}")
    print(f"   Error Type: {analysis['error_type']}")
    print(f"   Fix Confidence: {analysis['fix_confidence']}%")
    print(f"   Root Cause: {analysis['root_cause']}")


if __name__ == '__main__':
    main()
