#!/usr/bin/env python3
"""
Enhanced Workflow Copilot Integration Script - Thin Wrapper

This is a thin wrapper that provides workflow analysis and Copilot integration
checking. Core Copilot CLI functionality delegated to utils.cli_tools.Copilot.

For core Copilot CLI operations, see: ipfs_datasets_py/utils/cli_tools/copilot.py

Usage:
    python enhance_workflow_copilot_integration_refactored.py
"""

import json
import os
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add repository root to path for imports
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import from utils - this is the single source of truth for Copilot CLI
from ipfs_datasets_py.utils.cli_tools import Copilot


class WorkflowCopilotIntegration:
    """
    Manages integration of GitHub Copilot CLI with GitHub Actions workflows.
    
    Uses utils.cli_tools.Copilot for all CLI operations, keeping only
    workflow-specific analysis logic.
    """
    
    def __init__(self, workflows_dir: Optional[str] = None):
        """Initialize the integration manager."""
        if workflows_dir is None:
            workflows_dir = REPO_ROOT / '.github' / 'workflows'
        self.workflows_dir = Path(workflows_dir)
        
        # Use utils.cli_tools.Copilot for all Copilot operations
        self.copilot = Copilot()
    
    def check_gh_cli_available(self) -> bool:
        """Check if GitHub CLI is available."""
        return self.copilot.is_installed()
    
    def check_copilot_extension_installed(self) -> bool:
        """Check if gh-copilot extension is installed."""
        return self.copilot.copilot_installed
    
    def install_copilot_extension(self) -> bool:
        """Install gh-copilot extension."""
        return self.copilot.install()
    
    def get_workflow_files(self, include_disabled: bool = False) -> List[Path]:
        """Get list of workflow files."""
        pattern = "*.yml" if not include_disabled else "*.yml*"
        workflow_files = list(self.workflows_dir.glob(pattern))
        
        if not include_disabled:
            workflow_files = [f for f in workflow_files if not f.name.endswith('.disabled')]
        
        return sorted(workflow_files)
    
    def analyze_workflow(self, workflow_file: Path) -> Dict[str, Any]:
        """Analyze a workflow file for potential issues."""
        analysis = {
            'file': str(workflow_file),
            'name': workflow_file.name,
            'uses_self_hosted': False,
            'uses_container': False,
            'uses_gh_cli': False,
            'uses_copilot': False,
            'has_autofix': False,
            'issues': []
        }
        
        try:
            content = workflow_file.read_text()
            
            # Parse YAML
            try:
                workflow = yaml.safe_load(content)
            except yaml.YAMLError as e:
                analysis['issues'].append(f"YAML parsing error: {e}")
                return analysis
            
            # Check for self-hosted runners
            analysis['uses_self_hosted'] = 'self-hosted' in content
            analysis['uses_container'] = 'container:' in content
            analysis['uses_gh_cli'] = 'gh ' in content or 'github-cli' in content
            analysis['uses_copilot'] = 'copilot' in content.lower()
            analysis['has_autofix'] = 'autofix' in content.lower() or 'auto-healing' in content.lower()
            
            # Check for common issues
            if analysis['uses_self_hosted'] and not analysis['uses_container']:
                analysis['issues'].append("Uses self-hosted runners without container isolation")
            
            if analysis['uses_gh_cli']:
                if 'GH_TOKEN:' not in content and 'GITHUB_TOKEN' not in content:
                    analysis['issues'].append("Uses gh CLI but may be missing GH_TOKEN environment variable")
            
        except Exception as e:
            analysis['issues'].append(f"Error analyzing workflow: {e}")
        
        return analysis
    
    def generate_health_report(self) -> Dict[str, Any]:
        """Generate a comprehensive health report."""
        from datetime import datetime
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'github_cli': {
                'available': self.check_gh_cli_available(),
                'path': str(self.copilot.cli_path) if self.copilot.cli_path else None,
                'version': None
            },
            'copilot_extension': {
                'installed': self.check_copilot_extension_installed()
            },
            'workflows': {
                'total': 0,
                'active': 0,
                'disabled': 0,
                'using_self_hosted': 0,
                'using_gh_cli': 0,
                'using_copilot': 0,
                'with_issues': 0
            },
            'workflow_details': []
        }
        
        # Get gh version if available
        if report['github_cli']['available'] and self.copilot.cli_path:
            try:
                import subprocess
                result = subprocess.run(
                    [str(self.copilot.cli_path), '--version'],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.returncode == 0:
                    version_line = result.stdout.split('\n')[0]
                    if 'version' in version_line:
                        report['github_cli']['version'] = version_line.split()[-2]
            except Exception:
                pass
        
        # Analyze workflows
        all_workflows = self.get_workflow_files(include_disabled=True)
        active_workflows = self.get_workflow_files(include_disabled=False)
        
        report['workflows']['total'] = len(all_workflows)
        report['workflows']['active'] = len(active_workflows)
        report['workflows']['disabled'] = len(all_workflows) - len(active_workflows)
        
        for workflow_file in active_workflows:
            analysis = self.analyze_workflow(workflow_file)
            report['workflow_details'].append(analysis)
            
            if analysis['uses_self_hosted']:
                report['workflows']['using_self_hosted'] += 1
            if analysis['uses_gh_cli']:
                report['workflows']['using_gh_cli'] += 1
            if analysis['uses_copilot']:
                report['workflows']['using_copilot'] += 1
            if analysis['issues']:
                report['workflows']['with_issues'] += 1
        
        return report
    
    def print_health_report(self, report: Dict[str, Any]):
        """Print a formatted health report."""
        print("\n" + "=" * 80)
        print("GitHub Actions Workflow Health Report")
        print("=" * 80)
        print(f"Generated: {report['timestamp']}")
        print()
        
        # GitHub CLI status
        print("🔧 GitHub CLI Status")
        print("-" * 80)
        if report['github_cli']['available']:
            print(f"✅ Available: {report['github_cli']['path']}")
            if report['github_cli']['version']:
                print(f"   Version: {report['github_cli']['version']}")
        else:
            print("❌ Not available or not in PATH")
        print()
        
        # Copilot extension status
        print("🤖 GitHub Copilot Extension Status")
        print("-" * 80)
        if report['copilot_extension']['installed']:
            print("✅ Installed and available")
        else:
            print("❌ Not installed or not accessible")
            print("   Install with: gh extension install github/gh-copilot")
        print()
        
        # Workflow summary
        print("📊 Workflow Summary")
        print("-" * 80)
        print(f"Total workflows: {report['workflows']['total']}")
        print(f"  - Active: {report['workflows']['active']}")
        print(f"  - Disabled: {report['workflows']['disabled']}")
        print(f"Using self-hosted runners: {report['workflows']['using_self_hosted']}")
        print(f"Using GitHub CLI: {report['workflows']['using_gh_cli']}")
        print(f"Using Copilot: {report['workflows']['using_copilot']}")
        print(f"With potential issues: {report['workflows']['with_issues']}")
        print()
        
        # Issues detail
        if report['workflows']['with_issues'] > 0:
            print("⚠️  Workflows with Potential Issues")
            print("-" * 80)
            for workflow in report['workflow_details']:
                if workflow['issues']:
                    print(f"\n{workflow['name']}:")
                    for issue in workflow['issues']:
                        print(f"  • {issue}")
            print()
        
        print("=" * 80)
    
    def suggest_improvements(self, report: Dict[str, Any]) -> List[str]:
        """Generate improvement suggestions based on report."""
        suggestions = []
        
        if not report['github_cli']['available']:
            suggestions.append("Install GitHub CLI (gh) for enhanced workflow automation")
        
        if not report['copilot_extension']['installed']:
            suggestions.append("Install gh-copilot extension: gh extension install github/gh-copilot")
        
        if report['workflows']['using_gh_cli'] > 0:
            suggestions.append(
                f"{report['workflows']['using_gh_cli']} workflows use gh CLI - "
                "ensure GH_TOKEN is properly configured"
            )
        
        if report['workflows']['using_copilot'] == 0:
            suggestions.append(
                "Consider integrating Copilot CLI for automated code suggestions in workflows"
            )
        
        if report['workflows']['with_issues'] > 0:
            suggestions.append(
                f"Address {report['workflows']['with_issues']} workflows with potential issues"
            )
        
        return suggestions


def main():
    """Main entry point."""
    print("🚀 GitHub Actions Workflow Copilot Integration Tool")
    print("   (Core Copilot CLI operations via ipfs_datasets_py.utils.cli_tools.Copilot)")
    print()
    
    # Initialize integration manager
    integration = WorkflowCopilotIntegration()
    
    # Generate health report
    report = integration.generate_health_report()
    
    # Print report
    integration.print_health_report(report)
    
    # Print suggestions
    suggestions = integration.suggest_improvements(report)
    if suggestions:
        print("💡 Improvement Suggestions")
        print("-" * 80)
        for i, suggestion in enumerate(suggestions, 1):
            print(f"{i}. {suggestion}")
        print()
    
    # Save report to file
    report_file = REPO_ROOT / '.github' / 'workflow_health_report.json'
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"📄 Full report saved to: {report_file}")
    print()
    
    # Exit with appropriate code
    if report['workflows']['with_issues'] > 0:
        print("⚠️  Some workflows have potential issues")
        return 1
    else:
        print("✅ All workflows look healthy!")
        return 0


if __name__ == '__main__':
    sys.exit(main())
