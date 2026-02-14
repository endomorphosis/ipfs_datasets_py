"""Workflow failure analysis utilities.

This module provides tools for analyzing GitHub Actions workflow failures,
extracting root causes, and generating diagnostic reports.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class WorkflowAnalyzer:
    """Analyzes GitHub Actions workflow failures.
    
    Provides root cause analysis, error pattern detection, and diagnostic
    report generation for failed workflow runs.
    
    Example:
        >>> analyzer = WorkflowAnalyzer()
        >>> result = analyzer.analyze_failure(
        ...     workflow_file=Path('.github/workflows/ci.yml'),
        ...     error_log='Error: Command failed with exit code 1'
        ... )
        >>> print(result['root_cause'])
    """
    
    # Common error patterns and their root causes
    ERROR_PATTERNS = {
        r'rate limit': 'GitHub API rate limit exceeded',
        r'timeout': 'Operation timed out',
        r'connection refused': 'Network connection issue',
        r'permission denied': 'Permission or authentication issue',
        r'not found': 'Resource not found',
        r'module not found': 'Missing Python module/dependency',
        r'command not found': 'Missing system command/tool',
        r'syntax error': 'Syntax error in code or configuration',
        r'import error': 'Python import error',
    }
    
    def __init__(self):
        """Initialize workflow analyzer."""
        self.analysis_cache: Dict[str, Any] = {}
    
    def analyze_failure(
        self,
        workflow_file: Path,
        error_log: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Analyze a workflow failure.
        
        Args:
            workflow_file: Path to workflow YAML file
            error_log: Error log from failed run
            context: Optional additional context (job name, step, etc.)
        
        Returns:
            Dict with analysis results:
            - root_cause: Detected root cause
            - error_patterns: List of matched patterns
            - suggestions: List of fix suggestions
            - severity: Error severity (low/medium/high/critical)
        """
        result = {
            'workflow_file': str(workflow_file),
            'root_cause': 'Unknown',
            'error_patterns': [],
            'suggestions': [],
            'severity': 'medium',
            'context': context or {}
        }
        
        if not error_log:
            result['root_cause'] = 'No error log provided'
            return result
        
        # Detect error patterns
        error_log_lower = error_log.lower()
        for pattern, cause in self.ERROR_PATTERNS.items():
            if re.search(pattern, error_log_lower):
                result['error_patterns'].append({
                    'pattern': pattern,
                    'cause': cause
                })
                if result['root_cause'] == 'Unknown':
                    result['root_cause'] = cause
        
        # Generate suggestions based on root cause
        result['suggestions'] = self._generate_suggestions(result['root_cause'], error_log)
        
        # Determine severity
        result['severity'] = self._determine_severity(result['root_cause'], error_log)
        
        logger.info(f"Analyzed failure: {result['root_cause']}")
        return result
    
    def _generate_suggestions(self, root_cause: str, error_log: str) -> List[str]:
        """Generate fix suggestions based on root cause.
        
        Args:
            root_cause: Detected root cause
            error_log: Full error log
        
        Returns:
            List of suggestion strings
        """
        suggestions = []
        
        if 'rate limit' in root_cause.lower():
            suggestions.extend([
                'Implement API call caching',
                'Add exponential backoff and retry logic',
                'Use authenticated API calls to increase rate limit',
                'Reduce API call frequency'
            ])
        
        elif 'timeout' in root_cause.lower():
            suggestions.extend([
                'Increase timeout value',
                'Optimize operation to complete faster',
                'Break operation into smaller chunks',
                'Check for network issues'
            ])
        
        elif 'permission' in root_cause.lower():
            suggestions.extend([
                'Check GitHub token permissions',
                'Verify repository access settings',
                'Ensure correct authentication credentials',
                'Review workflow permissions configuration'
            ])
        
        elif 'not found' in root_cause.lower() or 'missing' in root_cause.lower():
            # Extract potential package/module name
            if 'module' in error_log.lower():
                match = re.search(r"module named '([^']+)'", error_log, re.IGNORECASE)
                if match:
                    module_name = match.group(1)
                    suggestions.append(f'Install missing module: pip install {module_name}')
            
            suggestions.extend([
                'Add missing dependency to requirements.txt',
                'Install required system packages',
                'Check resource paths and URLs'
            ])
        
        elif 'syntax error' in root_cause.lower():
            suggestions.extend([
                'Review code syntax',
                'Check YAML/JSON formatting',
                'Validate workflow file structure',
                'Use linting tools'
            ])
        
        # Default suggestions
        if not suggestions:
            suggestions.extend([
                'Review full error log for details',
                'Check recent code changes',
                'Verify environment configuration',
                'Test locally to reproduce issue'
            ])
        
        return suggestions
    
    def _determine_severity(self, root_cause: str, error_log: str) -> str:
        """Determine error severity.
        
        Args:
            root_cause: Detected root cause
            error_log: Full error log
        
        Returns:
            Severity level: 'low', 'medium', 'high', or 'critical'
        """
        root_cause_lower = root_cause.lower()
        error_log_lower = error_log.lower()
        
        # Critical issues
        if any(word in root_cause_lower for word in ['security', 'vulnerability', 'leak']):
            return 'critical'
        
        # High severity issues
        if any(word in root_cause_lower for word in ['permission', 'authentication', 'crash', 'corrupt']):
            return 'high'
        
        # Low severity issues
        if any(word in root_cause_lower for word in ['warning', 'deprecated', 'style']):
            return 'low'
        
        # Default to medium
        return 'medium'
    
    def generate_report(self, analysis_result: Dict[str, Any]) -> str:
        """Generate human-readable analysis report.
        
        Args:
            analysis_result: Result from analyze_failure()
        
        Returns:
            Formatted report string
        """
        lines = [
            "=" * 80,
            "Workflow Failure Analysis Report",
            "=" * 80,
            f"Workflow: {analysis_result['workflow_file']}",
            f"Root Cause: {analysis_result['root_cause']}",
            f"Severity: {analysis_result['severity'].upper()}",
            "",
        ]
        
        if analysis_result['error_patterns']:
            lines.append("Detected Patterns:")
            for pattern in analysis_result['error_patterns']:
                lines.append(f"  - {pattern['cause']} (pattern: {pattern['pattern']})")
            lines.append("")
        
        if analysis_result['suggestions']:
            lines.append("Suggested Fixes:")
            for i, suggestion in enumerate(analysis_result['suggestions'], 1):
                lines.append(f"  {i}. {suggestion}")
            lines.append("")
        
        if analysis_result['context']:
            lines.append("Context:")
            for key, value in analysis_result['context'].items():
                lines.append(f"  {key}: {value}")
            lines.append("")
        
        lines.append("=" * 80)
        
        return "\n".join(lines)
