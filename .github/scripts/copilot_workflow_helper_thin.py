#!/usr/bin/env python3
"""
Thin wrapper for Copilot Workflow Helper - imports from optimizers module.

This script provides backward compatibility for existing workflows while
using the unified implementation from ipfs_datasets_py.optimizers.agentic.

The actual workflow helper logic should be consolidated into the optimizers
module over time.
"""

import sys
from pathlib import Path

# Add repository root to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import from unified optimizers module for GitHub API functionality
from ipfs_datasets_py.optimizers.agentic.github_api_unified import UnifiedGitHubAPICache

# For now, keep the original CopilotWorkflowHelper class here
# TODO: Move this to optimizers/agentic/copilot_integration.py
import os
import subprocess
import json
from typing import Dict, List, Optional, Any


class CopilotWorkflowHelper:
    """
    Helper for using GitHub Copilot CLI with workflows.
    
    Uses unified GitHub API cache from optimizers module.
    """
    
    def __init__(self):
        """Initialize the helper with unified API cache."""
        self.gh_cli = self._find_gh_cli()
        self.copilot_available = self._check_copilot_available()
        self.api_cache = UnifiedGitHubAPICache()
    
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
            print(f"❌ Installation error: {e}")
            return False
    
    def run_command(self, command: List[str]) -> subprocess.CompletedProcess:
        """Run a command using the unified API cache for tracking."""
        return self.api_cache.run_gh_command(command)
    
    def get_api_stats(self) -> Dict[str, Any]:
        """Get API usage statistics."""
        return self.api_cache.get_statistics()


def main():
    """Main entry point for CLI usage."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='GitHub Copilot CLI Workflow Helper'
    )
    parser.add_argument(
        'action',
        choices=['check', 'install', 'stats'],
        help='Action to perform'
    )
    
    args = parser.parse_args()
    
    helper = CopilotWorkflowHelper()
    
    if args.action == 'check':
        if helper.copilot_available:
            print("✅ GitHub Copilot CLI is available")
        else:
            print("❌ GitHub Copilot CLI is not available")
            print("Run with 'install' to install it")
    
    elif args.action == 'install':
        helper.install_copilot()
    
    elif args.action == 'stats':
        stats = helper.get_api_stats()
        print(json.dumps(stats, indent=2))


if __name__ == '__main__':
    main()
