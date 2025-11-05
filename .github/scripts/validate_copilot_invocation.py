#!/usr/bin/env python3
"""
Validate GitHub Actions Workflows for Proper Copilot Invocation

This script checks all workflow files to ensure they use the correct method
for invoking GitHub Copilot Coding Agent (gh agent-task create) instead of
deprecated @copilot mentions.

Usage:
    python .github/scripts/validate_copilot_invocation.py [--fix]
    
Options:
    --fix    Suggest fixes for detected issues (does not modify files)
"""

import os
import sys
import yaml
import re
import argparse
from pathlib import Path
from typing import Dict, List, Any, Tuple
import json

# Colors for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def find_workflow_files(workflows_dir: Path) -> List[Path]:
    """Find all workflow YAML files."""
    patterns = ['*.yml', '*.yaml']
    workflow_files = []
    
    for pattern in patterns:
        workflow_files.extend(workflows_dir.glob(pattern))
    
    # Exclude disabled workflows
    workflow_files = [f for f in workflow_files if not f.name.endswith('.disabled')]
    
    return sorted(workflow_files)


def check_copilot_mentions(content: str) -> List[Dict[str, Any]]:
    """Check for @copilot mentions in workflow content."""
    issues = []
    
    # Pattern to find @copilot mentions in shell scripts or comments
    patterns = [
        (r'@copilot\s+/\w+', 'Found @copilot slash command'),
        (r'@copilot\s+[Pp]lease', 'Found @copilot mention with request'),
        (r'@github-copilot', 'Found @github-copilot mention'),
        (r'gh\s+(pr|issue)\s+comment.*@copilot', 'Creating comment with @copilot mention'),
    ]
    
    lines = content.split('\n')
    
    for i, line in enumerate(lines, 1):
        for pattern, description in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                issues.append({
                    'line': i,
                    'content': line.strip(),
                    'issue': description,
                    'severity': 'warning'
                })
    
    return issues


def check_agent_task_usage(content: str) -> bool:
    """Check if workflow uses gh agent-task create."""
    patterns = [
        r'gh\s+agent-task\s+create',
        r'gh\s+agent\s+create',
    ]
    
    for pattern in patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    
    return False


def check_gh_token(content: str) -> bool:
    """Check if workflow sets GH_TOKEN for gh commands."""
    # Look for env block with GH_TOKEN
    patterns = [
        r'env:\s*\n\s*GH_TOKEN:\s*\$\{\{\s*secrets\.GITHUB_TOKEN',
        r'GH_TOKEN:\s*\$\{\{\s*secrets\.GITHUB_TOKEN',
    ]
    
    for pattern in patterns:
        if re.search(pattern, content, re.MULTILINE):
            return True
    
    return False


def analyze_workflow(workflow_path: Path) -> Dict[str, Any]:
    """Analyze a single workflow file."""
    result = {
        'file': workflow_path.name,
        'path': str(workflow_path),
        'has_copilot_mentions': False,
        'uses_agent_task': False,
        'has_gh_token': False,
        'issues': [],
        'score': 100
    }
    
    try:
        content = workflow_path.read_text()
        
        # Check for @copilot mentions
        copilot_issues = check_copilot_mentions(content)
        if copilot_issues:
            result['has_copilot_mentions'] = True
            result['issues'].extend(copilot_issues)
            result['score'] -= 20 * len(copilot_issues)
        
        # Check for gh agent-task usage
        result['uses_agent_task'] = check_agent_task_usage(content)
        if result['uses_agent_task']:
            result['score'] += 10
        
        # Check for GH_TOKEN configuration
        result['has_gh_token'] = check_gh_token(content)
        if not result['has_gh_token'] and 'gh ' in content:
            result['issues'].append({
                'line': 0,
                'content': 'Workflow uses gh CLI but may be missing GH_TOKEN',
                'issue': 'Missing GH_TOKEN configuration',
                'severity': 'info'
            })
            result['score'] -= 5
        
        # Validate YAML syntax
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            result['issues'].append({
                'line': getattr(e, 'problem_mark', {}).line if hasattr(e, 'problem_mark') else 0,
                'content': str(e),
                'issue': 'YAML syntax error',
                'severity': 'error'
            })
            result['score'] = 0
        
        # Ensure score is in valid range
        result['score'] = max(0, min(100, result['score']))
        
    except Exception as e:
        result['issues'].append({
            'line': 0,
            'content': str(e),
            'issue': 'Failed to analyze workflow',
            'severity': 'error'
        })
        result['score'] = 0
    
    return result


def print_report(results: List[Dict[str, Any]], suggest_fixes: bool = False):
    """Print analysis report."""
    print(f"\n{Colors.HEADER}{Colors.BOLD}GitHub Actions Workflow Validation Report{Colors.ENDC}")
    print(f"{Colors.HEADER}={'='*80}{Colors.ENDC}\n")
    
    # Summary statistics
    total_workflows = len(results)
    workflows_with_issues = sum(1 for r in results if r['issues'])
    workflows_using_agent_task = sum(1 for r in results if r['uses_agent_task'])
    workflows_with_copilot_mentions = sum(1 for r in results if r['has_copilot_mentions'])
    
    avg_score = sum(r['score'] for r in results) / total_workflows if total_workflows > 0 else 0
    
    print(f"{Colors.BOLD}Summary:{Colors.ENDC}")
    print(f"  Total workflows analyzed: {total_workflows}")
    print(f"  Workflows with issues: {workflows_with_issues}")
    print(f"  Workflows using gh agent-task: {Colors.OKGREEN}{workflows_using_agent_task}{Colors.ENDC}")
    print(f"  Workflows with @copilot mentions: {Colors.WARNING}{workflows_with_copilot_mentions}{Colors.ENDC}")
    print(f"  Average score: {Colors.OKGREEN if avg_score >= 80 else Colors.WARNING if avg_score >= 60 else Colors.FAIL}{avg_score:.1f}/100{Colors.ENDC}\n")
    
    # Detailed results
    print(f"{Colors.BOLD}Detailed Results:{Colors.ENDC}\n")
    
    for result in sorted(results, key=lambda x: x['score']):
        score = result['score']
        score_color = Colors.OKGREEN if score >= 80 else Colors.WARNING if score >= 60 else Colors.FAIL
        
        status = "✅" if not result['issues'] else "⚠️" if score >= 60 else "❌"
        
        print(f"{status} {Colors.BOLD}{result['file']}{Colors.ENDC} - Score: {score_color}{score}/100{Colors.ENDC}")
        
        if result['uses_agent_task']:
            print(f"   {Colors.OKGREEN}✓{Colors.ENDC} Uses gh agent-task create")
        
        if result['has_gh_token']:
            print(f"   {Colors.OKGREEN}✓{Colors.ENDC} Has GH_TOKEN configured")
        
        if result['issues']:
            print(f"   {Colors.WARNING}Issues found:{Colors.ENDC}")
            for issue in result['issues'][:5]:  # Limit to first 5 issues
                severity_color = Colors.FAIL if issue['severity'] == 'error' else Colors.WARNING
                print(f"     {severity_color}•{Colors.ENDC} Line {issue['line']}: {issue['issue']}")
                if issue['content'] and len(issue['content']) < 100:
                    print(f"       {Colors.OKCYAN}{issue['content']}{Colors.ENDC}")
            
            if len(result['issues']) > 5:
                print(f"     ... and {len(result['issues']) - 5} more issues")
            
            if suggest_fixes:
                print(f"   {Colors.OKBLUE}Suggested fix:{Colors.ENDC}")
                if result['has_copilot_mentions']:
                    print(f"     Replace @copilot comments with: gh agent-task create")
                    print(f"     See: .github/workflows/COPILOT-CLI-INTEGRATION.md")
        
        print()
    
    # Recommendations
    print(f"{Colors.BOLD}Recommendations:{Colors.ENDC}")
    if workflows_with_copilot_mentions > 0:
        print(f"  {Colors.WARNING}•{Colors.ENDC} {workflows_with_copilot_mentions} workflow(s) use @copilot mentions (deprecated)")
        print(f"    {Colors.OKBLUE}→{Colors.ENDC} Migrate to gh agent-task create for better automation")
    
    if workflows_using_agent_task < workflows_with_copilot_mentions:
        print(f"  {Colors.WARNING}•{Colors.ENDC} Consider updating workflows to use gh agent-task create")
        print(f"    {Colors.OKBLUE}→{Colors.ENDC} See: .github/workflows/COPILOT-CLI-INTEGRATION.md")
    
    if workflows_using_agent_task > 0:
        print(f"  {Colors.OKGREEN}✓{Colors.ENDC} {workflows_using_agent_task} workflow(s) correctly use gh agent-task create")
    
    print()


def main():
    parser = argparse.ArgumentParser(
        description='Validate GitHub Actions workflows for proper Copilot invocation'
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='Suggest fixes for detected issues'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results as JSON'
    )
    parser.add_argument(
        '--workflows-dir',
        type=Path,
        default=Path('.github/workflows'),
        help='Path to workflows directory (default: .github/workflows)'
    )
    
    args = parser.parse_args()
    
    # Find repository root
    repo_root = Path(__file__).parent.parent.parent
    workflows_dir = repo_root / args.workflows_dir
    
    if not workflows_dir.exists():
        print(f"{Colors.FAIL}Error: Workflows directory not found: {workflows_dir}{Colors.ENDC}")
        sys.exit(1)
    
    # Find and analyze workflows
    workflow_files = find_workflow_files(workflows_dir)
    
    if not workflow_files:
        print(f"{Colors.WARNING}No workflow files found in {workflows_dir}{Colors.ENDC}")
        sys.exit(0)
    
    print(f"Analyzing {len(workflow_files)} workflow files...")
    
    results = []
    for workflow_file in workflow_files:
        result = analyze_workflow(workflow_file)
        results.append(result)
    
    # Output results
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_report(results, suggest_fixes=args.fix)
    
    # Exit with appropriate code
    has_errors = any(
        any(issue['severity'] == 'error' for issue in r['issues'])
        for r in results
    )
    
    if has_errors:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
