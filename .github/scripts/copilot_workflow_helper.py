#!/usr/bin/env python3
"""
GitHub Copilot CLI Workflow Helper

This script provides Copilot CLI integration for GitHub Actions workflows,
enabling automated code analysis, command suggestions, and workflow improvements.

Usage:
    python copilot_workflow_helper.py analyze <workflow_file>
    python copilot_workflow_helper.py suggest-fix <workflow_file>
    python copilot_workflow_helper.py explain <code>
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add parent directory to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


class CopilotWorkflowHelper:
    """
    Helper for using GitHub Copilot CLI with workflows
    """
    
    def __init__(self):
        """Initialize the helper"""
        self.gh_cli = self._find_gh_cli()
        self.copilot_available = self._check_copilot_available()
    
    def _find_gh_cli(self) -> Optional[str]:
        """Find gh CLI executable"""
        try:
            result = subprocess.run(
                ['which', 'gh'],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None
    
    def _check_copilot_available(self) -> bool:
        """Check if Copilot CLI extension is available"""
        if not self.gh_cli:
            return False
        
        # Check if we can run gh copilot
        # Note: This requires GH_TOKEN to be set
        if not os.environ.get('GH_TOKEN') and not os.environ.get('GITHUB_TOKEN'):
            return False
        
        try:
            result = subprocess.run(
                [self.gh_cli, 'copilot', '--version'],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, 'GH_TOKEN': os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN', '')}
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def install_copilot(self) -> bool:
        """Install gh-copilot extension"""
        if not self.gh_cli:
            print("❌ GitHub CLI not found")
            return False
        
        token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if not token:
            print("❌ GH_TOKEN or GITHUB_TOKEN required")
            return False
        
        try:
            print("📦 Installing gh-copilot extension...")
            result = subprocess.run(
                [self.gh_cli, 'extension', 'install', 'github/gh-copilot'],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, 'GH_TOKEN': token}
            )
            
            if result.returncode == 0:
                print("✅ gh-copilot installed successfully")
                self.copilot_available = True
                return True
            else:
                print(f"❌ Installation failed: {result.stderr}")
                return False
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    def explain_code(self, code: str) -> Optional[str]:
        """
        Use Copilot to explain code
        
        Args:
            code: Code snippet to explain
        
        Returns:
            Explanation or None if failed
        """
        if not self.copilot_available:
            print("⚠️  Copilot CLI not available")
            return None
        
        try:
            # Use gh copilot explain
            result = subprocess.run(
                [self.gh_cli, 'copilot', 'explain'],
                input=code,
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, 'GH_TOKEN': os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN', '')}
            )
            
            if result.returncode == 0:
                return result.stdout
            else:
                print(f"❌ Explanation failed: {result.stderr}")
                return None
        except Exception as e:
            print(f"❌ Error: {e}")
            return None
    
    def suggest_command(self, description: str) -> Optional[str]:
        """
        Get command suggestions from Copilot
        
        Args:
            description: What you want to do
        
        Returns:
            Suggested command or None if failed
        """
        if not self.copilot_available:
            print("⚠️  Copilot CLI not available")
            return None
        
        try:
            # Use gh copilot suggest
            result = subprocess.run(
                [self.gh_cli, 'copilot', 'suggest', '-t', 'shell', description],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, 'GH_TOKEN': os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN', '')}
            )
            
            if result.returncode == 0:
                return result.stdout
            else:
                print(f"❌ Suggestion failed: {result.stderr}")
                return None
        except Exception as e:
            print(f"❌ Error: {e}")
            return None
    
    def suggest_git_command(self, description: str) -> Optional[str]:
        """
        Get Git command suggestions from Copilot
        
        Args:
            description: What you want to do with Git
        
        Returns:
            Suggested Git command or None if failed
        """
        if not self.copilot_available:
            print("⚠️  Copilot CLI not available")
            return None
        
        try:
            # Use gh copilot suggest for git
            result = subprocess.run(
                [self.gh_cli, 'copilot', 'suggest', '-t', 'git', description],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, 'GH_TOKEN': os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN', '')}
            )
            
            if result.returncode == 0:
                return result.stdout
            else:
                print(f"❌ Suggestion failed: {result.stderr}")
                return None
        except Exception as e:
            print(f"❌ Error: {e}")
            return None
    
    def analyze_workflow(self, workflow_file: Path) -> Dict[str, Any]:
        """
        Analyze a workflow file using Copilot
        
        Args:
            workflow_file: Path to workflow file
        
        Returns:
            Analysis results
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
            explanation = self.explain_code(content[:1000])  # First 1000 chars
            if explanation:
                result['analysis'] = explanation
                result['success'] = True
        else:
            result['analysis'] = "Copilot CLI not available - install with: gh extension install github/gh-copilot"
        
        return result
    
    def suggest_workflow_fix(self, workflow_file: Path, error_log: Optional[str] = None) -> List[str]:
        """
        Suggest fixes for a workflow
        
        Args:
            workflow_file: Path to workflow file
            error_log: Optional error log from failed run
        
        Returns:
            List of suggestions
        """
        suggestions = []
        
        if not self.copilot_available:
            suggestions.append("Install Copilot CLI: gh extension install github/gh-copilot")
            return suggestions
        
        # Build a description of the issue
        description = f"Fix GitHub Actions workflow {workflow_file.name}"
        if error_log:
            description += f" with error: {error_log[:200]}"
        
        # Get command suggestions
        print(f"\n🔧 Getting fix suggestions for {workflow_file.name}...")
        suggestion = self.suggest_command(description)
        
        if suggestion:
            suggestions.append(suggestion)
        
        return suggestions


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='GitHub Copilot CLI Workflow Helper'
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
    suggest_parser.add_argument('--type', choices=['shell', 'git'], default='shell', help='Command type')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Initialize helper
    helper = CopilotWorkflowHelper()
    
    # Execute command
    if args.command == 'install':
        success = helper.install_copilot()
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
        explanation = helper.explain_code(args.code)
        
        if explanation:
            print("\n" + "=" * 80)
            print("Explanation:")
            print("=" * 80)
            print(explanation)
        else:
            print("\n❌ Explanation failed")
            return 1
    
    elif args.command == 'suggest':
        if args.type == 'git':
            suggestion = helper.suggest_git_command(args.description)
        else:
            suggestion = helper.suggest_command(args.description)
        
        if suggestion:
            print("\n" + "=" * 80)
            print("Suggestion:")
            print("=" * 80)
            print(suggestion)
        else:
            print("\n❌ Suggestion failed")
            return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
