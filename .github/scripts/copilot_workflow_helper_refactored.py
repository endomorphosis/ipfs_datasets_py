#!/usr/bin/env python3
"""
GitHub Copilot CLI Workflow Helper - Thin Wrapper

This is a thin wrapper around ipfs_datasets_py.utils.cli_tools.Copilot that provides
workflow-specific functionality for GitHub Actions.

For core Copilot CLI functionality, see: ipfs_datasets_py/utils/cli_tools/copilot.py

Usage:
    python copilot_workflow_helper.py install
    python copilot_workflow_helper.py analyze <workflow_file>
    python copilot_workflow_helper.py suggest-fix <workflow_file> [--error-log <log>]
    python copilot_workflow_helper.py explain <code>
    python copilot_workflow_helper.py suggest <description>
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add repository root to path for imports
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import from utils - this is the single source of truth
from ipfs_datasets_py.utils.cli_tools import Copilot


class CopilotWorkflowHelper:
    """
    Workflow-specific helper for GitHub Copilot CLI.
    
    This class wraps ipfs_datasets_py.utils.cli_tools.Copilot and adds
    workflow-specific functionality like analyze_workflow and suggest_workflow_fix.
    """
    
    def __init__(self):
        """Initialize the workflow helper."""
        self.copilot = Copilot(enable_cache=True)
        self.gh_cli = self.copilot.cli_path
        self.copilot_available = self.copilot.copilot_installed
    
    def analyze_workflow(self, workflow_file: Path) -> Dict[str, Any]:
        """Analyze a workflow file using Copilot.
        
        Args:
            workflow_file: Path to workflow YAML file
        
        Returns:
            Dict with analysis results including:
            - file: Path to workflow file
            - analysis: Copilot's explanation of the workflow
            - suggestions: List of improvement suggestions
            - success: Whether analysis succeeded
        """
        result = {
            'file': str(workflow_file),
            'analysis': None,
            'suggestions': [],
            'success': False
        }
        
        if not workflow_file.exists():
            result['error'] = f"File not found: {workflow_file}"
            return result
        
        # Read workflow content
        with open(workflow_file, 'r') as f:
            content = f.read()
        
        # Use Copilot to explain the workflow
        print(f"\n📋 Analyzing {workflow_file.name}...")
        
        if self.copilot_available:
            # Use the utils.cli_tools.Copilot.explain method
            explanation = self.copilot.explain(content[:1000])  # First 1000 chars
            if explanation and 'stdout' in explanation:
                result['analysis'] = explanation['stdout']
                result['success'] = True
        else:
            result['analysis'] = "Copilot CLI not available - install with: gh extension install github/gh-copilot"
        
        return result
    
    def suggest_workflow_fix(
        self, 
        workflow_file: Path, 
        error_log: Optional[str] = None
    ) -> List[str]:
        """Suggest fixes for a failing workflow.
        
        Args:
            workflow_file: Path to workflow file
            error_log: Optional error log from failed workflow run
        
        Returns:
            List of suggested fixes
        """
        suggestions = []
        
        if not self.copilot_available:
            suggestions.append("Install Copilot CLI: gh extension install github/gh-copilot")
            return suggestions
        
        # Build a description of the issue
        description = f"Fix GitHub Actions workflow {workflow_file.name}"
        if error_log:
            description += f" with error: {error_log[:200]}"
        
        # Get command suggestions using utils.cli_tools.Copilot
        print(f"\n🔧 Getting fix suggestions for {workflow_file.name}...")
        result = self.copilot.suggest(description)
        
        if result and 'stdout' in result:
            suggestions.append(result['stdout'])
        
        return suggestions


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='GitHub Copilot CLI Workflow Helper',
        epilog='Core Copilot functionality provided by ipfs_datasets_py.utils.cli_tools.Copilot'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Install command
    subparsers.add_parser('install', help='Install gh-copilot extension')
    
    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze a workflow')
    analyze_parser.add_argument('workflow', help='Workflow file path')
    
    # Suggest fix command
    fix_parser = subparsers.add_parser('suggest-fix', help='Suggest fixes for a workflow')
    fix_parser.add_argument('workflow', help='Workflow file path')
    fix_parser.add_argument('--error-log', help='Error log from failed run')
    
    # Explain command
    explain_parser = subparsers.add_parser('explain', help='Explain code')
    explain_parser.add_argument('code', help='Code to explain')
    
    # Suggest command
    suggest_parser = subparsers.add_parser('suggest', help='Suggest a command')
    suggest_parser.add_argument('description', help='What you want to do')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Initialize helper (uses utils.cli_tools.Copilot internally)
    helper = CopilotWorkflowHelper()
    
    # Execute command
    if args.command == 'install':
        success = helper.copilot.install()
        return 0 if success else 1
    
    elif args.command == 'analyze':
        workflow_path = Path(args.workflow)
        if not workflow_path.is_absolute():
            workflow_path = REPO_ROOT / '.github' / 'workflows' / workflow_path
        
        result = helper.analyze_workflow(workflow_path)
        
        if result['success'] and result['analysis']:
            print("\n" + "=" * 80)
            print("Analysis:")
            print("=" * 80)
            print(result['analysis'])
        else:
            print(f"\n❌ Analysis failed: {result.get('error', 'Unknown error')}")
            return 1
    
    elif args.command == 'suggest-fix':
        workflow_path = Path(args.workflow)
        if not workflow_path.is_absolute():
            workflow_path = REPO_ROOT / '.github' / 'workflows' / workflow_path
        
        suggestions = helper.suggest_workflow_fix(workflow_path, args.error_log)
        
        if suggestions:
            print("\n" + "=" * 80)
            print("Suggestions:")
            print("=" * 80)
            for i, suggestion in enumerate(suggestions, 1):
                print(f"\n{i}. {suggestion}")
        else:
            print("\n❌ No suggestions available")
            return 1
    
    elif args.command == 'explain':
        result = helper.copilot.explain(args.code)
        
        if result and 'stdout' in result:
            print("\n" + "=" * 80)
            print("Explanation:")
            print("=" * 80)
            print(result['stdout'])
        else:
            print("\n❌ Explanation failed")
            return 1
    
    elif args.command == 'suggest':
        result = helper.copilot.suggest(args.description)
        
        if result and 'stdout' in result:
            print("\n" + "=" * 80)
            print("Suggestion:")
            print("=" * 80)
            print(result['stdout'])
        else:
            print("\n❌ Suggestion failed")
            return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
